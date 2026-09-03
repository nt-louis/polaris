"""Tests for manage.py backup routing and helper parity."""

import os
import sys
import unittest
from unittest.mock import patch

import manage
from orchestrator.actions.backup import build_backup_command
from orchestrator.actions.backup import main as backup_main
from orchestrator.core.constants import REPO_ROOT


class TestBackupVpsSelection(unittest.TestCase):
    def test_invalid_vps_selection_fails_closed(self):
        with patch("sys.stderr"):
            exit_code = backup_main(["prune", "--vps", "INVALID"])
            self.assertEqual(exit_code, 2)


@patch("os.geteuid", return_value=1000, create=True)
class TestBackupCommandBuilder(unittest.TestCase):
    @patch("os.environ.get", return_value="A")
    def test_build_backup_command_invokes_doppler(self, mock_env, mock_geteuid):
        script_path = os.path.join(REPO_ROOT, "orchestrator", "scripts", "backup", "backup-prune.sh")
        cmd = build_backup_command(script_path, ["--vps", "a", "--max-unused", "10%"])
        self.assertEqual(cmd[0], "doppler")
        self.assertEqual(cmd[1], "run")
        self.assertIn("--project", cmd)
        self.assertIn("net-stream-vps-a", cmd)
        self.assertIn("--config", cmd)
        self.assertIn("backup", cmd)
        self.assertIn(script_path, cmd)
        self.assertIn("--max-unused", cmd)
        self.assertIn("10%", cmd)


@patch("os.geteuid", return_value=1000, create=True)
class TestManageBackupRouting(unittest.TestCase):
    @patch("subprocess.call", return_value=0)
    def test_backup_prune_routing(self, mock_call, mock_geteuid):
        with patch.object(sys, "argv", ["manage.py", "backup", "prune", "--vps", "B"]):
            with self.assertRaises(SystemExit) as exc:
                manage.main()
            self.assertEqual(exc.exception.code, 0)
            self.assertTrue(mock_call.called)
            called_cmd = mock_call.call_args[0][0]
            self.assertTrue(any("backup-prune.sh" in arg for arg in called_cmd))

    @patch("subprocess.call", return_value=0)
    def test_backup_stats_routing(self, mock_call, mock_geteuid):
        with patch.object(sys, "argv", ["manage.py", "backup", "stats", "--vps", "A", "--mode", "raw-data"]):
            with self.assertRaises(SystemExit) as exc:
                manage.main()
            self.assertEqual(exc.exception.code, 0)
            self.assertTrue(mock_call.called)
            called_cmd = mock_call.call_args[0][0]
            self.assertTrue(any("backup-stats.sh" in arg for arg in called_cmd))


if __name__ == "__main__":
    unittest.main()
