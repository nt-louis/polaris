"""Unit tests for orchestrator action orchestrators (stop, status, logs, history)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from orchestrator.actions.history import HistoryAction
from orchestrator.actions.logs import LogsAction
from orchestrator.actions.status import StatusAction
from orchestrator.actions.stop import StopAction
from orchestrator.core.models import (
    ActionContext,
    ExecutionResult,
    ServiceMetadata,
    ServiceTier,
)


class TestStopAction(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmppath = Path(self.tmpdir.name)

        # Setup 2 services: gateway and app
        self.gw_dir = self.tmppath / "Media" / "comics" / "gateway"
        self.gw_dir.mkdir(parents=True)
        (self.gw_dir / "docker-compose.yml").write_text("services:\n  gw:\n    image: gw\n", encoding="utf-8")
        self.gw_svc = ServiceMetadata(
            name="gateway",
            rel_dir="Media/comics/gateway",
            abs_dir=self.gw_dir,
            category="Network (Gateways)",
            tier=ServiceTier.GATEWAY,
            vps="A",
        )

        self.app_dir = self.tmppath / "Media" / "comics" / "kavita"
        self.app_dir.mkdir(parents=True)
        (self.app_dir / "docker-compose.yml").write_text("services:\n  kavita:\n    image: kavita\n", encoding="utf-8")
        self.app_svc = ServiceMetadata(
            name="kavita",
            rel_dir="Media/comics/kavita",
            abs_dir=self.app_dir,
            category="Media/comics",
            tier=ServiceTier.STANDARD,
            vps="A",
        )
        self.services = [self.gw_svc, self.app_svc]

    def tearDown(self):
        self.tmpdir.cleanup()

    @patch("orchestrator.actions.stop.load_services")
    def test_stop_targeted_services(self, mock_load_svcs):
        mock_load_svcs.return_value = self.services

        mock_compose = MagicMock()
        mock_compose.ps.return_value = ["kavita-app"]
        mock_compose.stop_by_ids.return_value = ExecutionResult(
            service=self.app_svc,
            action="stop_by_ids",
            success=True,
            exit_code=0,
        )

        action = StopAction(compose_engine=mock_compose)
        ctx = ActionContext(targets=["kavita"], yes=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        mock_compose.stop_by_ids.assert_called_once_with(self.app_svc, ["kavita-app"])

    @patch("orchestrator.actions.stop.load_services")
    def test_stop_unresolved_targets_fails(self, mock_load_svcs):
        mock_load_svcs.return_value = self.services
        action = StopAction()
        ctx = ActionContext(targets=["nonexistent-app"], yes=True)
        res = action.execute(ctx)
        self.assertFalse(res.success)
        self.assertEqual(res.exit_code, 1)

    @patch("orchestrator.actions.stop.load_services")
    def test_stop_dry_run(self, mock_load_svcs):
        mock_load_svcs.return_value = self.services
        mock_compose = MagicMock()
        mock_compose.ps.return_value = ["kavita-app"]

        action = StopAction(compose_engine=mock_compose)
        ctx = ActionContext(targets=["kavita"], dry_run=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        mock_compose.stop_by_ids.assert_not_called()

    @patch("orchestrator.actions.stop.load_services")
    def test_stop_confirmation_declined(self, mock_load_svcs):
        mock_load_svcs.return_value = self.services
        mock_compose = MagicMock()
        mock_compose.ps.return_value = ["kavita-app"]

        action = StopAction(compose_engine=mock_compose)
        with patch("orchestrator.ui.prompts.confirm_action", return_value=False):
            ctx = ActionContext(targets=["kavita"], yes=False)
            res = action.execute(ctx)
            self.assertFalse(res.success)
            self.assertEqual(res.exit_code, 1)
            mock_compose.stop_by_ids.assert_not_called()

    @patch("orchestrator.ui.dashboard.run_tui")
    @patch("orchestrator.actions.stop.load_services")
    def test_stop_interactive_selection(self, mock_load_svcs, mock_run_tui):
        mock_load_svcs.return_value = self.services
        mock_run_tui.return_value = [self.app_svc]

        mock_compose = MagicMock()
        mock_compose.ps.return_value = ["kavita-app"]
        mock_compose.stop_by_ids.return_value = ExecutionResult(
            service=self.app_svc,
            action="stop_by_ids",
            success=True,
            exit_code=0,
        )

        action = StopAction(compose_engine=mock_compose)
        ctx = ActionContext(interactive=True, yes=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        mock_run_tui.assert_called_once()
        mock_compose.stop_by_ids.assert_called_once_with(self.app_svc, ["kavita-app"])

    @patch("orchestrator.ui.dashboard.run_tui")
    @patch("orchestrator.actions.stop.load_services")
    def test_stop_interactive_dry_run_selection(self, mock_load_svcs, mock_run_tui):
        mock_load_svcs.return_value = self.services
        mock_run_tui.return_value = [self.app_svc]

        mock_compose = MagicMock()
        mock_compose.ps.return_value = ["kavita-app"]

        action = StopAction(compose_engine=mock_compose)
        ctx = ActionContext(interactive=True, dry_run=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        self.assertIn("1 active services would be stopped", res.message)
        mock_run_tui.assert_called_once()
        mock_compose.stop_by_ids.assert_not_called()

    @patch("orchestrator.actions.stop.load_services")
    def test_stop_multiple_gateways_with_same_name_no_collision(self, mock_load_svcs):
        """Ensure multiple distinct services named 'gateway' in different directories both stop on the first run."""
        gw1_dir = self.tmppath / "Media" / "stremio" / "addons" / "gateway"
        gw1_dir.mkdir(parents=True, exist_ok=True)
        (gw1_dir / "docker-compose.yml").write_text("services:\n  gw1:\n    image: gw\n", encoding="utf-8")
        gw1_svc = ServiceMetadata(
            name="gateway",
            rel_dir="Media/stremio/addons/gateway",
            abs_dir=gw1_dir,
            category="Network (Gateways)",
            tier=ServiceTier.GATEWAY,
            vps="B",
        )

        gw2_dir = self.tmppath / "Media" / "stremio" / "utilities" / "gateway"
        gw2_dir.mkdir(parents=True, exist_ok=True)
        (gw2_dir / "docker-compose.yml").write_text("services:\n  gw2:\n    image: gw\n", encoding="utf-8")
        gw2_svc = ServiceMetadata(
            name="gateway",
            rel_dir="Media/stremio/utilities/gateway",
            abs_dir=gw2_dir,
            category="Network (Gateways)",
            tier=ServiceTier.GATEWAY,
            vps="B",
        )

        mock_load_svcs.return_value = [gw1_svc, gw2_svc]

        mock_compose = MagicMock()
        def mock_ps(svc):
            if svc.rel_dir == gw1_svc.rel_dir:
                return ["cid-addons-gw"]
            if svc.rel_dir == gw2_svc.rel_dir:
                return ["cid-utils-gw"]
            return []

        mock_compose.ps.side_effect = mock_ps
        mock_compose.stop_by_ids.return_value = ExecutionResult(
            service=None,
            action="stop_by_ids",
            success=True,
            exit_code=0,
        )

        action = StopAction(compose_engine=mock_compose)
        ctx = ActionContext(vps="B", yes=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        self.assertEqual(mock_compose.stop_by_ids.call_count, 2)
        mock_compose.stop_by_ids.assert_any_call(gw1_svc, ["cid-addons-gw"])
        mock_compose.stop_by_ids.assert_any_call(gw2_svc, ["cid-utils-gw"])



class TestStatusAction(unittest.TestCase):
    @patch("orchestrator.actions.status.load_services")
    def test_status_json_output(self, mock_load_svcs):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            app_dir = tmppath / "app"
            app_dir.mkdir()
            (app_dir / "docker-compose.yml").write_text("services:\n  app:\n    image: test\n", encoding="utf-8")
            svc = ServiceMetadata(
                name="testapp",
                rel_dir="app",
                abs_dir=app_dir,
                category="Utilities",
                vps="A",
            )
            mock_load_svcs.return_value = [svc]

            action = StatusAction()
            with patch.object(action, "get_docker_containers", return_value=[
                {"Names": "testapp", "State": "running", "Status": "Up 2 hours", "Ports": "80/tcp", "Labels": ""}
            ]):
                ctx = ActionContext(json_output=True)
                res = action.execute(ctx)
                self.assertTrue(res.success)
                data = json.loads(res.message)
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["project"], "testapp")
                self.assertEqual(data[0]["status"], "Up 2 hours")

    @patch("orchestrator.actions.status.get_active_vps", return_value="A")
    @patch("orchestrator.actions.status.load_services")
    def test_status_filters_by_active_vps_default(self, mock_load_svcs, mock_active_vps):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            app_a = tmppath / "app_a"
            app_a.mkdir()
            (app_a / "docker-compose.yml").write_text("services:\n  a:\n    image: a\n", encoding="utf-8")
            app_b = tmppath / "app_b"
            app_b.mkdir()
            (app_b / "docker-compose.yml").write_text("services:\n  b:\n    image: b\n", encoding="utf-8")

            svcs = [
                ServiceMetadata(name="svca", rel_dir="app_a", abs_dir=app_a, category="Utilities", vps="A"),
                ServiceMetadata(name="svcb", rel_dir="app_b", abs_dir=app_b, category="Utilities", vps="B"),
            ]
            mock_load_svcs.return_value = svcs

            action = StatusAction()
            with patch.object(action, "get_docker_containers", return_value=[]):
                # When context.vps is None, defaults to active VPS ('A')
                ctx = ActionContext(json_output=True)
                res = action.execute(ctx)
                self.assertTrue(res.success)
                data = json.loads(res.message)
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["project"], "svca")

                # When context.vps is 'ALL', shows all nodes
                ctx_all = ActionContext(vps="ALL", json_output=True)
                res_all = action.execute(ctx_all)
                self.assertTrue(res_all.success)
                data_all = json.loads(res_all.message)
                self.assertEqual(len(data_all), 2)

    @patch("orchestrator.actions.status.get_active_vps", return_value="A")
    @patch("orchestrator.actions.status.load_services")
    def test_status_filters_by_query_state_category(self, mock_load_svcs, mock_active_vps):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            app_a = tmppath / "jellyfin"
            app_a.mkdir()
            (app_a / "docker-compose.yml").write_text("services:\n  jellyfin:\n    image: jellyfin\n", encoding="utf-8")
            app_b = tmppath / "dockhand"
            app_b.mkdir()
            (app_b / "docker-compose.yml").write_text("services:\n  dockhand:\n    image: dockhand\n", encoding="utf-8")

            svcs = [
                ServiceMetadata(name="jellyfin", rel_dir="jellyfin", abs_dir=app_a, category="Media", vps="A"),
                ServiceMetadata(name="dockhand", rel_dir="dockhand", abs_dir=app_b, category="Utilities", vps="A"),
            ]
            mock_load_svcs.return_value = svcs

            action = StatusAction()
            with patch.object(action, "get_docker_containers", return_value=[
                {"Names": "jellyfin", "State": "running", "Status": "Up 2 hours (healthy)", "Ports": "8096/tcp", "Labels": ""},
                {"Names": "dockhand", "State": "exited", "Status": "Stopped", "Ports": "", "Labels": ""},
            ]):
                # Test query filter
                ctx_q = ActionContext(query="jelly", json_output=True)
                res_q = action.execute(ctx_q)
                data_q = json.loads(res_q.message)
                self.assertEqual(len(data_q), 1)
                self.assertEqual(data_q[0]["project"], "jellyfin")

                # Test state filter
                ctx_st = ActionContext(state="healthy", json_output=True)
                res_st = action.execute(ctx_st)
                data_st = json.loads(res_st.message)
                self.assertEqual(len(data_st), 1)
                self.assertEqual(data_st[0]["project"], "jellyfin")

                ctx_stopped = ActionContext(state="stopped", json_output=True)
                res_stopped = action.execute(ctx_stopped)
                data_stopped = json.loads(res_stopped.message)
                self.assertEqual(len(data_stopped), 1)
                self.assertEqual(data_stopped[0]["project"], "dockhand")

                # Test category filter
                ctx_cat = ActionContext(category="Utilities", json_output=True)
                res_cat = action.execute(ctx_cat)
                data_cat = json.loads(res_cat.message)
                self.assertEqual(len(data_cat), 1)
                self.assertEqual(data_cat[0]["project"], "dockhand")


class TestLogsAction(unittest.TestCase):
    @patch("orchestrator.actions.logs.load_services")
    @patch("orchestrator.actions.logs.stream_logs", return_value=0)
    @patch("orchestrator.actions.logs.resolve_container", return_value="jellyfin-app")
    def test_logs_stream(self, mock_resolve, mock_stream, mock_load_svcs):
        mock_load_svcs.return_value = []
        action = LogsAction()
        ctx = ActionContext(targets=["jellyfin"], tail=50, follow=True)
        res = action.execute(ctx)
        self.assertTrue(res.success)
        mock_resolve.assert_called_once()
        mock_stream.assert_called_once_with(container_name="jellyfin-app", tail=50, follow=True)

    def test_logs_missing_target(self):
        action = LogsAction()
        ctx = ActionContext(targets=[])
        res = action.execute(ctx)
        self.assertFalse(res.success)
        self.assertEqual(res.exit_code, 1)


class TestHistoryAction(unittest.TestCase):
    @patch("orchestrator.actions.history.load_action_history")
    def test_history_json_output(self, mock_load):
        mock_load.return_value = [
            {"timestamp": "2026-08-19T07:00:00Z", "action": "STOP", "vps": "A", "status": "SUCCESS", "exit_code": 0, "duration_sec": 1.2}
        ]
        action = HistoryAction()
        ctx = ActionContext(json_output=True)
        res = action.execute(ctx)
        self.assertTrue(res.success)
        data = json.loads(res.message)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["action"], "STOP")


class TestDeployAction(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmppath = Path(self.tmpdir.name)

        self.gw_dir = self.tmppath / "Media" / "comics" / "gateway"
        self.gw_dir.mkdir(parents=True)
        (self.gw_dir / "docker-compose.yml").write_text("services:\n  gw:\n    image: gw\n", encoding="utf-8")
        self.gw_svc = ServiceMetadata(
            name="gateway",
            rel_dir="Media/comics/gateway",
            abs_dir=self.gw_dir,
            category="Network (Gateways)",
            tier=ServiceTier.GATEWAY,
            vps="A",
        )

        self.app_dir = self.tmppath / "Media" / "comics" / "kavita"
        self.app_dir.mkdir(parents=True)
        (self.app_dir / "docker-compose.yml").write_text("services:\n  kavita:\n    image: kavita\n", encoding="utf-8")
        self.app_svc = ServiceMetadata(
            name="kavita",
            rel_dir="Media/comics/kavita",
            abs_dir=self.app_dir,
            category="Media/comics",
            tier=ServiceTier.STANDARD,
            vps="A",
        )
        self.services = [self.gw_svc, self.app_svc]

    def tearDown(self):
        self.tmpdir.cleanup()

    @patch("orchestrator.actions.deploy.wait_for_gluetun_ready", return_value=True)
    @patch("orchestrator.actions.deploy.load_services")
    def test_deploy_targeted_services(self, mock_load_svcs, mock_wait):
        mock_load_svcs.return_value = self.services

        mock_compose = MagicMock()
        mock_compose.compose_up.return_value = ExecutionResult(
            service=self.app_svc,
            action="compose_up",
            success=True,
            exit_code=0,
        )

        mock_doppler = MagicMock()
        mock_doppler.is_authenticated.return_value = False

        from orchestrator.actions.deploy import DeployAction
        action = DeployAction(compose_engine=mock_compose, doppler_client=mock_doppler)
        ctx = ActionContext(targets=["kavita"], vps="A", yes=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        mock_compose.compose_up.assert_called_once()

    @patch("orchestrator.actions.deploy.load_services")
    def test_deploy_dry_run(self, mock_load_svcs):
        mock_load_svcs.return_value = self.services
        mock_compose = MagicMock()

        from orchestrator.actions.deploy import DeployAction
        action = DeployAction(compose_engine=mock_compose)
        ctx = ActionContext(targets=["kavita"], vps="A", dry_run=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        mock_compose.compose_up.assert_not_called()

    @patch("orchestrator.actions.deploy.load_services")
    def test_deploy_last_selection(self, mock_load_svcs):
        mock_load_svcs.return_value = self.services
        mock_compose = MagicMock()
        mock_compose.compose_up.return_value = ExecutionResult(
            service=self.app_svc,
            action="compose_up",
            success=True,
            exit_code=0,
        )

        from orchestrator.actions.deploy import DeployAction
        from orchestrator.core.state import save_last_deploy_services

        with patch("orchestrator.core.state.REPO_ROOT", self.tmppath):
            save_last_deploy_services([self.app_svc], vps="A")

            action = DeployAction(compose_engine=mock_compose)
            ctx = ActionContext(last=True, vps="A", yes=True)
            res = action.execute(ctx)
            self.assertTrue(res.success)
            mock_compose.compose_up.assert_called_once()

    @patch("orchestrator.actions.deploy.wait_for_gluetun_ready", return_value=True)
    @patch("orchestrator.ui.dashboard.run_tui")
    @patch("orchestrator.actions.deploy.load_services")
    def test_deploy_interactive_selection(self, mock_load_svcs, mock_run_tui, mock_wait):
        mock_load_svcs.return_value = self.services
        mock_run_tui.return_value = [self.app_svc]

        mock_compose = MagicMock()
        mock_compose.compose_up.return_value = ExecutionResult(
            service=self.app_svc,
            action="compose_up",
            success=True,
            exit_code=0,
        )

        from orchestrator.actions.deploy import DeployAction
        action = DeployAction(compose_engine=mock_compose)
        ctx = ActionContext(interactive=True, vps="A", yes=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        mock_run_tui.assert_called_once()
        mock_compose.compose_up.assert_called_once()

    @patch("orchestrator.actions.deploy.load_services")
    def test_deploy_with_pull_flag(self, mock_load_svcs):
        mock_load_svcs.return_value = self.services
        mock_compose = MagicMock()
        mock_compose.compose_up.return_value = ExecutionResult(
            service=self.app_svc,
            action="compose_up",
            success=True,
            exit_code=0,
        )

        from orchestrator.actions.deploy import DeployAction
        action = DeployAction(compose_engine=mock_compose)
        ctx = ActionContext(targets=["kavita"], vps="A", pull=True, yes=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        mock_compose.compose_up.assert_called_once()
        self.assertTrue(mock_compose.compose_up.call_args.kwargs.get("pull"))

    @patch("orchestrator.actions.deploy.load_services")
    def test_deploy_local_build_with_pull_flag_skips_pull(self, mock_load_svcs):
        mono_dir = self.tmppath / "Media" / "local-media" / "players" / "monochrome"
        mono_dir.mkdir(parents=True)
        (mono_dir / "docker-compose.yml").write_text("services:\n  monochrome:\n    image: local/monochrome:latest\n", encoding="utf-8")
        mono_svc = ServiceMetadata(
            name="monochrome",
            rel_dir="Media/local-media/players/monochrome",
            abs_dir=mono_dir,
            category="Media/local-media (Players)",
            tier=ServiceTier.STANDARD,
            vps="A",
            is_build_heavy=True,
        )
        mock_load_svcs.return_value = [mono_svc]
        mock_compose = MagicMock()
        mock_compose.compose_up.return_value = ExecutionResult(
            service=mono_svc,
            action="compose_up",
            success=True,
            exit_code=0,
        )
        mock_docker = MagicMock()
        mock_docker.image_exists.return_value = True

        from orchestrator.actions.deploy import DeployAction
        action = DeployAction(compose_engine=mock_compose, docker_client=mock_docker)
        ctx = ActionContext(targets=["monochrome"], vps="A", pull=True, yes=True)
        res = action.execute(ctx)

        self.assertTrue(res.success)
        mock_compose.compose_up.assert_called_once()
        self.assertFalse(mock_compose.compose_up.call_args.kwargs.get("pull"))

    @patch("orchestrator.actions.deploy.load_services")
    def test_deploy_service_failure_continues_remaining_services(self, mock_load_svcs):
        app2_dir = self.tmppath / "Media" / "comics" / "suwayomi"
        app2_dir.mkdir(parents=True)
        (app2_dir / "docker-compose.yml").write_text("services:\n  suwayomi:\n    image: suwayomi\n", encoding="utf-8")
        app2_svc = ServiceMetadata(
            name="suwayomi",
            rel_dir="Media/comics/suwayomi",
            abs_dir=app2_dir,
            category="Media/comics",
            tier=ServiceTier.STANDARD,
            vps="A",
        )
        mock_load_svcs.return_value = [self.app_svc, app2_svc]
        mock_compose = MagicMock()
        mock_compose.compose_up.side_effect = [
            ExecutionResult(service=self.app_svc, action="compose_up", success=False, exit_code=1, message="Error on kavita"),
            ExecutionResult(service=app2_svc, action="compose_up", success=True, exit_code=0, message="OK"),
        ]

        from orchestrator.actions.deploy import DeployAction
        action = DeployAction(compose_engine=mock_compose)
        ctx = ActionContext(targets=["kavita", "suwayomi"], vps="A", yes=True)
        res = action.execute(ctx)

        self.assertFalse(res.success)
        self.assertEqual(mock_compose.compose_up.call_count, 2)
        self.assertIn("Error on kavita", res.message)

    @patch("orchestrator.actions.deploy.load_services")
    def test_deploy_gateway_failure_aborts_remaining_services(self, mock_load_svcs):
        mock_load_svcs.return_value = [self.gw_svc, self.app_svc]
        mock_compose = MagicMock()
        mock_compose.compose_up.return_value = ExecutionResult(
            service=self.gw_svc,
            action="compose_up",
            success=False,
            exit_code=1,
            message="Gateway failed to start",
        )

        from orchestrator.actions.deploy import DeployAction
        action = DeployAction(compose_engine=mock_compose)
        ctx = ActionContext(targets=["gateway", "kavita"], vps="A", yes=True)
        res = action.execute(ctx)

        self.assertFalse(res.success)
        mock_compose.compose_up.assert_called_once()
        self.assertIn("Gateway failed to start", res.message)


class TestRedeployAction(unittest.TestCase):
    @patch("orchestrator.actions.deploy.load_services")
    @patch("orchestrator.actions.redeploy.load_services")
    def test_redeploy_targeted(self, mock_redeploy_svcs, mock_deploy_svcs):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            app_dir = tmppath / "app"
            app_dir.mkdir()
            (app_dir / "docker-compose.yml").write_text("services:\n  app:\n    image: test\n", encoding="utf-8")
            svc = ServiceMetadata(
                name="testapp",
                rel_dir="app",
                abs_dir=app_dir,
                category="Utilities",
                vps="A",
            )
            mock_redeploy_svcs.return_value = [svc]
            mock_deploy_svcs.return_value = [svc]

            mock_compose = MagicMock()
            mock_compose.compose_up.return_value = ExecutionResult(
                service=svc,
                action="compose_up",
                success=True,
                exit_code=0,
            )

            from orchestrator.actions.redeploy import RedeployAction
            action = RedeployAction(compose_engine=mock_compose)
            ctx = ActionContext(targets=["testapp"], vps="A", yes=True)
            res = action.execute(ctx)

            self.assertTrue(res.success)
            self.assertTrue(bool(res))
            mock_compose.compose_up.assert_called_once()

    @patch("orchestrator.actions.deploy.load_services")
    @patch("orchestrator.actions.redeploy.load_services")
    def test_redeploy_with_pull_flag(self, mock_redeploy_svcs, mock_deploy_svcs):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            app_dir = tmppath / "app"
            app_dir.mkdir()
            (app_dir / "docker-compose.yml").write_text("services:\n  app:\n    image: test\n", encoding="utf-8")
            svc = ServiceMetadata(
                name="testapp",
                rel_dir="app",
                abs_dir=app_dir,
                category="Utilities",
                vps="A",
            )
            mock_redeploy_svcs.return_value = [svc]
            mock_deploy_svcs.return_value = [svc]

            mock_compose = MagicMock()
            mock_compose.compose_up.return_value = ExecutionResult(
                service=svc,
                action="compose_up",
                success=True,
                exit_code=0,
            )

            from orchestrator.actions.redeploy import RedeployAction
            action = RedeployAction(compose_engine=mock_compose)
            ctx = ActionContext(targets=["testapp"], vps="A", pull=True, yes=True)
            res = action.execute(ctx)

            self.assertTrue(res.success)
            mock_compose.compose_up.assert_called_once()
            self.assertTrue(mock_compose.compose_up.call_args.kwargs.get("pull"))

    @patch("orchestrator.actions.deploy.load_services")
    @patch("orchestrator.actions.redeploy.load_services")
    def test_redeploy_local_build_with_pull_flag_skips_pull(self, mock_redeploy_svcs, mock_deploy_svcs):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            app_dir = tmppath / "Media" / "local-media" / "players" / "monochrome"
            app_dir.mkdir(parents=True)
            (app_dir / "docker-compose.yml").write_text("services:\n  monochrome:\n    image: local/monochrome:latest\n", encoding="utf-8")
            svc = ServiceMetadata(
                name="monochrome",
                rel_dir="Media/local-media/players/monochrome",
                abs_dir=app_dir,
                category="Media/local-media (Players)",
                tier=ServiceTier.STANDARD,
                vps="A",
                is_build_heavy=True,
            )
            mock_redeploy_svcs.return_value = [svc]
            mock_deploy_svcs.return_value = [svc]

            mock_compose = MagicMock()
            mock_compose.compose_up.return_value = ExecutionResult(
                service=svc,
                action="compose_up",
                success=True,
                exit_code=0,
            )

            mock_docker = MagicMock()
            mock_docker.image_exists.return_value = True

            from orchestrator.actions.redeploy import RedeployAction
            action = RedeployAction(compose_engine=mock_compose, docker_client=mock_docker)
            ctx = ActionContext(targets=["monochrome"], vps="A", pull=True, yes=True)
            res = action.execute(ctx)

            self.assertTrue(res.success)
            mock_compose.compose_up.assert_called_once()
            self.assertFalse(mock_compose.compose_up.call_args.kwargs.get("pull"))

    @patch("orchestrator.actions.deploy.load_services")
    @patch("orchestrator.actions.redeploy.load_services")
    def test_redeploy_service_failure_continues_remaining_services(self, mock_redeploy_svcs, mock_deploy_svcs):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            app1_dir = tmppath / "app1"
            app1_dir.mkdir()
            (app1_dir / "docker-compose.yml").write_text("services:\n  app1:\n    image: test1\n", encoding="utf-8")
            svc1 = ServiceMetadata(name="app1", rel_dir="app1", abs_dir=app1_dir, category="Utilities", vps="A")

            app2_dir = tmppath / "app2"
            app2_dir.mkdir()
            (app2_dir / "docker-compose.yml").write_text("services:\n  app2:\n    image: test2\n", encoding="utf-8")
            svc2 = ServiceMetadata(name="app2", rel_dir="app2", abs_dir=app2_dir, category="Utilities", vps="A")

            mock_redeploy_svcs.return_value = [svc1, svc2]
            mock_deploy_svcs.return_value = [svc1, svc2]

            mock_compose = MagicMock()
            mock_compose.compose_up.side_effect = [
                ExecutionResult(service=svc1, action="compose_up", success=False, exit_code=1, message="Failed app1"),
                ExecutionResult(service=svc2, action="compose_up", success=True, exit_code=0, message="OK"),
            ]

            from orchestrator.actions.redeploy import RedeployAction
            action = RedeployAction(compose_engine=mock_compose)
            ctx = ActionContext(targets=["app1", "app2"], vps="A", yes=True)
            res = action.execute(ctx)

            self.assertFalse(res.success)
            self.assertEqual(mock_compose.compose_up.call_count, 2)
            self.assertIn("Failed app1", res.message)

    @patch("orchestrator.actions.deploy.load_services")
    @patch("orchestrator.actions.redeploy.load_services")
    def test_redeploy_with_resume_from_file(self, mock_redeploy_svcs, mock_deploy_svcs):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            app_dir = tmppath / "app"
            app_dir.mkdir()
            (app_dir / "docker-compose.yml").write_text("services:\n  app:\n    image: test\n", encoding="utf-8")
            svc = ServiceMetadata(
                name="testapp",
                rel_dir="app",
                abs_dir=app_dir,
                category="Utilities",
                vps="A",
            )
            mock_redeploy_svcs.return_value = [svc]
            mock_deploy_svcs.return_value = [svc]

            resume_file = tmppath / "active_projects.txt"
            resume_file.write_text("app\n# comment line\n\n", encoding="utf-8")

            mock_compose = MagicMock()
            mock_compose.compose_up.return_value = ExecutionResult(
                service=svc,
                action="compose_up",
                success=True,
                exit_code=0,
            )

            from orchestrator.actions.redeploy import RedeployAction
            action = RedeployAction(compose_engine=mock_compose)
            ctx = ActionContext(resume_from=str(resume_file), vps="A", yes=True)
            res = action.execute(ctx)

            self.assertTrue(res.success)
            mock_compose.compose_up.assert_called_once()

    @patch("orchestrator.ui.dashboard.run_tui")
    @patch("orchestrator.actions.deploy.load_services")
    @patch("orchestrator.actions.redeploy.load_services")
    def test_redeploy_interactive_selection(self, mock_redeploy_svcs, mock_deploy_svcs, mock_run_tui):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            app_dir = tmppath / "app"
            app_dir.mkdir()
            (app_dir / "docker-compose.yml").write_text("services:\n  app:\n    image: test\n", encoding="utf-8")
            svc = ServiceMetadata(
                name="testapp",
                rel_dir="app",
                abs_dir=app_dir,
                category="Utilities",
                vps="A",
            )
            mock_redeploy_svcs.return_value = [svc]
            mock_deploy_svcs.return_value = [svc]
            mock_run_tui.return_value = [svc]

            mock_compose = MagicMock()
            mock_compose.is_project_active.return_value = True
            mock_compose.compose_up.return_value = ExecutionResult(
                service=svc,
                action="compose_up",
                success=True,
                exit_code=0,
            )

            from orchestrator.actions.redeploy import RedeployAction
            action = RedeployAction(compose_engine=mock_compose)
            ctx = ActionContext(interactive=True, vps="A", yes=True)
            res = action.execute(ctx)

            self.assertTrue(res.success)
            mock_run_tui.assert_called_once()
            mock_compose.compose_up.assert_called_once()

    @patch("orchestrator.actions.deploy.load_services")
    @patch("orchestrator.actions.redeploy.load_services")
    def test_redeploy_with_resume_from_non_interactive_without_yes_succeeds(self, mock_redeploy_svcs, mock_deploy_svcs):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            app_dir = tmppath / "app"
            app_dir.mkdir()
            (app_dir / "docker-compose.yml").write_text("services:\n  app:\n    image: test\n", encoding="utf-8")
            svc = ServiceMetadata(
                name="testapp",
                rel_dir="app",
                abs_dir=app_dir,
                category="Utilities",
                vps="A",
            )
            mock_redeploy_svcs.return_value = [svc]
            mock_deploy_svcs.return_value = [svc]

            resume_file = tmppath / "active_projects.txt"
            resume_file.write_text("app\n", encoding="utf-8")

            mock_compose = MagicMock()
            mock_compose.compose_up.return_value = ExecutionResult(
                service=svc,
                action="compose_up",
                success=True,
                exit_code=0,
            )

            from orchestrator.actions.redeploy import RedeployAction
            action = RedeployAction(compose_engine=mock_compose)
            ctx = ActionContext(resume_from=str(resume_file), vps="A", yes=False)

            with patch("sys.stdin.isatty", return_value=False):
                res = action.execute(ctx)
                self.assertTrue(res.success)
                mock_compose.compose_up.assert_called_once()

    @patch("orchestrator.actions.deploy.load_services")
    @patch("orchestrator.actions.redeploy.load_services")
    def test_targeted_redeploy_non_interactive_without_yes_blocked(self, mock_redeploy_svcs, mock_deploy_svcs):
        svc = ServiceMetadata(
            name="testapp",
            rel_dir="app",
            abs_dir=Path("/dummy/app"),
            category="Utilities",
            vps="A",
        )
        mock_redeploy_svcs.return_value = [svc]
        mock_deploy_svcs.return_value = [svc]

        from orchestrator.actions.redeploy import RedeployAction
        action = RedeployAction(compose_engine=MagicMock())
        ctx = ActionContext(targets=["testapp"], vps="A", yes=False)

        with patch("sys.stdin.isatty", return_value=False):
            res = action.execute(ctx)
            self.assertFalse(res.success)
            self.assertFalse(bool(res))
            self.assertEqual(res.exit_code, 1)


class TestDependencyReportAction(unittest.TestCase):
    @patch("orchestrator.actions.dependency_report.load_services")
    def test_dependency_report_generation(self, mock_load_svcs):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            app_dir = tmppath / "app"
            app_dir.mkdir()
            (app_dir / "docker-compose.yml").write_text(
                "services:\n"
                "  web:\n"
                "    image: nginx:1.25.0\n",
                encoding="utf-8",
            )
            svc = ServiceMetadata(
                name="web",
                rel_dir="app",
                abs_dir=app_dir,
                category="Utilities",
                vps="A",
            )
            mock_load_svcs.return_value = [svc]

            from datetime import datetime, timezone

            from orchestrator.actions.dependency_report import DependencyReportAction
            action = DependencyReportAction()
            with patch("orchestrator.actions.dependency_report.REPO_ROOT", tmppath), \
                 patch("orchestrator.actions.dependency_report.get_remote_tags", return_value=["1.25.0", "1.25.1", "1.26.0"]), \
                 patch("orchestrator.actions.dependency_report.get_tag_release_age", return_value=(datetime.now(timezone.utc), 10.0)):
                res = action.execute(ActionContext())
                self.assertTrue(res.success)
                self.assertTrue(bool(res))
                self.assertIn("Container Dependency & Vulnerability Assessment", res.message)
                self.assertTrue((tmppath / "dependency-report.md").is_file())


if __name__ == "__main__":
    unittest.main()
