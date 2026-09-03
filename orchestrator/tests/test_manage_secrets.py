"""Tests for manage.py secrets routing and helper parity."""

import sys
import unittest
from unittest.mock import patch

import manage


class TestManageSecretsSnapshots(unittest.TestCase):
    @patch("orchestrator.secrets.snapshots.SnapshotManager.snapshot_all")
    def test_secrets_snapshot_all(self, mock_snapshot_all):
        mock_snapshot_all.return_value = (5, 0)
        with patch.object(sys, "argv", ["manage.py", "secrets", "snapshot", "--vps", "A"]):
            with self.assertRaises(SystemExit) as exc:
                manage.main()
            self.assertEqual(exc.exception.code, 0)
            mock_snapshot_all.assert_called_once_with(vps_context="A")

    @patch("orchestrator.secrets.snapshots.SnapshotManager.snapshot_config")
    def test_secrets_snapshot_config(self, mock_snapshot_cfg):
        mock_snapshot_cfg.return_value = True
        with patch.object(sys, "argv", ["manage.py", "secrets", "snapshot-config", "auth_authelia", "--vps", "A"]):
            with self.assertRaises(SystemExit) as exc:
                manage.main()
            self.assertEqual(exc.exception.code, 0)
            mock_snapshot_cfg.assert_called_once_with("net-stream-vps-a", "auth_authelia")

    @patch("orchestrator.secrets.snapshots.SnapshotManager.list_snapshots")
    def test_secrets_snapshots_list(self, mock_list):
        mock_list.return_value = [
            {
                "project": "net-stream-vps-a",
                "config": "auth_authelia",
                "path": "/path/to/snapshot",
                "size": 1024,
                "timestamp": "2026-08-15",
            }
        ]
        with patch.object(sys, "argv", ["manage.py", "secrets", "snapshots", "--vps", "A"]):
            with self.assertRaises(SystemExit) as exc:
                manage.main()
            self.assertEqual(exc.exception.code, 0)
            mock_list.assert_called_once_with(vps_context="A")


if __name__ == "__main__":
    unittest.main()
