"""Interactive Rich TUI dashboard engine and checklist service selector."""

import subprocess
import sys
import time
from itertools import product

from orchestrator.core.constants import REPO_ROOT
from orchestrator.core.guards import get_current_git_branch, is_main_branch
from orchestrator.core.history import log_action_event
from orchestrator.core.state import (
    get_active_vps,
    load_last_deploy_services,
    save_last_deploy_services,
    set_active_vps,
)
from orchestrator.registry.manifest import get_registered_nodes, load_services
from orchestrator.ui.inspector import (
    _classify_services,
    get_cached_containers,
    get_cached_services,
    render_history_view,
    render_log_view,
    render_status_view,
)
from orchestrator.ui.prompts import (
    RawTerminalContext,
    StandardTerminalContext,
    get_key,
    set_mouse_tracking,
)

try:
    from rich import box as rich_box
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# Cyber-Slate design system — unified colour + geometry tokens
TUI_THEME = {
    # Header / footer chrome
    "header_style": "bold #38bdf8",
    "header_border": "#0284c7",
    "footer_style": "dim #94a3b8",
    "footer_border": "#0284c7",
    # Panel borders
    "active_border": "#38bdf8",        # Electric Cyan — focused panel
    "inactive_border": "#334155",      # Deep Slate — unfocused
    "warn_border": "#f59e0b",          # Vivid Amber — warning/branch guard
    "danger_border": "#f43f5e",        # Rose Red — destructive actions
    # Text
    "content_selected": "bold #f8fafc",
    "content_unselected": "#94a3b8",
    "action_selected": "bold #f59e0b",
    "action_unselected": "bold #38bdf8",
    # UI atoms
    "pointer": "▸ ",
    "bullet_checked": "[bold #22c55e]●[/bold #22c55e]",
    "bullet_unchecked": "[dim #64748b]○[/dim #64748b]",
    # Semantic colours
    "c_brand": "#38bdf8",
    "c_accent": "#f59e0b",
    "c_success": "#22c55e",
    "c_warn": "#eab308",
    "c_danger": "#f43f5e",
    "c_muted": "#94a3b8",
    "c_text": "#f8fafc",
}


def get_dashboard_categories() -> list[dict]:
    """Return declarative dashboard category definitions dynamically derived from nodes."""
    nodes = get_registered_nodes()
    vps_options = [
        {"type": "radio", "group": "vps", "label": "All Nodes (Deploy all services)", "value": "all", "selected": True}
    ]
    for n in nodes:
        vps_options.append({
            "type": "radio",
            "group": "vps",
            "label": f"Node {n.id} only ({n.name})",
            "value": n.id,
            "selected": False,
        })

    backup_vps_options = []
    for idx, n in enumerate(nodes):
        backup_vps_options.append({
            "type": "radio",
            "group": "backup_vps",
            "label": f"Node {n.id} backup repository ({n.name})",
            "value": n.id,
            "selected": (idx == 0),
        })

    return [
        {
            "id": "deploy_wizard",
            "name": "Deploy Stacks Wizard",
            "desc": "Select target node and mode to deploy or resume compose stacks.",
            "items": vps_options + [
                {"type": "separator"},
                {"type": "radio", "group": "mode", "label": "Interactive Service Selector (Checklist)", "value": "interactive", "selected": True},
                {"type": "radio", "group": "mode", "label": "Deploy all registered services", "value": "all", "selected": False},
                {"type": "radio", "group": "mode", "label": "Re-deploy last saved selection", "value": "last", "selected": False},
                {"type": "separator"},
                {"type": "checkbox", "label": "Pull latest images before deploying", "id": "pull", "checked": False},
                {"type": "checkbox", "label": "Force recreate core network gateways", "id": "force_gateways", "checked": False},
                {"type": "action", "label": "[ RUN DEPLOYMENT WIZARD ]", "action": "deploy"},
            ],
        },
        {
            "id": "redeploy",
            "name": "Redeploy Active Stacks",
            "desc": "Refresh and restart only the currently active/running containers.",
            "items": [
                {"type": "radio", "group": "redeploy_mode", "label": "Select active services interactively (Checklist)", "value": "interactive", "selected": True},
                {"type": "radio", "group": "redeploy_mode", "label": "Redeploy all currently active services", "value": "all", "selected": False},
                {"type": "separator"},
                {"type": "checkbox", "label": "Pull latest images before starting", "id": "pull", "checked": False},
                {"type": "checkbox", "label": "Force rebuild container images before starting", "id": "build", "checked": False},
                {"type": "checkbox", "label": "Force recreate active containers", "id": "recreate", "checked": False},
                {"type": "action", "label": "[ RE-DEPLOY ACTIVE CONTAINERS ]", "action": "redeploy"},
            ],
        },
        {
            "id": "stop_stack",
            "name": "Stop Stack / Services",
            "desc": "Gracefully stop and shut down all running containers in the stack.",
            "items": [
                {"type": "radio", "group": "stop_mode", "label": "Select active services to stop (Checklist)", "value": "interactive", "selected": True},
                {"type": "radio", "group": "stop_mode", "label": "Shutdown all active services", "value": "all", "selected": False},
                {"type": "separator"},
                {"type": "info", "label": "This will query and stop active containers managed by this repository."},
                {"type": "info", "label": "Persistent volumes and state files are preserved."},
                {"type": "action", "label": "[ SHUTDOWN ACTIVE SERVICES ]", "action": "stop"},
            ],
        },
        {
            "id": "registry_updates",
            "name": "Registry Updates & Backups",
            "desc": "Check and pull updates using parallel registry checks, age-gate, and automatic image backups.",
            "items": [
                {"type": "numeric", "label": "Stability Age Gate (Days)", "id": "min_age", "value": 0.0, "step": 0.5, "min": 0.0, "max": 30.0},
                {"type": "numeric", "label": "Backup Retention (Days)", "id": "backup_days", "value": 7, "step": 1, "min": 0, "max": 90},
                {"type": "action", "label": "[ CHECK & APPLY UPDATES ]", "action": "update"},
                {"type": "action", "label": "[ LIST CURRENT BACKUPS ]", "action": "list_backups"},
            ],
        },
        {
            "id": "secrets",
            "name": "Secrets Management (Doppler SaaS & SOPS Fallback)",
            "desc": "Automate config sync, audit secret integrity, prune redundancy, and manage encrypted SOPS snapshots.",
            "items": [
                {"type": "radio", "group": "secret_cmd", "label": "Verify Doppler CLI authentication", "value": "verify", "selected": True},
                {"type": "radio", "group": "secret_cmd", "label": "Open Doppler SaaS Web Dashboard in browser", "value": "open", "selected": False},
                {"type": "separator"},
                {"type": "radio", "group": "secret_cmd", "label": "Sync Doppler configs with repository (Create missing)", "value": "sync", "selected": False},
                {"type": "radio", "group": "secret_cmd", "label": "Audit secrets (Compare .env.example with Doppler)", "value": "audit", "selected": False},
                {"type": "separator"},
                {"type": "radio", "group": "secret_cmd", "label": "Refresh SOPS fallback snapshots (Node A)", "value": "snapshot-a", "selected": False},
                {"type": "radio", "group": "secret_cmd", "label": "Refresh SOPS fallback snapshots (Node B)", "value": "snapshot-b", "selected": False},
                {"type": "radio", "group": "secret_cmd", "label": "List offline encrypted SOPS snapshots", "value": "snapshots", "selected": False},
                {"type": "separator"},
                {"type": "radio", "group": "secret_cmd", "label": "Prune redundant inherited secrets (Node A)", "value": "prune-a", "selected": False},
                {"type": "radio", "group": "secret_cmd", "label": "Prune redundant inherited secrets (Node B)", "value": "prune-b", "selected": False},
                {"type": "action", "label": "[ RUN SECRETS UTILITY ]", "action": "secrets"},
            ],
        },
        {
            "id": "backup_restic",
            "name": "Backup & Recovery (Restic)",
            "desc": "Manage host snapshots, run backups, and restore appdata configurations via Restic.",
            "items": backup_vps_options + [
                {"type": "separator"},
                {"type": "radio", "group": "backup_cmd", "label": "Run incremental backup (Restic snapshot)", "value": "backup", "selected": True},
                {"type": "radio", "group": "backup_cmd", "label": "Run disaster recovery restore from Restic", "value": "restore", "selected": False},
                {"type": "radio", "group": "backup_cmd", "label": "List all backup snapshots for this host", "value": "snapshots", "selected": False},
                {"type": "radio", "group": "backup_cmd", "label": "Verify Restic repository integrity", "value": "backup-check", "selected": False},
                {"type": "radio", "group": "backup_cmd", "label": "Enforce retention & prune unreferenced blobs", "value": "prune", "selected": False},
                {"type": "radio", "group": "backup_cmd", "label": "Inspect repository storage statistics & compression", "value": "stats", "selected": False},
                {"type": "action", "label": "[ RUN RESTIC OPERATION ]", "action": "backup_op"},
            ],
        },
        {
            "id": "network",
            "name": "Network & Routing Fixes",
            "desc": "Apply Tailscale routing fixes and reset interface settings.",
            "items": [
                {"type": "radio", "group": "net_cmd", "label": "Apply Gluetun + Tailscale routing fix", "value": "fix-routing", "selected": True},
                {"type": "radio", "group": "net_cmd", "label": "Stop Tailscale and delete persistent state", "value": "reset-tailscale", "selected": False},
                {"type": "action", "label": "[ RUN NETWORK UTILITY ]", "action": "network"},
            ],
        },
        {
            "id": "sysutils",
            "name": "System Utilities & Diagnostics",
            "desc": "Execute repository utilities, pre-flight diagnostics, compose validation, and local app builds.",
            "items": [
                {"type": "radio", "group": "sys_cmd", "label": "Inspect stack container health (status)", "value": "status", "selected": True},
                {"type": "radio", "group": "sys_cmd", "label": "Run pre-flight infrastructure diagnostics (doctor)", "value": "doctor", "selected": False},
                {"type": "radio", "group": "sys_cmd", "label": "Validate compose & routing configs (validate)", "value": "validate", "selected": False},
                {"type": "separator"},
                {"type": "radio", "group": "sys_cmd", "label": "Install system-wide 'net-stream' CLI wrapper", "value": "cli-install", "selected": False},
                {"type": "radio", "group": "sys_cmd", "label": "Verify system-wide 'net-stream' CLI installation", "value": "cli-verify", "selected": False},
                {"type": "radio", "group": "sys_cmd", "label": "Uninstall system-wide 'net-stream' CLI wrapper", "value": "cli-uninstall", "selected": False},
                {"type": "separator"},
                {"type": "radio", "group": "sys_cmd", "label": "Build & deploy FMHY Wiki app", "value": "update-fmhy", "selected": False},
                {"type": "radio", "group": "sys_cmd", "label": "Build & deploy Monochrome music app", "value": "update-monochrome", "selected": False},
                {"type": "radio", "group": "sys_cmd", "label": "Configure NetBird control plane server", "value": "update-netbird-server", "selected": False},
                {"type": "radio", "group": "sys_cmd", "label": "Generate container dependency report", "value": "dependency-report", "selected": False},
                {"type": "separator"},
                {"type": "radio", "group": "sys_cmd", "label": "Set log stream mode: Native TTY (Default - Live colors & progress)", "value": "set-stream-native", "selected": False},
                {"type": "radio", "group": "sys_cmd", "label": "Set log stream mode: Piped Line Capture (Buffered streaming)", "value": "set-stream-piped", "selected": False},
                {"type": "action", "label": "[ RUN UTILITY COMMAND ]", "action": "sysutils"},
            ],
        },
        {
            "id": "help",
            "name": "Help & About",
            "desc": "Learn about keybindings, CLI tools, and unified control options.",
            "items": [
                {"type": "info", "label": "Welcome to Net-Stream Control Center!"},
                {"type": "info", "label": "Consolidated stack management and infrastructure CLI utilities."},
                {"type": "info", "label": ""},
                {"type": "info", "label": "Live Inspector Hotkeys:"},
                {"type": "info", "label": "  • S / M                    : Toggle Live Infrastructure Health Inspector"},
                {"type": "info", "label": "  • L                        : Stream active container / action logs"},
                {"type": "info", "label": "  • H                        : Open action history"},
                {"type": "info", "label": "  • /                        : Search all commands (Doctor, Validate, Status, etc)"},
                {"type": "info", "label": ""},
                {"type": "info", "label": "Direct CLI Subcommands:"},
                {"type": "info", "label": "  • ./manage.py status       : Real-time container health & port inspector"},
                {"type": "info", "label": "  • ./manage.py logs <svc>   : Stream container logs by short service name"},
                {"type": "info", "label": "  • ./manage.py doctor       : Automated pre-flight infrastructure diagnostics"},
                {"type": "info", "label": "  • ./manage.py validate     : Validate compose files and Caddy routing"},
                {"type": "info", "label": ""},
                {"type": "info", "label": "Keybindings:"},
                {"type": "info", "label": "  • 1-9                      : Select menu category or sub-option"},
                {"type": "info", "label": "  • Up / Down Arrow          : Move selection cursor"},
                {"type": "info", "label": "  • Space / Enter            : Pick item or trigger action"},
                {"type": "info", "label": "  • Esc / Q                  : Return to Main Menu or exit to shell"},
                {"type": "info", "label": ""},
                {"type": "info", "label": f"Repository Root: {REPO_ROOT}"},
            ],
        },
    ]


