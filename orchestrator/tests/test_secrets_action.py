"""Unit tests for SecretsAction orchestrator."""

import unittest
from unittest.mock import MagicMock, patch

from orchestrator.actions.secrets import SecretsAction, main
from orchestrator.core.models import ActionContext


class TestSecretsAction(unittest.TestCase):
    @patch("webbrowser.open")
    def test_secrets_open_dashboard(self, mock_open):
        action = SecretsAction()
        ctx = ActionContext(targets=["open"])
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        mock_open.assert_called_once()

    @patch("subprocess.run")
    def test_secrets_verify_success(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        action = SecretsAction()
        ctx = ActionContext(targets=["verify"])
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)

    @patch("subprocess.run")
    def test_secrets_verify_failure(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "Not logged in"
        mock_run.return_value = mock_proc

        action = SecretsAction()
        ctx = ActionContext(targets=["verify"])
        res = action.execute(ctx)
        self.assertFalse(res.success)
        self.assertEqual(res.exit_code, 1)

    @patch("orchestrator.secrets.doppler.audit_repository_secrets", return_value=0)
    def test_secrets_audit(self, mock_audit):
        action = SecretsAction()
        ctx = ActionContext(targets=["audit"])
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        mock_audit.assert_called_once()

    @patch("orchestrator.secrets.doppler.sync_repository_configs", return_value=(2, 0))
    def test_secrets_sync(self, mock_sync):
        action = SecretsAction()
        ctx = ActionContext(targets=["sync"], dry_run=True)
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        mock_sync.assert_called_once_with(dry_run=True)

    def test_secrets_prune_non_interactive_without_yes_blocked(self):
        action = SecretsAction()
        ctx = ActionContext(targets=["prune"], vps="A", yes=False, dry_run=False)

        with patch("sys.stdin.isatty", return_value=False):
            res = action.execute(ctx)
            self.assertFalse(res.success)
            self.assertEqual(res.exit_code, 1)
            self.assertIn("cancelled", res.message.lower())

    @patch("orchestrator.secrets.doppler.prune_redundant_secrets", return_value=(3, 0))
    def test_secrets_prune_with_yes(self, mock_prune):
        action = SecretsAction()
        ctx = ActionContext(targets=["prune"], vps="A", yes=True, dry_run=False)
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        mock_prune.assert_called_once_with(vps_context="A", dry_run=False)

    @patch("orchestrator.secrets.doppler.prune_redundant_secrets", return_value=(2, 0))
    def test_secrets_prune_vps_all(self, mock_prune):
        action = SecretsAction()
        ctx = ActionContext(targets=["prune"], vps="ALL", yes=True, dry_run=False)
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        self.assertEqual(mock_prune.call_count, 3)

    @patch("orchestrator.secrets.snapshots.SnapshotManager")
    def test_secrets_snapshot_all(self, mock_sm):
        mock_sm.return_value.snapshot_all.return_value = (5, 0)
        action = SecretsAction()
        ctx = ActionContext(targets=["snapshot"], vps="A")
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        mock_sm.return_value.snapshot_all.assert_called_once_with(vps_context="A")

    @patch("orchestrator.secrets.snapshots.SnapshotManager")
    def test_secrets_snapshot_config(self, mock_sm):
        mock_sm.return_value.snapshot_config.return_value = True
        action = SecretsAction()
        ctx = ActionContext(targets=["snapshot-config", "auth_authelia"], vps="A")
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        mock_sm.return_value.snapshot_config.assert_called_once_with("polaris-vps-a", "auth_authelia")

    def test_secrets_snapshot_config_rejects_vps_all(self):
        action = SecretsAction()
        ctx = ActionContext(targets=["snapshot-config", "auth_authelia"], vps="ALL")
        with patch("sys.stderr"):
            res = action.execute(ctx)
            self.assertFalse(res.success)
            self.assertEqual(res.exit_code, 2)
            self.assertIn("does not support --vps ALL", res.message)

    @patch("orchestrator.secrets.snapshots.SnapshotManager")
    def test_secrets_snapshots_list(self, mock_sm):
        mock_sm.return_value.list_snapshots.return_value = [
            {"project": "polaris-vps-a", "config": "auth_authelia", "size": 1024, "timestamp": "2026-08-15"}
        ]
        action = SecretsAction()
        ctx = ActionContext(targets=["snapshots"])
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)

    @patch("orchestrator.actions.secrets.sync_snapshots_to_branch", return_value=(True, "Synced"))
    def test_secrets_sync_branch(self, mock_sync):
        action = SecretsAction()
        ctx = ActionContext(targets=["sync-branch"])
        res = action.execute(ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)

    @patch("orchestrator.actions.secrets.sync_snapshots_to_branch", return_value=(True, "Synced"))
    def test_secrets_sync_branch_flags(self, mock_sync):
        action = SecretsAction()
        ctx = ActionContext(targets=["sync-branch", "--branch", "custom/sync", "--remote", "gitlab", "--base", "master"])
        res = action.execute(ctx)
        self.assertTrue(res.success)
        mock_sync.assert_called_once_with(
            repo_root=unittest.mock.ANY,
            vps_target="all",
            branch="custom/sync",
            remote="gitlab",
            base_branch="master",
        )

    @patch("orchestrator.actions.secrets.sync_snapshots_to_branch", return_value=(True, "Synced"))
    def test_main_cli_vps_all(self, mock_sync):
        code = main(["sync-branch", "--vps", "all"])
        self.assertEqual(code, 0)

    def test_main_cli_missing_vps_value(self):
        with patch("sys.stderr"):
            code = main(["sync-branch", "--vps"])
            self.assertEqual(code, 2)

    def test_main_cli_invalid_vps(self):
        with patch("sys.stderr"):
            code = main(["sync-branch", "--vps", "INVALID"])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
