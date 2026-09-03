"""Unit tests for BackupAction orchestrator and worktree snapshot sync."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from orchestrator.actions.backup import BackupAction, build_backup_command, main
from orchestrator.core.models import ActionContext
from orchestrator.secrets.snapshots import sync_snapshots_to_branch


class TestBackupAction(unittest.TestCase):
    def test_build_backup_command_forwards_vps(self):
        cmd = build_backup_command("/path/to/script.sh", ["--arg1"], vps="B")
        self.assertIn("doppler", cmd)
        self.assertIn("polaris-vps-b", cmd)
        self.assertIn("--vps", cmd)
        self.assertIn("B", cmd)
        self.assertIn("/path/to/script.sh", cmd)

    @patch("os.geteuid", return_value=0)
    @patch("subprocess.run")
    def test_build_backup_command_root_prefetch_failure_raises(self, mock_run, mock_euid):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "Doppler auth error"
        mock_run.return_value = mock_proc

        with patch("orchestrator.actions.backup.pwd.getpwuid", return_value=MagicMock(pw_name="ubuntu")):
            with self.assertRaises(RuntimeError) as ctx:
                build_backup_command("/path/to/script.sh", [], vps="A", force_prefetch=True)
            self.assertIn("Doppler download failed", str(ctx.exception))

    @patch("orchestrator.actions.backup.sync_snapshots_to_branch")
    @patch("subprocess.call", return_value=0)
    def test_backup_run_success_triggers_snapshot_sync(self, mock_call, mock_sync):
        action = BackupAction()
        ctx = ActionContext(targets=["run"], vps="A", yes=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        mock_call.assert_called_once()
        mock_sync.assert_called_once()

    @patch("orchestrator.actions.backup.sync_snapshots_to_branch")
    @patch("subprocess.call", return_value=0)
    def test_backup_run_dry_run_does_not_sync(self, mock_call, mock_sync):
        action = BackupAction()
        ctx = ActionContext(targets=["run"], vps="A", yes=True, dry_run=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        mock_call.assert_called_once()
        mock_sync.assert_not_called()

    @patch("subprocess.call", return_value=1)
    def test_backup_run_failure(self, mock_call):
        action = BackupAction()
        ctx = ActionContext(targets=["run"], vps="A", yes=True)
        res = action.execute(ctx)

        self.assertFalse(res.success)
        self.assertEqual(res.exit_code, 1)

    def test_backup_restore_non_interactive_without_yes_blocked(self):
        action = BackupAction()
        ctx = ActionContext(targets=["restore"], vps="A", yes=False, dry_run=False)

        with patch("sys.stdin.isatty", return_value=False):
            res = action.execute(ctx)
            self.assertFalse(res.success)
            self.assertEqual(res.exit_code, 1)
            self.assertIn("cancelled", res.message.lower())

    @patch("subprocess.call", return_value=0)
    def test_backup_restore_dry_run_preview(self, mock_call):
        action = BackupAction()
        ctx = ActionContext(targets=["restore"], vps="A", dry_run=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        self.assertIn("preview completed", res.message)
        mock_call.assert_called_once()
        args = mock_call.call_args[0][0]
        self.assertIn("--list", args)

    @patch("subprocess.call", return_value=0)
    def test_backup_restore_with_yes(self, mock_call):
        action = BackupAction()
        ctx = ActionContext(targets=["restore"], vps="A", yes=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        mock_call.assert_called_once()
        args = mock_call.call_args[0][0]
        self.assertIn("--yes", args)

    @patch("subprocess.call", return_value=0)
    def test_backup_snapshots_check_prune_stats(self, mock_call):
        action = BackupAction()

        for subcmd in ("snapshots", "check", "prune", "stats"):
            ctx = ActionContext(targets=[subcmd], vps="A", yes=True)
            res = action.execute(ctx)
            self.assertTrue(res.success)
            self.assertEqual(res.exit_code, 0)

    @patch("orchestrator.actions.backup.sync_snapshots_to_branch")
    @patch("subprocess.call", return_value=0)
    def test_main_cli_dispatch(self, mock_call, mock_sync):
        code = main(["run", "--vps", "B", "--yes"])
        self.assertEqual(code, 0)
        mock_call.assert_called_once()
        mock_sync.assert_called_once()

    def test_main_cli_invalid_vps(self):
        with patch("sys.stderr"):
            code = main(["run", "--vps", "INVALID"])
            self.assertEqual(code, 2)

    def test_main_cli_missing_vps_value(self):
        with patch("sys.stderr"):
            code = main(["run", "--vps"])
            self.assertEqual(code, 2)
            code2 = main(["restore", "--yes", "--vps"])
            self.assertEqual(code2, 2)


class TestSnapshotSync(unittest.TestCase):
    @patch("orchestrator.secrets.snapshots._run_git")
    def test_sync_snapshots_to_branch_no_git_dir(self, mock_git):
        success, msg = sync_snapshots_to_branch(repo_root=Path("/nonexistent/path/12345"))
        self.assertFalse(success)
        self.assertIn("not a git repository", msg.lower())

    def test_sync_snapshots_no_changes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / ".git").mkdir()
            wt_dir = tmppath / "worktree"
            wt_dir.mkdir()

            with patch("orchestrator.secrets.snapshots._run_git") as mock_git, \
                 patch("orchestrator.secrets.snapshots.tempfile.mkdtemp", return_value=str(wt_dir)), \
                 patch("orchestrator.secrets.snapshots.SnapshotManager.snapshot_all", return_value=(5, 0)):

                diff_res = MagicMock()
                diff_res.returncode = 0
                mock_git.return_value = diff_res

                ok, msg = sync_snapshots_to_branch(repo_root=tmppath)
                self.assertTrue(ok)
                self.assertIn("No snapshot changes detected", msg)

    def test_sync_snapshots_uses_force_fetch_refspec(self):
        import tempfile
        from unittest.mock import MagicMock, patch
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / ".git").mkdir()
            wt_dir = tmppath / "worktree"
            wt_dir.mkdir()

            with patch("orchestrator.secrets.snapshots._run_git") as mock_git, \
                 patch("orchestrator.secrets.snapshots.tempfile.mkdtemp", return_value=str(wt_dir)), \
                 patch("orchestrator.secrets.snapshots.SnapshotManager.snapshot_all", return_value=(5, 0)):

                # Simulate ls-remote finding existing remote branch
                ls_res = MagicMock()
                ls_res.returncode = 0
                ls_res.stdout = "a1b2c3d refs/heads/snapshots/sync\n"

                diff_res = MagicMock()
                diff_res.returncode = 0

                def mock_git_dispatch(cmd, **kwargs):
                    if "ls-remote" in cmd:
                        return ls_res
                    return diff_res

                mock_git.side_effect = mock_git_dispatch

                ok, msg = sync_snapshots_to_branch(repo_root=tmppath)
                self.assertTrue(ok)

                # Verify fetch was called with '+snapshots/sync:snapshots/sync'
                fetch_calls = [call for call in mock_git.call_args_list if "fetch" in call[0][0]]
                self.assertTrue(len(fetch_calls) > 0)
                self.assertIn("+snapshots/sync:snapshots/sync", fetch_calls[0][0][0])


if __name__ == "__main__":
    unittest.main()