CATEGORY_CAPABILITIES = {
    "deploy_wizard": "[ WIZARD / DAG ]",
    "redeploy": "[ LIVE REFRESH ]",
    "stop_stack": "[ SHUTDOWN ]",
    "registry_updates": "[ AGE-GATED ]",
    "secrets": "[ DOPPLER/SOPS ]",
    "backup_restic": "[ RESTIC SNAP ]",
    "network": "[ TAILSCALE/VPN ]",
    "sysutils": "[ DIAGNOSTICS ]",
    "help": "[ REFERENCE ]",
}

CATEGORY_SCOPES = {
    "deploy_wizard": "Node A / B",
    "redeploy": "Active Containers",
    "stop_stack": "All Clusters",
    "registry_updates": "Docker Registries",
    "secrets": "Doppler SaaS",
    "backup_restic": "Restic Repo",
    "network": "Mesh / Gateway",
    "sysutils": "Local Host",
    "help": "CLI Guide",
}


def get_item_flag_hint(item: dict) -> str:
    """Return the associated CLI flag or subcommand string for an item."""
    if item.get("flag"):
        return item["flag"]
    t = item.get("type")
    if t == "radio":
        grp = item.get("group")
        val = item.get("value")
        if grp in ("vps", "backup_vps"):
            return f"--vps {val.upper()}"
        elif grp in ("mode", "redeploy_mode", "stop_mode"):
            return f"--{val}"
        elif grp == "secret_cmd":
            if val == "snapshot-a":
                return "secrets snapshot --vps A"
            elif val == "snapshot-b":
                return "secrets snapshot --vps B"
            elif val == "prune-a":
                return "secrets prune --vps A"
            elif val == "prune-b":
                return "secrets prune --vps B"
            return f"secrets {val}"
        elif grp == "backup_cmd":
            if val == "backup":
                return "backup run"
            elif val == "backup-check":
                return "backup check"
            return f"backup {val}"
        elif grp == "net_cmd":
            if val == "fix-routing":
                return "network fix"
            elif val == "reset-tailscale":
                return "network reset"
            return f"network {val}"
        elif grp == "sys_cmd":
            if val in ("status", "doctor", "validate"):
                return f"./manage.py {val}"
            elif val and val.startswith("cli-"):
                return f"./manage.py cli {val.replace('cli-', '')}"
            return f"./manage.py utils {val}"
    elif t == "checkbox":
        cid = item.get("id", "")
        return f"--{cid.replace('_', '-')}"
    elif t == "numeric":
        cid = item.get("id", "")
        val = item.get("value")
        return f"--{cid.replace('_', '-')} {val}"
    elif t == "action":
        act = item.get("action", "")
        if act == "list_backups":
            return "./manage.py update --list-backups"
        elif act == "backup_op":
            return "./manage.py backup"
        return f"./manage.py {act}"
    return ""


def get_action_command(action: str, values: dict, allow_dev: bool = False, dry_run: bool = False) -> list[str]:
    """Translate UI active parameters to shell command arrays."""
    manage_script = str(REPO_ROOT / "manage.py")

    if action == "deploy":
        vps = values.get("vps")
        mode = values.get("mode")
        force_gateways = values.get("force_gateways")
        pull = values.get("pull")
        cmd = [sys.executable, manage_script, "deploy"]
        if vps:
            cmd += ["--vps", vps]
        if mode == "last":
            cmd += ["--last"]
        elif mode == "interactive":
            cmd += ["--interactive"]
        if pull:
            cmd += ["--pull"]
        if force_gateways:
            cmd += ["--force-gateways"]
        if allow_dev:
            cmd += ["--allow-dev"]
        if dry_run:
            cmd += ["--dry-run"]
        return cmd

    elif action == "redeploy":
        mode = values.get("redeploy_mode", "interactive")
        build = values.get("build")
        recreate = values.get("recreate")
        pull = values.get("pull")
        cmd = [sys.executable, manage_script, "redeploy"]
        if mode == "interactive":
            cmd += ["--interactive"]
        if pull:
            cmd += ["--pull"]
        if build:
            cmd += ["--build"]
        if recreate:
            cmd += ["--recreate"]
        if allow_dev:
            cmd += ["--allow-dev"]
        if dry_run:
            cmd += ["--dry-run"]
        return cmd

    elif action == "stop":
        mode = values.get("stop_mode", "interactive")
        cmd = [sys.executable, manage_script, "stop"]
        if mode == "interactive":
            cmd += ["--interactive"]
        if allow_dev:
            cmd += ["--allow-dev"]
        if dry_run:
            cmd += ["--dry-run"]
        return cmd

    elif action == "update":
        min_age = values.get("min_age", 0.0)
        backup_days = values.get("backup_days", 7)
        cmd = [sys.executable, manage_script, "update", "--min-age", str(min_age), "--backup-days", str(backup_days)]
        if allow_dev:
            cmd += ["--allow-dev"]
        if dry_run:
            cmd += ["--dry-run"]
        return cmd

    elif action == "list_backups":
        return [sys.executable, manage_script, "update", "--list-backups"]

    elif action == "secrets":
        sub = values.get("secret_cmd", "verify")
        if sub in ("prune-a", "prune-b"):
            node_vps = "A" if "a" in sub else "B"
            cmd = [sys.executable, manage_script, "secrets", "prune", "--vps", node_vps]
            if dry_run:
                cmd.append("--dry-run")
            else:
                cmd.append("--yes")
            return cmd
        elif sub == "snapshot-a":
            return [sys.executable, manage_script, "secrets", "snapshot", "--vps", "A"]
        elif sub == "snapshot-b":
            return [sys.executable, manage_script, "secrets", "snapshot", "--vps", "B"]
        elif sub == "snapshots":
            return [sys.executable, manage_script, "secrets", "snapshots"]
        cmd = [sys.executable, manage_script, "secrets", sub]
        if dry_run and sub in ("sync", "sync-branch"):
            cmd.append("--dry-run")
        return cmd

    elif action == "backup_op":
        sub = values.get("backup_cmd", "backup")
        sub_map = {
            "backup": "run",
            "restore": "restore",
            "snapshots": "snapshots",
            "backup-check": "check",
            "prune": "prune",
            "stats": "stats",
        }
        mapped = sub_map.get(sub, sub)
        cmd = [sys.executable, manage_script, "backup", mapped]
        backup_vps = values.get("backup_vps")
        if backup_vps in ("A", "B"):
            cmd += ["--vps", backup_vps]
        if mapped == "restore" and not dry_run:
            cmd.append("--yes")
        if dry_run and mapped in ("run", "restore", "prune"):
            cmd.append("--dry-run")
        return cmd


    elif action == "network":
        sub = values.get("net_cmd", "fix-routing")
        sub_map = {
            "fix-routing": "fix",
            "reset-tailscale": "reset",
        }
        return [sys.executable, manage_script, "network", sub_map.get(sub, sub)]

    elif action == "sysutils":
        sub = values.get("sys_cmd", "status")
        if sub == "status":
            return [sys.executable, manage_script, "status"]
        elif sub == "doctor":
            return [sys.executable, manage_script, "doctor"]
        elif sub == "validate":
            return [sys.executable, manage_script, "validate"]
        elif sub in ("cli-install", "cli-verify", "cli-uninstall"):
            return [sys.executable, manage_script, "cli", sub.replace("cli-", "")]
        elif sub == "set-stream-native":
            return [sys.executable, manage_script, "stream-mode", "native"]
        elif sub == "set-stream-piped":
            return [sys.executable, manage_script, "stream-mode", "piped"]
        else:
            sub_map = {
                "update-fmhy": "fmhy",
                "update-monochrome": "monochrome",
                "update-netbird-server": "netbird-server",
                "dependency-report": "dependency-report",
            }
            return [sys.executable, manage_script, "utils", sub_map.get(sub, sub)]

    return []


def handle_radio_select(items: list[dict], selected_item: dict) -> None:
    """Update selection state within a radio button group."""
    group = selected_item.get("group")
    for item in items:
        if item.get("type") == "radio" and item.get("group") == group:
            item["selected"] = (item == selected_item)


