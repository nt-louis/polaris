"""Unit tests for manage.py CLI routing, action delegation, and option parsing."""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import manage
from orchestrator.core.constants import REPO_ROOT


class TestManageCliRouter(unittest.TestCase):
    def test_manage_deploy_dry_run(self):
        manage_path = REPO_ROOT / "manage.py"
        res = subprocess.run(
            [sys.executable, str(manage_path), "deploy", "--dry-run", "--vps", "A"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Would deploy", res.stdout)
        self.assertIn("VPS A", res.stdout)

    def test_manage_preserves_error_exit_codes(self):
        manage_path = REPO_ROOT / "manage.py"
        res = subprocess.run(
            [sys.executable, str(manage_path), "deploy", "nonexistent-target-12345", "--vps", "A"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        self.assertEqual(res.returncode, 1)

    def test_manage_stop_dry_run(self):
        manage_path = REPO_ROOT / "manage.py"
        res = subprocess.run(
            [sys.executable, str(manage_path), "stop", "--dry-run", "--vps", "A"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        self.assertEqual(res.returncode, 0)

    def test_manage_redeploy_dry_run(self):
        manage_path = REPO_ROOT / "manage.py"
        res = subprocess.run(
            [sys.executable, str(manage_path), "redeploy", "--dry-run", "--vps", "A"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        self.assertEqual(res.returncode, 0)

    def test_manage_update_list_backups(self):
        manage_path = REPO_ROOT / "manage.py"
        res = subprocess.run(
            [sys.executable, str(manage_path), "update", "--list-backups"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        self.assertEqual(res.returncode, 0)

    def test_manage_rejects_unknown_flags(self):
        manage_path = REPO_ROOT / "manage.py"
        res = subprocess.run(
            [sys.executable, str(manage_path), "deploy", "--dryrun"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        self.assertEqual(res.returncode, 2)
        self.assertTrue(
            "unrecognized arguments: --dryrun" in res.stderr
            or "Unknown deploy option '--dryrun'" in res.stderr
        )

    def test_manage_update_delegation(self):
        with patch("orchestrator.docker.updater.handle_updates") as mock_updater, \
             patch("sys.argv", ["manage.py", "update", "--yes", "--min-age", "3.0", "--backup-days", "10", "--vps", "A"]), \
             self.assertRaises(SystemExit) as cm:
            manage.main()
        self.assertEqual(cm.exception.code, 0)
        mock_updater.assert_called_once()
        self.assertEqual(mock_updater.call_args.kwargs.get("auto_confirm"), True)
        self.assertEqual(mock_updater.call_args.kwargs.get("min_age_days"), 3.0)
    def test_manage_cli_router_install_and_status(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Status when not installed
            with patch("sys.argv", ["manage.py", "cli", "status", tmpdir]), \
                 self.assertRaises(SystemExit) as cm:
                manage.main()
            self.assertEqual(cm.exception.code, 1)

            # 2. Install
            with patch("sys.argv", ["manage.py", "cli", "install", tmpdir]), \
                 self.assertRaises(SystemExit) as cm:
                manage.main()
            self.assertEqual(cm.exception.code, 0)
            target = Path(tmpdir) / "net-stream"
            self.assertTrue(target.exists())
            self.assertTrue(os.access(target, os.X_OK))

            # 3. Verify
            with patch("sys.argv", ["manage.py", "cli", "verify", tmpdir]), \
                 self.assertRaises(SystemExit) as cm:
                manage.main()
            self.assertEqual(cm.exception.code, 0)

            # 4. Uninstall
            with patch("sys.argv", ["manage.py", "cli", "uninstall", tmpdir]), \
                 self.assertRaises(SystemExit) as cm:
                manage.main()
            self.assertEqual(cm.exception.code, 0)
            self.assertFalse(target.exists())

    def test_manage_cli_router_rejects_unknown(self):
        with patch("sys.argv", ["manage.py", "cli", "invalid-subcmd"]), \
             self.assertRaises(SystemExit) as cm:
            manage.main()
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
