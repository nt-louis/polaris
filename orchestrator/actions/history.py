"""Action orchestrator for viewing persistent action audit logs."""

import json
import logging
import sys
from typing import Optional

from orchestrator.actions.base import BaseAction
from orchestrator.core.history import format_action_history_text, load_action_history
from orchestrator.core.models import ActionContext, ExecutionResult

logger = logging.getLogger(__name__)

try:
    from rich.console import Console
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class HistoryAction(BaseAction):
    """View persistent action execution history and audit logs."""

    @property
    def action_name(self) -> str:
        return "history"

    def run(self, context: ActionContext) -> ExecutionResult:
        limit = context.tail if context.tail > 0 else 50
        records = load_action_history(limit=limit)

        if context.json_output:
            rendered = json.dumps(records, indent=2)
            print(rendered)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message=rendered,
            )

        if not records:
            msg = "[INFO] No persistent action history records found in state/action_history.jsonl"
            print(msg)
            return ExecutionResult(
                service=None,
                action=self.action_name,
                success=True,
                exit_code=0,
                message=msg,
            )

        if HAS_RICH:
            console = Console()
            table = Table(
                title="Net-Stream Persistent Operations & Action Audit History",
                header_style="bold #38bdf8",
                border_style="#d97706",
            )
            table.add_column("Timestamp (UTC)", style="dim white")
            table.add_column("VPS", justify="center")
            table.add_column("Action", style="bold white")
            table.add_column("Status")
            table.add_column("Duration", justify="right", style="cyan")
            table.add_column("Command / Details", style="dim white")

            for r in reversed(records):
                ts = r.get("timestamp", "")[:19].replace("T", " ")
                vps_badge = "[bold blue]A[/bold blue]" if r.get("vps") == "A" else "[bold yellow]B[/bold yellow]"
                status_text = r.get("status", "UNKNOWN")
                if status_text == "SUCCESS":
                    status_formatted = "[bold green]✔ SUCCESS[/bold green]"
                else:
                    code = r.get("exit_code", 1)
                    status_formatted = f"[bold red]❌ FAILED (exit {code})[/bold red]"
                duration = f"{r.get('duration_sec', 0.0):.1f}s"
                cmd = r.get("command") or r.get("details") or "-"

                table.add_row(ts, vps_badge, r.get("action", ""), status_formatted, duration, cmd)

            console.print(table)
        else:
            print(format_action_history_text(records))

        return ExecutionResult(
            service=None,
            action=self.action_name,
            success=True,
            exit_code=0,
            message=f"Displayed {len(records)} history records",
        )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for standalone history execution."""
    import sys

    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

    from orchestrator.actions.base import create_action_parser
    from orchestrator.core.history import prune_action_history

    parser = create_action_parser(
        prog="history",
        description="Display and manage persistent operation & action audit history.",
        with_targets=False,
        with_vps=False,
        with_json=True,
    )
    parser.add_argument("--tail", type=int, default=100, help="Number of recent records to display (default: 100)")
    parser.add_argument("--prune", action="store_true", help="Prune expired action history records based on retention window")
    parser.add_argument("--max-age", type=int, default=30, help="Retention period in days (default: 30)")
    parser.add_argument("--max-records", type=int, default=1000, help="Maximum number of records to retain (default: 1000)")

    raw_args = argv if argv is not None else sys.argv[1:]
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    if args.prune:
        pruned = prune_action_history(max_age_days=args.max_age, max_records=args.max_records)
        print(f"[OK] Pruned {pruned} historical action records (retention: {args.max_age} days, max records: {args.max_records}).")
        return 0

    context = ActionContext(
        json_output=args.json,
        tail=args.tail,
    )

    action = HistoryAction()
    result = action.execute(context)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