def execute_action(
    action: str,
    items: list[dict],
    live: "Live",
    action_status: dict | None = None,
    confirmed: bool = False,
    allow_dev: bool = False,
    dry_run: bool = False,
) -> None:
    """Execute a console action by suspending the Live screen and running a subprocess."""
    sys.stdout.write("\x1b[?1000l\x1b[?1006l")
    sys.stdout.flush()

    live.stop()
    sys.stdout.write("\033[H\033[J")

    values = {}
    for item in items:
        if item.get("type") == "checkbox":
            values[item.get("id")] = item.get("checked")
        elif item.get("type") == "numeric":
            values[item.get("id")] = item.get("value")
        elif item.get("type") == "radio" and item.get("selected"):
            values[item.get("group")] = item.get("value")

    is_destructive = False
    warning_msg = ""

    if not dry_run:
        if action == "stop":
            is_destructive = True
            warning_msg = "WARNING: This will gracefully stop and shut down ALL running stack containers."
        elif action == "backup_op" and values.get("backup_cmd") == "restore":
            is_destructive = True
            warning_msg = "WARNING: This will overwrite current configurations and databases from a backup snapshot."
        elif action == "network" and values.get("net_cmd") == "reset-tailscale":
            is_destructive = True
            warning_msg = "WARNING: This will stop Tailscale and completely DELETE its persistent authentication state."

    set_mouse_tracking(False)
    with StandardTerminalContext():
        branch = get_current_git_branch()
        is_on_main = is_main_branch() or not branch
        is_mutating = action in ("deploy", "redeploy", "stop", "update")

        if not dry_run and not is_on_main and is_mutating and not confirmed and not allow_dev:
            print(f"\033[1;33m[BRANCH GUARD] You are currently on development branch '\033[1;36m{branch}\033[1;33m'.\033[0m")
            print(f"\033[1;33mMutating action '\033[1;37m{action.upper()}\033[1;33m' is restricted to the 'main' branch by default.\033[0m")
            confirm_dev = input("\033[1;32mForce execution on development branch with --allow-dev? [y/N]: \033[0m").strip().lower()
            if confirm_dev in ("y", "yes"):
                allow_dev = True
            else:
                print("\nAction cancelled. Returning to Dashboard...")
                time.sleep(1.5)
                live.start()
                set_mouse_tracking(True)
                return

        if is_destructive and not confirmed:
            print(f"\033[1;31m[WARNING] {warning_msg}\033[0m")
            confirm = input("\033[1;33mAre you sure you want to proceed? (y/N): \033[0m").strip().lower()
            if confirm not in ("y", "yes"):
                print("\nAction cancelled. Returning to Dashboard...")
                time.sleep(1.5)
                live.start()
                set_mouse_tracking(True)
                return

        print("\033[1;36m=====================================================")
        action_title = f"[DRY-RUN PREVIEW] {action.upper()}" if dry_run else action.upper()
        print(f"    Executing stack action: {action_title}")
        print("=====================================================\033[0m\n")

        start_time = time.time()
        exit_code = 1
        cmd = []
        try:
            cmd = get_action_command(action, values, allow_dev=allow_dev, dry_run=dry_run)
            if cmd:
                exit_code = subprocess.call(cmd)
            else:
                print(f"ERROR: No command mapped for action '{action}'")
        except Exception as e:
            print(f"\n[ERROR] Command execution failed: {e}")
            exit_code = 1
        finally:
            duration = time.time() - start_time
            try:
                cmd_str = " ".join(cmd) if cmd else action
                vps = values.get("vps") or get_active_vps()
                log_name = f"[DRY-RUN] {action}" if dry_run else action
                log_action_event(action=log_name, vps=vps, exit_code=exit_code, duration=duration, command=cmd_str)
            except Exception:
                pass

        choice = input("\nPress Enter to return to Dashboard, or type 'q' and press Enter to exit: ").strip().lower()
        if choice == "q":
            sys.stdout.write("\033[H\033[J")
            print("Exiting stack manager. Goodbye!")
            sys.exit(0)

    live.start()
    set_mouse_tracking(True)


def trigger_action(
    action_name: str,
    items: list[dict],
    live: "Live",
    action_status: dict,
    confirmation_state: dict,
    dry_run: bool = False,
) -> None:
    """Trigger an action or open confirmation dialog for branch guard / destructive actions."""
    if dry_run:
        execute_action(action_name, items, live, action_status, confirmed=True, allow_dev=False, dry_run=True)
        return

    branch = get_current_git_branch()
    is_dev = bool(branch and not is_main_branch())
    is_mutating = action_name in ("deploy", "redeploy", "stop", "update")

    values = {}
    for item in items:
        if item.get("type") == "checkbox":
            values[item.get("id")] = item.get("checked")
        elif item.get("type") == "numeric":
            values[item.get("id")] = item.get("value")
        elif item.get("type") == "radio" and item.get("selected"):
            values[item.get("group")] = item.get("value")

    if is_dev and is_mutating:
        confirmation_state.update({
            "active": True,
            "action": action_name,
            "items": items,
            "allow_dev": True,
            "warning": (
                f"Branch Guard Notice:\n"
                f"You are currently on development branch '{branch}'.\n"
                f"Mutating action '{action_name.upper()}' is restricted to 'main' by default.\n\n"
                f"Press Y to force execution on this branch with --allow-dev."
            ),
        })
    elif action_name == "stop":
        confirmation_state.update({
            "active": True,
            "action": action_name,
            "items": items,
            "allow_dev": False,
            "warning": "This will gracefully stop and shut down ALL active stack containers.",
        })
    elif action_name == "backup_op" and values.get("backup_cmd") == "restore":
        confirmation_state.update({
            "active": True,
            "action": action_name,
            "items": items,
            "allow_dev": False,
            "warning": "This will overwrite current configurations and databases from a backup snapshot.",
        })
    elif action_name == "network" and values.get("net_cmd") == "reset-tailscale":
        confirmation_state.update({
            "active": True,
            "action": action_name,
            "items": items,
            "allow_dev": False,
            "warning": "This will stop Tailscale and completely DELETE its persistent authentication state.",
        })
    else:
        execute_action(action_name, items, live, action_status, allow_dev=False)



def find_palette_matches(categories: list[dict], query: str) -> list[tuple]:
    """Return searchable action entries matching the current palette query."""
    query = query.lower().strip()
    matches = []
    for category_idx, category in enumerate(categories):
        radio_groups = {}
        for item in category["items"]:
            if item.get("type") == "radio":
                radio_groups.setdefault(item.get("group"), []).append(item)
        radio_options = list(radio_groups.values())

        for item_idx, item in enumerate(category["items"]):
            if item.get("type") != "action":
                continue
            option_sets = product(*radio_options) if radio_options else [()]
            for option_set in option_sets:
                selections = {option.get("group"): option.get("value") for option in option_set}
                option_labels = ", ".join(option.get("label", "") for option in option_set)
                label = item["label"]
                if option_labels:
                    label = f"{label} [{option_labels}]"
                haystack = f"{category['name']} {label}".lower()
                if not query or query in haystack:
                    matches.append((category_idx, item_idx, category["name"], label, selections))
    return matches


def render_palette(palette_state: dict, categories: list[dict]) -> "Table":
    """Render the command palette with sliding viewport and Cyber-Slate styling."""
    query = palette_state.get("query", "")
    matches = find_palette_matches(categories, query)
    selected = palette_state.get("selected", 0)
    palette_state["matches"] = matches
    if matches:
        selected = max(0, min(selected, len(matches) - 1))
        palette_state["selected"] = selected

    PAGE = 10
    # Sliding window centered on selected item
    if matches:
        half = PAGE // 2
        start = max(0, min(selected - half, len(matches) - PAGE))
        end = min(len(matches), start + PAGE)
        visible = list(enumerate(matches))[start:end]
    else:
        visible = []
        start = 0

    outer = Table.grid(expand=True, padding=(0, 0))
    outer.add_column()

    # Palette header
    hdr = Text()
    hdr.append("\n  Command Palette", style=f"bold {TUI_THEME['c_brand']}")
    hdr.append("   Search across all actions and utilities\n", style=f"dim {TUI_THEME['c_muted']}")
    outer.add_row(hdr)

    # Search bar
    search_bar = Table(box=rich_box.ROUNDED, expand=True, show_header=False,
                       border_style=TUI_THEME["active_border"], padding=(0, 1))
    search_bar.add_column()
    search_bar.add_row(Text(f"  > {query}_", style=f"bold {TUI_THEME['c_text']}"))
    outer.add_row(search_bar)
    outer.add_row(Text(""))

    if not matches:
        outer.add_row(Text(f"  No actions match '{query}'\n" if query else "  Type to search actions and utilities...\n",
                           style=f"dim {TUI_THEME['c_muted']}"))
    else:
        results_tbl = Table(
            box=rich_box.ROUNDED,
            expand=True,
            show_header=True,
            border_style=TUI_THEME["inactive_border"],
            padding=(0, 1),
        )
        results_tbl.add_column("#", width=3, justify="center")
        results_tbl.add_column("Module / Category", width=22)
        results_tbl.add_column("Action / Target Command", ratio=1)

        for idx, (_, _, category_name, label, _) in visible:
            is_sel = (idx == selected)
            marker = Text("▸", style=f"bold {TUI_THEME['c_brand']}") if is_sel else Text(" ")
            cat_badge = Text(
                f" {category_name[:18]} ",
                style=f"bold reverse {TUI_THEME['c_brand']}" if is_sel else f"dim {TUI_THEME['c_muted']}",
            )
            lbl_text = Text(
                label,
                style=f"bold {TUI_THEME['c_text']}" if is_sel else TUI_THEME["content_unselected"],
            )
            results_tbl.add_row(marker, cat_badge, lbl_text)


        outer.add_row(results_tbl)

        if len(matches) > PAGE:
            more_text = Text()
            more_text.append(
                f"  {len(matches)} total results — Use Up/Down to scroll\n",
                style=f"dim {TUI_THEME['c_muted']}",
            )
            outer.add_row(more_text)

    footer = Text()
    footer.append(
        f"  [Up/Down] Navigate   [Enter] Run   [Esc] Close   [{len(matches)} results]",
        style=f"bold {TUI_THEME['c_brand']}",
    )
    outer.add_row(footer)
    return outer


