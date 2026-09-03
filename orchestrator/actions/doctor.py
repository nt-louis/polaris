"""Pre-flight infrastructure diagnostics action orchestrator."""

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from orchestrator.actions.base import BaseAction
from orchestrator.core.constants import REPO_ROOT
from orchestrator.core.models import ActionContext, ContainerStatus, ExecutionResult
from orchestrator.core.state import get_active_vps
from orchestrator.docker.client import DockerClient
from orchestrator.registry.discovery import load_services
from orchestrator.registry.manifest import (
    get_node_tailscale_name,
)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

logger = logging.getLogger(__name__)


def check_git_hooks() -> tuple[bool, str]:
    """Verify pre-commit secret guard hook installation."""
    try:
        hook_path = REPO_ROOT / ".git" / "hooks" / "pre-commit"
        target_script = REPO_ROOT / "orchestrator" / "scripts" / "hooks" / "pre-commit"

        if not (REPO_ROOT / ".git").is_dir():
            return True, "Not inside a git repository."

        if not hook_path.exists():
            return False, "Pre-commit secret guard hook not installed. Run './manage.py hooks install'."

        if not os.access(str(hook_path), os.X_OK):
            return False, f"Pre-commit hook exists but is not executable. Run 'chmod +x {hook_path}'."

        if hook_path.is_symlink():
            if hook_path.resolve() == target_script.resolve():
                return True, "Pre-commit secret & state guard active (symlinked)."

        return True, "Pre-commit secret & state guard active."
    except Exception as e:
        return False, f"Git hook check failed: {e}"


