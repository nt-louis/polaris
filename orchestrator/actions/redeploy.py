"""Action orchestrator for refreshing and recreating active Compose services."""

import logging
import sys
from pathlib import Path
from typing import Optional

from orchestrator.actions.base import BaseAction
from orchestrator.actions.deploy import DeployAction
from orchestrator.core.models import ActionContext, ExecutionResult
from orchestrator.core.state import get_active_vps
from orchestrator.docker.client import DockerClient, default_client
from orchestrator.docker.compose import ComposeEngine
from orchestrator.registry.manifest import load_services
from orchestrator.registry.resolver import resolve_all_services, resolve_targets

logger = logging.getLogger(__name__)


class RedeployAction(BaseAction):
    """Refresh or recreate active Compose services."""

    action_name = "redeploy"
    is_mutating = True

    def __init__(
        self,
        compose_engine: Optional[ComposeEngine] = None,
        docker_client: Optional[DockerClient] = None,
    ):
        self.client = docker_client or default_client
        self.compose = compose_engine or ComposeEngine()
        self.deploy_action = DeployAction(
            compose_engine=self.compose,
            docker_client=self.client,
        )

    def run(self, context: ActionContext) -> ExecutionResult:
        all_services = load_services()
        target_vps = (context.vps or get_active_vps()).upper()

        target_queries: list[str] = list(context.targets)

        # 1. Handle resume-from state file (e.g. cold-backup restart)
        if context.resume_from:
            resume_path = Path(context.resume_from)
            if not resume_path.is_file():
                err_msg = f"Resume file '{context.resume_from}' not found."
                logger.error(err_msg)
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=False,
                    exit_code=1,
                    message=err_msg,
                )
            try:
                lines = [
                    line.strip()
                    for line in resume_path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
                target_queries.extend(lines)
            except Exception as exc:
                err_msg = f"Failed to read resume file '{context.resume_from}': {exc}"
                logger.error(err_msg)
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=False,
                    exit_code=1,
                    message=err_msg,
                )

        if target_queries:
            matched, unresolved = resolve_targets(all_services, target_queries, vps=target_vps)
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
            prompt_desc = f"{len(selected_services)} service(s) ({', '.join(s.name for s in selected_services[:3])}{'...' if len(selected_services) > 3 else ''})"
        else:
            # Discover all currently active services for the VPS
            vps_services = resolve_all_services(all_services, vps=target_vps)
            active_services = [s for s in vps_services if self.compose.is_project_active(s)]

            if not active_services:
                msg = f"No active containers found running for VPS {target_vps} to redeploy."
                logger.info(msg)
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=True,
                    exit_code=0,
                    message=msg,
                )
            if context.interactive:
                from orchestrator.ui.dashboard import run_tui
                selected = run_tui(active_services, vps=target_vps, action_verb="redeploy")
                if not selected:
                    return ExecutionResult(
                        service=None,
                        action=self.action_name,
                        success=True,
                        exit_code=0,
                        message="Redeploy cancelled in service selector.",
                    )
                selected_services = selected
                prompt_desc = f"{len(selected_services)} selected active service(s)"
            else:
                selected_services = active_services
                prompt_desc = f"{len(selected_services)} active service(s) on VPS {target_vps}"

        # 2. Confirmation gate (auto-approved when resuming from an explicit state file)
        if not context.dry_run and not context.yes and not context.resume_from:
            from orchestrator.ui.prompts import confirm_action

            prompt = f"redeploy will recreate {prompt_desc}. Proceed?"
            if not confirm_action(prompt, yes=context.yes):
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=False,
                    exit_code=1,
                    message="Operation cancelled by user",
                )

        # 3. Dispatch to DeployAction
        deploy_ctx = ActionContext(
            targets=[s.rel_dir for s in selected_services],
            vps=target_vps,
            recreate=True,
            build=context.build,
            pull=context.pull,
            force_gateways=context.force_gateways,
            dry_run=context.dry_run,
            yes=True,
            stream_mode=context.stream_mode,
        )
        return self.deploy_action.run(deploy_ctx)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for standalone redeploy execution."""
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

    from orchestrator.actions.base import create_action_parser, parse_action_targets

    parser = create_action_parser(
        prog="redeploy",
        description="Refresh and recreate active Compose services.",
        with_targets=True,
        with_vps=True,
        with_yes=True,
        with_dry_run=True,
        with_stream_mode=True,
        with_pull=True,
    )
    parser.add_argument("-i", "--interactive", "--select", action="store_true", help="Select active services interactively via checklist TUI")
    parser.add_argument("--resume-from", help="Resume deployment from container snapshot file")
    parser.add_argument("--build", action="store_true", help="Force image rebuild")
    parser.add_argument("--recreate", action="store_true", help="Force container recreation")
    parser.add_argument("--force-gateways", action="store_true", help="Force recreation of network gateways")

    raw_args = argv if argv is not None else sys.argv[1:]
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    context = ActionContext(
        targets=parse_action_targets(args),
        vps=args.vps,
        recreate=True,
        build=args.build,
        pull=args.pull,
        force_gateways=args.force_gateways,
        dry_run=args.dry_run,
        yes=args.yes,
        allow_dev=args.allow_dev,
        resume_from=args.resume_from,
        interactive=args.interactive,
        stream_mode=args.stream_mode,
    )

    action = RedeployAction()
    result = action.execute(context)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
