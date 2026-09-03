"""Doppler SaaS secret management client and process injection wrapper.

Provides type-safe wrappers for Doppler CLI authentication, project/config resolution,
and runtime process variable injection without exposing secret values to disk or logs.
"""

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from orchestrator.core.constants import REPO_ROOT
from orchestrator.core.models import ServiceMetadata

logger = logging.getLogger(__name__)

DOPPLER_DASHBOARD_URL = "https://dashboard.doppler.com/workplace"


def clean_slug(text: str) -> str:
    """Convert a path or category string into a valid Doppler slug."""
    slug = re.sub(r"[^a-zA-Z0-9_]", "_", text)
    slug = re.sub(r"_+", "_", slug).strip("_").lower()
    return slug


def get_short_category_slug(category_name: str, rel_dir: str) -> str:
    """Map categories to concise Doppler environment slugs."""
    cat_lower = (category_name or "").lower()
    rel_lower = (rel_dir or "").lower()

    if (
        "network" in cat_lower
        or "gateway" in rel_lower
        or "exit-node" in rel_lower
        or "cloudflare-tunnel" in rel_lower
        or "netbird-server" in rel_lower
        or rel_lower == "network"
    ):
        return "network"
    elif "auth" in cat_lower:
        return "auth"
    elif "admin" in cat_lower:
        return "admin"
    elif "monitoring" in cat_lower:
        return "monitoring"
    elif "cloud" in cat_lower or "docs" in cat_lower:
        return "cloud_docs"
    elif (
        "tools" in cat_lower
        or "bookmarks" in cat_lower
        or "information" in cat_lower
        or "search" in cat_lower
    ):
        return "tools"
    elif "comics" in cat_lower:
        return "comics"
    elif "stremio" in cat_lower:
        return "stremio"
    elif "local-media" in cat_lower:
        return "local_media"
    else:
        return clean_slug(category_name)


def get_doppler_project(vps_context: Optional[str] = "A") -> str:
    """Return the Doppler project name for a VPS context ('A' or 'B')."""
    vps_upper = (vps_context or "A").upper()
    return f"net-stream-vps-{vps_upper.lower()}"


def get_doppler_config(
    rel_dir: str,
    service_name: str,
    category_name: str = "",
) -> str:
    """Compute the Doppler config name for a service according to the inheritance tree."""
    env_slug = get_short_category_slug(category_name, rel_dir)

    if rel_dir == "Network":
        service_name = "exit_node"

    # Gateway and exit-node services exist in multiple directories.
    # Use full rel_dir so each maps to a distinct config name.
    if clean_slug(service_name) in ("gateway", "exit_node") and rel_dir != "Network":
        clean_svc = clean_slug(rel_dir)
    else:
        clean_svc = clean_slug(service_name)

    return f"{env_slug}_{clean_svc}"[:60]


