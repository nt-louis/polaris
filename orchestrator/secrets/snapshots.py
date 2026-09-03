"""Automated SOPS encrypted secrets snapshot synchronization and offline snapshot manager."""

import datetime
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Union

from orchestrator.core.constants import REPO_ROOT
from orchestrator.registry.manifest import get_valid_node_ids
from orchestrator.secrets.doppler import DopplerClient
from orchestrator.secrets.sops import find_sops_binary, setup_age_key_env

logger = logging.getLogger(__name__)

DEFAULT_SYNC_BRANCH = "snapshots/sync"
DEFAULT_REMOTE = "origin"
DEFAULT_BASE_BRANCH = "main"


def parse_dotenv_content(content: str) -> dict[str, str]:
    """Parse dotenv key=value formatted text into a dictionary."""
    env_vars = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and (
                (val.startswith('"') and val.endswith('"'))
                or (val.startswith("'") and val.endswith("'"))
            ):
                val = val[1:-1]
            if key:
                env_vars[key] = val
    return env_vars


class SnapshotManager:
    """Manages offline SOPS-encrypted secret snapshots for Doppler fallback."""

    def __init__(self, repo_root: Optional[Union[str, Path]] = None) -> None:
        self.repo_root = Path(repo_root or REPO_ROOT)
        self.snapshots_dir = self.repo_root / ".snapshots"
        self.doppler = DopplerClient()

    def get_snapshot_path(self, project: str, config: str) -> str:
        """Get the filesystem path for a specific project/config snapshot."""
        return str(self.snapshots_dir / project / f"{config}.env.enc")

    def get_snapshot_content(self, project: str, config: str) -> Optional[tuple[str, str]]:
        """Fetch encrypted snapshot ciphertext from origin/snapshots/sync, snapshots/sync, or local disk."""
        rel_path = f".snapshots/{project}/{config}.env.enc"

        for ref in ("origin/snapshots/sync", "snapshots/sync"):
            try:
                res = subprocess.run(
                    ["git", "cat-file", "-e", f"{ref}:{rel_path}"],
                    cwd=str(self.repo_root),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if res.returncode == 0:
                    show_res = subprocess.run(
                        ["git", "show", f"{ref}:{rel_path}"],
                        cwd=str(self.repo_root),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    if show_res.returncode == 0 and show_res.stdout.strip():
                        return show_res.stdout, f"git branch {ref}"
            except Exception:
                pass

        local_path = Path(self.get_snapshot_path(project, config))
        if local_path.is_file() and local_path.stat().st_size > 0:
            try:
                return local_path.read_text(encoding="utf-8"), f"local disk ({local_path})"
            except OSError:
                pass

        return None

    def is_snapshot_available(self, project: str, config: str) -> bool:
        """Check if an encrypted snapshot exists for the given project and config."""
        rel_path = f".snapshots/{project}/{config}.env.enc"
        for ref in ("origin/snapshots/sync", "snapshots/sync"):
            try:
                res = subprocess.run(
                    ["git", "cat-file", "-e", f"{ref}:{rel_path}"],
                    cwd=str(self.repo_root),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if res.returncode == 0:
                    return True
            except Exception:
                pass

        path = Path(self.get_snapshot_path(project, config))
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    def get_snapshot_timestamp(self, project: str, config: str) -> Optional[str]:
        """Get the git commit timestamp for the snapshot file from tracking branch or local commit."""
        rel_path = f".snapshots/{project}/{config}.env.enc"

        for ref in ("origin/snapshots/sync", "snapshots/sync"):
            try:
                res = subprocess.run(
                    ["git", "log", "-1", "--format=%cs", ref, "--", rel_path],
                    cwd=str(self.repo_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass

        path = Path(self.get_snapshot_path(project, config))
        if path.exists():
            res = subprocess.run(
                ["git", "log", "-1", "--format=%cs", "--", str(path)],
                cwd=str(self.repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()

            mtime = path.stat().st_mtime
            return datetime.date.fromtimestamp(mtime).isoformat()

        return None

    def snapshot_config(self, project: str, config: str) -> bool:
        """Export a single config from Doppler and save encrypted SOPS snapshot."""
        sops_bin = find_sops_binary(self.repo_root)
        if not sops_bin:
            logger.error("SOPS binary not found.")
            return False
        setup_age_key_env(self.repo_root)

        cmd = ["doppler", "secrets", "download", "--project", project, "--config", config, "--format", "env", "--no-file"]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if res.returncode != 0:
            logger.error("Failed to download secrets for %s/%s from Doppler: %s", project, config, res.stderr.strip())
            return False

        dotenv_data = res.stdout
        out_path = Path(self.get_snapshot_path(project, config))
        out_path.parent.mkdir(parents=True, exist_ok=True)

        sops_res = subprocess.run(
            [sops_bin, "encrypt", "--filename-override", str(out_path), "--input-type", "dotenv", "--output-type", "dotenv", "--encrypted-regex", ".*"],
            input=dotenv_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self.repo_root),
        )
        if sops_res.returncode != 0:
            logger.error("Failed to encrypt snapshot for %s/%s: %s", project, config, sops_res.stderr.strip())
            return False

        out_path.write_text(sops_res.stdout, encoding="utf-8")
        return True

    def snapshot_all(self, vps_context: str = "A") -> tuple[int, int]:
        """Export all configs for a VPS from Doppler and encrypt to .snapshots."""
        vps = vps_context.upper()
        project = f"net-stream-vps-{vps.lower()}"

        logger.info("[INFO] Fetching configuration list for %s from Doppler...", project)
        cmd = ["doppler", "configs", "--project", project, "--json"]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if res.returncode != 0:
            logger.error("[ERROR] Failed to list Doppler configs: %s", res.stderr.strip())
            return 0, 1

        try:
            configs_data = json.loads(res.stdout)
        except json.JSONDecodeError:
            return 0, 1

        success_count = 0
        fail_count = 0

        for item in configs_data:
            cfg_name = item.get("name")
            if not cfg_name:
                continue
            logger.info("[INFO] Snapshotting %s/%s...", project, cfg_name)
            if self.snapshot_config(project, cfg_name):
                success_count += 1
            else:
                fail_count += 1

        logger.info("[SUCCESS] Snapshot complete for Node %s: %d succeeded, %d failed.", vps, success_count, fail_count)
        return success_count, fail_count

    def restore_env_from_snapshot(self, project: str, config: str) -> dict[str, str]:
        """Decrypt an encrypted SOPS snapshot in-memory and return a dictionary of secrets."""
        content_info = self.get_snapshot_content(project, config)
        if not content_info:
            path = self.get_snapshot_path(project, config)
            raise FileNotFoundError(f"Snapshot not found for {project}/{config} on branch snapshots/sync or at {path}")

        raw_enc, source_desc = content_info
        sops_bin = find_sops_binary(self.repo_root)
        if not sops_bin:
            raise RuntimeError("SOPS binary not found.")
        setup_age_key_env(self.repo_root)

        decrypt_target = "/dev/stdin"
        res = subprocess.run(
            [sops_bin, "--decrypt", "--input-type", "dotenv", "--output-type", "dotenv", decrypt_target],
            input=raw_enc,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self.repo_root),
        )
        if res.returncode != 0:
            raise RuntimeError(f"Failed to decrypt snapshot for {project}/{config} from {source_desc}: {res.stderr.strip()}")

        return parse_dotenv_content(res.stdout)

    def list_snapshots(self, vps_context: Optional[str] = None) -> list[dict]:
        """List all available snapshots with their sizes and timestamps."""
        snapshots = []
        if not self.snapshots_dir.exists():
            return snapshots

        projects = [f"net-stream-vps-{vps_context.lower()}"] if vps_context else os.listdir(str(self.snapshots_dir))

        for proj in projects:
            proj_dir = self.snapshots_dir / proj
            if not proj_dir.is_dir():
                continue
            for fname in sorted(os.listdir(str(proj_dir))):
                if fname.endswith(".env.enc"):
                    cfg = fname[:-8]
                    full_path = proj_dir / fname
                    size = full_path.stat().st_size
                    ts = self.get_snapshot_timestamp(proj, cfg)
                    snapshots.append({
                        "project": proj,
                        "config": cfg,
                        "path": str(full_path),
                        "size": size,
                        "timestamp": ts or "unknown",
                    })

        return snapshots


def _run_git(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Execute a git subcommand inside the given working directory."""
    res = subprocess.run(
        ["git"] + cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and res.returncode != 0:
        err = res.stderr.strip() or res.stdout.strip()
        raise RuntimeError(f"git {' '.join(cmd)} failed (exit {res.returncode}): {err}")
    return res


def sync_snapshots_to_branch(
    repo_root: Optional[Path] = None,
    branch: Optional[str] = None,
    remote: Optional[str] = None,
    base_branch: Optional[str] = None,
    vps_target: str = "all",
) -> tuple[bool, str]:
    """Refresh encrypted secrets snapshots in an isolated git worktree and push to a dedicated branch."""
    root = repo_root or REPO_ROOT
    sync_branch = branch or DEFAULT_SYNC_BRANCH
    remote_name = remote or DEFAULT_REMOTE
    base = base_branch or DEFAULT_BASE_BRANCH

    if not (root / ".git").is_dir():
        msg = f"Cannot sync snapshots: {root} is not a git repository."
        logger.error(msg)
        return False, msg

    _run_git(["worktree", "prune"], cwd=root, check=False)

    has_remote_branch = False
    res_ls = _run_git(["ls-remote", "--heads", remote_name, sync_branch], cwd=root, check=False)
    if res_ls.returncode == 0 and res_ls.stdout.strip():
        has_remote_branch = True

    if has_remote_branch:
        _run_git(["fetch", remote_name, f"+{sync_branch}:{sync_branch}"], cwd=root, check=False)
        start_ref = sync_branch
    else:
        start_ref = base

    worktree_dir = Path(tempfile.mkdtemp(prefix="net-stream-sync-"))

    try:
        _run_git(["worktree", "add", "--detach", str(worktree_dir), start_ref, "--quiet"], cwd=root)
        _run_git(["checkout", "-B", sync_branch, "--quiet"], cwd=worktree_dir)

        sops_config = root / ".sops.yaml"
        if sops_config.is_file() and not (worktree_dir / ".sops.yaml").is_file():
            shutil.copy2(sops_config, worktree_dir / ".sops.yaml")

        sm = SnapshotManager(repo_root=worktree_dir)
        vps_upper = vps_target.upper()

        total_succeeded = 0
        total_failed = 0

        if vps_upper == "ALL":
            for node_id in sorted(get_valid_node_ids()):
                s, f = sm.snapshot_all(vps_context=node_id)
                total_succeeded += s
                total_failed += f
        else:
            s, f = sm.snapshot_all(vps_context=vps_upper)
            total_succeeded += s
            total_failed += f

        if total_failed > 0:
            raise RuntimeError(
                f"Snapshot generation failed for {total_failed} config(s) ({total_succeeded} succeeded). "
                f"Aborting sync to prevent publishing incomplete snapshots."
            )

        _run_git(["add", "-f", ".snapshots/"], cwd=worktree_dir)
        res_diff = _run_git(["diff", "--cached", "--quiet"], cwd=worktree_dir, check=False)
        if res_diff.returncode == 0:
            msg = "No snapshot changes detected. Everything is up to date."
            logger.info("[SUCCESS] %s", msg)
            return True, msg

        res_names = _run_git(["diff", "--cached", "--name-only"], cwd=worktree_dir)
        changed_files = [line.strip() for line in res_names.stdout.strip().splitlines() if line.strip()]
        changed_count = len(changed_files)

        commit_msg = (
            f"chore(secrets): automated snapshot sync [skip ci]\n\n"
            f"- Updated {changed_count} encrypted snapshots in .snapshots/\n"
            f"- VPS Target: {vps_target}\n"
            f"- Generated automatically by orchestrator.secrets.snapshots"
        )
        _run_git(["commit", "-m", commit_msg, "--quiet"], cwd=worktree_dir)
        _run_git(["push", "-u", remote_name, sync_branch, "--quiet"], cwd=worktree_dir)

        msg = f"Successfully synchronized {changed_count} snapshot(s) to {remote_name}/{sync_branch}."
        logger.info("[SUCCESS] %s", msg)
        return True, msg

    except Exception as e:
        msg = f"Snapshot worktree sync failed: {e}"
        logger.error("[ERROR] %s", msg)
        return False, msg
    finally:
        try:
            _run_git(["worktree", "remove", "--force", str(worktree_dir)], cwd=root, check=False)
        except Exception:
            pass
        if worktree_dir.exists():
            shutil.rmtree(worktree_dir, ignore_errors=True)
