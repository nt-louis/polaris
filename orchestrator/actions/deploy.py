"""Action orchestrator for deploying managed Compose services."""

import logging
import subprocess
import sys
from typing import Optional

from orchestrator.actions.base import BaseAction
from orchestrator.core.constants import REPO_ROOT
from orchestrator.core.guards import is_test_environment
from orchestrator.core.models import (
    ActionContext,
    ExecutionResult,
    ServiceTier,
)
from orchestrator.core.state import (
    get_active_vps,
    load_last_deploy_services,
    save_last_deploy_services,
    set_active_vps,
)
from orchestrator.docker.client import DockerClient, default_client
from orchestrator.docker.compose import ComposeEngine
from orchestrator.docker.readiness import wait_for_gluetun_ready
from orchestrator.network.graph import NetworkDAG
from orchestrator.registry.manifest import get_valid_node_ids, load_services
from orchestrator.registry.resolver import resolve_all_services, resolve_targets
from orchestrator.secrets.doppler import DopplerClient
from orchestrator.secrets.transient import materialize_transient_env

logger = logging.getLogger(__name__)


class DeployAction(BaseAction):
    """Deploy Compose services in topological dependency order with Doppler secret injection."""

    action_name = "deploy"
    is_mutating = True

    def __init__(
        self,
        compose_engine: Optional[ComposeEngine] = None,
        docker_client: Optional[DockerClient] = None,
        doppler_client: Optional[DopplerClient] = None,
    ):
        self.client = docker_client or default_client
        self.compose = compose_engine or ComposeEngine()
        self.doppler = doppler_client or DopplerClient()

    def run(self, context: ActionContext) -> ExecutionResult:
        all_services = load_services()
        target_vps = (context.vps or get_active_vps()).upper()
        vps_services = resolve_all_services(all_services, vps=target_vps)

        # 1. Target Selection
        if context.last:
            selected_services = load_last_deploy_services(vps_services, vps=target_vps)
            if not selected_services:
                err_msg = f"No saved last deploy selection found for VPS {target_vps}."
                logger.error(err_msg)
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=False,
                    exit_code=1,
                    message=err_msg,
                )
            logger.info("Restored last deployment selection (%d services) for VPS %s.", len(selected_services), target_vps)
        elif context.targets:
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
            logger.info("Targeted deploy: %d service(s) — %s", len(selected_services), ", ".join(s.name for s in selected_services))
        elif context.interactive:
            from orchestrator.ui.dashboard import run_tui
            selected = run_tui(vps_services, vps=target_vps, action_verb="deploy")
            if not selected:
                return ExecutionResult(
                    service=None,
                    action=self.action_name,
                    success=True,
                    exit_code=0,
                    message="Deployment cancelled in service selector.",
                )
            selected_services = selected
            logger.info("Selected %d service(s) for deployment: %s", len(selected_services), ", ".join(s.name for s in selected_services))
        else:
            selected_services = vps_services
            logger.info("Deploying all %d services for VPS %s.", len(selected_services), target_vps)

        if not selected_services:
            msg = f"No matching services found for VPS {target_vps}."
            logger.info(msg)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message=msg,
            )

        # Save selection and update active VPS context
        if not context.dry_run:
            valid_nodes = get_valid_node_ids()
            if target_vps in valid_nodes:
                set_active_vps(target_vps)
            save_last_deploy_services(selected_services, vps=target_vps)

        # 2. Dependency Sequencing via NetworkDAG
        dag = NetworkDAG(all_services)
        ordered_sequence = dag.topological_sort(selected_services)

        # 3. Doppler Authentication Check
        doppler_active = self.doppler.is_authenticated()
        if doppler_active:
            logger.info("[INFO] Doppler active: Process secret injection enabled (zero disk secrets).")
        else:
            logger.info("[INFO] Standalone deployment mode active.")

        # 4. Deployment Execution
        deployed_count = 0
        errors: list[str] = []

        for svc in ordered_sequence:
            is_gw = (svc.tier == ServiceTier.GATEWAY or svc.is_gateway)
            recreate = context.recreate or (is_gw and context.force_gateways)
            is_local = svc.is_local_build
            build = context.build and not is_local
            pull = context.pull and not is_local

            if context.pull and is_local:
                logger.info("[INFO] Skipping remote registry pull for local source-built service '%s'.", svc.name)

            if context.dry_run:
                logger.info(
                    "[DRY-RUN] Would deploy %s: '%s' (%s) [recreate=%s, build=%s]",
                    "gateway" if is_gw else "service",
                    svc.name,
                    svc.rel_dir,
                    recreate,
                    build,
                )
                deployed_count += 1
                continue

            if svc.name in ("monochrome", "fmhy") and not is_test_environment():
                image_tag = f"local/{svc.name}:latest"
                if context.build or not self.client.image_exists(image_tag):
                    logger.info("[INFO] Local image '%s' not present or rebuild requested. Building locally...", image_tag)
                    build_script = REPO_ROOT / "orchestrator" / "scripts" / "utils" / "build-local-app.sh"
                    if build_script.is_file():
                        build_proc = subprocess.run(
                            ["bash", str(build_script), svc.name],
                            cwd=str(REPO_ROOT),
                        )
                        if build_proc.returncode != 0:
                            err_msg = f"Failed to build local application '{svc.name}'"
                            logger.error(err_msg)
                            errors.append(err_msg)
                            if is_gw:
                                logger.error("[ABORT] Gateway '%s' failed to deploy. Aborting dependent deployments.", svc.name)
                                break
                            continue

            logger.info("Deploying %s in %s...", svc.name, svc.rel_dir)
            cmd_wrapper = (
                (lambda cmd, s=svc: self.doppler.wrap_command(cmd, service=s, vps=target_vps))
                if doppler_active
                else None
            )

            from orchestrator.core.state import get_log_stream_mode
            stream_mode = context.stream_mode or get_log_stream_mode(
                vps=target_vps,
                prompt_if_missing=(context.interactive or (sys.stdin.isatty() and not context.yes)) and not context.dry_run,
            )

            try:
                with materialize_transient_env(svc, doppler_client=self.doppler if doppler_active else None):
                    res = self.compose.compose_up(
                        service=svc,
                        recreate=recreate,
                        build=build,
                        pull=pull,
                        cmd_wrapper=cmd_wrapper,
                        stream_mode=stream_mode,
                    )
            except Exception as exc:
                err_msg = f"Failed to materialize secrets or deploy '{svc.name}': {exc}"
                logger.error(err_msg)
                errors.append(err_msg)
                if is_gw:
                    logger.error("[ABORT] Gateway '%s' failed to deploy. Aborting dependent deployments.", svc.name)
                    break
                continue

            if not res.success:
                err_msg = f"Failed to deploy '{svc.name}': {res.message}"
                logger.error(err_msg)
                errors.append(err_msg)
                if is_gw:
                    logger.error("[ABORT] Gateway '%s' failed to deploy. Aborting dependent deployments.", svc.name)
                    break
                continue

            deployed_count += 1
            logger.info("[OK] Service '%s' deployed successfully.", svc.name)

            # Wait for Gluetun health on network gateways before starting dependent apps
            if is_gw:
                ready = wait_for_gluetun_ready(svc, client=self.client, timeout=60)
                if not ready:
                    logger.warning("Gateway '%s' started, but Gluetun health check did not confirm within timeout.", svc.name)

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
            message=f"Successfully deployed {deployed_count} service(s)",
        )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for standalone deployment execution."""
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

    from orchestrator.actions.base import create_action_parser, parse_action_targets

    parser = create_action_parser(
        prog="deploy",
        description="Deploy Net-Stream containerized services with DAG dependency sequencing and Doppler secrets.",
        with_targets=True,
        with_vps=True,
        with_yes=True,
        with_dry_run=True,
        with_stream_mode=True,
        with_pull=True,
    )
    parser.add_argument("-i", "--interactive", "--select", action="store_true", help="Launch interactive checklist service selector TUI")
    parser.add_argument("--last", action="store_true", help="Deploy last saved service selection")
    parser.add_argument("--force-gateways", action="store_true", help="Force recreation of network gateways")
    parser.add_argument("--recreate", action="store_true", help="Force container recreation")
    parser.add_argument("--build", action="store_true", help="Force image rebuild")

    raw_args = argv if argv is not None else sys.argv[1:]
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    context = ActionContext(
        targets=parse_action_targets(args),
        vps=args.vps,
        last=args.last,
        force_gateways=args.force_gateways,
        recreate=args.recreate,
        build=args.build,
        pull=args.pull,
        dry_run=args.dry_run,
        yes=args.yes,
        allow_dev=args.allow_dev,
        interactive=args.interactive,
        stream_mode=args.stream_mode,
    )

    action = DeployAction()
    result = action.execute(context)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
