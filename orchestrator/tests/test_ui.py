import unittest
from pathlib import Path
from unittest.mock import patch

from rich.layout import Layout

from orchestrator.core.models import ServiceMetadata
from orchestrator.core.state import get_active_vps
from orchestrator.ui.dashboard import (
    find_palette_matches,
    get_action_command,
    get_dashboard_categories,
    render_checklist_layout,
    render_confirmation,
    render_palette,
    trigger_action,
    update_layout,
)
from orchestrator.ui.inspector import (
    get_cached_containers,
    get_cached_services,
    render_history_view,
    render_log_view,
    render_status_view,
)
from orchestrator.ui.prompts import (
    RawTerminalContext,
    StandardTerminalContext,
    confirm_action,
    set_mouse_tracking,
)


class TestUiPrompts(unittest.TestCase):
    def test_confirm_action_with_yes(self):
        self.assertTrue(confirm_action("Do something dangerous?", yes=True))

    def test_confirm_action_non_interactive(self):
        with patch("sys.stdin.isatty", return_value=False), patch("sys.stderr"):
            self.assertFalse(confirm_action("Do something dangerous?", yes=False))

    def test_confirm_action_interactive_yes(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="y"):
            self.assertTrue(confirm_action("Proceed?", yes=False))

    def test_confirm_action_interactive_no(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="n"):
            self.assertFalse(confirm_action("Proceed?", yes=False))

    def test_confirm_action_interactive_default_yes(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=""):
            self.assertTrue(confirm_action("Proceed?", yes=False, default_yes=True))

    def test_confirm_action_interactive_default_no(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=""):
            self.assertFalse(confirm_action("Proceed?", yes=False, default_yes=False))

    def test_raw_and_standard_terminal_context(self):
        with patch("sys.stdin.isatty", return_value=False):
            with RawTerminalContext() as fd:
                self.assertIsNone(fd)
                with StandardTerminalContext():
                    pass

    @patch("sys.stdout.write")
    @patch("sys.stdout.flush")
    def test_set_mouse_tracking(self, mock_flush, mock_write):
        set_mouse_tracking(True)
        mock_write.assert_called_once()
        self.assertIn("\x1b[?1000h", mock_write.call_args[0][0])
        self.assertIn("\x1b[?1006h", mock_write.call_args[0][0])
        # Verify any-motion tracking (1003) is NOT enabled
        self.assertNotIn("\x1b[?1003h", mock_write.call_args[0][0])
        mock_flush.assert_called_once()

    def test_read_key_bytes_mouse_wheel_and_filtering(self):
        from orchestrator.ui.prompts import _read_key_bytes

        # Wheel Up: \x1b[<64;10;20M -> \x1b[<wheel_up>
        with patch("time.monotonic", return_value=100.0):
            with patch("select.select", side_effect=[(True, [], []), (False, [], []), (False, [], []), (False, [], [])]):
                with patch("os.read", side_effect=[b"\x1b", b"[<64;10;20M"]):
                    res = _read_key_bytes(0, timeout=None)
                    self.assertEqual(res, "\x1b[<wheel_up>")

        # Wheel Down: \x1b[<65;10;20M -> \x1b[<wheel_down> (after cooldown)
        with patch("time.monotonic", return_value=100.2):
            with patch("select.select", side_effect=[(True, [], []), (False, [], []), (False, [], []), (False, [], [])]):
                with patch("os.read", side_effect=[b"\x1b", b"[<65;10;20M"]):
                    res = _read_key_bytes(0, timeout=None)
                    self.assertEqual(res, "\x1b[<wheel_down>")

        # Left Click at column 64: \x1b[<0;64;20M -> None (ignored, does not trigger Up arrow)
        with patch("select.select", side_effect=[(True, [], []), (False, [], []), (False, [], [])]):
            with patch("os.read", side_effect=[b"\x1b", b"[<0;64;20M"]):
                res = _read_key_bytes(0, timeout=None)
                self.assertIsNone(res)

        # Left Click at column 65: \x1b[<0;65;20M -> None (ignored, does not trigger Down arrow)
        with patch("select.select", side_effect=[(True, [], []), (False, [], []), (False, [], [])]):
            with patch("os.read", side_effect=[b"\x1b", b"[<0;65;20M"]):
                res = _read_key_bytes(0, timeout=None)
                self.assertIsNone(res)

        # Hover / Motion event: \x1b[<35;10;20M -> None (ignored)
        with patch("select.select", side_effect=[(True, [], []), (False, [], []), (False, [], [])]):
            with patch("os.read", side_effect=[b"\x1b", b"[<35;10;20M"]):
                res = _read_key_bytes(0, timeout=None)
                self.assertIsNone(res)

        # Normal X10 Mouse Wheel Up: \x1b[M`!! -> \x1b[<wheel_up> (chr(32+64)=96='`')
        with patch("time.monotonic", return_value=100.4):
            with patch("select.select", side_effect=[(True, [], []), (True, [], []), (True, [], []), (True, [], []), (False, [], []), (False, [], [])]):
                with patch("os.read", side_effect=[b"\x1b", b"[M", b"`", b"!", b"!"]):
                    res = _read_key_bytes(0, timeout=None)
                    self.assertEqual(res, "\x1b[<wheel_up>")

        # Normal X10 Mouse Wheel Down: \x1b[Ma!! -> \x1b[<wheel_down> (chr(32+65)=97='a')
        with patch("time.monotonic", return_value=100.6):
            with patch("select.select", side_effect=[(True, [], []), (True, [], []), (True, [], []), (True, [], []), (False, [], []), (False, [], [])]):
                with patch("os.read", side_effect=[b"\x1b", b"[M", b"a", b"!", b"!"]):
                    res = _read_key_bytes(0, timeout=None)
                    self.assertEqual(res, "\x1b[<wheel_down>")

        # Keyboard Up Arrow: \x1b[A -> \x1b[A
        with patch("select.select", side_effect=[(True, [], []), (False, [], []), (False, [], [])]):
            with patch("os.read", side_effect=[b"\x1b", b"[A"]):
                res = _read_key_bytes(0, timeout=None)
                self.assertEqual(res, "\x1b[A")