def render_confirmation(confirmation_state: dict) -> "Table":
    """Render a styled in-dashboard confirmation / branch-guard modal."""
    is_branch_guard = confirmation_state.get("allow_dev", False)
    action_name = confirmation_state.get("action", "ACTION").upper()
    warning = confirmation_state.get("warning", "This action may be destructive.")

    outer = Table.grid(expand=True, padding=(0, 0))
    outer.add_column()

    # Title row
    title_text = Text()
    if is_branch_guard:
        title_text.append("\n  Branch Guard Warning\n", style=f"bold {TUI_THEME['c_accent']}")
    else:
        title_text.append("\n  Confirm Action\n", style=f"bold {TUI_THEME['c_danger']}")
    outer.add_row(title_text)

    # Action pill badge
    badge_row = Text()
    badge_row.append("  Action:  ", style=f"dim {TUI_THEME['c_muted']}")
    badge_row.append(f" {action_name} ", style=f"bold reverse {TUI_THEME['c_brand']}")
    badge_row.append("\n")
    outer.add_row(badge_row)
    outer.add_row(Text(""))

    # Warning body
    warning_style = TUI_THEME["c_accent"] if is_branch_guard else TUI_THEME["c_danger"]
    for line in warning.splitlines():
        body_row = Text()
        body_row.append(f"  {line}", style=warning_style)
        outer.add_row(body_row)

    outer.add_row(Text(""))

    # Key binding footer
    bindings = Text()
    bindings.append("  ")
    if is_branch_guard:
        bindings.append(" Y / Enter ", style=f"bold reverse {TUI_THEME['c_success']}")
        bindings.append("  Force with --allow-dev   ", style=f"dim {TUI_THEME['c_muted']}")
    else:
        bindings.append(" Y / Enter ", style=f"bold reverse {TUI_THEME['c_success']}")
        bindings.append("  Confirm   ", style=f"dim {TUI_THEME['c_muted']}")
    bindings.append(" N / Esc ", style=f"bold reverse {TUI_THEME['c_danger']}")
    bindings.append("  Cancel", style=f"dim {TUI_THEME['c_muted']}")
    outer.add_row(bindings)
    return outer


