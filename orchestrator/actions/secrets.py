"""Doppler and SOPS encrypted secrets management action orchestrator."""

import logging
import sys
import webbrowser

from orchestrator.actions.base import BaseAction
from orchestrator.core.constants import REPO_ROOT
from orchestrator.core.models import ActionContext, ExecutionResult
from orchestrator.core.state import get_active_vps
from orchestrator.registry.manifest import get_valid_node_ids
from orchestrator.secrets.doppler import (
    DOPPLER_DASHBOARD_URL,
    default_doppler_client,
)
from orchestrator.secrets.snapshots import sync_snapshots_to_branch

logger = logging.getLogger(__name__)


class SecretsAction(BaseAction):
    """Orchestrates Doppler secrets operations and SOPS offline fallback snapshot workflows."""

    action_name = "secrets"

    def run(self, context: ActionContext) -> ExecutionResult:
        """Execute secrets action subcommand."""
        target_vps = (context.vps or get_active_vps()).upper()
        subcmd = context.targets[0] if context.targets else "verify"
        remaining_args = context.targets[1:] if len(context.targets) > 1 else []

        if subcmd in ("sync", "prune", "snapshot", "sync-branch") and not context.dry_run:
            from orchestrator.core.guards import verify_branch_guard

            guard = verify_branch_guard(f"secrets {subcmd}", context)
            if guard is not None:
                return guard

        if subcmd == "open":
            print(f"[INFO] Opening Doppler dashboard: {DOPPLER_DASHBOARD_URL}")
            try:
                webbrowser.open(DOPPLER_DASHBOARD_URL)
            except Exception as e:
                logger.warning("Could not launch web browser: %s", e)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message=f"Opened {DOPPLER_DASHBOARD_URL}",
            )

        if subcmd == "verify":
            ok = default_doppler_client.is_authenticated()
            if ok:
                print("[SUCCESS] Doppler CLI is authenticated and active.")
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=True,
                    exit_code=0,
                    message="Doppler CLI authenticated.",
                )
            else:
                print("[ERROR] Doppler CLI verification failed: Not logged in", file=sys.stderr)
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=False,
                    exit_code=1,
                    message="Doppler CLI verification failed.",
                )

        if subcmd == "sync":
            from orchestrator.secrets.doppler import sync_repository_configs

            created, missing = sync_repository_configs(dry_run=context.dry_run)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message=f"Doppler sync complete: {created} created, {missing} missing.",
            )

        if subcmd == "audit":
            from orchestrator.secrets.doppler import audit_repository_secrets

            code = audit_repository_secrets()
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=(code == 0),
                exit_code=code,
                message="Doppler secrets audit passed." if code == 0 else "Doppler secrets audit failed.",
            )

        if subcmd == "prune":
            print("\n[NOTE] Doppler CLI output does not distinguish inherited from explicit keys.")
            print("[NOTE] Verify redundant keys in the Doppler Web Dashboard ('./manage.py secrets open') before pruning.")

            vps_targets = sorted(get_valid_node_ids()) if target_vps == "ALL" else [target_vps]
            proj_names = ", ".join(f"net-stream-vps-{v.lower()}" for v in vps_targets)
            prompt = f"secrets prune will delete redundant entries from Doppler project(s) {proj_names}. Proceed?"
            from orchestrator.ui.prompts import confirm_action

            if not confirm_action(prompt, yes=context.yes):
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=False,
                    exit_code=1,
                    message="Secrets prune cancelled by user.",
                )

            from orchestrator.secrets.doppler import prune_redundant_secrets

            dry_run = context.dry_run or ("--dry-run" in remaining_args)
            total_removed, total_failed = 0, 0
            for node_vps in vps_targets:
                rem, fl = prune_redundant_secrets(vps_context=node_vps, dry_run=dry_run)
                total_removed += rem
                total_failed += fl

            success = (total_failed == 0)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=success,
                exit_code=0 if success else 1,
                message=f"Prune finished: {total_removed} removed, {total_failed} failed.",
            )

        if subcmd in ("snapshot", "snapshots-create"):
            from orchestrator.secrets.snapshots import SnapshotManager

            sm = SnapshotManager(repo_root=REPO_ROOT)
            vps_tgt = target_vps if context.vps and context.vps != "ALL" else "ALL"
            if vps_tgt == "ALL":
                s_total, f_total = 0, 0
                for node_id in sorted(get_valid_node_ids()):
                    s, f = sm.snapshot_all(vps_context=node_id)
                    s_total += s
                    f_total += f
                s, f = s_total, f_total
            else:
                s, f = sm.snapshot_all(vps_context=vps_tgt)

            success = (f == 0)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=success,
                exit_code=0 if success else 1,
                message=f"Snapshot generation complete: {s} succeeded, {f} failed.",
            )

        if subcmd == "snapshot-config":
            if target_vps == "ALL":
                print("ERROR: snapshot-config requires a specific node (--vps A or --vps B), not ALL.", file=sys.stderr)
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=False,
                    exit_code=2,
                    message="snapshot-config does not support --vps ALL.",
                )
            if not remaining_args:
                print("ERROR: snapshot-config requires a config name (e.g. auth_authelia).", file=sys.stderr)
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=False,
                    exit_code=2,
                    message="Missing config name argument.",
                )
            cfg = remaining_args[0]
            project = f"net-stream-vps-{target_vps.lower()}"

            from orchestrator.secrets.snapshots import SnapshotManager

            sm = SnapshotManager(repo_root=REPO_ROOT)
            ok = sm.snapshot_config(project, cfg)
            if ok:
                print(f"[SUCCESS] Snapshotted {project}/{cfg} to .snapshots/")
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=True,
                    exit_code=0,
                    message=f"Snapshotted {project}/{cfg} to .snapshots/",
                )
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=False,
                exit_code=1,
                message=f"Failed to snapshot {project}/{cfg}.",
            )

        if subcmd == "snapshots":
            from orchestrator.secrets.snapshots import SnapshotManager

            sm = SnapshotManager(repo_root=REPO_ROOT)
            items = sm.list_snapshots(vps_context=context.vps if context.vps != "ALL" else None)
            if not items:
                print("[INFO] No encrypted snapshots found in .snapshots/.")
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=True,
                    exit_code=0,
                    message="No encrypted snapshots found in .snapshots/.",
                )

            print(f"\n[INFO] Found {len(items)} SOPS-encrypted snapshot(s):")
            print(f"{'PROJECT':<20} {'CONFIG':<35} {'SIZE':<10} {'TIMESTAMP'}")
            print("-" * 80)
            for it in items:
                print(f"{it['project']:<20} {it['config']:<35} {it['size']:<10} {it['timestamp']}")

            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message=f"Found {len(items)} snapshot(s).",
            )

        if subcmd in ("sync-branch", "sync-snapshots"):
            branch = "snapshots/sync"
            remote = "origin"
            base = "main"

            i = 0
            while i < len(remaining_args):
                arg = remaining_args[i]
                if arg == "--branch" and i + 1 < len(remaining_args):
                    branch = remaining_args[i + 1]
                    i += 2
                elif arg.startswith("--branch="):
                    branch = arg.split("=", 1)[1]
                    i += 1
                elif arg == "--remote" and i + 1 < len(remaining_args):
                    remote = remaining_args[i + 1]
                    i += 2
                elif arg.startswith("--remote="):
                    remote = arg.split("=", 1)[1]
                    i += 1
                elif arg in ("--base", "--base-branch") and i + 1 < len(remaining_args):
                    base = remaining_args[i + 1]
                    i += 2
                elif arg.startswith("--base=") or arg.startswith("--base-branch="):
                    base = arg.split("=", 1)[1]
                    i += 1
                else:
                    i += 1

            vps_tgt = target_vps.lower() if context.vps and context.vps != "ALL" else "all"
            success, msg = sync_snapshots_to_branch(
                repo_root=REPO_ROOT,
                vps_target=vps_tgt,
                branch=branch,
                remote=remote,
                base_branch=base,
            )
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=success,
                exit_code=0 if success else 1,
                message=msg,
            )

        print(
            f"ERROR: Unknown secrets subcommand '{subcmd}'. Expected: open, verify, sync, audit, prune, snapshot, snapshot-config, snapshots, sync-branch",
            file=sys.stderr,
        )
        return ExecutionResult(
            service=None,
            action=self.action_name,
            success=False,
            exit_code=1,
            message=f"Unknown secrets subcommand '{subcmd}'.",
        )


def main(argv=None) -> int:
    """CLI entrypoint for secrets action."""
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

    from orchestrator.actions.base import create_action_parser, parse_action_targets

    parser = create_action_parser(
        prog="secrets",
        description="Manage Doppler SaaS secrets and offline fallback snapshots.",
        with_targets=True,
        with_vps=True,
        with_yes=True,
        with_dry_run=True,
        allow_all_nodes=True,
    )

    raw_args = list(argv if argv is not None else sys.argv[1:])
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    action = SecretsAction()
    ctx = ActionContext(
        targets=parse_action_targets(args),
        vps=args.vps,
        yes=args.yes,
        dry_run=args.dry_run,
        allow_dev=args.allow_dev,
    )
    res = action.execute(ctx)
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
