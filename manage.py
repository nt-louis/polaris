#!/usr/bin/python3
"""Polaris Unified Stack Manager CLI router.

Delegates commands directly to domain-specific action modules in orchestrator.actions.
"""

import logging
import os
import subprocess
import sys

# Ensure ANSI escape codes and UTF-8 work on Windows Terminal if run locally
if sys.platform == "win32":
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def print_help():
    print("""Polaris Unified Stack Manager

Usage:
  ./manage.py <command> [subcommand/options]

Core Operations:
  deploy           Deploy or resume compose stacks (TUI by default)
                   Options: [service/app ...], --services DIR/APP..., --vps <ID>, --pull, --last, --force-gateways, --dry-run
  redeploy         Refresh active containers to apply config changes
                   Options: [service/app ...], --services DIR/APP..., --pull, --build, --recreate, --dry-run
  stop             Gracefully stop running containers (all, by VPS, or by service name/path)
                   Options: [service/app ...], --services DIR/APP..., --vps A|B, --dry-run, --yes
  backup           Manage stack backups and snapshots (Restic)
                   Subcommands: run, restore, snapshots, check, prune, stats

Status & Diagnostics:
  status           Inspect real-time container health, status, and ports
                   Options: --vps A|B, --json
  logs             Tail/stream container logs for a service or gateway
                   Options: <service>, -f / --follow, --tail=N
  doctor           Run pre-flight infrastructure diagnostics (Doppler, Tailscale, VPN, Disk)
  validate         Validate Docker Compose and Caddyfile syntax across repository
                   Options: --vps A|B, --fix
  history          Display persistent operation & action audit history
                   Options: --json, --tail=N

Maintenance & Utilities:
  update           Check and apply container image updates
                   Options: --check, --list-backups, --min-age N, --backup-days N, --yes, --dry-run
  secrets          Manage Doppler SaaS secrets & SOPS fallback snapshots
                   Subcommands: verify, open, sync [--dry-run], audit, prune, snapshot, snapshot-config, snapshots, sync-branch
  network          Manage network gateways and Tailscale interface
                   Subcommands: fix, reset [--yes]
  utils            Execute repository setup and custom updates
                   Subcommands: env, fmhy, monochrome, build, netbird-server, dependency-report
  hooks            Install or verify git hooks (pre-commit secret guard)
                   Subcommands: install, verify
  cli              Install, verify, or uninstall system-wide polaris CLI wrapper
                   Subcommands: install, verify, status, uninstall

  Global flag: --yes / -y   auto-confirm destructive prompts (e.g. for scripts/CI)

Examples:
  ./manage.py deploy --vps A --last
  ./manage.py deploy bazarr sonarr
  ./manage.py stop jellyfin
  ./manage.py stop --vps B
  ./manage.py status --vps A
  ./manage.py logs jellyfin -f
  ./manage.py backup snapshots
  ./manage.py doctor
""")