class DopplerClient:
    """Type-safe interface to the Doppler CLI."""

    def __init__(self, repo_root: Optional[Path] = None):
        self.repo_root = repo_root or REPO_ROOT

    def get_cmd_prefix(self) -> list[str]:
        """Return CLI prefix, delegating from root to repo owner when necessary."""
        if os.environ.get("DOPPLER_TOKEN"):
            return ["doppler"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            try:
                import pwd

                repo_uid = os.stat(str(self.repo_root)).st_uid
                repo_user = pwd.getpwuid(repo_uid).pw_name
                if repo_user and repo_user != "root":
                    return ["sudo", "-u", repo_user, "-H", "doppler"]
            except Exception:
                pass
        return ["doppler"]

    def is_authenticated(self) -> bool:
        """Check if Doppler CLI is authenticated and reachable."""
        if os.environ.get("DOPPLER_TOKEN"):
            return True
        try:
            cmd = self.get_cmd_prefix() + ["me", "--json"]
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            return res.returncode == 0
        except Exception:
            return False

    def wrap_command(
        self,
        cmd: list[str],
        service: Optional[ServiceMetadata] = None,
        vps: Optional[str] = None,
        config: Optional[str] = None,
    ) -> list[str]:
        """Wrap a shell command with 'doppler run --project ... --config ... --'."""
        if not service and not config:
            return list(cmd)

        vps_ctx = vps or (service.vps if service else "A")
        project = get_doppler_project(vps_ctx)

        if config:
            cfg = config
        elif service:
            cfg = get_doppler_config(service.rel_dir, service.name, service.category)
        else:
            cfg = "prd"

        return self.get_cmd_prefix() + [
            "run",
            "--project",
            project,
            "--config",
            cfg,
            "--",
        ] + cmd

    def fetch_secrets(
        self,
        project: str,
        config: str,
        format_type: str = "json",
    ) -> str:
        """Fetch raw secrets from Doppler (JSON or ENV format).

        CAUTION: Never log or print return values.
        """
        cmd = self.get_cmd_prefix() + [
            "secrets",
            "download",
            "--format",
            format_type,
            "--no-file",
            "--project",
            project,
            "--config",
            config,
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Doppler secrets download failed for {project}/{config}: {res.stderr.strip()}")
        return res.stdout

    def fetch_secrets_dict(self, project: str, config: str) -> dict[str, str]:
        """Download secrets and parse into a dictionary."""
        raw_json = self.fetch_secrets(project, config, format_type="json")
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse Doppler secrets JSON for {project}/{config}: {e}")

    def open_dashboard(self) -> int:
        """Open Doppler SaaS web dashboard."""
        return subprocess.call(["doppler", "open"])


default_doppler_client = DopplerClient()


def check_missing_secrets(service: ServiceMetadata, repo_root: Optional[Path] = None) -> list[str]:
    """Check if any environment variables declared in compose file are missing from Doppler."""
    root = repo_root or REPO_ROOT
    abs_dir = root / service.rel_dir
    compose_path = abs_dir / "docker-compose.yml"
    if not compose_path.is_file():
        return []

    required_keys: set[str] = set()
    try:
        content = compose_path.read_text(encoding="utf-8")
        # Match ${VAR} or ${VAR:-default} or ${VAR:?error}
        for match in re.finditer(r"\$\{([a-zA-Z0-9_]+)(?::[-=?][^}]*)?\}", content):
            required_keys.add(match.group(1))

        # Check env_file directives if present
        for match in re.finditer(r"env_file:\s*\n(?:\s*-\s*([^\n]+)\n)+", content):
            env_file_section = match.group(0)
            for file_match in re.finditer(r"-\s*([^\n]+)", env_file_section):
                env_file_rel = file_match.group(1).strip().strip("'\"")
                env_file_abs = abs_dir / env_file_rel
                if env_file_abs.is_file():
                    for line in env_file_abs.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key = line.split("=")[0].split(":")[0].strip()
                            if key:
                                required_keys.add(key)
    except Exception:
        return []

    if not required_keys:
        return []

    doppler_proj = get_doppler_project(service.vps)
    doppler_cfg = get_doppler_config(service.rel_dir, service.name, service.category)

    client = DopplerClient(repo_root=root)
    try:
        actual_secrets = client.fetch_secrets_dict(doppler_proj, doppler_cfg)
        actual_keys = set(actual_secrets.keys())
    except Exception:
        return sorted(list(required_keys))

    missing = required_keys - actual_keys
    return sorted(list(missing))


def audit_repository_secrets(repo_root: Optional[Path] = None) -> int:
    """Audit all registered services to ensure Doppler has all declared environment variables."""
    from orchestrator.registry.manifest import load_services

    root = repo_root or REPO_ROOT
    client = DopplerClient(repo_root=root)
    if not client.is_authenticated():
        print("[ERROR] Doppler CLI is not authenticated. Run 'doppler login'.", file=sys.stderr)
        return 1

    services = load_services()
    print(f"[INFO] Auditing secrets for {len(services)} services across Doppler...")

    missing_by_service = {}
    for svc in services:
        missing = check_missing_secrets(svc, repo_root=root)
        if missing:
            missing_by_service[f"[{svc.vps}] {svc.name} ({svc.rel_dir})"] = missing

    if missing_by_service:
        print(f"\n[FAIL] Found {len(missing_by_service)} service(s) with missing Doppler secrets:")
        for svc_label, keys in missing_by_service.items():
            print(f"  ✖ {svc_label}:")
            for k in keys:
                print(f"      - {k}")
        print("\nPopulate missing secrets via Doppler CLI or web dashboard ('./manage.py secrets open').")
        return 1

    print("[SUCCESS] All services have complete secrets in Doppler.")
    return 0


def sync_repository_configs(dry_run: bool = False, repo_root: Optional[Path] = None) -> tuple[int, int]:
    """Ensure all required Doppler environments and service configs exist in Doppler projects."""
    from orchestrator.registry.manifest import get_valid_node_ids, load_services

    root = repo_root or REPO_ROOT
    client = DopplerClient(repo_root=root)
    if not client.is_authenticated():
        print("[ERROR] Doppler CLI is not authenticated. Run 'doppler login'.", file=sys.stderr)
        return 0, 1

    services = load_services()
    total_created = 0
    total_missing = 0

    for node_id in sorted(get_valid_node_ids()):
        proj = get_doppler_project(node_id)
        node_services = [s for s in services if s.vps == node_id]

        print(f"\n[INFO] Checking Doppler project: {proj} ({len(node_services)} services)...")
        cmd = client.get_cmd_prefix() + ["configs", "--project", proj, "--json"]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            print(f"[ERROR] Failed to list configs for {proj}: {res.stderr.strip()}", file=sys.stderr)
            total_missing += 1
            continue

        try:
            existing_configs = {c["name"] for c in json.loads(res.stdout)}
        except Exception:
            existing_configs = set()

        # Environments
        required_envs = {get_short_category_slug(s.category, s.rel_dir) for s in node_services}
        for env in sorted(required_envs):
            if env not in existing_configs:
                total_missing += 1
                if dry_run:
                    print(f"  [DRY-RUN] Would create environment config: {env}")
                else:
                    create_cmd = client.get_cmd_prefix() + [
                        "environments", "create", env,
                        "--project", proj,
                        "--slug", env,
                    ]
                    c_res = subprocess.run(create_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if c_res.returncode == 0:
                        print(f"  [CREATED] Environment: {env}")
                        total_created += 1
                        existing_configs.add(env)
                    else:
                        print(f"  [ERROR] Failed to create environment {env}: {c_res.stderr.strip()}", file=sys.stderr)

        # Service configs
        for s in node_services:
            cfg_name = get_doppler_config(s.rel_dir, s.name, s.category)
            env_slug = get_short_category_slug(s.category, s.rel_dir)
            if cfg_name not in existing_configs and cfg_name != env_slug:
                total_missing += 1
                if dry_run:
                    print(f"  [DRY-RUN] Would create service config: {cfg_name} (parent: {env_slug})")
                else:
                    create_cfg_cmd = client.get_cmd_prefix() + [
                        "configs", "create", cfg_name,
                        "--project", proj,
                        "--environment", env_slug,
                    ]
                    cc_res = subprocess.run(create_cfg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if cc_res.returncode == 0:
                        print(f"  [CREATED] Config: {cfg_name} (parent: {env_slug})")
                        total_created += 1
                        existing_configs.add(cfg_name)
                    else:
                        print(f"  [ERROR] Failed to create config {cfg_name}: {cc_res.stderr.strip()}", file=sys.stderr)

    return total_created, total_missing


def prune_redundant_secrets(vps_context: str = "A", dry_run: bool = False, repo_root: Optional[Path] = None) -> tuple[int, int]:
    """Remove secrets from child service configs that are already inherited from parent environment."""
    from orchestrator.registry.manifest import load_services

    root = repo_root or REPO_ROOT
    client = DopplerClient(repo_root=root)
    if not client.is_authenticated():
        print("[ERROR] Doppler CLI is not authenticated. Run 'doppler login'.", file=sys.stderr)
        return 0, 1

    services = [s for s in load_services() if s.vps == vps_context.upper()]
    doppler_proj = get_doppler_project(vps_context)

    environments = {get_short_category_slug(s.category, s.rel_dir) for s in services}
    if dry_run:
        print("[INFO] Dry-run mode — no changes will be made to Doppler.")
    print(f"[INFO] Fetching {len(environments)} parent environment configs from {doppler_proj}...")

    env_secrets = {}
    for env in environments:
        try:
            secrets = client.fetch_secrets_dict(doppler_proj, env)
            env_secrets[env] = secrets
        except Exception:
            print(f"[WARNING] Could not fetch parent environment '{env}' in {doppler_proj}; skipping children.", file=sys.stderr)

    pruned_total = 0
    failed_total = 0

    for s in services:
        env = get_short_category_slug(s.category, s.rel_dir)
        if env not in env_secrets:
            continue

        cfg_name = get_doppler_config(s.rel_dir, s.name, s.category)
        if cfg_name == env:
            continue

        try:
            child_secrets = client.fetch_secrets_dict(doppler_proj, cfg_name)
        except Exception:
            continue

        parent_secrets = env_secrets[env]
        redundant_keys = [
            k for k in child_secrets
            if not k.startswith("DOPPLER_")
            and k in parent_secrets
            and child_secrets[k] == parent_secrets[k]
        ]

        if not redundant_keys:
            continue

        action = "Would prune" if dry_run else "Pruning"
        print(f"[INFO] {action} {len(redundant_keys)} redundant keys from {cfg_name} (inherited from {env}): {redundant_keys}")

        if dry_run:
            pruned_total += len(redundant_keys)
            continue

        del_cmd = client.get_cmd_prefix() + [
            "secrets", "delete",
            "--project", doppler_proj,
            "--config", cfg_name,
            "--yes",
        ] + redundant_keys
        delete_res = subprocess.run(del_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if delete_res.returncode == 0:
            pruned_total += len(redundant_keys)
        else:
            failed_total += len(redundant_keys)
            print(f"[ERROR] Failed to delete redundant keys from {cfg_name}: {delete_res.stderr.strip()}", file=sys.stderr)

    action = "Would remove" if dry_run else "Removed"
    print(f"[SUCCESS] Pruning complete. {action} {pruned_total} redundant secret entries across Node {vps_context}.")
    return pruned_total, failed_total

