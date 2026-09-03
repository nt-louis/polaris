"""Backup and restore action orchestrator managing Restic operations and post-backup auto-sync."""

import json
import logging
import os
import shutil
import subprocess
import sys

try:
    import pwd
except ImportError:
    pwd = None

from orchestrator.actions.base import BaseAction
from orchestrator.core.constants import REPO_ROOT
from orchestrator.core.guards import is_test_environment
from orchestrator.core.models import ActionContext, ExecutionResult
from orchestrator.core.state import get_active_vps
from orchestrator.secrets.snapshots import sync_snapshots_to_branch

logger = logging.getLogger(__name__)

BACKUP_DOPPLER_CONFIG = "backup"

BACKUP_PRESERVED_ENV = (
    "BACKUP_PASSWORD",
    "RCLONE_REMOTE",
    "RCLONE_REMOTE_SECONDARY",
    "STOP_DURING_BACKUP",
    "KEEP_DAILY",
    "KEEP_WEEKLY",
    "KEEP_MONTHLY",
    "BACKUP_DIR",
    "BASE_PATH",
    "RESTIC_CACHE_DIR",
    "RCLONE_CONFIG",
)


def build_backup_command(
    script_path: str,
    args: list[str],
    vps: str = "A",
    force_prefetch: bool = False,
) -> list[str]:
    """Run a backup script with secrets injected by the active VPS Doppler config."""
    project = f"net-stream-vps-{vps.lower()}"

    # Ensure --vps is explicitly passed to backup scripts so they target the resolved node
    fwd_args = list(args)
    has_vps_arg = any(a == "--vps" or a.startswith("--vps=") for a in fwd_args)
    if not has_vps_arg:
        fwd_args = ["--vps", vps] + fwd_args

    # Cron invokes manage.py as root, while Doppler authentication belongs to
    # the repository owner. Fetch the backup config in memory as that user,
    # then execute the backup script directly as root. Fail closed if prefetch fails.
    if hasattr(os, "geteuid") and os.geteuid() == 0 and (not is_test_environment() or force_prefetch):
        if pwd is None:
            raise RuntimeError("Cannot resolve repository owner for root backup execution (pwd module unavailable).")
        try:
            repo_uid = os.stat(str(REPO_ROOT)).st_uid
            repo_user = pwd.getpwuid(repo_uid).pw_name if repo_uid != 0 else None
            cmd_prefix = ["sudo", "-u", repo_user, "-H"] if (repo_user and repo_user != "root" and shutil.which("sudo")) else []
            result = subprocess.run(
                cmd_prefix + [
                    "doppler", "secrets", "download",
                    "--format", "json", "--no-file",
                    "--project", project,
                    "--config", BACKUP_DOPPLER_CONFIG,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if result.returncode != 0:
                err_msg = result.stderr.strip() or f"exit code {result.returncode}"
                raise RuntimeError(f"Doppler download failed for root backup execution: {err_msg}")

            backup_values = json.loads(result.stdout)
            for key in BACKUP_PRESERVED_ENV:
                if key in backup_values:
                    os.environ[key] = backup_values[key]
            return ["bash", script_path] + fwd_args
        except Exception as ex:
            logger.error("[ERROR] Failed to pre-fetch Doppler backup credentials for root execution: %s", ex)
            raise

    preserved_env = ",".join(BACKUP_PRESERVED_ENV)
    return [
        "doppler", "run",
        "--project", project,
        "--config", BACKUP_DOPPLER_CONFIG,
        "--",
        "sudo", f"--preserve-env={preserved_env}",
        "bash", script_path,
    ] + fwd_args


class BackupAction(BaseAction):
    """Orchestrates Restic backups, restores, snapshots listing, pruning, and post-backup sync."""

    action_name = "backup"

    def run(self, context: ActionContext) -> ExecutionResult:
        """Execute backup operation."""
        target_vps = (context.vps or get_active_vps()).upper()
        subcmd = context.targets[0] if context.targets else "run"
        remaining_args = context.targets[1:] if len(context.targets) > 1 else []

        valid_subcmds = ("run", "restore", "snapshots", "check", "prune", "stats")
        if subcmd not in valid_subcmds:
            # If target[0] is not a valid subcommand, treat all targets as arguments to 'run'
            subcmd = "run"
            remaining_args = list(context.targets)

        if subcmd in ("run", "restore", "prune") and not context.dry_run:
            from orchestrator.core.guards import verify_branch_guard

            guard = verify_branch_guard(f"backup {subcmd}", context)
            if guard is not None:
                return guard

        if subcmd == "restore":
            is_preview = (
                context.dry_run
                or "--dry-run" in remaining_args
                or "-n" in remaining_args
                or "--preview" in remaining_args
            )
            if is_preview:
                logger.info(
                    "[DRY-RUN] Restore preview for Node %s: listing snapshots (dry-run mode, no disk changes).",
                    target_vps,
                )
                restore_script = str(REPO_ROOT / "orchestrator" / "scripts" / "backup" / "restore-all.sh")
                clean_args = [a for a in remaining_args if a not in ("--dry-run", "-n", "--preview")]
                cmd = build_backup_command(restore_script, ["--list"] + clean_args, vps=target_vps)
                res = subprocess.call(cmd)
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=(res == 0),
                    exit_code=res,
                    message="Restore dry-run preview completed." if res == 0 else f"Restore preview failed with exit code {res}.",
                )

            from orchestrator.ui.prompts import confirm_action

            if not confirm_action(
                f"backup restore OVERWRITES current state on Node {target_vps} from a Restic snapshot. Proceed?",
                yes=context.yes,
                danger=True,
            ):
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=False,
                    exit_code=1,
                    message="Operation cancelled by user.",
                )

            restore_script = str(REPO_ROOT / "orchestrator" / "scripts" / "backup" / "restore-all.sh")
            fwd = list(remaining_args)
            if context.yes and not any(a in ("--yes", "-y") for a in fwd):
                fwd.append("--yes")

            cmd = build_backup_command(restore_script, fwd, vps=target_vps)
            res = subprocess.call(cmd)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=(res == 0),
                exit_code=res,
                message="Restore completed." if res == 0 else f"Restore failed with exit code {res}.",
            )

        if subcmd == "run":
            backup_script = str(REPO_ROOT / "orchestrator" / "scripts" / "backup" / "backup-all.sh")
            fwd = [a for a in remaining_args if a not in ("--yes", "-y")]
            if context.dry_run and "--dry-run" not in fwd:
                fwd.append("--dry-run")

            cmd = build_backup_command(backup_script, fwd, vps=target_vps)
            code = subprocess.call(cmd)

            if code == 0 and not context.dry_run and "--dry-run" not in fwd:
                logger.info("[INFO] Synchronizing offline encrypted secrets snapshots...")
                sync_snapshots_to_branch(repo_root=REPO_ROOT, vps_target=target_vps.lower())

            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=(code == 0),
                exit_code=code,
                message="Backup completed successfully." if code == 0 else f"Backup failed with exit code {code}.",
            )

        if subcmd == "snapshots":
            restore_script = str(REPO_ROOT / "orchestrator" / "scripts" / "backup" / "restore-all.sh")
            fwd = [a for a in remaining_args if a not in ("--yes", "-y")]
            cmd = build_backup_command(restore_script, ["--list"] + fwd, vps=target_vps)
            code = subprocess.call(cmd)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=(code == 0),
                exit_code=code,
                message="Listed snapshots." if code == 0 else f"Snapshot listing failed with exit code {code}.",
            )

        if subcmd == "check":
            check_script = str(REPO_ROOT / "orchestrator" / "scripts" / "backup" / "backup-check.sh")
            fwd = [a for a in remaining_args if a not in ("--yes", "-y")]
            cmd = build_backup_command(check_script, fwd, vps=target_vps)
            code = subprocess.call(cmd)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=(code == 0),
                exit_code=code,
                message="Repository check completed." if code == 0 else f"Repository check failed with code {code}.",
            )

        if subcmd == "prune":
            prune_script = str(REPO_ROOT / "orchestrator" / "scripts" / "backup" / "backup-prune.sh")
            fwd = [a for a in remaining_args if a not in ("--yes", "-y")]
            if context.dry_run and "--dry-run" not in fwd:
                fwd.append("--dry-run")
            cmd = build_backup_command(prune_script, fwd, vps=target_vps)
            code = subprocess.call(cmd)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=(code == 0),
                exit_code=code,
                message="Repository prune completed." if code == 0 else f"Repository prune failed with code {code}.",
            )

        if subcmd == "stats":
            stats_script = str(REPO_ROOT / "orchestrator" / "scripts" / "backup" / "backup-stats.sh")
            fwd = [a for a in remaining_args if a not in ("--yes", "-y")]
            cmd = build_backup_command(stats_script, fwd, vps=target_vps)
            code = subprocess.call(cmd)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=(code == 0),
                exit_code=code,
                message="Repository stats retrieved." if code == 0 else f"Repository stats failed with code {code}.",
            )

        return ExecutionResult(
            service=None,
            action=self.action_name,
            success=False,
            exit_code=1,
            message=f"Unknown backup subcommand '{subcmd}'.",
        )


def main(argv=None) -> int:
    """CLI entrypoint for backup action."""
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

    from orchestrator.actions.base import create_action_parser, parse_action_targets

    parser = create_action_parser(
        prog="backup",
        description="Manage stack backups, restores, snapshots, pruning, and verification (Restic).",
        with_targets=True,
        with_vps=True,
        with_yes=True,
        with_dry_run=True,
    )
    parser.add_argument("--preview", action="store_true", help="Preview restore snapshots without restoring")

    raw_args = list(argv if argv is not None else sys.argv[1:])
    try:
        args, unknown = parser.parse_known_args(raw_args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    dry_run = args.dry_run or args.preview
    action = BackupAction()
    ctx = ActionContext(
        targets=parse_action_targets(args) + unknown,
        vps=args.vps,
        yes=args.yes,
        dry_run=dry_run,
        allow_dev=args.allow_dev,
    )
    res = action.execute(ctx)
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
