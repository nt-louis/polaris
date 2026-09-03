"""Branch and environment protection guards for orchestrator mutations."""

import logging
import os
import subprocess
import sys
from typing import Optional

from orchestrator.core.constants import REPO_ROOT
from orchestrator.core.models import ActionContext, ExecutionResult

logger = logging.getLogger(__name__)


def is_test_environment() -> bool:
    """Return True if running inside automated unit test runner (unittest / pytest)."""
    return "unittest" in sys.modules or "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ


def get_current_git_branch() -> Optional[str]:
    """Return the currently checked out Git branch name or None if unavailable."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if res.returncode == 0:
            branch = res.stdout.strip()
            return branch if branch else None
    except Exception:
        pass
    return None


def is_main_branch() -> bool:
    """Return True if on 'main' branch or 'master' branch."""
    branch = get_current_git_branch()
    return branch in ("main", "master")


def verify_branch_guard(
    action_name: str,
    context: ActionContext,
    force_check: bool = False,
) -> Optional[ExecutionResult]:
    """Enforce that mutating operations only run on main unless explicitly overridden.

    Args:
        action_name: Name of the action being executed.
        context: Action execution context.
        force_check: If True, enforces guard even during unit test discovery.

    Returns:
        Optional[ExecutionResult]: None if execution is permitted, or ExecutionResult(success=False) if blocked.
    """
    # Dry-run is always safe on any branch (zero disk/container mutations)
    if context.dry_run:
        return None

    # Check if explicit override is active (CLI flag or environment variable)
    allow_dev = context.allow_dev or os.environ.get("POLARIS_ALLOW_DEV") or os.environ.get("NET_STREAM_ALLOW_DEV", "").strip().lower() in ("1", "true", "yes")

    # In automated test suite runners, allow execution unless test explicitly tests the guard
    if is_test_environment() and not force_check and not allow_dev:
        return None

    branch = get_current_git_branch()
    # If not a git repo or branch could not be determined, proceed
    if not branch:
        return None

    if branch in ("main", "master"):
        return None

    # We are on a development/feature branch
    if allow_dev:
        logger.warning(
            "[WARN] Executing mutating action '%s' on development branch '%s' (--allow-dev enabled).",
            action_name,
            branch,
        )
        return None

    # Block execution
    msg = (
        f"[BLOCK] Mutating operation '{action_name}' is restricted to the 'main' branch to prevent accidental outages.\n"
        f"        Current branch: '{branch}'.\n"
        f"        - To preview safely: pass --dry-run / -n\n"
        f"        - To test on development branch: pass --allow-dev (or set POLARIS_ALLOW_DEV=1)"
    )
    logger.error("%s", msg)
    return ExecutionResult(
        service=None,
        action=action_name,
        success=False,
        exit_code=1,
        message=msg,
    )
