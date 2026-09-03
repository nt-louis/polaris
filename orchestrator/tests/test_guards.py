"""Unit tests for branch protection guard mechanisms."""

import unittest
from unittest.mock import patch

from orchestrator.actions.base import BaseAction
from orchestrator.core.guards import (
    is_main_branch,
    verify_branch_guard,
)
from orchestrator.core.models import ActionContext, ExecutionResult


class DummyMutatingAction(BaseAction):
    action_name = "dummy_mutating"
    is_mutating = True

    def run(self, context: ActionContext) -> ExecutionResult:
        return ExecutionResult(service=None, action=self.action_name, success=True, exit_code=0)


class DummySafeAction(BaseAction):
    action_name = "dummy_safe"
    is_mutating = False

    def run(self, context: ActionContext) -> ExecutionResult:
        return ExecutionResult(service=None, action=self.action_name, success=True, exit_code=0)


class TestBranchGuard(unittest.TestCase):
    @patch("orchestrator.core.guards.get_current_git_branch", return_value="main")
    def test_on_main_branch_allowed(self, mock_branch):
        self.assertTrue(is_main_branch())
        ctx = ActionContext()
        res = verify_branch_guard("deploy", ctx, force_check=True)
        self.assertIsNone(res)

    @patch("orchestrator.core.guards.get_current_git_branch", return_value="feat/my-feature")
    def test_on_dev_branch_blocked_by_default(self, mock_branch):
        self.assertFalse(is_main_branch())
        ctx = ActionContext(allow_dev=False)
        with patch.dict("os.environ", {}, clear=True):
            res = verify_branch_guard("deploy", ctx, force_check=True)
            self.assertIsNotNone(res)
            self.assertFalse(res.success)
            self.assertEqual(res.exit_code, 1)
            self.assertIn("restricted to the 'main' branch", res.message)

    @patch("orchestrator.core.guards.get_current_git_branch", return_value="feat/my-feature")
    def test_on_dev_branch_with_allow_dev_flag(self, mock_branch):
        ctx = ActionContext(allow_dev=True)
        res = verify_branch_guard("deploy", ctx, force_check=True)
        self.assertIsNone(res)

    @patch("orchestrator.core.guards.get_current_git_branch", return_value="feat/my-feature")
    def test_on_dev_branch_with_env_var(self, mock_branch):
        ctx = ActionContext(allow_dev=False)
        with patch.dict("os.environ", {"NET_STREAM_ALLOW_DEV": "1"}):
            res = verify_branch_guard("deploy", ctx, force_check=True)
            self.assertIsNone(res)

    @patch("orchestrator.core.guards.get_current_git_branch", return_value="feat/my-feature")
    def test_dry_run_always_allowed_on_dev_branch(self, mock_branch):
        ctx = ActionContext(dry_run=True, allow_dev=False)
        res = verify_branch_guard("deploy", ctx, force_check=True)
        self.assertIsNone(res)

    @patch("orchestrator.core.guards.get_current_git_branch", return_value="feat/my-feature")
    def test_base_action_blocks_mutating_on_dev_branch(self, mock_branch):
        action = DummyMutatingAction()
        with patch("orchestrator.core.guards.is_test_environment", return_value=False):
            with patch.dict("os.environ", {}, clear=True):
                res = action.execute(ActionContext(allow_dev=False))
                self.assertFalse(res.success)
                self.assertIn("restricted to the 'main' branch", res.message)

    @patch("orchestrator.core.guards.get_current_git_branch", return_value="feat/my-feature")
    def test_base_action_allows_safe_action_on_dev_branch(self, mock_branch):
        action = DummySafeAction()
        with patch("orchestrator.core.guards.is_test_environment", return_value=False):
            with patch.dict("os.environ", {}, clear=True):
                res = action.execute(ActionContext(allow_dev=False))
                self.assertTrue(res.success)


if __name__ == "__main__":
    unittest.main()
