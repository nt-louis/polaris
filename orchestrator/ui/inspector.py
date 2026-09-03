"""Live container health, status, and history inspector rendering for TUI."""

import logging
import threading
import time

from orchestrator.core.history import load_action_history
from orchestrator.docker.client import DockerClient
from orchestrator.registry.discovery import load_services

logger = logging.getLogger(__name__)

try:
    from rich import box as rich_box
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# Cyber-Slate inspector colour tokens
_C_BRAND = "#38bdf8"       # Electric Cyan — titles, headers, focus indicators
_C_ACCENT = "#f59e0b"      # Vivid Amber — warnings, dev badges, selection marks
_C_SUCCESS = "#22c55e"     # Emerald Green — healthy status, success badges
_C_WARN = "#eab308"        # Gold — running/partial state, follow-mode paused
_C_DANGER = "#f43f5e"      # Rose Red — stopped, failed, destructive badges
_C_MUTED = "#94a3b8"       # Cool Slate — descriptions, paths, hints
_C_BORDER_ACTIVE = "#0284c7"    # Focused border
_C_BORDER_INACTIVE = "#334155"  # Unfocused / secondary border
_C_TEXT = "#f8fafc"        # Crisp White — primary labels

_CACHE_LOCK = threading.Lock()
_CONTAINER_CACHE = {
    "timestamp": 0.0,
    "last_updated_str": time.strftime("%H:%M:%S"),
    "containers": [],
    "fetching": False,
    "initialized": False,
}
_PROJECTS_CACHE = {
    "timestamp": 0.0,
    "projects": [],
    "initialized": False,
}


def refresh_containers_bg(force: bool = False) -> None:
    """Trigger background refresh of running Docker containers."""
    with _CACHE_LOCK:
        if _CONTAINER_CACHE["fetching"] and not force:
            return
        _CONTAINER_CACHE["fetching"] = True

    def _worker():
        try:
            client = DockerClient()
            containers = client.get_all_containers_info()
            now = time.monotonic()
            now_str = time.strftime("%H:%M:%S")
            with _CACHE_LOCK:
                _CONTAINER_CACHE["containers"] = containers
                _CONTAINER_CACHE["timestamp"] = now
                _CONTAINER_CACHE["last_updated_str"] = now_str
                _CONTAINER_CACHE["initialized"] = True
        except Exception as e:
            logger.debug("Background container refresh failed: %s", e)
            with _CACHE_LOCK:
                _CONTAINER_CACHE["timestamp"] = time.monotonic()
                _CONTAINER_CACHE["initialized"] = True
        finally:
            with _CACHE_LOCK:
                _CONTAINER_CACHE["fetching"] = False

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def get_cached_containers(ttl: float = 10.0, force: bool = False) -> list[dict]:
    """Retrieve running containers with non-blocking background TTL cache."""
    now = time.monotonic()
    with _CACHE_LOCK:
        is_init = _CONTAINER_CACHE.get("initialized", False)
        is_fetching = _CONTAINER_CACHE.get("fetching", False)
        ts = _CONTAINER_CACHE.get("timestamp", 0.0)

    if not is_init:
        # First load: fetch synchronously so initial UI frame has data
        try:
            client = DockerClient()
            containers = client.get_all_containers_info()
            now_str = time.strftime("%H:%M:%S")
            with _CACHE_LOCK:
                _CONTAINER_CACHE["containers"] = containers
                _CONTAINER_CACHE["timestamp"] = now
                _CONTAINER_CACHE["last_updated_str"] = now_str
                _CONTAINER_CACHE["initialized"] = True
                _CONTAINER_CACHE["fetching"] = False
        except Exception:
            with _CACHE_LOCK:
                _CONTAINER_CACHE["containers"] = []
                _CONTAINER_CACHE["timestamp"] = now
                _CONTAINER_CACHE["initialized"] = True
                _CONTAINER_CACHE["fetching"] = False
    elif force:
        if not is_fetching:
            refresh_containers_bg(force=True)
    elif now - ts > ttl:
        if not is_fetching:
            refresh_containers_bg()

    with _CACHE_LOCK:
        return list(_CONTAINER_CACHE.get("containers", []))