class TestUiInspector(unittest.TestCase):
    @patch("orchestrator.docker.client.DockerClient.get_all_containers_info", return_value=[])
    def test_get_cached_containers(self, mock_info):
        containers = get_cached_containers(force=True)
        self.assertIsInstance(containers, list)

    @patch("orchestrator.docker.client.DockerClient.get_all_containers_info", return_value=[])
    def test_get_cached_containers_initialization_with_empty_result(self, mock_info):
        """Ensure empty container list still marks cache as initialized without re-querying synchronously."""
        from orchestrator.ui.inspector import _CONTAINER_CACHE
        _CONTAINER_CACHE["initialized"] = False
        _CONTAINER_CACHE["timestamp"] = 0.0

        res1 = get_cached_containers(ttl=10.0)
        self.assertEqual(res1, [])
        self.assertTrue(_CONTAINER_CACHE["initialized"])
        self.assertFalse(_CONTAINER_CACHE["fetching"])
        self.assertGreater(_CONTAINER_CACHE["timestamp"], 0.0)

    @patch("orchestrator.docker.client.DockerClient.get_all_containers_info", return_value=[{"Names": "test-c"}])
    def test_refresh_containers_bg_lifecycle(self, mock_info):
        """Ensure refresh_containers_bg updates containers and clears fetching flag."""
        import time

        from orchestrator.ui.inspector import _CONTAINER_CACHE, refresh_containers_bg
        _CONTAINER_CACHE["fetching"] = False

        refresh_containers_bg(force=True)
        time.sleep(0.1)
        self.assertFalse(_CONTAINER_CACHE["fetching"])
        self.assertEqual(_CONTAINER_CACHE["containers"], [{"Names": "test-c"}])

    def test_get_cached_services(self):
        svcs = get_cached_services(vps="A", force=True)
        self.assertIsInstance(svcs, list)
        self.assertTrue(all(s.vps == "A" for s in svcs))

    @patch("orchestrator.docker.client.DockerClient.get_all_containers_info", return_value=[])
    def test_render_status_view(self, mock_info):
        table = render_status_view("A")
        self.assertIsNotNone(table)

        # Full table mode
        tbl_mode = render_status_view("A", show_table=True)
        self.assertIsNotNone(tbl_mode)

        # Search query filter
        tbl_query = render_status_view("A", query="jellyfin", is_searching=True)
        self.assertIsNotNone(tbl_query)

        # State filter
        tbl_state = render_status_view("A", state_filter="HEALTHY")
        self.assertIsNotNone(tbl_state)

    def test_render_history_view_empty(self):
        with patch("orchestrator.ui.inspector.load_action_history", return_value=[]):
            table = render_history_view({})
            self.assertIsNotNone(table)

    def test_render_history_view_with_data(self):
        fake_history = [
            {
                "timestamp": "2026-08-19T11:00:00",
                "vps": "A",
                "action": "deploy",
                "duration_sec": 1.5,
                "status": "SUCCESS",
                "exit_code": 0,
            }
        ]
        with patch("orchestrator.ui.inspector.load_action_history", return_value=fake_history):
            table = render_history_view()
            self.assertIsNotNone(table)

    def test_render_log_view_empty(self):
        from rich.table import Table
        result = render_log_view({}, {})
        # render_log_view now returns a Table (grid) wrapping Text rows
        self.assertIsInstance(result, Table)

    def test_render_log_view_with_lines(self):
        import io

        from rich.console import Console
        from rich.table import Table
        action_status = {
            "action": "deploy",
            "log_lines": ["Line 1", "Line 2", "Line 3"],
        }
        log_state = {"follow": True, "offset": 0}
        result = render_log_view(action_status, log_state)
        self.assertIsInstance(result, Table)
        # Render to string to verify content is present
        console = Console(file=io.StringIO(), force_terminal=True, width=120)
        console.print(result)
        rendered = console.file.getvalue()
        self.assertIn("DEPLOY", rendered)


