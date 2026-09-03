"""Action orchestrator for inspecting real-time container health, status, and ports."""

import json
import logging
import subprocess
import sys
from typing import Optional

from orchestrator.actions.base import BaseAction
from orchestrator.core.models import ActionContext, ExecutionResult
from orchestrator.core.state import get_active_vps
from orchestrator.docker.client import DockerClient, default_client
from orchestrator.docker.readiness import extract_container_names
from orchestrator.registry.manifest import load_services
from orchestrator.registry.resolver import resolve_all_services, resolve_targets

logger = logging.getLogger(__name__)

try:
    from rich.console import Console
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class StatusAction(BaseAction):
    """Inspect and report real-time status, health, and port mappings of stack services."""

    def __init__(self, docker_client: Optional[DockerClient] = None):
        self.client = docker_client or default_client

    @property
    def action_name(self) -> str:
        return "status"

    def get_docker_containers(self) -> list[dict]:
        """Retrieve all Docker containers as a list of dicts via `docker ps -a --format json`."""
        try:
            res = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{json .}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=10,
            )
            containers = []
            for line in res.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    containers.append(json.loads(line))
                except Exception:
                    pass
            return containers
        except Exception as e:
            logger.warning("Could not query docker ps: %s", e)
            return []

    def run(self, context: ActionContext) -> ExecutionResult:
        all_services = load_services()
        target_vps = (context.vps or get_active_vps()).upper()

        if context.targets:
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
            services = matched
        else:
            services = resolve_all_services(all_services, vps=target_vps)

        containers = self.get_docker_containers()
        container_map = {c.get("Names"): c for c in containers}

        status_rows: list[dict] = []
        for s in services:
            compose_path = s.compose_path
            if not compose_path.is_file():
                continue

            matched_container = None
            abs_dir_str = str(s.abs_dir)
            declared_names = set(extract_container_names(s))

            for name, c in container_map.items():
                labels = c.get("Labels", "")
                if (
                    (name and name in declared_names)
                    or f"com.docker.compose.project.working_dir={abs_dir_str}" in labels
                    or f"com.docker.compose.project={s.name}" in labels
                    or (s.custom_project_name and f"com.docker.compose.project={s.custom_project_name}" in labels)
                    or name == s.name
                ):
                    matched_container = c
                    break

            if matched_container:
                c_name = matched_container.get("Names", s.name)
                state = matched_container.get("State", "unknown")
                status_text = matched_container.get("Status", state)
                ports = matched_container.get("Ports", "")
            else:
                c_name = s.name
                state = "exited"
                status_text = "Stopped"
                ports = ""

            status_rows.append({
                "project": s.name,
                "rel_dir": s.rel_dir,
                "vps": s.vps,
                "category": s.category,
                "container": c_name,
                "state": state,
                "status": status_text,
                "ports": ports,
            })

        # Apply state filter
        if context.state and context.state.upper() != "ALL":
            st_filter = context.state.lower()
            filtered_rows = []
            for r in status_rows:
                st_text = r["status"].lower()
                st_state = r["state"].lower()
                if st_filter == "healthy" and "healthy" in st_text:
                    filtered_rows.append(r)
                elif st_filter == "running" and ("up" in st_text or st_state == "running"):
                    filtered_rows.append(r)
                elif st_filter in ("stopped", "exited") and ("stopped" in st_text or "exited" in st_state):
                    filtered_rows.append(r)
            status_rows = filtered_rows

        # Apply category filter
        if context.category:
            cat_filter = context.category.lower()
            status_rows = [r for r in status_rows if cat_filter in r["category"].lower()]

        # Apply query/search filter
        if context.query:
            q = context.query.lower()
            status_rows = [
                r for r in status_rows
                if q in r["project"].lower()
                or q in r["rel_dir"].lower()
                or q in r["container"].lower()
                or q in r["ports"].lower()
                or q in r["category"].lower()
            ]

        if context.json_output:
            rendered = json.dumps(status_rows, indent=2)
            print(rendered)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message=rendered,
            )

        if HAS_RICH:
            console = Console()
            vps_title = f" [VPS {target_vps.upper()}]" if target_vps else ""
            table = Table(
                title=f"Net-Stream Service Health & Status Inspector{vps_title}",
                header_style="bold #38bdf8",
                border_style="#d97706",
            )
            table.add_column("Project", style="bold white")
            table.add_column("VPS", justify="center")
            table.add_column("Category", style="cyan")
            table.add_column("Container", style="yellow")
            table.add_column("Health / Status")
            table.add_column("Ports", style="dim white")

            for r in status_rows:
                vps_badge = "[bold blue]A[/bold blue]" if r["vps"] == "A" else "[bold yellow]B[/bold yellow]"
                status_str = r["status"]
                if "healthy" in status_str:
                    status_formatted = f"[bold green]✔ {status_str}[/bold green]"
                elif "Up" in status_str:
                    status_formatted = f"[green]● {status_str}[/green]"
                elif "Stopped" in status_str or "exited" in r["state"]:
                    status_formatted = f"[dim red]○ {status_str}[/dim red]"
                else:
                    status_formatted = f"[yellow]▲ {status_str}[/yellow]"

                table.add_row(
                    r["project"],
                    vps_badge,
                    r["category"],
                    r["container"],
                    status_formatted,
                    r["ports"] or "-",
                )

            console.print(table)
        else:
            vps_title = f" [VPS {target_vps.upper()}]" if target_vps else ""
            print("=" * 80)
            print(f"Net-Stream Service Health & Status Inspector{vps_title}")
            print("=" * 80)
            for r in status_rows:
                print(f"[{r['vps']}] {r['project']:<20} | {r['status']:<25} | {r['ports']}")

        return ExecutionResult(
            service=None,
            action=self.action_name,
            success=True,
            exit_code=0,
            message=f"Reported status for {len(status_rows)} services",
        )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for standalone status execution."""
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

    from orchestrator.actions.base import create_action_parser, parse_action_targets

    parser = create_action_parser(
        prog="status",
        description="Inspect real-time container health, status, and ports.",
        with_targets=True,
        with_vps=True,
        with_json=True,
        allow_all_nodes=True,
    )
    parser.add_argument(
        "--state",
        choices=["all", "healthy", "running", "stopped"],
        type=lambda s: s.strip().lower(),
        default=None,
        help="Filter services by container state (all/healthy/running/stopped)",
    )
    parser.add_argument(
        "--category",
        "-c",
        type=str,
        default=None,
        help="Filter services by category name",
    )
    parser.add_argument(
        "--search",
        "-q",
        dest="query",
        type=str,
        default=None,
        help="Search query to filter services by project, container, category, or port",
    )

    raw_args = argv if argv is not None else sys.argv[1:]
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    context = ActionContext(
        targets=parse_action_targets(args),
        vps=args.vps,
        json_output=args.json,
        state=getattr(args, "state", None),
        category=getattr(args, "category", None),
        query=getattr(args, "query", None),
    )

    action = StatusAction()
    result = action.execute(context)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