def get_cached_services(vps: str | None = None, ttl: float = 60.0, force: bool = False):
    """Retrieve declared services from services.yaml manifest with TTL cache."""
    now = time.monotonic()
    with _CACHE_LOCK:
        is_init = _PROJECTS_CACHE.get("initialized", False)
        ts = _PROJECTS_CACHE.get("timestamp", 0.0)

    if force or not is_init or (now - ts > ttl):
        loaded = load_services()
        with _CACHE_LOCK:
            _PROJECTS_CACHE["projects"] = loaded
            _PROJECTS_CACHE["timestamp"] = now
            _PROJECTS_CACHE["initialized"] = True

    with _CACHE_LOCK:
        all_svcs = list(_PROJECTS_CACHE.get("projects", []))

    if vps and vps.upper() != "ALL":
        return [s for s in all_svcs if s.vps == vps.upper()]
    return all_svcs


def _classify_services(services, container_map):
    """Match declared services against live containers and classify their state."""
    records = []
    for svc in services:
        proj_name = svc.custom_project_name or svc.name
        matched = None
        for name, c in container_map.items():
            labels = c.get("Labels", "")
            if (
                f"com.docker.compose.project.working_dir={svc.abs_dir}" in labels
                or f"com.docker.compose.project={proj_name}" in labels
                or name == proj_name
                or name.startswith(f"{proj_name}-")
                or name.endswith(f"-{proj_name}")
                or name == svc.name
                or name.startswith(f"{svc.name}-")
            ):
                matched = c
                break

        if matched:
            raw = matched.get("Status", "").lower()
            state = matched.get("State", "").lower()
            ports = matched.get("Ports", "") or "-"
            c_name = matched.get("Names", "-")
            if "healthy" in raw:
                records.append((svc, "HEALTHY", _C_SUCCESS, c_name, ports))
            elif "up" in raw or state == "running":
                records.append((svc, "RUNNING", _C_WARN, c_name, ports))
            else:
                records.append((svc, "STOPPED", _C_DANGER, c_name, ports))
        else:
            records.append((svc, "STOPPED", _C_DANGER, "-", "-"))
    return records


