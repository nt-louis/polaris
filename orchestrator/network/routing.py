"""Gateway routing repairs and Tailscale state reset operations."""

import logging
import shutil
import subprocess
import sys
from typing import Optional

from orchestrator.core.constants import REPO_ROOT
from orchestrator.core.models import (
    ContainerStatus,
    ExecutionResult,
    ServiceMetadata,
    ServiceTier,
)
from orchestrator.docker.client import DockerClient, default_client
from orchestrator.docker.readiness import extract_container_names
from orchestrator.registry.manifest import load_services

logger = logging.getLogger(__name__)


def apply_routing_fix(
    script_args: Optional[list[str]] = None,
    yes: bool = False,
) -> ExecutionResult:
    """Execute host routing fix for Gluetun and Tailscale table priorities."""
    fix_script = REPO_ROOT / "orchestrator" / "scripts" / "network" / "fix-routing.sh"
    if not fix_script.is_file():
        return ExecutionResult(
            service=None,
            action="apply_routing_fix",
            success=False,
            exit_code=1,
            message=f"Routing fix script not found at {fix_script}",
        )

    cmd = ["sudo", "bash", str(fix_script)] if sys.platform != "win32" else ["bash", str(fix_script)]
    if script_args:
        cmd.extend(script_args)
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        success = res.returncode == 0
        msg = res.stdout.strip() if success else res.stderr.strip()
        return ExecutionResult(
            service=None,
            action="apply_routing_fix",
            success=success,
            exit_code=res.returncode,
            message=msg,
        )
    except Exception as e:
        return ExecutionResult(
            service=None,
            action="apply_routing_fix",
            success=False,
            exit_code=1,
            message=str(e),
        )


def reset_tailscale_state(
    services: Optional[list[ServiceMetadata]] = None,
    vps: Optional[str] = None,
    yes: bool = False,
    client: Optional[DockerClient] = None,
    allow_dev: bool = False,
) -> ExecutionResult:
    """Reset and repair Tailscale network interfaces across gateway containers.

    Identifies gateway services matching the active VPS context, prompts for confirmation
    if unconfirmed, stops declared Tailscale containers via DockerClient, and securely removes
    only Tailscale-specific state subdirectories and files.

    Args:
        services: Optional candidate list of ServiceMetadata. If None, loads all from manifest.
                  If an explicit empty list is passed, resets 0 services.
        vps: Optional VPS filter ('A', 'B', etc.).
        yes: Auto-confirm destructive prompt flag.
        client: Optional DockerClient instance.
        allow_dev: Allow execution on development branches.

    Returns:
        ExecutionResult: Summary of stopped containers and purged state directories.
    """
    from orchestrator.core.guards import verify_branch_guard
    from orchestrator.core.models import ActionContext

    guard = verify_branch_guard("network reset", ActionContext(allow_dev=allow_dev))
    if guard is not None:
        return guard

    if not yes:
        from orchestrator.ui.prompts import confirm_action

        if not confirm_action("Reset Tailscale state across gateways?", yes=yes, danger=True):
            msg = (
                "Non-interactive shell requires --yes to confirm Tailscale state reset."
                if not sys.stdin.isatty()
                else "Tailscale state reset cancelled by user."
            )
            return ExecutionResult(
                service=None,
                action="reset_tailscale_state",
                success=False,
                exit_code=1,
                message=msg,
            )

    all_svcs = list(services) if services is not None else load_services()
    target_vps = vps.upper() if vps and vps.upper() != "ALL" else None

    # Filter strictly to gateway/tailscale services
    gateways: list[ServiceMetadata] = []
    for s in all_svcs:
        if target_vps and s.vps.upper() != target_vps:
            continue
        if s.tier == ServiceTier.GATEWAY or s.is_gateway or "gateway" in s.name:
            gateways.append(s)

    if not gateways:
        return ExecutionResult(
            service=None,
            action="reset_tailscale_state",
            success=True,
            exit_code=0,
            message="No matching gateway services found for Tailscale reset.",
        )

    docker = client or default_client
    stopped_containers: list[str] = []
    purged_paths: list[str] = []
    errors: list[str] = []

    for gw in gateways:
        declared = extract_container_names(gw)
        # Match only containers dedicated to Tailscale (do not match generic exit-nodes or gluetun)
        ts_containers = [c for c in declared if "tailscale" in c.lower()]
        gw_stop_failed = False

        for c_name in ts_containers:
            status = docker.get_container_status(c_name)
            if status in (ContainerStatus.ERROR, ContainerStatus.UNKNOWN):
                errors.append(f"Docker inspection error checking status for container '{c_name}' in gateway '{gw.name}'")
                gw_stop_failed = True
                continue

            if status in (
                ContainerStatus.RUNNING,
                ContainerStatus.HEALTHY,
                ContainerStatus.STARTING,
                ContainerStatus.UNHEALTHY,
            ):
                stop_res = docker.stop_containers([c_name], timeout=10)
                if not stop_res.success:
                    errors.append(f"Failed to stop container '{c_name}' for gateway '{gw.name}': {stop_res.message}")
                    gw_stop_failed = True
                else:
                    stopped_containers.append(c_name)

        # If container stopping or inspection failed, skip deletion for this gateway to fail closed
        if gw_stop_failed:
            logger.warning("Skipping state deletion for gateway '%s' due to container stop/inspection failure.", gw.name)
            continue

        # Target strictly Tailscale state paths, never the entire parent state directory
        tailscale_candidate_dirs = [
            gw.abs_dir / "state" / "tailscale",
            gw.abs_dir / "tailscale" / "state",
        ]

        for cand in tailscale_candidate_dirs:
            if not cand.is_dir():
                continue

            try:
                cand_resolved = cand.resolve()
                repo_resolved = REPO_ROOT.resolve()
                gw_resolved = gw.abs_dir.resolve()

                # Guard against path traversal
                cand_resolved.relative_to(gw_resolved)
                cand_resolved.relative_to(repo_resolved)

                shutil.rmtree(cand)
                purged_paths.append(str(cand.relative_to(REPO_ROOT)))
            except (ValueError, OSError) as e:
                errors.append(f"Failed to remove Tailscale state dir '{cand}': {e}")

        # Check for individual tailscale state file (e.g. tailscaled.state)
        single_state = gw.abs_dir / "state" / "tailscaled.state"
        if single_state.is_file():
            try:
                single_resolved = single_state.resolve()
                single_resolved.relative_to(gw.abs_dir.resolve())
                single_resolved.relative_to(REPO_ROOT.resolve())
                single_state.unlink()
                purged_paths.append(str(single_state.relative_to(REPO_ROOT)))
            except (ValueError, OSError) as e:
                errors.append(f"Failed to unlink '{single_state}': {e}")

    if errors:
        return ExecutionResult(
            service=None,
            action="reset_tailscale_state",
            success=False,
            exit_code=1,
            message="; ".join(errors),
        )

    msg = (
        f"Tailscale reset complete across {len(gateways)} gateway(s). "
        f"Stopped {len(stopped_containers)} container(s). "
        f"Purged {len(purged_paths)} state path(s)."
    )
    return ExecutionResult(
        service=None,
        action="reset_tailscale_state",
        success=True,
        exit_code=0,
        message=msg,
    )
