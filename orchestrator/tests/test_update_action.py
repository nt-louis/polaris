"""Unit tests for UpdateAction orchestrator."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from orchestrator.actions.update import (
    UpdateAction,
    main,
)
from orchestrator.core.models import ActionContext, ServiceMetadata
from orchestrator.docker.updater import (
    format_age,
    get_host_platform,
    parse_iso_datetime,
)


class TestUpdateAction(unittest.TestCase):
    def test_helpers(self):
        plat = get_host_platform()
        self.assertIn("linux/", plat)

        dt = parse_iso_datetime("2026-08-15T12:00:00Z")
        self.assertEqual(dt.year, 2026)

        dt_frac = parse_iso_datetime("2026-08-15T12:00:00.123456789+00:00")
        self.assertEqual(dt_frac.year, 2026)

        self.assertEqual(format_age(0.5), "12.0 hours")
        self.assertEqual(format_age(2.5), "2.5 days")

    @patch("orchestrator.docker.updater.handle_updates")
    def test_dry_run_updates(self, mock_updater):
        action = UpdateAction()
        ctx = ActionContext(dry_run=True, vps="A")
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        self.assertIn("[DRY-RUN]", res.message)

    @patch("subprocess.run")
    def test_list_backups_found(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "linuxserver/jellyfin:backup-20260815-120000 sha256:1234567890ab 2026-08-15\n"
        mock_run.return_value = mock_proc

        action = UpdateAction()
        ctx = ActionContext(list_backups=True)
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        self.assertIn("Found 1 backup image(s)", res.message)

    @patch("subprocess.run")
    def test_list_backups_none(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_run.return_value = mock_proc

        action = UpdateAction()
        ctx = ActionContext(list_backups=True)
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        self.assertEqual(res.message, "No backup images found.")

    @patch("orchestrator.docker.check_upgrades.check_upgrades", return_value=[])
    def test_check_upgrades(self, mock_check):
        action = UpdateAction()
        ctx = ActionContext(check=True, json_output=True, vps="A")
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        mock_check.assert_called_once()

    @patch("orchestrator.docker.updater.handle_updates")
    def test_execute_updates_with_target_filter(self, mock_updater):
        action = UpdateAction()
        ctx = ActionContext(targets=["jellyfin"], yes=True, min_age=1.5, backup_days=5, vps="A")
        res = action.execute(ctx)

        self.assertTrue(res.success)
        mock_updater.assert_called_once()
        self.assertEqual(mock_updater.call_args.kwargs.get("auto_confirm"), True)
        self.assertEqual(mock_updater.call_args.kwargs.get("min_age_days"), 1.5)
        self.assertEqual(mock_updater.call_args.kwargs.get("backup_days"), 5)

    @patch("orchestrator.docker.updater.handle_updates")
    def test_main_cli_dispatch(self, mock_updater):
        code = main(["--yes", "--min-age", "2.0", "--backup-days", "14", "--vps", "A"])
        self.assertEqual(code, 0)
        mock_updater.assert_called_once()
        self.assertEqual(mock_updater.call_args.kwargs.get("auto_confirm"), True)
        self.assertEqual(mock_updater.call_args.kwargs.get("min_age_days"), 2.0)
        self.assertEqual(mock_updater.call_args.kwargs.get("backup_days"), 14)

    @patch("orchestrator.actions.update.load_services")
    @patch("orchestrator.docker.updater.handle_updates")
    def test_execute_updates_filters_by_vps_node(self, mock_updater, mock_load):
        mock_load.return_value = [
            ServiceMetadata(
                name="jellyfin",
                rel_dir="Media/local-media/players/jellyfin",
                abs_dir=Path("/mock/Media/local-media/players/jellyfin"),
                category="Media",
                vps="A",
            )
        ]

        action = UpdateAction()
        ctx = ActionContext(yes=True, vps="A")
        res = action.execute(ctx)

        self.assertTrue(res.success)
        mock_updater.assert_called_once()
        self.assertEqual(mock_updater.call_args.kwargs.get("auto_confirm"), True)
        self.assertEqual(mock_updater.call_args.kwargs.get("min_age_days"), 0.0)
        self.assertEqual(mock_updater.call_args.kwargs.get("backup_days"), 7)

    def test_main_cli_rejects_unknown_flags(self):
        with patch("sys.stderr"):
            code = main(["--invalid-flag-123"])
            self.assertEqual(code, 2)

    def test_main_cli_missing_vps_value(self):
        with patch("sys.stderr"):
            code = main(["--vps"])
            self.assertEqual(code, 2)

    def test_main_cli_invalid_vps(self):
        with patch("sys.stderr"):
            code = main(["--vps", "INVALID"])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