def render_status_view(
    vps_label: str | None = None,
    show_table: bool = False,
    offset: int = 0,
    query: str = "",
    state_filter: str = "ALL",
    is_searching: bool = False,
) -> "Table":
    """Render infrastructure health status with real-time search and filter controls.

    In overview mode: shows metric summary cards, filter status, and stopped-stack list.
    In table mode (show_table=True): renders a scrollable full-service table with highlighted matches.
    """
    services = get_cached_services(vps=vps_label, ttl=10.0)
    containers = get_cached_containers(ttl=10.0)
    container_map = {c.get("Names"): c for c in containers}

    all_records = _classify_services(services, container_map)

    # 1. Total counts across current node selection before filtering
    total_count = len(all_records)
    healthy_count = sum(1 for _, st, _, _, _ in all_records if st == "HEALTHY")
    running_count = sum(1 for _, st, _, _, _ in all_records if st == "RUNNING")
    stopped_count = sum(1 for _, st, _, _, _ in all_records if st == "STOPPED")
    stopped_names = [svc.name for svc, st, _, _, _ in all_records if st == "STOPPED"]

    # 2. Apply state filter
    records = all_records
    if state_filter and state_filter.upper() != "ALL":
        records = [r for r in records if r[1] == state_filter.upper()]

    # 3. Apply search query
    if query:
        q = query.strip().lower()
        records = [
            r for r in records
            if q in r[0].name.lower()
            or q in r[0].rel_dir.lower()
            or q in r[0].category.lower()
            or q in r[3].lower()
            or q in r[4].lower()
        ]

    filtered_count = len(records)
    last_updated = _CONTAINER_CACHE.get("last_updated_str", time.strftime("%H:%M:%S"))
    if _CONTAINER_CACHE.get("fetching"):
        last_updated += "  (refreshing...)"

    node_label = f"Node {vps_label}" if vps_label and vps_label.upper() != "ALL" else "All Nodes"

    outer = Table.grid(expand=True, padding=(0, 0))
    outer.add_column()

    # ------------------------------------------------------------------
    # Metric summary cards (always shown at top)
    # ------------------------------------------------------------------
    cards = Table.grid(expand=True, padding=(0, 1))
    for _ in range(4):
        cards.add_column(ratio=1)

    def _metric_card(value: str, title: str, val_style: str, border_style: str) -> "Panel":
        txt = Text(str(value), style=f"bold {val_style}", justify="center")
        return Panel(txt, title=title, border_style=border_style, padding=(0, 1))

    cards.add_row(
        _metric_card(total_count, "Total Stacks", _C_TEXT, _C_BORDER_INACTIVE),
        _metric_card(healthy_count, "Healthy", _C_SUCCESS, _C_SUCCESS),
        _metric_card(running_count, "Running", _C_WARN, _C_WARN),
        _metric_card(stopped_count, "Stopped", _C_DANGER if stopped_count > 0 else _C_MUTED,
                     _C_DANGER if stopped_count > 0 else _C_BORDER_INACTIVE),
    )
    outer.add_row(cards)

    # ------------------------------------------------------------------
    # Interactive Search & Filter Status Bar
    # ------------------------------------------------------------------
    filter_box = Table.grid(expand=True, padding=(0, 1))
    filter_box.add_column()

    f_text = Text()
    f_text.append("  Search [/]: ", style=f"bold {_C_BRAND}")
    if is_searching:
        f_text.append(f" {query}\u2588 ", style="bold white on #0284c7")
        f_text.append(" (Type query... Press Enter to lock, Esc to clear)", style=f"italic {_C_MUTED}")
    elif query:
        f_text.append(f"\"{query}\"", style=f"bold {_C_ACCENT}")
        f_text.append(" (Press / to edit, C to clear)", style=f"dim {_C_MUTED}")
    else:
        f_text.append("All (Press / to search)", style=f"dim {_C_MUTED}")

    f_text.append("  │  State [F]: ", style=f"bold {_C_BRAND}")
    st_style = _C_SUCCESS if state_filter == "HEALTHY" else (_C_WARN if state_filter == "RUNNING" else (_C_DANGER if state_filter == "STOPPED" else _C_TEXT))
    f_text.append(f"{state_filter}", style=f"bold {st_style}")

    f_text.append("  │  Node [N]: ", style=f"bold {_C_BRAND}")
    f_text.append(f"{node_label}", style=f"bold {_C_BRAND}")

    has_active_filter = bool(query or state_filter != "ALL")
    filter_border = _C_BORDER_ACTIVE if (is_searching or has_active_filter) else _C_BORDER_INACTIVE
    filter_box.add_row(Panel(f_text, border_style=filter_border, padding=(0, 1)))
    outer.add_row(filter_box)

    if show_table or query or state_filter != "ALL":
        # ------------------------------------------------------------------
        # Full scrollable services table
        # ------------------------------------------------------------------
        PAGE = 10
        max_offset = max(0, len(records) - PAGE)
        clamped = max(0, min(offset, max_offset))
        visible = records[clamped:clamped + PAGE]

        tbl = Table(
            box=rich_box.ROUNDED,
            expand=True,
            show_header=True,
            header_style=f"bold {_C_BRAND}",
            border_style=_C_BORDER_INACTIVE,
            padding=(0, 1),
        )
        tbl.add_column("Status", width=11, justify="center")
        tbl.add_column("Service", style=f"bold {_C_TEXT}", width=18)
        tbl.add_column("Category", style=f"dim {_C_MUTED}", width=16)
        tbl.add_column("Node", width=6, justify="center")
        tbl.add_column("Container", style=f"dim {_C_MUTED}", width=22)
        tbl.add_column("Ports / Network", style=_C_BRAND)

        for svc, st, color, c_name, ports in visible:
            st_badge = Text(f"[{st}]", style=f"bold {color}")
            node_badge = Text(f"[{svc.vps}]", style=f"bold {_C_BRAND}")
            tbl.add_row(st_badge, svc.name, svc.category, node_badge, c_name, ports)

        sub_hdr = Text()
        sub_hdr.append(f"  Services Table  [{node_label}]  ", style=f"bold {_C_BRAND}")
        count_display = f"({clamped + 1}-{min(clamped + PAGE, filtered_count)} of {filtered_count} matched)" if filtered_count else "(0 matches)"
        sub_hdr.append(count_display, style=f"dim {_C_MUTED}")
        outer.add_row(sub_hdr)
        outer.add_row(tbl)

        footer = Text()
        footer.append(
            f"\n  Last Refreshed: {last_updated}   ",
            style=f"dim {_C_MUTED}",
        )
        if is_searching:
            footer.append(
                "[Enter] Lock Query   [Esc] Clear / Close Search",
                style=f"bold {_C_ACCENT}",
            )
        else:
            footer.append(
                "[/] Search   [F] State   [N] Node   [V/Tab] Overview   [Up/Down] Scroll   [R] Refresh   [Esc/S] Close",
                style=f"bold {_C_BRAND}",
            )
        outer.add_row(footer)
        return outer

    # ------------------------------------------------------------------
    # Overview mode — stopped stack alerts
    # ------------------------------------------------------------------
    body = Text()
    if stopped_names:
        body.append("\n  Inactive / Stopped Stacks:\n", style=f"bold {_C_ACCENT}")
        for name in stopped_names[:8]:
            body.append(f"    o  {name}\n", style=f"dim {_C_DANGER}")
        if len(stopped_names) > 8:
            body.append(
                f"    ... and {len(stopped_names) - 8} more stopped stacks\n",
                style=f"italic dim {_C_MUTED}",
            )
    else:
        body.append("\n  All workloads are active, healthy, and operational!\n", style=f"bold {_C_SUCCESS}")

    outer.add_row(body)

    footer = Text()
    footer.append(
        f"\n  Last Refreshed: {last_updated}   ",
        style=f"dim {_C_MUTED}",
    )
    footer.append(
        "[/] Search   [F] State   [N] Node   [V/Tab] Full Table   [R] Refresh   [Esc/S] Close",
        style=f"bold {_C_BRAND}",
    )
    outer.add_row(footer)
    return outer


