"""Compose project and network configuration validator."""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

import yaml

from orchestrator.actions.base import BaseAction
from orchestrator.core.constants import REPO_ROOT
from orchestrator.core.models import ActionContext, ExecutionResult, ServiceMetadata
from orchestrator.registry.discovery import detect_manifest_drift, load_services
from orchestrator.registry.manifest import (
    DEFAULT_MANIFEST_PATH,
    get_default_node_id,
    load_manifest_raw,
)
from orchestrator.secrets.doppler import default_doppler_client
from orchestrator.secrets.transient import materialize_transient_env

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

logger = logging.getLogger(__name__)


def validate_caddyfile(repo_path: Optional[Path] = None) -> tuple[bool, str]:
    """Validate Caddyfile syntax if caddy CLI is available on host."""
    root = repo_path or REPO_ROOT
    caddy_path = root / "Network" / "Caddyfile"
    if not caddy_path.is_file():
        return True, "No root Caddyfile found (Skipped)"

    try:
        res = subprocess.run(
            ["caddy", "validate", "--config", str(caddy_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if res.returncode == 0:
            return True, "Caddyfile syntax valid"
        return False, f"Caddyfile error: {res.stderr.strip()}"
    except FileNotFoundError:
        return True, "Caddy CLI not installed (Skipped Caddyfile check)"
    except Exception as e:
        return False, f"Caddy validation failed: {e}"


def sync_manifest_with_disk(manifest_path: Optional[Path] = None, repo_root: Optional[Path] = None) -> tuple[int, int]:
    """Append newly discovered compose files to services.yaml as template entries for review.

    Preserves existing entries (append-only) and derives default node declaratively.
    """
    root = repo_root or REPO_ROOT
    m_path = manifest_path or DEFAULT_MANIFEST_PATH

    data = load_manifest_raw(m_path)
    services_list = list(data.get("services", []))
    default_node = get_default_node_id(m_path) or "A"

    missing_on_disk, extra_in_manifest = detect_manifest_drift(m_path, root)

    if not missing_on_disk:
        return 0, len(extra_in_manifest)

    # Append template entries for untracked on-disk compose projects (append-only)
    for rel_path in sorted(missing_on_disk):
        svc_name = Path(rel_path).name
        parts = Path(rel_path).parts
        category = "/".join(parts[:-1]) if len(parts) > 1 else "Other"
        services_list.append({
            "name": svc_name,
            "path": rel_path,
            "category": category,
            "tier": 2,
            "vps": default_node,
        })

    data["services"] = sorted(services_list, key=lambda s: (s.get("category", ""), s.get("name", "")))
    with open(m_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False)

    return len(missing_on_disk), len(extra_in_manifest)


class ValidateAction(BaseAction):
    """Orchestrates validation across Compose files, Caddy routing, and declarative manifest drift."""

    action_name = "validate"

    def validate_service_compose(self, svc: ServiceMetadata) -> tuple[bool, str]:
        """Validate a single service's compose file syntax and variable interpolation."""
        compose_path = svc.compose_path
        if not compose_path.is_file():
            return False, f"Compose file missing: {compose_path}"

        base_cmd = ["docker", "compose", "-f", str(compose_path), "config", "--quiet"]

        # Wrap with Doppler SaaS if available
        try:
            cmd = default_doppler_client.wrap_command(
                cmd=base_cmd,
                service=svc,
            )
        except Exception:
            cmd = base_cmd

        # Materialize transient .env if service declares env_file
        try:
            with materialize_transient_env(svc):
                res = subprocess.run(
                    cmd,
                    cwd=str(svc.abs_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if res.returncode == 0:
                    return True, "Valid compose syntax"
                err_msg = res.stderr.strip() or "Syntax / interpolation error"
                return False, err_msg

        except Exception as e:
            return False, f"Validation error: {e}"

    def run(self, context: ActionContext) -> ExecutionResult:
        """Run validation checks across compose services, Caddyfile, and manifest drift."""
        # 1. Manifest drift detection & repair
        missing_on_disk, extra_in_manifest = detect_manifest_drift()
        drift_fixed = False
        drift_msg = "Manifest in sync with disk."

        if missing_on_disk or extra_in_manifest:
            if context.fix:
                added, orphaned = sync_manifest_with_disk()
                drift_fixed = True
                drift_msg = f"Manifest auto-synced (+{added} template entries appended for review)."
                logger.info("[SUCCESS] %s", drift_msg)
            else:
                drift_msg = f"Manifest drift detected: {len(missing_on_disk)} untracked, {len(extra_in_manifest)} orphaned. Run './manage.py validate --fix' to sync."

        # 2. Compose validation
        services = load_services(vps=context.vps)
        total_services = len(services)
        passed_count = 0
        failed_items = []

        logger.info("[INFO] Validating %d Docker Compose project configuration(s)...", total_services)

        for svc in services:
            passed, msg = self.validate_service_compose(svc)
            if passed:
                passed_count += 1
            else:
                failed_items.append((svc.name, svc.rel_dir, msg))

        # 3. Caddyfile validation
        caddy_ok, caddy_msg = validate_caddyfile(REPO_ROOT)
        manifest_ok = (not missing_on_disk and not extra_in_manifest) or drift_fixed
        all_passed = (passed_count == total_services) and caddy_ok and manifest_ok

        if HAS_RICH and not context.json_output:
            console = Console()
            summary_text = (
                f"Compose Stacks Validated: {passed_count} / {total_services}\n"
                f"Caddyfile Syntax Check: {caddy_msg}\n"
                f"Manifest Registry Check: {drift_msg}\n"
            )
            if all_passed:
                summary_text += "\n✔ All Docker Compose files and manifest declarations passed validation!"
                panel = Panel(summary_text, title="Validation Summary: PASS", border_style="green")
            else:
                summary_text += f"\n✖ {len(failed_items)} project(s) failed validation."
                panel = Panel(summary_text, title="Validation Summary: FAIL", border_style="red")

            console.print(panel)

            if failed_items:
                table = Table(show_header=True, header_style="bold red")
                table.add_column("Service", style="cyan", width=20)
                table.add_column("Directory", style="dim", width=35)
                table.add_column("Validation Error", style="bold red")

                for name, path_str, err in failed_items:
                    table.add_row(name, path_str, err)

                console.print(table)
        else:
            print("\n=======================================================")
            print("    Validation Summary")
            print("=======================================================")
            print(f" Compose Stacks Validated: {passed_count} / {total_services}")
            print(f" Caddyfile Syntax Check  : {caddy_msg}")
            print(f" Manifest Registry Check : {drift_msg}")
            if failed_items:
                print("\n Failed Stacks:")
                for name, path_str, err in failed_items:
                    print(f"   ✖ {name} ({path_str}): {err}")
            print("=======================================================\n")

        summary = f"Validated {passed_count}/{total_services} services. Caddy: {caddy_msg}. Manifest: {drift_msg}"
        return ExecutionResult(
            service=None,
            action=self.action_name,
            success=all_passed,
            exit_code=0 if all_passed else 1,
            message=summary,
        )


def main(argv=None) -> int:
    """CLI entrypoint for validate action."""
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

    from orchestrator.actions.base import create_action_parser

    parser = create_action_parser(
        prog="validate",
        description="Validate Docker Compose configurations and Caddyfile routing.",
        with_targets=False,
        with_vps=True,
        with_json=True,
    )
    parser.add_argument("--fix", action="store_true", help="Auto-sync manifest drift (append untracked compose files as templates)")

    raw_args = list(argv if argv is not None else sys.argv[1:])
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    action = ValidateAction()
    ctx = ActionContext(vps=args.vps, fix=args.fix, json_output=args.json)
    res = action.execute(ctx)
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