def update_layout(
    layout: "Layout",
    menu_state: dict,
    categories: list[dict],
    action_status: dict,
    palette_state: dict,
    confirmation_state: dict,
    log_state: dict,
    history_state: dict,
    status_state: dict | None = None,
) -> list[int]:
    """Draw the single-pane layout (Header, Main Content, Footer) using Rich."""
    if status_state is None:
        status_state = {"active": False}

    vps_label = get_active_vps()
    branch = get_current_git_branch()
    on_main = is_main_branch() or not branch

    header_text = Text()
    header_text.append("NET-STREAM", style=f"bold {TUI_THEME['c_brand']}")
    header_text.append("  Control Center", style=f"bold {TUI_THEME['c_text']}")
    header_text.append("   ", style="")
    header_text.append(f" Node {vps_label} ", style=f"bold reverse {TUI_THEME['c_brand']}")
    header_text.append("  ", style="")
    if on_main:
        header_text.append(f" {branch or 'main'} ", style=f"bold reverse {TUI_THEME['c_success']}")
    else:
        header_text.append(f" {branch} ", style=f"bold reverse {TUI_THEME['c_accent']}")
        header_text.append("  DEV BRANCH  ", style=f"bold {TUI_THEME['c_accent']}")
    layout["header"].update(Panel(
        header_text,
        border_style=TUI_THEME["header_border"],
        box=rich_box.ROUNDED,
        padding=(0, 1),
    ))

    selectable_indices = []

    if confirmation_state.get("active"):
        is_branch_guard = confirmation_state.get("allow_dev", False)
        border_col = TUI_THEME["warn_border"] if is_branch_guard else TUI_THEME["danger_border"]
        title_text = "Branch Guard Warning" if is_branch_guard else "Confirmation Required"
        layout["main"].update(Panel(
            render_confirmation(confirmation_state),
            border_style=border_col,
            title=f"[bold]{title_text}[/bold]",
            title_align="left",
            box=rich_box.ROUNDED,
        ))
    elif palette_state.get("active"):
        layout["main"].update(Panel(
            render_palette(palette_state, categories),
            border_style=TUI_THEME["active_border"],
            title="[bold]Command Palette[/bold]",
            title_align="left",
            box=rich_box.ROUNDED,
        ))
    elif log_state.get("active"):
        layout["main"].update(Panel(
            render_log_view(action_status=action_status, log_state=log_state),
            border_style=TUI_THEME["active_border"],
            title="[bold]Activity & Container Logs[/bold]",
            title_align="left",
            box=rich_box.ROUNDED,
        ))
    elif history_state.get("active"):
        layout["main"].update(Panel(
            render_history_view(offset=history_state.get("offset", 0)),
            border_style=TUI_THEME["active_border"],
            title="[bold]Action Execution History[/bold]",
            title_align="left",
            box=rich_box.ROUNDED,
        ))
    elif status_state.get("active"):
        show_table = status_state.get("show_table", False)
        status_node = status_state.get("node_filter") or vps_label
        layout["main"].update(Panel(
            render_status_view(
                vps_label=status_node,
                show_table=show_table,
                offset=status_state.get("offset", 0),
                query=status_state.get("query", ""),
                state_filter=status_state.get("state_filter", "ALL"),
                is_searching=status_state.get("is_searching", False),
            ),
            border_style=TUI_THEME["active_border"],
            title="[bold]Infrastructure Health Inspector[/bold]",
            title_align="left",
            box=rich_box.ROUNDED,
        ))
    elif menu_state["view"] == "main":
        # --- Main Menu: Compact Tabulated Grid + Rich Informational Context Dashboard ---
        outer = Table.grid(expand=True, padding=(0, 0))
        outer.add_column()

        menu_tbl = Table(
            box=rich_box.ROUNDED,
            expand=True,
            show_header=True,
            show_lines=False,
            border_style=TUI_THEME["inactive_border"],
            padding=(0, 1),
        )
        menu_tbl.add_column("#", width=8, justify="center", no_wrap=True)
        menu_tbl.add_column("Operation / Module", ratio=2)
        menu_tbl.add_column("Workflow Summary", ratio=4)
        menu_tbl.add_column("Capabilities", width=18, justify="center")

        for idx, cat in enumerate(categories):
            is_selected = (idx == menu_state["main_idx"])
            pointer = TUI_THEME["pointer"] if is_selected else "  "
            num = str(idx + 1)
            cap_tag = CATEGORY_CAPABILITIES.get(cat.get("id", ""), "[ WORKFLOW ]")

            num_style = f"bold {TUI_THEME['c_accent']}" if is_selected else f"bold {TUI_THEME['c_brand']}"
            name_style = f"bold {TUI_THEME['c_text']}" if is_selected else TUI_THEME["content_unselected"]
            desc_style = f"bold {TUI_THEME['c_brand']}" if is_selected else f"dim {TUI_THEME['c_text']}"
            cap_style = f"bold reverse {TUI_THEME['c_brand']}" if is_selected else f"dim {TUI_THEME['c_muted']}"

            menu_tbl.add_row(
                Text(f"{pointer}[{num}]", style=num_style),
                Text(cat["name"], style=name_style),
                Text(cat["desc"], style=desc_style),
                Text(cap_tag, style=cap_style),
            )

            # Horizontal section dividers between functional groups
            if idx in (2, 5, 7) and idx < len(categories) - 1:
                menu_tbl.add_section()


        outer.add_row(menu_tbl)
        outer.add_row(Text(""))

        # --- Lower Half: Informational Context Dashboard ---
        sel_cat = categories[menu_state["main_idx"]]
        
        # Query cached service metrics
        svcs = get_cached_services(vps=vps_label, ttl=10.0)
        cnts = get_cached_containers(ttl=10.0)
        c_map = {c.get("Names"): c for c in cnts}
        recs = _classify_services(svcs, c_map) if svcs else []
        tot_cnt = len(recs)
        hlth_cnt = sum(1 for _, st, _, _, _ in recs if st == "HEALTHY")
        run_cnt = sum(1 for _, st, _, _, _ in recs if st == "RUNNING")
        stop_cnt = sum(1 for _, st, _, _, _ in recs if st == "STOPPED")

        info_tbl = Table(box=rich_box.ROUNDED, expand=True, show_header=False,
                         border_style=TUI_THEME["inactive_border"], padding=(0, 2))
        info_tbl.add_column(ratio=3)
        info_tbl.add_column(ratio=2)

        left_side = Table.grid(expand=True, padding=(0, 0))
        left_side.add_column()

        # Selected Category Focus
        focus_txt = Text()
        focus_txt.append("Focused Category: ", style=f"dim {TUI_THEME['c_muted']}")
        focus_txt.append(sel_cat["name"], style=f"bold {TUI_THEME['c_brand']}")
        left_side.add_row(focus_txt)

        desc_txt = Text()
        desc_txt.append(f"  {sel_cat['desc']}", style=f"dim {TUI_THEME['c_text']}")
        left_side.add_row(desc_txt)
        left_side.add_row(Text(""))

        # Last Execution
        last_txt = Text()
        last_txt.append("Last Operation: ", style=f"dim {TUI_THEME['c_muted']}")
        state = action_status.get("state", "idle")
        if state == "success":
            last_txt.append(f"{action_status.get('action','').upper()} ", style=f"bold {TUI_THEME['c_success']}")
            last_txt.append("succeeded", style=f"dim {TUI_THEME['c_success']}")
        elif state == "failed":
            last_txt.append(f"{action_status.get('action','').upper()} ", style=f"bold {TUI_THEME['c_danger']}")
            last_txt.append("failed", style=f"dim {TUI_THEME['c_danger']}")
        else:
            last_txt.append("Ready / Awaiting Selection", style=f"dim {TUI_THEME['c_muted']}")
        left_side.add_row(last_txt)

        # Right side: Metric summary cards for active node
        right_side = Table.grid(expand=True, padding=(0, 0))
        right_side.add_column()

        snap_hdr = Text()
        snap_hdr.append(f"Node {vps_label} Infrastructure Snapshot", style=f"bold {TUI_THEME['c_text']}")
        right_side.add_row(snap_hdr)

        metrics_row = Text()
        metrics_row.append(f"Stacks: {tot_cnt} ", style=f"bold {TUI_THEME['c_brand']}")
        metrics_row.append(f"│ Healthy: {hlth_cnt} ", style=f"bold {TUI_THEME['c_success']}")
        metrics_row.append(f"│ Running: {run_cnt} ", style=f"bold {TUI_THEME['c_warn']}")
        metrics_row.append(f"│ Stopped: {stop_cnt}", style=f"bold {TUI_THEME['c_danger']}")
        right_side.add_row(metrics_row)
        right_side.add_row(Text(""))

        node_vps = vps_label.upper() if vps_label and vps_label.upper() != "ALL" else "A"
        sys_ctx = Text()
        sys_ctx.append("Secrets: ", style=f"dim {TUI_THEME['c_muted']}")
        sys_ctx.append(f"net-stream-vps-{node_vps.lower()} ", style=f"bold {TUI_THEME['c_accent']}")
        sys_ctx.append("│ Mesh: ", style=f"dim {TUI_THEME['c_muted']}")
        sys_ctx.append("Tailscale MagicDNS", style=f"bold {TUI_THEME['c_brand']}")
        right_side.add_row(sys_ctx)

        info_tbl.add_row(left_side, right_side)
        outer.add_row(info_tbl)

        layout["main"].update(Panel(
            outer,
            border_style=TUI_THEME["active_border"],
            title="[bold]Main Menu[/bold]",
            title_align="left",
            box=rich_box.ROUNDED,
            padding=(0, 1),
        ))
    else:
        active_cat = categories[menu_state["main_idx"]]
        cat_id = active_cat.get("id", "")
        outer = Table.grid(expand=True, padding=(0, 0))
        outer.add_column()

        desc_row = Text()
        desc_row.append(f"  {active_cat['desc']}\n", style=f"italic dim {TUI_THEME['c_muted']}")
        outer.add_row(desc_row)

        detail_tbl = Table(
            box=rich_box.ROUNDED,
            expand=True,
            show_header=True,
            show_lines=False,
            border_style=TUI_THEME["inactive_border"],
            padding=(0, 1),
        )
        detail_tbl.add_column("#", width=8, justify="center", no_wrap=True)
        detail_tbl.add_column("State", width=9, justify="center")
        detail_tbl.add_column("Setting / Parameter", ratio=3)
        detail_tbl.add_column("CLI Flag / Target", ratio=2)

        items = active_cat["items"]
        cur_action_name = None
        for item_idx, item in enumerate(items):
            t = item.get("type")
            flag_hint = get_item_flag_hint(item)
            if t == "separator":
                detail_tbl.add_row(
                    Text(""),
                    Text("───", style=f"dim {TUI_THEME['inactive_border']}"),
                    Text("────────────────────────────────────────", style=f"dim {TUI_THEME['inactive_border']}"),
                    Text("─────────────", style=f"dim {TUI_THEME['inactive_border']}"),
                )
            elif t == "info":
                detail_tbl.add_row(
                    Text(""),
                    Text("ℹ", style=f"bold {TUI_THEME['c_accent']}"),
                    Text(item.get("label", ""), style=f"dim {TUI_THEME['c_text']}"),
                    Text(""),
                )
            else:
                selectable_indices.append(item_idx)
                is_selected = (len(selectable_indices) - 1 == menu_state["item_idx"])
                pointer = TUI_THEME["pointer"] if is_selected else "  "
                row_num = len(selectable_indices)

                num_style = f"bold {TUI_THEME['c_accent']}" if is_selected else f"bold {TUI_THEME['c_brand']}"
                label_style = f"bold {TUI_THEME['c_text']}" if is_selected else TUI_THEME["content_unselected"]
                flag_style = f"bold {TUI_THEME['c_brand']}" if is_selected else f"dim {TUI_THEME['c_brand']}"

                if t == "checkbox":
                    state_text = (
                        Text("[X]", style=f"bold {TUI_THEME['c_success']}")
                        if item.get("checked")
                        else Text("[ ]", style=f"dim {TUI_THEME['c_muted']}")
                    )
                    detail_tbl.add_row(
                        Text(f"{pointer}[{row_num}]", style=num_style),
                        state_text,
                        Text(item.get("label", ""), style=label_style),
                        Text(flag_hint, style=flag_style),
                    )

                elif t == "radio":
                    state_text = (
                        Text("(●)", style=f"bold {TUI_THEME['c_brand']}")
                        if item.get("selected")
                        else Text("(○)", style=f"dim {TUI_THEME['c_muted']}")
                    )
                    detail_tbl.add_row(
                        Text(f"{pointer}[{row_num}]", style=num_style),
                        state_text,
                        Text(item.get("label", ""), style=label_style),
                        Text(flag_hint, style=flag_style),
                    )

                elif t == "numeric":
                    val = item.get("value")
                    state_text = Text(f"[ {val} ]", style=f"bold {TUI_THEME['c_accent']}")
                    detail_tbl.add_row(
                        Text(f"{pointer}[{row_num}]", style=num_style),
                        state_text,
                        Text(item.get("label", ""), style=label_style),
                        Text(flag_hint, style=flag_style),
                    )

                elif t == "action":
                    cur_action_name = item.get("action")
                    label = item.get("label", "").strip("[] ")
                    state_text = Text("[EXEC]", style=f"bold {TUI_THEME['c_success']}")
                    action_label = (
                        Text(f" {label} ", style=f"bold reverse {TUI_THEME['c_success']}")
                        if is_selected
                        else Text(f"[ {label} ]", style=f"bold {TUI_THEME['c_success']}")
                    )
                    detail_tbl.add_row(
                        Text(f"{pointer}[{row_num}]", style=num_style),
                        state_text,
                        action_label,
                        Text(flag_hint, style=f"bold {TUI_THEME['c_success']}"),
                    )

        outer.add_row(detail_tbl)
        outer.add_row(Text(""))

        # --- Lower Half: Rich Operational Context & Target Inventory Panel ---
        preview_values = {}
        target_vps = vps_label
        for itm in items:
            if itm.get("type") == "checkbox":
                preview_values[itm.get("id")] = itm.get("checked")
            elif itm.get("type") == "numeric":
                preview_values[itm.get("id")] = itm.get("value")
            elif itm.get("type") == "radio" and itm.get("selected"):
                preview_values[itm.get("group")] = itm.get("value")
                if itm.get("group") in ("vps", "backup_vps"):
                    target_vps = itm.get("value")

        cmd_preview = []
        if cur_action_name:
            try:
                cmd_preview = get_action_command(cur_action_name, preview_values)
            except Exception:
                pass

        # Query services for the target VPS
        svcs = get_cached_services(vps=target_vps, ttl=10.0)
        cnts = get_cached_containers(ttl=10.0)
        c_map = {c.get("Names"): c for c in cnts}
        recs = _classify_services(svcs, c_map) if svcs else []
        tot_cnt = len(recs)
        hlth_cnt = sum(1 for _, st, _, _, _ in recs if st == "HEALTHY")
        run_cnt = sum(1 for _, st, _, _, _ in recs if st == "RUNNING")
        stop_cnt = sum(1 for _, st, _, _, _ in recs if st == "STOPPED")

        # Category contextual tips
        cat_tips = {
            "deploy_wizard": "Deploys services in dependency order within isolated VPN namespaces.",
            "redeploy": "Performs rolling refresh or recreation of existing active workloads.",
            "stop_stack": "Gracefully halts running containers while preserving persistent volumes.",
            "registry_updates": "Checks upstream registries against stability age-gates with backup snapshots.",
            "secrets": "Doppler SaaS runtime injection with encrypted SOPS fallback snapshots.",
            "backup_restic": "Deduplicated, encrypted volume snapshots with retention policy pruning.",
            "network": "Repairs Tailscale MagicDNS routing, subnet routes, and VPN gateways.",
            "sysutils": "Pre-flight infrastructure diagnostics, Compose linting, and health inspection.",
        }
        tip_text = cat_tips.get(cat_id, "Net-Stream modular orchestration workflow.")

        detail_info_tbl = Table(box=rich_box.ROUNDED, expand=True, show_header=False,
                                border_style=TUI_THEME["inactive_border"], padding=(0, 2))
        detail_info_tbl.add_column(ratio=3)
        detail_info_tbl.add_column(ratio=2)

        # Left Column: Command preview & action details
        left_col = Table.grid(expand=True, padding=(0, 0))
        left_col.add_column()

        cmd_hdr = Text()
        cmd_hdr.append("Command Execution Preview: ", style=f"dim {TUI_THEME['c_muted']}")
        left_col.add_row(cmd_hdr)

        if cmd_preview:
            display_cmd = [c if not c.endswith("manage.py") and not c.startswith("/") else ("./manage.py" if "manage.py" in c else c) for c in cmd_preview if not c.endswith("python3") and not c.endswith("python")]
            cmd_text = Text(f"  {' '.join(display_cmd)}", style=f"bold {TUI_THEME['c_brand']}")
            left_col.add_row(cmd_text)
        else:
            left_col.add_row(Text("  Interactive Configuration & Parameter Inspector", style=f"dim {TUI_THEME['c_muted']}"))

        left_col.add_row(Text(""))

        arch_note = Text()
        arch_note.append("Architecture: ", style=f"dim {TUI_THEME['c_muted']}")
        arch_note.append(tip_text, style=f"dim {TUI_THEME['c_text']}")
        left_col.add_row(arch_note)

        # Right Column: Target Node & Live container inventory
        right_col = Table.grid(expand=True, padding=(0, 0))
        right_col.add_column()

        node_hdr = Text()
        node_hdr.append(f"Target: Node {target_vps} Inventory", style=f"bold {TUI_THEME['c_text']}")
        right_col.add_row(node_hdr)

        status_line = Text()
        status_line.append(f"Declared: {tot_cnt} stacks ", style=f"bold {TUI_THEME['c_brand']}")
        status_line.append(f"│ Healthy: {hlth_cnt} ", style=f"bold {TUI_THEME['c_success']}")
        status_line.append(f"│ Stopped: {stop_cnt}", style=f"bold {TUI_THEME['c_danger']}")
        right_col.add_row(status_line)

        right_col.add_row(Text(""))

        is_mut = cur_action_name in ("deploy", "redeploy", "stop", "update")
        safety_line = Text()
        safety_line.append("Mode: ", style=f"dim {TUI_THEME['c_muted']}")
        if is_mut:
            safety_line.append("Mutating Operation ", style=f"bold {TUI_THEME['c_warn']}")
            safety_line.append("([P] for Safe Preview)", style=f"dim {TUI_THEME['c_accent']}")
        else:
            safety_line.append("Read-only / Safe Diagnostic", style=f"bold {TUI_THEME['c_success']}")
        right_col.add_row(safety_line)

        detail_info_tbl.add_row(left_col, right_col)
        outer.add_row(detail_info_tbl)

        layout["main"].update(Panel(
            outer,
            border_style=TUI_THEME["active_border"],
            title=f"[bold]{active_cat['name']}[/bold]",
            title_align="left",
            box=rich_box.ROUNDED,
            padding=(0, 1),
        ))







    # Status bar (line 1)
    state = action_status.get("state", "idle")
    duration = action_status.get("duration")
    timing = f" ({duration:.1f}s)" if duration is not None else ""

    footer_text = Text()
    if state == "success":
        footer_text.append(" SUCCESS ", style=f"bold reverse {TUI_THEME['c_success']}")
        footer_text.append(f"  {action_status.get('action', 'ACTION').upper()} completed{timing}", style=f"bold {TUI_THEME['c_success']}")
    elif state == "failed":
        code = action_status.get("exit_code")
        code_text = f" (exit {code})" if code is not None else ""
        footer_text.append(" FAILED ", style=f"bold reverse {TUI_THEME['c_danger']}")
        footer_text.append(f"  {action_status.get('action', 'ACTION').upper()} failed{code_text}{timing}", style=f"bold {TUI_THEME['c_danger']}")
    elif state == "cancelled":
        footer_text.append(" CANCELLED ", style=f"bold reverse {TUI_THEME['c_warn']}")
        footer_text.append(f"  {action_status.get('action', 'ACTION').upper()}{timing}", style=f"{TUI_THEME['c_warn']}")
    elif state == "running":
        footer_text.append(" RUNNING ", style=f"bold reverse {TUI_THEME['c_accent']}")
        footer_text.append(f"  {action_status.get('action', 'ACTION').upper()}", style=f"bold {TUI_THEME['c_accent']}")
    else:
        footer_text.append(" READY ", style=f"bold reverse {TUI_THEME['c_muted']}")
        footer_text.append("  Awaiting command", style=TUI_THEME["footer_style"])

    footer_text.append("\n")

    # Context-sensitive key bindings (line 2)
    is_subview = (
        log_state.get("active") or history_state.get("active") or status_state.get("active")
    )
    if is_subview:
        footer_text.append(
            "[Up/Down] Scroll   [PgUp/PgDn] Page   "
            "[F] Follow (logs)   [V/Tab] Toggle View (status)   [R] Refresh   [Esc/Key] Close",
            style=TUI_THEME["footer_style"],
        )
    elif palette_state.get("active"):
        footer_text.append(
            "[Up/Down] Navigate Results   [Enter] Run   [Esc] Close",
            style=TUI_THEME["footer_style"],
        )
    elif menu_state["view"] == "main":
        footer_text.append(
            "[1-9] Select Category   [Up/Down] Navigate   [Enter] Open   [R] Run   [P] Dry-Run   "
            "[/] Search   [S] Status   [L] Logs   [H] History   [D] Doctor   [Q] Exit",
            style=TUI_THEME["footer_style"],
        )
    else:
        footer_text.append(
            "[1-9] Select   [Up/Down] Navigate   [Space/Enter] Toggle   "
            "[R] Run Action   [P] Dry-Run   [Esc] Back   [/] Search   [D] Doctor   [Q] Exit",
            style=TUI_THEME["footer_style"],
        )


    layout["footer"].update(Panel(
        footer_text,
        border_style=TUI_THEME["footer_border"],
        box=rich_box.ROUNDED,
        padding=(0, 1),
    ))

    return selectable_indices


