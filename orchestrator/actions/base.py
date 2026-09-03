"""Base contract, common execution foundation, and shared argument parsing for actions."""

import argparse
import logging
import sys
import time
from abc import ABC, abstractmethod
from typing import Optional

from orchestrator.core.history import log_action_event
from orchestrator.core.models import ActionContext, ExecutionResult
from orchestrator.core.state import get_active_vps

logger = logging.getLogger(__name__)


class ActionArgumentParser(argparse.ArgumentParser):
    """Custom ArgumentParser tailored for orchestrator CLI actions."""

    def error(self, message: str) -> None:
        sys.stderr.write(f"ERROR: {message}\n")
        sys.exit(2)


def create_action_parser(
    prog: Optional[str] = None,
    description: Optional[str] = None,
    with_targets: bool = True,
    with_vps: bool = True,
    with_yes: bool = False,
    with_dry_run: bool = False,
    with_json: bool = False,
    allow_all_nodes: bool = False,
    with_allow_dev: bool = False,
    with_stream_mode: bool = False,
    with_pull: bool = False,
) -> ActionArgumentParser:
    """Create a standardized CLI argument parser for orchestrator actions."""
    parser = ActionArgumentParser(prog=prog, description=description)

    if with_targets:
        parser.add_argument("targets", nargs="*", default=[], help="Optional service name(s) or path(s)")
        parser.add_argument("--services", "-s", nargs="+", dest="services_flag", help="Explicit target service list")

    if with_vps:
        from orchestrator.registry.manifest import get_valid_node_ids
        valid_nodes = sorted(get_valid_node_ids())
        choices = valid_nodes + ["ALL"] if allow_all_nodes else valid_nodes
        parser.add_argument(
            "--vps",
            "-vps",
            type=lambda s: s.strip().upper(),
            choices=choices,
            help=f"Target node ID ({'/'.join(choices)})",
        )

    if with_pull:
        parser.add_argument("--pull", action="store_true", help="Pull latest images from registry before starting")

    if with_yes:
        parser.add_argument("--yes", "-y", action="store_true", help="Auto-confirm destructive prompts")

    if with_dry_run:
        parser.add_argument("--dry-run", "-n", action="store_true", help="Simulation mode (zero mutations)")

    if with_allow_dev or with_yes or with_dry_run:
        parser.add_argument("--allow-dev", action="store_true", help="Allow mutating operations on non-main git branch")

    if with_stream_mode:
        parser.add_argument(
            "--stream-mode",
            choices=["native", "piped"],
            default=None,
            help="Log streaming output mode: 'native' (direct interactive TTY) or 'piped' (line-buffered capture)",
        )

    if with_json:
        parser.add_argument("--json", action="store_true", help="Format output as JSON")

    return parser


def parse_action_targets(args: argparse.Namespace) -> list[str]:
    """Combine positional targets and --services flag arguments into a single list."""
    services_flag = getattr(args, "services_flag", None) or []
    pos_targets = getattr(args, "targets", None) or []
    return list(services_flag) + list(pos_targets)


class BaseAction(ABC):
    """Abstract base class for all orchestrator actions."""

    is_mutating: bool = False

    @property
    @abstractmethod
    def action_name(self) -> str:
        """Name of the action (e.g. 'deploy', 'stop', 'redeploy', 'status')."""
        ...

    @abstractmethod
    def run(self, context: ActionContext) -> ExecutionResult:
        """Execute the action logic with the given context."""
        ...

    def execute(self, context: Optional[ActionContext] = None) -> ExecutionResult:
        """Execute action with automatic timing, context normalization, and audit logging."""
        ctx = context or ActionContext()
        vps = ctx.vps or get_active_vps()
        start_time = time.monotonic()

        # Enforce branch protection guard on mutating actions (unless dry-run or overridden)
        if self.is_mutating and not ctx.dry_run:
            from orchestrator.core.guards import verify_branch_guard

            guard_result = verify_branch_guard(self.action_name, ctx)
            if guard_result is not None:
                return guard_result

        try:
            result = self.run(ctx)
        except Exception as e:
            logger.exception("Unexpected error executing action '%s': %s", self.action_name, e)
            result = ExecutionResult(
                service=None,
                action=self.action_name,
                success=False,
                exit_code=1,
                message=f"Execution error: {e}",
            )

        duration = time.monotonic() - start_time
        result.duration_seconds = duration

        # Sanitize details for structured audit log (avoid dumping full JSON/markdown blobs)
        details = result.message or ""
        if details:
            details_stripped = details.strip()
            if details_stripped.startswith(("{", "[")) or "\n" in details_stripped:
                first_line = details_stripped.splitlines()[0]
                if len(first_line) > 120:
                    first_line = first_line[:117] + "..."
                details = f"{first_line} ({len(details_stripped)} bytes)"
            elif len(details) > 200:
                details = details[:197] + "..."

        # Audit log the execution event
        action_name = f"[DRY-RUN] {self.action_name}" if ctx.dry_run else self.action_name
        command_str = f"{'[DRY-RUN] ' if ctx.dry_run else ''}{self.action_name} {' '.join(ctx.targets)}".strip()
        log_action_event(
            action=action_name,
            vps=vps,
            exit_code=result.exit_code,
            duration_sec=duration,
            command=command_str,
            details=details,
        )

        return result