def render_history_view(action_status: dict | None = None, offset: int = 0) -> "Table":
    """Render the persistent action history view inside the TUI pane with scrolling."""
    history = load_action_history(limit=50)

    outer = Table.grid(expand=True, padding=(0, 0))
    outer.add_column()

    if not history:
        body = Text()
        body.append("\n  No persistent action records found.\n", style=f"dim {_C_MUTED}")
        body.append("  Records are written to state/action_history.jsonl after each managed action.\n\n", style=f"dim {_C_MUTED}")
        body.append("  [Esc/H] Close", style=f"bold {_C_BRAND}")
        outer.add_row(body)
        return outer

    history_rev = list(reversed(history))
    PAGE = 14
    max_offset = max(0, len(history_rev) - PAGE)
    clamped = max(0, min(offset, max_offset))
    visible = history_rev[clamped:clamped + PAGE]

    hdr = Text()
    hdr.append(
        f"\n  Persistent Operations Audit Log   "
        f"({clamped + 1}-{min(clamped + PAGE, len(history_rev))} of {len(history_rev)} records)\n",
        style=f"bold {_C_BRAND}",
    )
    outer.add_row(hdr)

    tbl = Table(
        box=rich_box.ROUNDED,
        expand=True,
        show_header=True,
        header_style=f"bold {_C_BRAND}",
        border_style=_C_BORDER_INACTIVE,
        padding=(0, 1),
    )
    tbl.add_column("Timestamp", style=f"dim {_C_MUTED}", width=19)
    tbl.add_column("Node", width=8, justify="center")
    tbl.add_column("Status", width=13, justify="center")
    tbl.add_column("Exit", width=5, justify="center", style=f"dim {_C_MUTED}")
    tbl.add_column("Action", style=f"bold {_C_TEXT}", width=14)
    tbl.add_column("Duration", justify="right", width=9, style=_C_BRAND)
    tbl.add_column("Command", style=f"dim {_C_MUTED}")

    for entry in visible:
        ts = entry.get("timestamp", "")[:19].replace("T", " ")
        vps = entry.get("vps", "A")
        action = entry.get("action", "")
        duration = entry.get("duration_sec", 0.0)
        status = entry.get("status", "UNKNOWN").upper()
        code = entry.get("exit_code", 0)
        cmd = entry.get("command", action)

        st_color = _C_SUCCESS if status == "SUCCESS" else (_C_ACCENT if status == "CANCELLED" else _C_DANGER)
        st_badge = Text(f"[{status}]", style=f"bold {st_color}")
        node_badge = Text(f"[{vps}]", style=f"bold {_C_BRAND}")
        tbl.add_row(ts, node_badge, st_badge, str(code), action, f"{duration:.1f}s", cmd)

    outer.add_row(tbl)

    footer = Text()
    footer.append(
        "\n  [Up/Down/Wheel] Scroll   [PgUp/PgDn] Page   [Esc/H] Close",
        style=f"bold {_C_BRAND}",
    )
    outer.add_row(footer)
    return outer