def run_dashboard(vps: str | None = None) -> None:
    """Run the modern Rich-based interactive dashboard."""
    if not HAS_RICH:
        print("Rich library is required for the full dashboard UI. Falling back to simple CLI.")
        return

    active_vps = vps or get_active_vps()
    categories = get_dashboard_categories()

    for cat in categories:
        if cat["id"] == "deploy_wizard":
            for item in cat["items"]:
                if item.get("group") == "vps":
                    item["selected"] = (item["value"] == active_vps)
        elif cat["id"] == "backup_restic":
            for item in cat["items"]:
                if item.get("group") == "backup_vps":
                    item["selected"] = (item["value"] == active_vps)

    menu_state = {"view": "main", "main_idx": 0, "item_idx": 0}
    action_status = {"state": "idle"}
    palette_state = {"active": False, "query": "", "selected": 0, "matches": []}
    confirmation_state = {"active": False}
    log_state = {"active": False, "offset": 0, "follow": True}
    history_state = {"active": False}
    status_state = {"active": False}

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3),
    )

    update_layout(
        layout,
        menu_state,
        categories,
        action_status,
        palette_state,
        confirmation_state,
        log_state,
        history_state,
        status_state,
    )

    set_mouse_tracking(True)

    try:
        with RawTerminalContext() as term_fd:
            with Live(layout, auto_refresh=False, screen=True) as live:
                while True:
                    selectable_indices = update_layout(
                        layout,
                        menu_state,
                        categories,
                        action_status,
                        palette_state,
                        confirmation_state,
                        log_state,
                        history_state,
                        status_state,
                    )
                    live.update(layout, refresh=True)


                    key = get_key(term_fd, timeout=0.05)
                    if key is None:
                        continue

                    # Global Views Toggle
                    if confirmation_state.get("active"):
                        if key in ("y", "Y", "\n", "\r"):
                            confirmed_action = confirmation_state.get("action")
                            target_items = confirmation_state.get("items")
                            if target_items is None:
                                target_items = categories[menu_state["main_idx"]]["items"]
                            allow_dev = confirmation_state.get("allow_dev", False)
                            confirmation_state["active"] = False
                            execute_action(
                                confirmed_action,
                                target_items,
                                live,
                                action_status,
                                confirmed=True,
                                allow_dev=allow_dev,
                            )
                        elif key in ("n", "N", "\x1b", "q", "Q"):
                            confirmation_state["active"] = False
                        continue

                    if palette_state.get("active"):
                        if key in ("\x1b",):
                            palette_state["active"] = False
                        elif key == "\x1b[A":
                            matches = palette_state.get("matches", [])
                            if matches:
                                palette_state["selected"] = (palette_state.get("selected", 0) - 1) % len(matches)
                        elif key == "\x1b[<wheel_up>":
                            palette_state["selected"] = max(0, palette_state.get("selected", 0) - 1)
                        elif key == "\x1b[B":
                            matches = palette_state.get("matches", [])
                            if matches:
                                palette_state["selected"] = (palette_state.get("selected", 0) + 1) % len(matches)
                        elif key == "\x1b[<wheel_down>":
                            matches = palette_state.get("matches", [])
                            palette_state["selected"] = min(len(matches) - 1, palette_state.get("selected", 0) + 1)
                        elif key in ("\n", "\r"):
                            matches = palette_state.get("matches", [])
                            idx = palette_state.get("selected", 0)
                            if matches and 0 <= idx < len(matches):
                                cat_idx, item_idx, _, _, selections = matches[idx]
                                palette_state["active"] = False
                                menu_state["view"] = "detail"
                                menu_state["main_idx"] = cat_idx
                                target_cat = categories[cat_idx]
                                for opt_grp, opt_val in selections.items():
                                    for itm in target_cat["items"]:
                                        if itm.get("type") == "radio" and itm.get("group") == opt_grp:
                                            itm["selected"] = (itm.get("value") == opt_val)
                                act_name = target_cat["items"][item_idx].get("action")
                                trigger_action(act_name, target_cat["items"], live, action_status, confirmation_state)
                        elif key in ("\x7f", "\x08"):
                            palette_state["query"] = palette_state.get("query", "")[:-1]
                        elif len(key) == 1 and key.isprintable():
                            palette_state["query"] = palette_state.get("query", "") + key
                        continue

                    if status_state.get("active"):
                        if status_state.get("is_searching"):
                            if key in ("\r", "\n"):
                                status_state["is_searching"] = False
                            elif key in ("\x1b",):
                                status_state["is_searching"] = False
                                status_state["query"] = ""
                                status_state["offset"] = 0
                            elif key in ("\x7f", "\x08", "KEY_BACKSPACE"):
                                status_state["query"] = status_state.get("query", "")[:-1]
                                status_state["offset"] = 0
                            elif len(key) == 1 and key.isprintable():
                                status_state["query"] = status_state.get("query", "") + key
                                status_state["show_table"] = True
                                status_state["offset"] = 0
                            continue

                        if key in ("\x1b", "s", "S", "q", "Q"):
                            status_state["active"] = False
                            status_state["is_searching"] = False
                            status_state["query"] = ""
                        elif key == "/":
                            status_state["is_searching"] = True
                            status_state["show_table"] = True
                        elif key in ("c", "C"):
                            status_state["query"] = ""
                            status_state["state_filter"] = "ALL"
                            status_state["offset"] = 0
                        elif key in ("f", "F"):
                            states = ["ALL", "HEALTHY", "RUNNING", "STOPPED"]
                            cur_st = status_state.get("state_filter", "ALL").upper()
                            idx = (states.index(cur_st) + 1) % len(states) if cur_st in states else 0
                            status_state["state_filter"] = states[idx]
                            status_state["offset"] = 0
                        elif key in ("n", "N"):
                            cur_node = (status_state.get("node_filter") or get_active_vps()).upper()
                            if cur_node == "A":
                                status_state["node_filter"] = "B"
                            elif cur_node == "B":
                                status_state["node_filter"] = "ALL"
                            else:
                                status_state["node_filter"] = "A"
                            status_state["offset"] = 0
                        elif key in ("r", "R"):
                            from orchestrator.ui.inspector import (
                                get_cached_containers,
                                get_cached_services,
                            )
                            get_cached_services(force=True)
                            get_cached_containers(force=True)
                        elif key in ("v", "V", "\t"):
                            status_state["show_table"] = not status_state.get("show_table", False)
                            status_state["offset"] = 0
                        elif key in ("\x1b[A", "\x1b[<wheel_up>"):
                            status_state["offset"] = max(0, status_state.get("offset", 0) - 1)
                        elif key in ("\x1b[B", "\x1b[<wheel_down>"):
                            status_state["offset"] = status_state.get("offset", 0) + 1
                        elif key == "\x1b[5~":  # PageUp
                            status_state["offset"] = max(0, status_state.get("offset", 0) - 10)
                        elif key == "\x1b[6~":  # PageDown
                            status_state["offset"] = status_state.get("offset", 0) + 10
                        continue

                    if history_state.get("active"):
                        if key in ("\x1b", "h", "H", "q", "Q"):
                            history_state["active"] = False
                        elif key in ("\x1b[A", "\x1b[<wheel_up>"):
                            history_state["offset"] = max(0, history_state.get("offset", 0) - 1)
                        elif key in ("\x1b[B", "\x1b[<wheel_down>"):
                            history_state["offset"] = history_state.get("offset", 0) + 1
                        elif key == "\x1b[5~":  # PageUp
                            history_state["offset"] = max(0, history_state.get("offset", 0) - 14)
                        elif key == "\x1b[6~":  # PageDown
                            history_state["offset"] = history_state.get("offset", 0) + 14
                        continue

                    if log_state.get("active"):
                        if key in ("\x1b", "l", "L", "q", "Q"):
                            log_state["active"] = False
                        elif key in ("f", "F"):
                            log_state["follow"] = not log_state.get("follow", True)
                        elif key in ("g",) or key == "\x1b[H":   # Home / g
                            log_state["follow"] = False
                            log_state["offset"] = 0
                        elif key in ("G",) or key == "\x1b[F":   # End / G
                            log_state["follow"] = True
                        elif key in ("\x1b[A", "\x1b[<wheel_up>"):
                            log_state["follow"] = False
                            log_state["offset"] = max(0, log_state.get("offset", 0) - 1)
                        elif key in ("\x1b[B", "\x1b[<wheel_down>"):
                            log_state["follow"] = False
                            log_state["offset"] = log_state.get("offset", 0) + 1
                        elif key == "\x1b[5~":  # PageUp
                            log_state["follow"] = False
                            log_state["offset"] = max(0, log_state.get("offset", 0) - 16)
                        elif key == "\x1b[6~":  # PageDown
                            log_state["follow"] = False
                            log_state["offset"] = log_state.get("offset", 0) + 16
                        continue

                    # Global hotkeys
                    if key in ("q", "Q"):
                        break
                    elif key in ("/",):
                        palette_state["active"] = True
                        palette_state["query"] = ""
                        palette_state["selected"] = 0
                        continue
                    elif key in ("s", "S"):
                        status_state["active"] = not status_state.get("active", False)
                        status_state.setdefault("offset", 0)
                        status_state.setdefault("show_table", False)
                        continue
                    elif key in ("h", "H"):
                        history_state["active"] = not history_state.get("active", False)
                        history_state.setdefault("offset", 0)
                        continue
                    elif key in ("l", "L"):
                        log_state["active"] = not log_state.get("active", False)
                        log_state.setdefault("follow", True)
                        continue
                    elif key in ("n", "N"):
                        # Quick node switcher — cycle active VPS context
                        _nodes = [n.id for n in get_registered_nodes()]
                        if _nodes:
                            _cur = get_active_vps().upper()
                            _idx = _nodes.index(_cur) if _cur in _nodes else 0
                            _next = _nodes[(_idx + 1) % len(_nodes)]
                            try:
                                set_active_vps(_next)
                            except Exception:  # noqa: BLE001
                                pass
                        continue
                    elif key in ("d", "D"):
                        trigger_action("sysutils", [{"type": "radio", "group": "sys_cmd", "value": "doctor", "selected": True}], live, action_status, confirmation_state)
                        continue

                    # Navigation & Selection
                    if menu_state["view"] == "main":
                        if key == "\x1b[A":
                            menu_state["main_idx"] = (menu_state["main_idx"] - 1) % len(categories)
                        elif key == "\x1b[<wheel_up>":
                            menu_state["main_idx"] = max(0, menu_state["main_idx"] - 1)
                        elif key == "\x1b[B":
                            menu_state["main_idx"] = (menu_state["main_idx"] + 1) % len(categories)
                        elif key == "\x1b[<wheel_down>":
                            menu_state["main_idx"] = min(len(categories) - 1, menu_state["main_idx"] + 1)
                        elif key in ("\n", "\r", " "):
                            menu_state["view"] = "detail"
                            menu_state["item_idx"] = 0
                        elif key.isdigit() and 1 <= int(key) <= len(categories):
                            menu_state["main_idx"] = int(key) - 1
                            menu_state["view"] = "detail"
                            menu_state["item_idx"] = 0
                        elif key in ("r", "R"):
                            active_cat = categories[menu_state["main_idx"]]
                            for item in active_cat["items"]:
                                if item.get("type") == "action":
                                    trigger_action(item.get("action"), active_cat["items"], live, action_status, confirmation_state)
                                    break
                        elif key in ("p", "P"):
                            active_cat = categories[menu_state["main_idx"]]
                            for item in active_cat["items"]:
                                if item.get("type") == "action":
                                    trigger_action(item.get("action"), active_cat["items"], live, action_status, confirmation_state, dry_run=True)
                                    break
                    else:
                        active_cat = categories[menu_state["main_idx"]]
                        num_selectable = len(selectable_indices)
                        if key == "\x1b[A":
                            if num_selectable > 0:
                                menu_state["item_idx"] = (menu_state["item_idx"] - 1) % num_selectable
                        elif key == "\x1b[<wheel_up>":
                            menu_state["item_idx"] = max(0, menu_state["item_idx"] - 1)
                        elif key == "\x1b[B":
                            if num_selectable > 0:
                                menu_state["item_idx"] = (menu_state["item_idx"] + 1) % num_selectable
                        elif key == "\x1b[<wheel_down>":
                            menu_state["item_idx"] = min(num_selectable - 1, menu_state["item_idx"] + 1)
                        elif key in ("\x1b", "\x7f", "\x08"):
                            menu_state["view"] = "main"
                        elif key.isdigit() and 1 <= int(key) <= num_selectable:
                            menu_state["item_idx"] = int(key) - 1
                            raw_idx = selectable_indices[menu_state["item_idx"]]
                            item = active_cat["items"][raw_idx]
                            if item.get("type") == "checkbox":
                                item["checked"] = not item.get("checked", False)
                            elif item.get("type") == "radio":
                                handle_radio_select(active_cat["items"], item)
                            elif item.get("type") == "numeric":
                                step = item.get("step", 1)
                                min_val = item.get("min", 0)
                                max_val = item.get("max", 9999)
                                cur = item.get("value", 0)
                                new_val = round(cur + step, 2)
                                if new_val > max_val:
                                    new_val = min_val
                                item["value"] = new_val if isinstance(step, float) else int(new_val)
                            elif item.get("type") == "action":
                                trigger_action(item.get("action"), active_cat["items"], live, action_status, confirmation_state)
                        elif key in ("\x1b[C", "+", "="):
                            if selectable_indices:
                                raw_idx = selectable_indices[menu_state["item_idx"]]
                                item = active_cat["items"][raw_idx]
                                if item.get("type") == "numeric":
                                    step = item.get("step", 1)
                                    max_val = item.get("max", 9999)
                                    cur = item.get("value", 0)
                                    new_val = round(cur + step, 2)
                                    if new_val <= max_val:
                                        item["value"] = new_val if isinstance(step, float) else int(new_val)
                        elif key in ("\x1b[D", "-", "_"):
                            if selectable_indices:
                                raw_idx = selectable_indices[menu_state["item_idx"]]
                                item = active_cat["items"][raw_idx]
                                if item.get("type") == "numeric":
                                    step = item.get("step", 1)
                                    min_val = item.get("min", 0)
                                    cur = item.get("value", 0)
                                    new_val = round(cur - step, 2)
                                    if new_val >= min_val:
                                        item["value"] = new_val if isinstance(step, float) else int(new_val)
                        elif key in ("\n", "\r", " "):
                            if selectable_indices:
                                raw_idx = selectable_indices[menu_state["item_idx"]]
                                item = active_cat["items"][raw_idx]
                                if item.get("type") == "checkbox":
                                    item["checked"] = not item.get("checked", False)
                                elif item.get("type") == "radio":
                                    handle_radio_select(active_cat["items"], item)
                                elif item.get("type") == "numeric":
                                    step = item.get("step", 1)
                                    min_val = item.get("min", 0)
                                    max_val = item.get("max", 9999)
                                    cur = item.get("value", 0)
                                    new_val = round(cur + step, 2)
                                    if new_val > max_val:
                                        new_val = min_val
                                    item["value"] = new_val if isinstance(step, float) else int(new_val)
                                elif item.get("type") == "action":
                                    trigger_action(item.get("action"), active_cat["items"], live, action_status, confirmation_state)
                        elif key in ("r", "R"):
                            for item in active_cat["items"]:
                                if item.get("type") == "action":
                                    trigger_action(item.get("action"), active_cat["items"], live, action_status, confirmation_state)
                                    break
                        elif key in ("p", "P"):
                            for item in active_cat["items"]:
                                if item.get("type") == "action":
                                    trigger_action(item.get("action"), active_cat["items"], live, action_status, confirmation_state, dry_run=True)
                                    break

    finally:
        set_mouse_tracking(False)


