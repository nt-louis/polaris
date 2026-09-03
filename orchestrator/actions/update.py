"""Update action orchestrator handling image updates, age-gating, and container recreation."""

import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from orchestrator.actions.base import BaseAction
from orchestrator.core.models import ActionContext, ExecutionResult
from orchestrator.core.state import get_active_vps
from orchestrator.docker.client import DockerClient
from orchestrator.docker.compose import ComposeEngine
from orchestrator.registry.discovery import load_services

logger = logging.getLogger(__name__)


class UpdateAction(BaseAction):
    """Orchestrates image registry checks, age gating, image backup tagging, and container updates."""

    action_name = "update"

    def __init__(
        self,
        compose_engine: Optional[ComposeEngine] = None,
        docker_client: Optional[DockerClient] = None,
    ) -> None:
        self.compose_engine = compose_engine or ComposeEngine()
        self.docker_client = docker_client or DockerClient()

    def run(self, context: ActionContext) -> ExecutionResult:
        """Execute update action based on context flags."""
        target_vps = (context.vps or get_active_vps()).upper()

        if context.check:
            return self.execute_check(context, target_vps)

        if context.list_backups:
            return self.execute_list_backups()

        from orchestrator.core.guards import verify_branch_guard

        guard = verify_branch_guard(self.action_name, context)
        if guard is not None:
            return guard

        return self.execute_updates(context, target_vps)

    def execute_list_backups(self) -> ExecutionResult:
        """List container images backed up prior to past updates."""
        try:
            res = subprocess.run(
                ["docker", "images", "--format", "{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedAt}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as e:
            logger.info("[INFO] Docker unavailable: %s", e)
            print("[INFO] No backup images found (Docker unavailable).")
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message="Docker CLI unavailable.",
            )

        if res.returncode != 0:
            logger.info("[INFO] Failed to query Docker images: %s", res.stderr.strip())
            print("[INFO] No backup images found.")
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message="No backup images found.",
            )

        pattern = re.compile(r":backup-(\d{8})-(\d{6})$")
        backups = []

        for line in res.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(maxsplit=2)
            if len(parts) < 2:
                continue
            image_ref, image_id = parts[0], parts[1]
            created_at = parts[2] if len(parts) > 2 else "Unknown"

            match = pattern.search(image_ref)
            if match:
                backups.append((image_ref, image_id, created_at))

        if not backups:
            print("[INFO] No backup images found.")
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message="No backup images found.",
            )

        print("\n" + "=" * 105)
        print("    Currently Backed Up Container Images")
        print("=" * 105)
        print(f" {'#':<3} | {'Image Reference':<55} | {'Image ID':<12} | {'Created At':<25}")
        print("-" * 105)
        for idx, (ref, img_id, created) in enumerate(backups, 1):
            print(f" {idx:<3} | {ref:<55} | {img_id:<12} | {created:<25}")
        print("-" * 105 + "\n")

        return ExecutionResult(
            service=None,
            action=self.action_name,
            success=True,
            exit_code=0,
            message=f"Found {len(backups)} backup image(s).",
        )

    def execute_check(self, context: ActionContext, target_vps: str) -> ExecutionResult:
        """Check for available image updates across active services registered for the target node."""
        from orchestrator.docker.check_upgrades import check_upgrades

        node_services = load_services(vps=target_vps)
        upgrades = check_upgrades(services=node_services, vps=target_vps, json_output=context.json_output)
        return ExecutionResult(
            service=None,
            action=self.action_name,
            success=True,
            exit_code=0,
            message=f"Found {len(upgrades)} upgrade(s)." if upgrades else "All services up to date.",
        )

    def execute_updates(self, context: ActionContext, target_vps: str) -> ExecutionResult:
        """Check registries and apply updates to active services filtered by node metadata."""
        from orchestrator.docker.updater import handle_updates

        # Filter services by target node
        node_services = load_services(vps=target_vps)

        if context.targets:
            targets_lower = {t.lower() for t in context.targets}
            node_services = [
                s for s in node_services
                if s.name.lower() in targets_lower
                or s.rel_dir.lower() in targets_lower
                or Path(s.rel_dir).name.lower() in targets_lower
            ]

        if context.dry_run:
            logger.info("[DRY-RUN] Evaluating container updates and stability age-gates on Node %s...", target_vps)
            from unittest.mock import patch
            try:
                with patch("sys.stdin.isatty", return_value=False):
                    handle_updates(
                        node_services,
                        auto_confirm=False,
                        min_age_days=context.min_age,
                        backup_days=context.backup_days,
                    )
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=True,
                    exit_code=0,
                    message=f"[DRY-RUN] Evaluated updates for active services on Node {target_vps}.",
                )
            except SystemExit as e:
                code = int(e.code) if e.code is not None else 0
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=(code == 0),
                    exit_code=code,
                    message=f"[DRY-RUN] Evaluated updates for active services on Node {target_vps}.",
                )

        try:
            handle_updates(
                node_services,
                auto_confirm=context.yes,
                min_age_days=context.min_age,
                backup_days=context.backup_days,
            )
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message="Updates applied successfully.",
            )
        except SystemExit as e:
            code = int(e.code) if e.code is not None else 0
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=(code == 0),
                exit_code=code,
                message="Updates completed." if code == 0 else f"Update failed with code {code}.",
            )
        except Exception as e:
            logger.error("[ERROR] Failed to execute updates: %s", e)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=False,
                exit_code=1,
                message=f"Update failed: {e}",
            )


def main(argv=None) -> int:
    """CLI entrypoint for update action."""
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

    from orchestrator.actions.base import create_action_parser, parse_action_targets

    parser = create_action_parser(
        prog="update",
        description="Check remote registries and apply container image updates with stability age gates.",
        with_targets=True,
        with_vps=True,
        with_yes=True,
        with_dry_run=True,
        with_json=True,
    )
    parser.add_argument("--check", action="store_true", help="Check for available image updates without applying")
    parser.add_argument("--list-backups", action="store_true", help="List container images backed up prior to past updates")
    parser.add_argument("--min-age", type=float, default=0.0, help="Minimum release age in days before updating (default: 0.0)")
    parser.add_argument("--backup-days", type=int, default=7, help="Days to retain rollback backup images (default: 7)")

    raw_args = list(argv if argv is not None else sys.argv[1:])
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    action = UpdateAction()
    ctx = ActionContext(
        targets=parse_action_targets(args),
        vps=args.vps,
        check=args.check,
        list_backups=args.list_backups,
        min_age=args.min_age,
        backup_days=args.backup_days,
        yes=args.yes,
        dry_run=args.dry_run,
        json_output=args.json,
        allow_dev=args.allow_dev,
    )
    res = action.execute(ctx)
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