def render_log_view(
    action_status: dict | None = None,
    log_state: dict | None = None,
    vps: str | None = None,
) -> "Table":
    """Render the action/container log output with scrolling and follow-mode indicator."""
    if action_status is None:
        action_status = {}
    if log_state is None:
        log_state = {}

    lines = action_status.get("log_lines", [])
    act_name = action_status.get("action", "STACK ACTION").upper()

    outer = Table.grid(expand=True, padding=(0, 0))
    outer.add_column()

    if not lines:
        body = Text()
        body.append(f"\n  No log output captured for {act_name}.\n\n", style=f"dim {_C_MUTED}")
        body.append("  Run an action or use './manage.py logs <service>' to stream live container logs.\n\n", style=f"dim {_C_MUTED}")
        body.append("  [Esc/L] Close", style=f"bold {_C_BRAND}")
        outer.add_row(body)
        return outer

    PAGE = 16
    max_offset = max(0, len(lines) - PAGE)
    is_following = log_state.get("follow", True)

    if is_following:
        log_state["offset"] = max_offset
    else:
        log_state["offset"] = max(0, min(log_state.get("offset", max_offset), max_offset))
    offset = log_state["offset"]

    follow_badge = (
        Text("[FOLLOWING]", style=f"bold {_C_SUCCESS}")
        if is_following
        else Text("[PAUSED]", style=f"bold {_C_WARN}")
    )

    hdr = Text()
    hdr.append(f"\n  Activity Logs: {act_name}   ", style=f"bold {_C_BRAND}")
    hdr.append(
        f"[{offset + 1}-{min(offset + PAGE, len(lines))} / {len(lines)}]   ",
        style=f"dim {_C_MUTED}",
    )
    hdr.append_text(follow_badge)
    hdr.append("\n")
    outer.add_row(hdr)

    log_tbl = Table(
        box=rich_box.ROUNDED,
        expand=True,
        show_header=False,
        border_style=_C_BORDER_INACTIVE,
        padding=(0, 1),
    )
    log_tbl.add_column()
    for line in lines[offset:offset + PAGE]:
        try:
            rendered = Text.from_ansi(line[:2000])
        except Exception:
            rendered = Text(line[:2000], style="white")
        log_tbl.add_row(rendered)

    outer.add_row(log_tbl)

    footer = Text()
    footer.append(
        "\n  [Up/Down/Wheel] Scroll   [PgUp/PgDn] Page   "
        "[F] Toggle Follow   [Home/g] Top   [End/G] Bottom   [Esc/L] Close",
        style=f"bold {_C_BRAND}",
    )
    outer.add_row(footer)
    return outer