def check_secrets_auth() -> tuple[bool, str]:
    """Verify secrets provider authentication status."""
    try:
        res = subprocess.run(["doppler", "me"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            return True, "Doppler SaaS CLI is authenticated and active."
        return False, "Doppler SaaS CLI authentication failed. Run 'doppler login'."
    except FileNotFoundError:
        return False, "Doppler CLI not installed on host."
    except Exception as e:
        return False, f"Secrets provider check failed: {e}"


def check_secrets_integrity() -> tuple[bool, str]:
    """Perform audit of Doppler secrets against repository requirements."""
    try:
        from orchestrator.secrets.doppler import audit_repository_secrets

        code = audit_repository_secrets()
        if code == 0:
            return True, "All required secrets are populated in Doppler."
        return False, "Some projects are missing secret keys in Doppler. Run './manage.py secrets audit' for details."
    except Exception as e:
        return False, f"Secrets integrity check failed: {e}"


def check_sops_snapshots() -> tuple[bool, str]:
    """Verify SOPS snapshot offline fallback readiness and remote sync status."""
    try:
        from orchestrator.secrets.snapshots import SnapshotManager

        sm = SnapshotManager(repo_root=REPO_ROOT)
        snapshots = sm.list_snapshots()

        try:
            res = subprocess.run(
                ["git", "log", "-1", "--format=%cs", "origin/snapshots/sync"],
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            sync_info = f" (remote sync: {res.stdout.strip()})" if res.returncode == 0 and res.stdout.strip() else ""
        except Exception:
            sync_info = ""

        if not snapshots and not sync_info:
            return False, "No encrypted snapshots found. Run './manage.py secrets snapshot' or './manage.py secrets sync-branch'."
        return True, f"SOPS fallback active; {len(snapshots)} snapshot(s){sync_info} available."
    except Exception as e:
        return False, f"SOPS snapshot check failed: {e}"


def check_tailscale(target_vps: str, is_remote: bool) -> tuple[bool, str]:
    """Verify Tailscale mesh status locally or check remote peer reachability."""
    try:
        res = subprocess.run(["tailscale", "status", "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            return False, "Tailscale daemon is not active or logged out."

        data = json.loads(res.stdout)
        self_node = data.get("Self", {})
        self_host = self_node.get("HostName", "unknown")
        self_ips = self_node.get("TailscaleIPs", ["unknown"])

        if not is_remote:
            return True, f"Tailscale daemon active: {self_ips[0]} ({self_host})"

        # Remote node peer check
        expected_ts_name = get_node_tailscale_name(target_vps)
        if not expected_ts_name:
            return False, f"Node '{target_vps}' has no 'tailscale_name' declared in services.yaml"

        target_name_lower = expected_ts_name.lower()
        peers = data.get("Peer", {})
        matching_peer = None

        for peer_data in peers.values():
            peer_host = peer_data.get("HostName", "").lower()
            peer_dns = peer_data.get("DNSName", "").lower()
            dns_label = peer_dns.split(".")[0] if peer_dns else ""
            if peer_host == target_name_lower or dns_label == target_name_lower:
                matching_peer = peer_data
                break

        if not matching_peer:
            return False, f"[WARN] Remote peer '{expected_ts_name}' (Node {target_vps}) not found in tailnet mesh."

        peer_online = matching_peer.get("Online", False)
        peer_ips = matching_peer.get("TailscaleIPs", ["unknown"])
        peer_os = matching_peer.get("OS", "linux")

        if peer_online:
            return True, f"Remote Peer (Node {target_vps}: '{expected_ts_name}') Online ({peer_ips[0]}, {peer_os})"
        return False, f"[WARN] Remote peer '{expected_ts_name}' (Node {target_vps}) is offline / unreachable."

    except FileNotFoundError:
        return False, "Tailscale CLI not installed on host."
    except Exception as e:
        return False, f"Tailscale check failed: {e}"


def check_routing_rules(is_remote: bool, target_vps: str, remote_online: bool = True) -> tuple[bool, str]:
    """Verify policy routing table priority."""
    if is_remote:
        expected_ts_name = get_node_tailscale_name(target_vps) or target_vps
        if not remote_online:
            return False, f"[WARN] Remote node {target_vps} ('{expected_ts_name}') is offline; cannot probe policy routing."
        return False, f"[WARN] Remote host (Node {target_vps}): Policy routing table 52 cannot be verified without local host access."

    try:
        res = subprocess.run(["ip", "rule", "show"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            if "lookup 52" in res.stdout or "priority 50" in res.stdout:
                return True, "Policy routing (priority 50 / table 52) configured."
            return False, "Routing rule missing priority 50. Run './manage.py network fix'."
        return False, "Could not query host ip rules."
    except Exception as e:
        return False, f"Routing rule check failed: {e}"


def check_disk_space(is_remote: bool, target_vps: str, remote_online: bool = True, repo_path: Optional[Path] = None) -> tuple[bool, str]:
    """Check disk space on repository filesystem."""
    if is_remote:
        expected_ts_name = get_node_tailscale_name(target_vps) or target_vps
        if not remote_online:
            return False, f"[WARN] Remote node {target_vps} ('{expected_ts_name}') is offline; cannot probe disk storage."
        return False, f"[WARN] Remote host (Node {target_vps}): Host disk storage cannot be verified without local host access."

    try:
        usage = shutil.disk_usage(str(repo_path or REPO_ROOT))
        free_gb = usage.free / (1024 ** 3)
        percent_free = (usage.free / usage.total) * 100
        if free_gb < 5.0:
            return False, f"Low disk space: {free_gb:.1f} GB ({percent_free:.1f}%) remaining."
        return True, f"{free_gb:.1f} GB ({percent_free:.1f}%) free space available."
    except Exception as e:
        return False, f"Disk space query error: {e}"


class DoctorAction(BaseAction):
    """Orchestrates pre-flight infrastructure diagnostics across secrets, network, and disk."""

    action_name = "doctor"

    def __init__(self, docker_client: Optional[DockerClient] = None) -> None:
        self.docker_client = docker_client or DockerClient()

    def check_gateway_clusters(self, vps: str, is_remote: bool, remote_online: bool = True) -> tuple[bool, str]:
        """Check status of active gateway clusters."""
        if is_remote:
            expected_ts_name = get_node_tailscale_name(vps) or vps
            if not remote_online:
                return False, f"[WARN] Remote node {vps} ('{expected_ts_name}') is offline; cannot probe gateway clusters."
            return False, f"[WARN] Remote host (Node {vps}): Docker gateway clusters cannot be verified without local host access."

        try:
            services = load_services(vps=vps)
            gateways = [s for s in services if s.is_gateway]
            if not gateways:
                return True, "No gateway services declared."

            running_containers = self.docker_client.list_running_containers()
            if not running_containers:
                return True, "No active containers running (Idle / Not deployed)."

            active_gateways = []
            unhealthy_containers = []

            for gw in gateways:
                gw_proj = (gw.custom_project_name or gw.name).lower()
                cluster_containers = [
                    c for c in running_containers
                    if c.lower() == gw_proj
                    or c.lower().startswith(f"{gw_proj}-")
                    or c.lower() == gw.name.lower()
                    or c.lower().startswith(f"{gw.name.lower()}-")
                ]
                if cluster_containers:
                    active_gateways.append(gw.custom_project_name or gw.name)
                    for c_name in cluster_containers:
                        st = self.docker_client.get_container_status(c_name)
                        if st in (ContainerStatus.UNHEALTHY, ContainerStatus.DEAD, ContainerStatus.ERROR):
                            unhealthy_containers.append(c_name)

            if unhealthy_containers:
                return False, f"Gateway cluster issues in: {', '.join(unhealthy_containers)}"
            if active_gateways:
                return True, f"{len(active_gateways)} active gateway cluster(s) healthy."
            return True, "No gateway clusters currently active (Idle / Not deployed)."
        except Exception as e:
            return False, f"Gateway health check error: {e}"

    def run(self, context: ActionContext) -> ExecutionResult:
        """Run diagnostic checks."""
        local_vps = get_active_vps().upper()
        target_vps = (context.vps or local_vps).upper()
        is_remote = bool(context.vps and target_vps != local_vps)

        # Pre-evaluate remote peer status if targeting a remote node
        remote_online = True
        if is_remote:
            ts_ok, ts_msg = check_tailscale(target_vps, is_remote=True)
            remote_online = ts_ok
            ts_check_fn = lambda: (ts_ok, ts_msg)
        else:
            ts_check_fn = lambda: check_tailscale(target_vps, is_remote=False)

        checks = [
            ("Git Security Guard", check_git_hooks),
            ("Secrets & Auth Provider", check_secrets_auth),
            ("Doppler Secrets Audit", check_secrets_integrity),
            ("SOPS Snapshot Fallback", check_sops_snapshots),
            ("Tailscale Mesh Network", ts_check_fn),
            ("Tailnet Policy Routing", lambda: check_routing_rules(is_remote, target_vps, remote_online)),
            ("Gluetun VPN Gateways", lambda: self.check_gateway_clusters(target_vps, is_remote, remote_online)),
            ("Storage & Disk Space", lambda: check_disk_space(is_remote, target_vps, remote_online)),
        ]

        results = []
        all_passed = True

        for name, fn in checks:
            passed, msg = fn()
            results.append((name, passed, msg))
            if not passed:
                all_passed = False

        title_suffix = f" (Node {target_vps})"
        if is_remote:
            title_suffix += f" [Remote Target; Local Host is Node {local_vps}]"

        if HAS_RICH and not context.json_output:
            console = Console()
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Diagnostic Probe", style="cyan", width=25)
            table.add_column("Status", width=10)
            table.add_column("Details", style="dim")

            for name, passed, msg in results:
                if passed:
                    status_text = Text("PASS", style="bold green")
                elif "[WARN]" in msg:
                    status_text = Text("WARN", style="bold yellow")
                else:
                    status_text = Text("FAIL", style="bold red")
                table.add_row(name, status_text, msg)

            summary_panel = Panel(
                table,
                title=f"[bold white]Pre-Flight Diagnostics{title_suffix}[/bold white]",
                border_style="green" if all_passed else "yellow" if any("[WARN]" in m for _, _, m in results) else "red",
            )
            console.print(summary_panel)
        else:
            print("\n=======================================================")
            print(f"    Pre-Flight Diagnostics{title_suffix}")
            print("=======================================================")
            for name, passed, msg in results:
                status_str = "[PASS]" if passed else "[WARN]" if "[WARN]" in msg else "[FAIL]"
                print(f" {status_str:<7} {name:<25} : {msg}")
            print("=======================================================\n")

        summary = "All diagnostic probes passed." if all_passed else "One or more diagnostic probes returned warnings/failures."
        return ExecutionResult(
            service=None,
            action=self.action_name,
            success=all_passed,
            exit_code=0 if all_passed else 1,
            message=summary,
        )


def main(argv=None) -> int:
    """CLI entrypoint for doctor action."""
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

    from orchestrator.actions.base import create_action_parser

    parser = create_action_parser(
        prog="doctor",
        description="Run pre-flight infrastructure diagnostics (Doppler, Tailscale, VPN, Disk).",
        with_targets=False,
        with_vps=True,
        with_json=True,
    )

    raw_args = list(argv if argv is not None else sys.argv[1:])
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    action = DoctorAction()
    ctx = ActionContext(vps=args.vps, json_output=args.json)
    res = action.execute(ctx)
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