def main():
    """Main routing function for the Polaris stack manager."""
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

    if len(sys.argv) < 2:
        if sys.stdin.isatty():
            from orchestrator.ui.dashboard import run_dashboard
            run_dashboard()
            sys.exit(0)
        else:
            print_help()
            sys.exit(1)

    cmd = sys.argv[1]
    args = list(sys.argv[2:])

    if cmd in ("--help", "-h", "help"):
        print_help()
        sys.exit(0)

    # Deprecated command aliases
    deprecated_mappings = {
        "deploy-last": ("deploy", ["--last"]),
        "deploy-vps-a": ("deploy", ["--vps", "A"]),
        "deploy-vps-b": ("deploy", ["--vps", "B"]),
        "deploy-last-a": ("deploy", ["--last", "--vps", "A"]),
        "deploy-last-b": ("deploy", ["--last", "--vps", "B"]),
        "check-upgrades": ("update", ["--check"]),
        "list-backups": ("update", ["--list-backups"]),
        "verify-secrets": ("secrets", ["verify"]),
        "open-secrets": ("secrets", ["open"]),
        "restore": ("backup", ["restore"]),
        "snapshots": ("backup", ["snapshots"]),
        "backup-check": ("backup", ["check"]),
        "fix-routing": ("network", ["fix"]),
        "reset-tailscale": ("network", ["reset"]),
        "bootstrap-env": ("utils", ["env"]),
        "update-fmhy": ("utils", ["fmhy"]),
        "update-monochrome": ("utils", ["monochrome"]),
        "update-netbird-server": ("utils", ["netbird-server"]),
    }

    if cmd in deprecated_mappings:
        new_cmd, extra_args = deprecated_mappings[cmd]
        mapped_args = extra_args + args
        print(f"[DEPRECATED] Command '{cmd}' is deprecated. Please use './manage.py {new_cmd} {' '.join(mapped_args)}' instead.\n")
        cmd = new_cmd
        args = mapped_args

    # Forward global --yes/-y flag across all delegated subcommands
    auto_yes = "--yes" in args or "-y" in args
    if auto_yes and not any(a in ("--yes", "-y") for a in args):
        args.append("--yes")

    # Command Dispatch Table
    if cmd == "deploy":
        from orchestrator.actions.deploy import main as deploy_main
        sys.exit(deploy_main(args))

    elif cmd == "redeploy":
        from orchestrator.actions.redeploy import main as redeploy_main
        sys.exit(redeploy_main(args))

    elif cmd == "stop":
        from orchestrator.actions.stop import main as stop_main
        sys.exit(stop_main(args))

    elif cmd == "status":
        from orchestrator.actions.status import main as status_main
        sys.exit(status_main(args))

    elif cmd == "logs":
        from orchestrator.actions.logs import main as logs_main
        sys.exit(logs_main(args))

    elif cmd == "doctor":
        from orchestrator.actions.doctor import main as doctor_main
        sys.exit(doctor_main(args))

    elif cmd in ("validate", "check-config"):
        from orchestrator.actions.validate import main as validate_main
        sys.exit(validate_main(args))

    elif cmd in ("history", "audit"):
        from orchestrator.actions.history import main as history_main
        sys.exit(history_main(args))

    elif cmd == "update":
        from orchestrator.actions.update import main as update_main
        sys.exit(update_main(args))

    elif cmd == "secrets":
        from orchestrator.actions.secrets import main as secrets_main
        sys.exit(secrets_main(args))

    elif cmd == "backup":
        from orchestrator.actions.backup import main as backup_main
        sys.exit(backup_main(args))

    elif cmd == "network":
        subcmd = args[0] if args else None
        remaining_args = args[1:]

        if subcmd in ("fix", "fix-routing"):
            from orchestrator.network.routing import apply_routing_fix
            res = apply_routing_fix(script_args=remaining_args, yes=auto_yes)
            if not res.success:
                print(f"[ERROR] {res.message}", file=sys.stderr)
            elif res.message:
                print(res.message)
            sys.exit(res.exit_code)
        elif subcmd in ("reset", "reset-tailscale"):
            from orchestrator.network.routing import reset_tailscale_state
            allow_dev = ("--allow-dev" in remaining_args) or ("--allow-dev" in sys.argv)
            res = reset_tailscale_state(yes=auto_yes, allow_dev=allow_dev)
            if not res.success:
                print(f"[ERROR] {res.message}", file=sys.stderr)
            elif res.message:
                print(res.message)
            sys.exit(res.exit_code)
        else:
            print(f"ERROR: Unknown network subcommand '{subcmd}'. Expected: fix, reset", file=sys.stderr)
            sys.exit(1)

    elif cmd == "hooks":
        subcmd = args[0] if args else None
        if subcmd == "install":
            install_script = os.path.join(REPO_ROOT, "orchestrator", "scripts", "hooks", "install-hooks.sh")
            sys.exit(subprocess.call(["bash", install_script]))
        elif subcmd == "verify":
            hook = os.path.join(REPO_ROOT, ".git", "hooks", "pre-commit")
            src = os.path.join(REPO_ROOT, "orchestrator", "scripts", "hooks", "pre-commit")
            if os.path.islink(hook) and os.path.realpath(hook) == os.path.realpath(src):
                print(f"[hooks] pre-commit installed (symlink -> {src})")
                sys.exit(0)
            if os.path.isfile(hook) and os.path.isfile(src):
                with open(hook, "rb") as a, open(src, "rb") as b:
                    if a.read() == b.read():
                        print("[hooks] pre-commit installed (file copy, matches tracked script)")
                        sys.exit(0)
            print("[hooks] pre-commit NOT installed. Run: ./manage.py hooks install")
            sys.exit(1)
        else:
            print(f"ERROR: Unknown hooks subcommand '{subcmd}'. Expected: install, verify", file=sys.stderr)
            sys.exit(1)

    elif cmd == "cli":
        subcmd = args[0] if args else None
        prefix = args[1] if len(args) > 1 else os.path.expanduser("~/.local/bin")
        target = os.path.join(prefix, "polaris")
        wrapper_src = os.path.join(REPO_ROOT, "orchestrator", "scripts", "cli", "polaris")

        if subcmd == "install":
            install_script = os.path.join(REPO_ROOT, "install-cli.sh")
            sys.exit(subprocess.call(["bash", install_script, prefix]))
        elif subcmd in ("verify", "status"):
            if os.path.islink(target) and os.path.realpath(target) == os.path.realpath(wrapper_src):
                print(f"[cli] polaris installed (symlink -> {wrapper_src}) at {target}")
                sys.exit(0)
            if os.path.isfile(target):
                print(f"[cli] polaris installed at {target}")
                sys.exit(0)
            print(f"[cli] polaris CLI wrapper NOT installed at {target}. Run: ./install-cli.sh or ./manage.py cli install")
            sys.exit(1)
        elif subcmd == "uninstall":
            if os.path.exists(target) or os.path.islink(target):
                os.remove(target)
                print(f"[cli] Removed {target}")
                sys.exit(0)
            else:
                print(f"[cli] polaris CLI wrapper not found at {target}")
                sys.exit(0)
        else:
            print(f"ERROR: Unknown cli subcommand '{subcmd}'. Expected: install, verify, status, uninstall", file=sys.stderr)
            sys.exit(1)

    elif cmd == "utils":
        subcmd = args[0] if args else None
        remaining_args = args[1:]

        if subcmd in ("env", "bootstrap-env"):
            print("[INFO] Static .env bootstrapping is archived. Runtime environment secrets are managed via Doppler SaaS ('manage.py secrets').")
            sys.exit(0)
        elif subcmd in ("fmhy", "update-fmhy"):
            build_script = os.path.join(REPO_ROOT, "orchestrator", "scripts", "utils", "build-local-app.sh")
            sys.exit(subprocess.call(["bash", build_script, "fmhy"] + remaining_args))
        elif subcmd in ("monochrome", "update-monochrome"):
            build_script = os.path.join(REPO_ROOT, "orchestrator", "scripts", "utils", "build-local-app.sh")
            sys.exit(subprocess.call(["bash", build_script, "monochrome"] + remaining_args))
        elif subcmd == "build":
            build_script = os.path.join(REPO_ROOT, "orchestrator", "scripts", "utils", "build-local-app.sh")
            sys.exit(subprocess.call(["bash", build_script] + remaining_args))
        elif subcmd in ("netbird-server", "update-netbird-server"):
            update_script = os.path.join(REPO_ROOT, "orchestrator", "scripts", "utils", "update-netbird-server.sh")
            sys.exit(subprocess.call(["bash", update_script] + remaining_args))
        elif subcmd in ("dependency-report", "report"):
            from orchestrator.actions.dependency_report import main as dep_main
            sys.exit(dep_main(remaining_args))
        elif subcmd in ("log-mode", "stream-mode"):
            from orchestrator.core.state import (
                get_active_vps,
                get_log_stream_mode,
                set_log_stream_mode,
            )
            vps = None
            mode_val = None
            for i, a in enumerate(remaining_args):
                if a in ("--vps", "-vps") and len(remaining_args) > i + 1:
                    vps = remaining_args[i + 1].upper()
                elif a.lower() in ("native", "piped"):
                    mode_val = a.lower()
            target_vps = vps or get_active_vps()
            if mode_val:
                set_log_stream_mode(mode_val, vps=target_vps)
                print(f"[INFO] Log stream mode for Node {target_vps} set to: '{mode_val}'")
                sys.exit(0)
            else:
                cur = get_log_stream_mode(vps=target_vps)
                print(f"[INFO] Current log stream mode for Node {target_vps}: '{cur}' (options: native, piped)")
                sys.exit(0)
        else:
            print(f"ERROR: Unknown utils subcommand '{subcmd}'. Expected: env, fmhy, monochrome, build, netbird-server, dependency-report, log-mode", file=sys.stderr)
            sys.exit(1)

    elif cmd in ("stream-mode", "log-mode"):
        from orchestrator.core.state import (
            get_active_vps,
            get_log_stream_mode,
            set_log_stream_mode,
        )
        vps = None
        mode_val = None
        for i, a in enumerate(args):
            if a in ("--vps", "-vps") and len(args) > i + 1:
                vps = args[i + 1].upper()
            elif a.lower() in ("native", "piped"):
                mode_val = a.lower()
        target_vps = vps or get_active_vps()
        if mode_val:
            set_log_stream_mode(mode_val, vps=target_vps)
            print(f"[INFO] Log stream mode for Node {target_vps} set to: '{mode_val}'")
            sys.exit(0)
        else:
            cur = get_log_stream_mode(vps=target_vps)
            print(f"[INFO] Current log stream mode for Node {target_vps}: '{cur}' (options: native, piped)")
            sys.exit(0)

    else:
        print(f"ERROR: Unknown command '{cmd}'. Run './manage.py --help' for usage.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