def render_checklist_layout(
    all_services: list,
    categories: dict[str, list],
    cat_names: list[str],
    checked_services: set[str],
    current_menu: str,
    selected_cat_idx: int,
    selected_svc_idx: int,
    active_cat: str,
    vps_label: str,
    verb: str,
    restored_notice: str | None = None,
) -> "Layout":
    """Build a double-buffered Rich layout for the checklist service selector."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3),
    )

    verb_title = verb.capitalize()
    checked_count = len([s for s in all_services if s.rel_dir in checked_services])
    total_count = len(all_services)

    # Header
    hdr = Text()
    hdr.append("NET-STREAM", style=f"bold {TUI_THEME['c_brand']}")
    hdr.append(f"  Interactive {verb_title} Selector", style=f"bold {TUI_THEME['c_text']}")
    hdr.append(f"  {vps_label}   ", style=f"dim {TUI_THEME['c_muted']}")
    frac_style = TUI_THEME["c_success"] if checked_count == total_count else (TUI_THEME["c_accent"] if checked_count > 0 else TUI_THEME["c_muted"])
    hdr.append(f" {checked_count}/{total_count} selected ", style=f"bold reverse {frac_style}")
    layout["header"].update(Panel(
        hdr,
        border_style=TUI_THEME["header_border"],
        box=rich_box.ROUNDED,
        padding=(0, 1),
    ))

    main_layout = Layout()
    main_layout.split_column(
        Layout(name="cards", size=4),
        Layout(name="panes"),
    )

    # 4 Metric summary cards at the top
    cards = Table.grid(expand=True, padding=(0, 1))
    for _ in range(4):
        cards.add_column(ratio=1)

    def _chk_metric_card(value: str, title: str, val_style: str, border_style: str) -> Panel:
        txt = Text(str(value), style=f"bold {val_style}", justify="center")
        return Panel(txt, title=title, border_style=border_style, box=rich_box.ROUNDED, padding=(0, 1))

    unselected_count = total_count - checked_count
    cards.add_row(
        _chk_metric_card(total_count, "Total Stacks", TUI_THEME["c_text"], TUI_THEME["inactive_border"]),
        _chk_metric_card(checked_count, "Selected Targets", TUI_THEME["c_success"] if checked_count > 0 else TUI_THEME["c_muted"], TUI_THEME["c_success"] if checked_count > 0 else TUI_THEME["inactive_border"]),
        _chk_metric_card(unselected_count, "Unselected", TUI_THEME["c_accent"] if unselected_count > 0 else TUI_THEME["c_muted"], TUI_THEME["inactive_border"]),
        _chk_metric_card(f"Node {vps_label}" if vps_label and vps_label.upper() != "ALL" else "All Nodes", "Target Scope", TUI_THEME["c_brand"], TUI_THEME["header_border"]),
    )
    main_layout["cards"].update(cards)

    panes_layout = Layout()
    panes_layout.split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=2),
    )

    def get_cat_progress(cat: str) -> tuple[int, int, str, str]:
        total = len(categories[cat])
        done = sum(1 for s in categories[cat] if s.rel_dir in checked_services)
        if done == 0:
            badge = f"[ 0/{total} ]"
            color = TUI_THEME["c_muted"]
        elif done == total:
            badge = f"[ {done}/{total} ]"
            color = TUI_THEME["c_success"]
        else:
            badge = f"[ {done}/{total} ]"
            color = TUI_THEME["c_accent"]
        return done, total, badge, color

    # Left: Categories pane
    cat_table = Table(
        box=rich_box.ROUNDED,
        expand=True,
        show_header=True,
        header_style=f"bold {TUI_THEME['c_brand']}",
        border_style=TUI_THEME["active_border"] if current_menu == "categories" else TUI_THEME["inactive_border"],
        padding=(0, 1),
    )
    cat_table.add_column("Progress", width=12, justify="center")
    cat_table.add_column("Stack Category", ratio=1)

    for idx, cat in enumerate(cat_names):
        _, _, badge, badge_color = get_cat_progress(cat)
        is_selected = (idx == selected_cat_idx)
        pointer = TUI_THEME["pointer"] if is_selected else "  "

        if is_selected and current_menu == "categories":
            name_style = f"bold {TUI_THEME['c_text']}"
        elif is_selected:
            name_style = f"bold {TUI_THEME['c_accent']}"
        else:
            name_style = TUI_THEME["content_unselected"]

        cat_table.add_row(
            Text(badge, style=f"bold {badge_color}"),
            Text(f"{pointer}{cat}", style=name_style),
        )

    left_title = f"[bold]Stacks / Categories ({len(cat_names)})"
    if current_menu == "categories":
        left_title += "  [ACTIVE][/bold]"
    else:
        left_title += "[/bold]"
    panes_layout["left"].update(Panel(
        cat_table,
        title=left_title,
        border_style=TUI_THEME["active_border"] if current_menu == "categories" else TUI_THEME["inactive_border"],
        box=rich_box.ROUNDED,
    ))

    # Right: Services pane
    svc_list = categories.get(active_cat, [])
    svc_table = Table(
        box=rich_box.ROUNDED,
        expand=True,
        show_header=True,
        header_style=f"bold {TUI_THEME['c_brand']}",
        border_style=TUI_THEME["active_border"] if current_menu == "services" else TUI_THEME["inactive_border"],
        padding=(0, 1),
    )
    svc_table.add_column("State", width=8, justify="center", no_wrap=True)
    svc_table.add_column("Service Name", ratio=2)
    svc_table.add_column("Compose Path", ratio=3, style=f"dim {TUI_THEME['c_muted']}")

    for idx, s in enumerate(svc_list):
        is_checked = s.rel_dir in checked_services
        chk_text = Text("[X]", style=f"bold {TUI_THEME['c_success']}") if is_checked else Text("[ ]", style=f"dim {TUI_THEME['c_muted']}")
        is_selected = (idx == selected_svc_idx)
        pointer = TUI_THEME["pointer"] if is_selected else "  "

        if is_selected and current_menu == "services":
            name_style = f"bold {TUI_THEME['c_text']}"
        elif is_selected:
            name_style = f"bold {TUI_THEME['c_accent']}"
        else:
            name_style = TUI_THEME["content_unselected"]

        svc_table.add_row(
            chk_text,
            Text(f"{pointer}{s.name}", style=name_style),
            Text(s.rel_dir),
        )

    right_title = f"[bold]Services in {active_cat} ({len(svc_list)})"
    if current_menu == "services":
        right_title += "  [ACTIVE][/bold]"
    else:
        right_title += "[/bold]"
    panes_layout["right"].update(Panel(
        svc_table,
        title=right_title,
        border_style=TUI_THEME["active_border"] if current_menu == "services" else TUI_THEME["inactive_border"],
        box=rich_box.ROUNDED,
    ))

    main_layout["panes"].update(panes_layout)
    layout["main"].update(main_layout)

    # Footer
    action_hint = "S/D: Stop Selected" if verb == "stop" else f"D: {verb_title} Selected"
    footer_parts = [
        f"[bold {TUI_THEME['c_accent']}]Space[/]: Toggle",
        f"[bold {TUI_THEME['c_accent']}]Tab/←/→[/]: Switch Panel",
        f"[bold {TUI_THEME['c_accent']}]↑/↓[/]: Navigate",
        f"[bold {TUI_THEME['c_brand']}]A[/]: All   [bold {TUI_THEME['c_brand']}]N[/]: None   [bold {TUI_THEME['c_brand']}]I[/]: Invert",
        f"[bold {TUI_THEME['c_success']}]{action_hint}[/]",
        f"[bold {TUI_THEME['c_brand']}]R[/]: Reset",
        f"[bold {TUI_THEME['c_danger']}]Q/Esc[/]: Cancel",
    ]
    if restored_notice:
        footer_parts.insert(0, restored_notice)

    layout["footer"].update(Panel(
        Text.from_markup("   ".join(footer_parts)),
        border_style=TUI_THEME["footer_border"],
        box=rich_box.ROUNDED,
        padding=(0, 1),
    ))
    return layout


def run_tui(
    services: list | None = None,
    vps: str | None = None,
    action_verb: str = "deploy",
) -> list:
    """Double-buffered, flicker-free interactive checklist selector."""
    all_services = services or load_services(vps=vps)
    if vps and vps.upper() != "ALL":
        all_services = [s for s in all_services if s.vps == vps.upper()]

    if not all_services:
        return []

    vps_label = f" [Node {vps}]" if vps else " [All Nodes]"
    verb = action_verb.strip().lower()

    categories = {}
    for s in all_services:
        categories.setdefault(s.category, []).append(s)

    cat_names = sorted(list(categories.keys()))
    all_rel_dirs = {s.rel_dir for s in all_services}
    current_menu = "categories"
    selected_cat_idx = 0
    selected_svc_idx = 0
    active_cat = cat_names[0] if cat_names else ""

    if verb == "deploy":
        last_selection = load_last_deploy_services(all_services, vps=vps)
        if last_selection:
            checked_services = {s.rel_dir for s in last_selection}
            restored_notice = f"[bold #22c55e]Restored {len(checked_services)} services[/bold #22c55e]"
        else:
            checked_services = set(all_rel_dirs)
            restored_notice = None
    else:
        checked_services = set(all_rel_dirs)
        restored_notice = None

    set_mouse_tracking(True)
    try:
        with RawTerminalContext() as term_fd:
            with Live(auto_refresh=False, screen=True) as live:
                while True:
                    layout = render_checklist_layout(
                        all_services=all_services,
                        categories=categories,
                        cat_names=cat_names,
                        checked_services=checked_services,
                        current_menu=current_menu,
                        selected_cat_idx=selected_cat_idx,
                        selected_svc_idx=selected_svc_idx,
                        active_cat=active_cat,
                        vps_label=vps_label,
                        verb=verb,
                        restored_notice=restored_notice,
                    )
                    live.update(layout, refresh=True)

                    key = get_key(term_fd, timeout=0.05)
                    if key is None:
                        continue

                    if key in ("q", "Q", "\x1b") and current_menu == "categories":
                        return []

                    elif key in ("r", "R"):
                        checked_services = set(all_rel_dirs)
                        restored_notice = f"[bold {TUI_THEME['c_accent']}]Reset — all services selected[/]"

                    elif key in ("a", "A"):
                        # Select All
                        checked_services = set(all_rel_dirs)
                        restored_notice = f"[bold {TUI_THEME['c_success']}]All {len(all_rel_dirs)} services selected[/]"

                    elif key in ("n", "N"):
                        # Deselect All
                        checked_services = set()
                        restored_notice = f"[bold {TUI_THEME['c_danger']}]All services deselected[/]"


                    elif key in ("i", "I"):
                        # Invert selection
                        checked_services = all_rel_dirs - checked_services
                        restored_notice = f"[bold {TUI_THEME['c_brand']}]Selection inverted ({len(checked_services)} selected)[/]"

                    elif key in ("d", "D", "s", "S"):
                        final_services = [s for s in all_services if s.rel_dir in checked_services]
                        if not final_services:
                            restored_notice = f"[bold {TUI_THEME['c_danger']}]No services selected for {verb}[/]"
                            continue
                        if verb == "deploy":
                            save_last_deploy_services(final_services, vps=vps)
                        return final_services

                    elif key == "\x1b[A":
                        if current_menu == "categories":
                            if cat_names:
                                selected_cat_idx = (selected_cat_idx - 1) % len(cat_names)
                                active_cat = cat_names[selected_cat_idx]
                                selected_svc_idx = 0
                        else:
                            svc_len = len(categories.get(active_cat, []))
                            if svc_len > 0:
                                selected_svc_idx = (selected_svc_idx - 1) % svc_len

                    elif key == "\x1b[<wheel_up>":
                        if current_menu == "categories":
                            if cat_names:
                                selected_cat_idx = max(0, selected_cat_idx - 1)
                                active_cat = cat_names[selected_cat_idx]
                                selected_svc_idx = 0
                        else:
                            selected_svc_idx = max(0, selected_svc_idx - 1)

                    elif key == "\x1b[B":

                        if current_menu == "categories":
                            if cat_names:
                                selected_cat_idx = (selected_cat_idx + 1) % len(cat_names)
                                active_cat = cat_names[selected_cat_idx]
                                selected_svc_idx = 0
                        else:
                            svc_len = len(categories.get(active_cat, []))
                            if svc_len > 0:
                                selected_svc_idx = (selected_svc_idx + 1) % svc_len

                    elif key == "\x1b[<wheel_down>":
                        if current_menu == "categories":
                            if cat_names:
                                selected_cat_idx = min(len(cat_names) - 1, selected_cat_idx + 1)
                                active_cat = cat_names[selected_cat_idx]
                                selected_svc_idx = 0
                        else:
                            svc_len = len(categories.get(active_cat, []))
                            if svc_len > 0:
                                selected_svc_idx = min(svc_len - 1, selected_svc_idx + 1)

                    elif key in ("\x1b[C", "\t", "\n", "\r"):
                        if current_menu == "categories":
                            current_menu = "services"
                            selected_svc_idx = 0
                        elif key in ("\n", "\r"):
                            # Enter in services pane confirms selection
                            final_services = [s for s in all_services if s.rel_dir in checked_services]
                            if not final_services:
                                restored_notice = f"[bold #ef4444]No services selected for {verb}[/bold #ef4444]"
                                continue
                            if verb == "deploy":
                                save_last_deploy_services(final_services, vps=vps)
                            return final_services

                    elif key in ("\x1b[D", "\x1b", "b", "B"):
                        if current_menu == "services":
                            current_menu = "categories"

                    elif key == " ":
                        if current_menu == "categories":
                            cat = cat_names[selected_cat_idx]
                            cat_svcs = categories.get(cat, [])
                            total = len(cat_svcs)
                            c_count = sum(1 for s in cat_svcs if s.rel_dir in checked_services)
                            if c_count == total:
                                for s in cat_svcs:
                                    checked_services.discard(s.rel_dir)
                            else:
                                for s in cat_svcs:
                                    checked_services.add(s.rel_dir)
                        else:
                            svc_list = categories.get(active_cat, [])
                            if 0 <= selected_svc_idx < len(svc_list):
                                s = svc_list[selected_svc_idx]
                                if s.rel_dir in checked_services:
                                    checked_services.discard(s.rel_dir)
                                else:
                                    checked_services.add(s.rel_dir)
    finally:
        set_mouse_tracking(False)
