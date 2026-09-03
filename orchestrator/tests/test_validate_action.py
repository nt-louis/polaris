"""Unit tests for ValidateAction compose and configuration validator."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from orchestrator.actions.validate import ValidateAction, main, validate_caddyfile
from orchestrator.core.models import ActionContext, ServiceMetadata


class TestValidateAction(unittest.TestCase):
    @patch("subprocess.run")
    def test_validate_caddyfile_success(self, mock_run):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            net_dir = tmppath / "Network"
            net_dir.mkdir()
            (net_dir / "Caddyfile").write_text("localhost\n", encoding="utf-8")

            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_run.return_value = mock_proc

            ok, msg = validate_caddyfile(repo_path=tmppath)
            self.assertTrue(ok)
            self.assertEqual(msg, "Caddyfile syntax valid")

    def test_validate_caddyfile_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            ok, msg = validate_caddyfile(repo_path=tmppath)
            self.assertTrue(ok)
            self.assertIn("Skipped", msg)

    @patch("orchestrator.actions.validate.detect_manifest_drift", return_value=(set(), set()))
    @patch("orchestrator.actions.validate.load_services")
    def test_validate_action_success(self, mock_load, mock_drift):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            app_dir = tmppath / "app"
            app_dir.mkdir()
            compose_file = app_dir / "docker-compose.yml"
            compose_file.write_text("services:\n  web:\n    image: nginx\n", encoding="utf-8")

            svc = ServiceMetadata(
                name="testweb",
                rel_dir="app",
                abs_dir=app_dir,
                category="Utilities",
                vps="A",
            )
            mock_load.return_value = [svc]

            action = ValidateAction()
            with patch.object(action, "validate_service_compose", return_value=(True, "Valid compose syntax")), \
                 patch("orchestrator.actions.validate.validate_caddyfile", return_value=(True, "Caddyfile valid")):
                ctx = ActionContext(vps="A", json_output=True)
                res = action.execute(ctx)
                self.assertTrue(res.success)
                self.assertEqual(res.exit_code, 0)

    @patch("orchestrator.actions.validate.detect_manifest_drift", return_value=(set(), set()))
    @patch("orchestrator.actions.validate.load_services")
    def test_validate_action_failure(self, mock_load, mock_drift):
        svc = ServiceMetadata(
            name="broken",
            rel_dir="broken",
            abs_dir=Path("/nonexistent"),
            category="Utilities",
            vps="A",
        )
        mock_load.return_value = [svc]

        action = ValidateAction()
        with patch.object(action, "validate_service_compose", return_value=(False, "Syntax error")), \
             patch("orchestrator.actions.validate.validate_caddyfile", return_value=(True, "Caddyfile valid")):
            ctx = ActionContext(vps="A", json_output=True)
            res = action.execute(ctx)
            self.assertFalse(res.success)
            self.assertEqual(res.exit_code, 1)

    @patch("orchestrator.actions.validate.detect_manifest_drift", return_value=({"Utilities/new-tool"}, set()))
    @patch("orchestrator.actions.validate.load_services", return_value=[])
    def test_validate_manifest_drift_failure(self, mock_load, mock_drift):
        action = ValidateAction()
        with patch("orchestrator.actions.validate.validate_caddyfile", return_value=(True, "OK")):
            ctx = ActionContext(vps="A", fix=False, json_output=True)
            res = action.execute(ctx)
            self.assertFalse(res.success)
            self.assertIn("drift detected", res.message)

    @patch("orchestrator.actions.validate.sync_manifest_with_disk", return_value=(1, 0))
    @patch("orchestrator.actions.validate.detect_manifest_drift", return_value=({"Utilities/new-tool"}, set()))
    @patch("orchestrator.actions.validate.load_services", return_value=[])
    def test_validate_manifest_drift_fix(self, mock_load, mock_drift, mock_sync):
        action = ValidateAction()
        with patch("orchestrator.actions.validate.validate_caddyfile", return_value=(True, "OK")):
            ctx = ActionContext(vps="A", fix=True, json_output=True)
            res = action.execute(ctx)
            self.assertTrue(res.success)
            self.assertIn("auto-synced", res.message)
            mock_sync.assert_called_once()

    def test_main_cli_invalid_vps(self):
        with patch("sys.stderr"):
            code = main(["--vps", "INVALID"])
            self.assertEqual(code, 2)

    def test_main_cli_missing_vps_value(self):
        with patch("sys.stderr"):
            code = main(["--vps"])
            self.assertEqual(code, 2)

    def test_sync_manifest_with_disk_appends_only(self):
        from orchestrator.actions.validate import sync_manifest_with_disk
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            manifest_file = tmppath / "services.yaml"
            manifest_file.write_text(
                "schema_version: 1\n"
                "defaults:\n"
                "  vps: A\n"
                "nodes:\n"
                "  - id: A\n"
                "    name: Node A\n"
                "services:\n"
                "  - name: existing\n"
                "    path: Utilities/existing\n"
                "    category: Utilities\n"
                "    tier: 2\n"
                "    vps: A\n",
                encoding="utf-8",
            )
            with patch("orchestrator.actions.validate.detect_manifest_drift", return_value=({"Media/new-app"}, {"Utilities/orphan"})):
                added, orphaned = sync_manifest_with_disk(manifest_path=manifest_file, repo_root=tmppath)
                self.assertEqual(added, 1)
                self.assertEqual(orphaned, 1)

                import yaml
                with open(manifest_file, "r") as f:
                    data = yaml.safe_load(f)
                service_names = {s["name"] for s in data["services"]}
                self.assertIn("existing", service_names)
                self.assertIn("new-app", service_names)


if __name__ == "__main__":
    unittest.main()