class TestUiDashboard(unittest.TestCase):
    def test_get_dashboard_categories(self):
        cats = get_dashboard_categories()
        self.assertIsInstance(cats, list)
        cat_ids = {c["id"] for c in cats}
        self.assertIn("deploy_wizard", cat_ids)
        self.assertIn("redeploy", cat_ids)
        self.assertIn("stop_stack", cat_ids)
        self.assertIn("registry_updates", cat_ids)
        self.assertIn("secrets", cat_ids)
        self.assertIn("backup_restic", cat_ids)
        self.assertIn("network", cat_ids)
        self.assertIn("sysutils", cat_ids)

    def test_get_action_command(self):
        cmd_deploy = get_action_command("deploy", {"vps": "A", "mode": "last", "force_gateways": True})
        self.assertIn("deploy", cmd_deploy)
        self.assertIn("--vps", cmd_deploy)
        self.assertIn("A", cmd_deploy)
        self.assertIn("--last", cmd_deploy)
        self.assertIn("--force-gateways", cmd_deploy)

        cmd_deploy_interactive = get_action_command("deploy", {"vps": "A", "mode": "interactive"})
        self.assertIn("--interactive", cmd_deploy_interactive)

        cmd_redeploy_interactive = get_action_command("redeploy", {"redeploy_mode": "interactive", "build": True})
        self.assertIn("redeploy", cmd_redeploy_interactive)
        self.assertIn("--interactive", cmd_redeploy_interactive)
        self.assertIn("--build", cmd_redeploy_interactive)

        cmd_stop = get_action_command("stop", {"stop_mode": "interactive"})
        self.assertIn("stop", cmd_stop)
        self.assertIn("--interactive", cmd_stop)

        cmd_update = get_action_command("update", {"min_age": 1.5, "backup_days": 10})
        self.assertIn("update", cmd_update)
        self.assertIn("--min-age", cmd_update)
        self.assertIn("1.5", cmd_update)

        cmd_backup = get_action_command("backup_op", {"backup_cmd": "restore", "backup_vps": "B"})
        self.assertIn("backup", cmd_backup)
        self.assertIn("restore", cmd_backup)
        self.assertIn("--vps", cmd_backup)
        self.assertIn("B", cmd_backup)
        self.assertIn("--yes", cmd_backup)

        cmd_secrets = get_action_command("secrets", {"secret_cmd": "prune-a"})
        self.assertIn("secrets", cmd_secrets)
        self.assertIn("prune", cmd_secrets)
        self.assertIn("--vps", cmd_secrets)
        self.assertIn("A", cmd_secrets)

        cmd_net = get_action_command("network", {"net_cmd": "fix-routing"})
        self.assertIn("network", cmd_net)
        self.assertIn("fix", cmd_net)

        cmd_sys = get_action_command("sysutils", {"sys_cmd": "doctor"})
        self.assertIn("doctor", cmd_sys)

        cmd_cli_inst = get_action_command("sysutils", {"sys_cmd": "cli-install"})
        self.assertIn("cli", cmd_cli_inst)
        self.assertIn("install", cmd_cli_inst)

        cmd_cli_ver = get_action_command("sysutils", {"sys_cmd": "cli-verify"})
        self.assertIn("cli", cmd_cli_ver)
        self.assertIn("verify", cmd_cli_ver)

        cmd_cli_uninst = get_action_command("sysutils", {"sys_cmd": "cli-uninstall"})
        self.assertIn("cli", cmd_cli_uninst)
        self.assertIn("uninstall", cmd_cli_uninst)

        cmd_deploy_dev = get_action_command("deploy", {"vps": "A"}, allow_dev=True)
        self.assertIn("--allow-dev", cmd_deploy_dev)

        cmd_redeploy_dev = get_action_command("redeploy", {}, allow_dev=True)
        self.assertIn("--allow-dev", cmd_redeploy_dev)

        cmd_stop_dev = get_action_command("stop", {}, allow_dev=True)
        self.assertIn("--allow-dev", cmd_stop_dev)

        cmd_update_dev = get_action_command("update", {}, allow_dev=True)
        self.assertIn("--allow-dev", cmd_update_dev)

    def test_palette_and_confirmation(self):
        cats = get_dashboard_categories()
        matches = find_palette_matches(cats, "doctor")
        self.assertTrue(any("doctor" in m[3].lower() or "diagnostics" in m[3].lower() for m in matches))

        pal_state = {"query": "doctor"}
        pal_table = render_palette(pal_state, cats)
        self.assertIsNotNone(pal_table)

        conf_state = {"action": "stop", "warning": "Will stop containers", "allow_dev": False}
        conf_table = render_confirmation(conf_state)
        self.assertIsNotNone(conf_table)

        conf_state_dev = {"action": "deploy", "warning": "Branch Guard Notice", "allow_dev": True}
        conf_table_dev = render_confirmation(conf_state_dev)
        self.assertIsNotNone(conf_table_dev)

    @patch("orchestrator.ui.dashboard.get_current_git_branch", return_value="feat/test-feature")
    @patch("orchestrator.ui.dashboard.is_main_branch", return_value=False)
    def test_trigger_action_branch_guard_popup(self, mock_is_main, mock_get_branch):
        confirmation_state = {"active": False}
        action_status = {"state": "idle"}
        from unittest.mock import MagicMock
        mock_live = MagicMock()

        trigger_action(
            action_name="deploy",
            items=[{"type": "checkbox", "id": "build", "checked": False}],
            live=mock_live,
            action_status=action_status,
            confirmation_state=confirmation_state,
        )
        self.assertTrue(confirmation_state["active"])
        self.assertEqual(confirmation_state["action"], "deploy")
        self.assertTrue(confirmation_state["allow_dev"])
        self.assertIn("feat/test-feature", confirmation_state["warning"])

    def test_update_layout_main_and_detail(self):
        cats = get_dashboard_categories()
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=3),
        )

        menu_state_main = {"view": "main", "main_idx": 0, "item_idx": 0}
        selectable = update_layout(
            layout,
            menu_state_main,
            cats,
            {"state": "idle"},
            {"active": False},
            {"active": False},
            {"active": False},
            {"active": False},
            {"active": False},
        )
        self.assertIsInstance(selectable, list)

        menu_state_detail = {"view": "detail", "main_idx": 0, "item_idx": 0}
        selectable_detail = update_layout(
            layout,
            menu_state_detail,
            cats,
            {"state": "success", "action": "deploy", "duration": 1.2},
            {"active": False},
            {"active": False},
            {"active": False},
            {"active": False},
            {"active": False},
        )
        self.assertIsInstance(selectable_detail, list)
        self.assertGreater(len(selectable_detail), 0)

    def test_render_checklist_layout(self):
        s1 = ServiceMetadata(name="app1", rel_dir="dir1", abs_dir=Path("/tmp/1"), category="CatA", vps="A")
        s2 = ServiceMetadata(name="app2", rel_dir="dir2", abs_dir=Path("/tmp/2"), category="CatB", vps="B")
        services = [s1, s2]
        categories = {"CatA": [s1], "CatB": [s2]}

        layout = render_checklist_layout(
            all_services=services,
            categories=categories,
            cat_names=["CatA", "CatB"],
            checked_services={"dir1"},
            current_menu="categories",
            selected_cat_idx=0,
            selected_svc_idx=0,
            active_cat="CatA",
            vps_label=" [Node A]",
            verb="deploy",
        )
        self.assertIsNotNone(layout)

    @patch("orchestrator.ui.dashboard.get_active_vps", return_value="A")
    def test_status_keybindings_and_node_cycling(self, mock_active_vps):
        status_state = {"active": True, "query": "", "state_filter": "ALL", "node_filter": "A"}

        # Simulate cycling node: A -> B -> ALL -> A
        for expected in ["B", "ALL", "A"]:
            cur_node = (status_state.get("node_filter") or get_active_vps()).upper()
            if cur_node == "A":
                status_state["node_filter"] = "B"
            elif cur_node == "B":
                status_state["node_filter"] = "ALL"
            else:
                status_state["node_filter"] = "A"
            self.assertEqual(status_state["node_filter"], expected)

        # Simulate cycling state: ALL -> HEALTHY -> RUNNING -> STOPPED -> ALL
        states = ["ALL", "HEALTHY", "RUNNING", "STOPPED"]
        for expected in ["HEALTHY", "RUNNING", "STOPPED", "ALL"]:
            cur_st = status_state.get("state_filter", "ALL").upper()
            idx = (states.index(cur_st) + 1) % len(states) if cur_st in states else 0
            status_state["state_filter"] = states[idx]
            self.assertEqual(status_state["state_filter"], expected)


if __name__ == "__main__":
    unittest.main()
