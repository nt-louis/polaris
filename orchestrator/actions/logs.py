"""Action orchestrator for resolving containers and streaming container logs."""

import logging
import sys
from typing import Optional

from orchestrator.actions.base import BaseAction
from orchestrator.core.models import ActionContext, ExecutionResult
from orchestrator.docker.client import DockerClient, default_client
from orchestrator.docker.logs import resolve_container, stream_logs
from orchestrator.registry.manifest import load_services

logger = logging.getLogger(__name__)


class LogsAction(BaseAction):
    """Stream stdout/stderr logs from a managed container."""

    def __init__(self, docker_client: Optional[DockerClient] = None):
        self.client = docker_client or default_client

    @property
    def action_name(self) -> str:
        return "logs"

    def run(self, context: ActionContext) -> ExecutionResult:
        all_services = load_services()
        query = context.targets[0] if context.targets else ""

        if not query:
            err_msg = "No service or container name specified to stream logs from."
            logger.error(err_msg)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=False,
                exit_code=1,
                message=err_msg,
            )

        container_name = resolve_container(query, services=all_services, client=self.client)
        if not container_name:
            err_msg = f"Could not resolve active container for query: '{query}'"
            logger.error(err_msg)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=False,
                exit_code=1,
                message=err_msg,
            )

        logger.info("Streaming logs for container: %s (tail=%d, follow=%s)...", container_name, context.tail, context.follow)
        exit_code = stream_logs(
            container_name=container_name,
            tail=context.tail,
            follow=context.follow,
        )

        return ExecutionResult(
            service=None,
            action=self.action_name,
            success=(exit_code == 0),
            exit_code=exit_code,
            message=f"Log stream ended with exit code {exit_code}",
        )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for standalone logs execution."""
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

    from orchestrator.actions.base import create_action_parser, parse_action_targets

    parser = create_action_parser(
        prog="logs",
        description="Stream stdout/stderr logs from a managed container.",
        with_targets=True,
        with_vps=False,
    )
    parser.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    parser.add_argument("--tail", type=int, default=100, help="Number of lines to show (default: 100)")

    raw_args = argv if argv is not None else sys.argv[1:]
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    context = ActionContext(
        targets=parse_action_targets(args),
        follow=args.follow,
        tail=args.tail,
    )

    action = LogsAction()
    result = action.execute(context)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
