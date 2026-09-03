"""Action orchestrator for stopping managed Compose services."""

import logging
import sys
from typing import Optional

from orchestrator.actions.base import BaseAction
from orchestrator.core.models import ActionContext, ExecutionResult
from orchestrator.docker.client import DockerClient, default_client
from orchestrator.docker.compose import ComposeEngine
from orchestrator.network.graph import NetworkDAG
from orchestrator.registry.manifest import load_services
from orchestrator.registry.resolver import resolve_all_services, resolve_targets

logger = logging.getLogger(__name__)


class StopAction(BaseAction):
    """Gracefully stop running Compose services (targeted, by VPS, or all)."""

    action_name = "stop"
    is_mutating = True

    def __init__(
        self,
        compose_engine: Optional[ComposeEngine] = None,
        docker_client: Optional[DockerClient] = None,
    ):
        self.client = docker_client or default_client
        self.compose = compose_engine or ComposeEngine()

    def run(self, context: ActionContext) -> ExecutionResult:
        all_services = load_services()
        target_vps = context.vps

        # 1. Resolve targeted services
        if context.targets:
            matched, unresolved = resolve_targets(all_services, context.targets, vps=target_vps)
            if unresolved:
                err_msg = f"Unknown service target(s): {', '.join(unresolved)}"
                logger.error(err_msg)
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=False,
                    exit_code=1,
                    message=err_msg,
                )
            selected_services = matched
        else:
            selected_services = resolve_all_services(all_services, vps=target_vps)

        if not selected_services:
            logger.info("No matching services found to stop.")
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message="No matching services found",
            )

        # 2. Check active status and order in reverse dependency order (gateways last)
        dag = NetworkDAG(all_services)
        ordered_services = dag.topological_sort(selected_services)
        # Reverse order: dependent services stop before gateway sidecars
        stop_sequence = list(reversed(ordered_services))

        # Collect running container IDs at liveness-check time so we can stop by ID
        # directly without needing compose file env interpolation at stop time.
        # Keyed by svc.rel_dir (not svc.name) to prevent dictionary collisions between
        # independent services sharing the same short name (e.g. multiple "gateway" stacks).
        active_containers: dict[str, list[str]] = {}  # svc.rel_dir -> [container_id, ...]
        for svc in stop_sequence:
            running = self.compose.ps(svc)
            if running:
                active_containers[svc.rel_dir] = running

        active_to_stop = [svc for svc in stop_sequence if svc.rel_dir in active_containers]

        if context.interactive and active_to_stop:
            from orchestrator.ui.dashboard import run_tui
            selected = run_tui(active_to_stop, vps=target_vps, action_verb="stop")
            if not selected:
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=True,
                    exit_code=0,
                    message="Stop operation cancelled in service selector.",
                )
            selected_dirs = {s.rel_dir for s in selected}
            active_to_stop = [s for s in active_to_stop if s.rel_dir in selected_dirs]

        # 3. Handle Dry Run
        if context.dry_run:
            if not active_to_stop:
                logger.info("[DRY-RUN] No active containers found running for the specified service(s).")
            else:
                logger.info("[DRY-RUN] Found %d active service(s) to stop.", len(active_to_stop))
                for svc in active_to_stop:
                    logger.info("[DRY-RUN] Service '%s' (%s): [ACTIVE] — Would stop container", svc.name, svc.rel_dir)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message=f"[DRY-RUN] Stop simulation completed: {len(active_to_stop)} active services would be stopped",
            )


        if not active_to_stop:
            logger.info("No active containers found running for the specified targets.")
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message="No active containers running",
            )

        # 4. Confirmation Prompt
        if not context.yes:
            from orchestrator.ui.prompts import confirm_action

            if context.targets:
                svc_desc = ", ".join(s.name for s in active_to_stop[:3]) + ("..." if len(active_to_stop) > 3 else "")
                prompt = f"Stop will halt {len(active_to_stop)} specified service(s) ({svc_desc}). Proceed?"
            elif target_vps:
                prompt = f"Stop will halt ALL {len(active_to_stop)} active stack containers for VPS {target_vps}. Proceed?"
            else:
                prompt = f"Stop will gracefully halt ALL {len(active_to_stop)} active stack containers. Proceed?"

            if not confirm_action(prompt, yes=context.yes):
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=False,
                    exit_code=1,
                    message="Operation cancelled by user",
                )

        # 5. Execute Stop
        logger.info("Stopping %d active service(s)...", len(active_to_stop))
        errors: list[str] = []
        stopped_count = 0

        for svc in active_to_stop:
            cids = active_containers.get(svc.rel_dir, [])
            logger.info("Stopping %d container(s) for '%s' (%s)...", len(cids), svc.name, svc.rel_dir)
            res = self.compose.stop_by_ids(svc, cids)
            if res.success:
                stopped_count += 1
                logger.info("[OK] Service '%s' stopped successfully.", svc.name)
            else:
                err = f"Failed to stop service '{svc.name}': {res.message}"
                logger.error(err)
                errors.append(err)

        if errors:
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=False,
                exit_code=1,
                message="; ".join(errors),
            )

        return ExecutionResult(
            service=None,
            action=self.action_name,
            success=True,
            exit_code=0,
            message=f"Successfully stopped {stopped_count} service(s)",
        )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for standalone stop execution."""
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

    from orchestrator.actions.base import create_action_parser, parse_action_targets

    parser = create_action_parser(
        prog="stop",
        description="Gracefully stop running Compose services (targeted, by VPS, or all).",
        with_targets=True,
        with_vps=True,
        with_yes=True,
        with_dry_run=True,
        with_stream_mode=True,
    )
    parser.add_argument("-i", "--interactive", "--select", action="store_true", help="Select active services to stop interactively via checklist TUI")

    raw_args = argv if argv is not None else sys.argv[1:]
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    context = ActionContext(
        targets=parse_action_targets(args),
        vps=args.vps,
        dry_run=args.dry_run,
        yes=args.yes,
        allow_dev=args.allow_dev,
        interactive=args.interactive,
        stream_mode=args.stream_mode,
    )

    action = StopAction()
    result = action.execute(context)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
