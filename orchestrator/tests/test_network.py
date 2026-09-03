"""Unit tests for NetworkDAG topological sorting, real compose edge parsing, and routing repairs."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from orchestrator.core.models import (
    ContainerStatus,
    ExecutionResult,
    ServiceMetadata,
    ServiceTier,
)
from orchestrator.network.graph import CyclicDependencyError, NetworkDAG
from orchestrator.network.routing import apply_routing_fix, reset_tailscale_state


class TestNetworkDAG(unittest.TestCase):
    """Test sidecar network dependency extraction from Compose files and topological sequencing."""

    def test_dependency_extraction_and_topological_sort_with_real_compose(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Gateway project
            gw_dir = tmppath / "Media" / "comics" / "gateway"
            gw_dir.mkdir(parents=True)
            (gw_dir / "docker-compose.yml").write_text(
                "services:\n"
                "  gluetun:\n"
                "    container_name: media-comics-gluetun\n"
                "    image: qmcgaw/gluetun\n"
                "  tailscale:\n"
                "    container_name: media-comics-tailscale\n"
                "    network_mode: service:gluetun\n",
                encoding="utf-8",
            )
            gw_svc = ServiceMetadata(
                name="gateway",
                rel_dir="Media/comics/gateway",
                abs_dir=gw_dir,
                category="Network (Gateways)",
                vps="A",
                tier=ServiceTier.GATEWAY,
                custom_project_name="media-comics-gateway",
            )

            # Dependent App 1 (network_mode: container:media-comics-gluetun)
            app1_dir = tmppath / "Media" / "comics" / "athenaeum"
            app1_dir.mkdir(parents=True)
            (app1_dir / "docker-compose.yml").write_text(
                "services:\n"
                "  athenaeum:\n"
                "    container_name: athenaeum\n"
                "    network_mode: container:media-comics-gluetun\n",
                encoding="utf-8",
            )
            app1_svc = ServiceMetadata(
                name="athenaeum",
                rel_dir="Media/comics/athenaeum",
                abs_dir=app1_dir,
                category="Media/comics",
                vps="A",
                tier=ServiceTier.STANDARD,
            )

            # Dependent App 2 (External network dependency vps_b_net)
            gw_b_dir = tmppath / "Utilities" / "gateway-b"
            gw_b_dir.mkdir(parents=True)
            (gw_b_dir / "docker-compose.yml").write_text(
                "services:\n"
                "  gateway-b:\n"
                "    container_name: utilities-gateway-b\n",
                encoding="utf-8",
            )
            gw_b_svc = ServiceMetadata(
                name="gateway-b",
                rel_dir="Utilities/gateway-b",
                abs_dir=gw_b_dir,
                category="Network (Gateways)",
                vps="B",
                tier=ServiceTier.GATEWAY,
            )

            app2_dir = tmppath / "Utilities" / "tools" / "open-webui"
            app2_dir.mkdir(parents=True)
            (app2_dir / "docker-compose.yml").write_text(
                "# Comment mentioning vps_b_net: external: true\n"
                "services:\n"
                "  open-webui:\n"
                "    container_name: open-webui\n"
                "    networks:\n"
                "      - vps_b_net\n"
                "networks:\n"
                "  vps_b_net:\n"
                "    external: true\n",
                encoding="utf-8",
            )
            app2_svc = ServiceMetadata(
                name="open-webui",
                rel_dir="Utilities/tools/open-webui",
                abs_dir=app2_dir,
                category="Utilities (Tools)",
                vps="B",
                tier=ServiceTier.STANDARD,
            )

            all_services = [app1_svc, app2_svc, gw_svc, gw_b_svc]
            dag = NetworkDAG(all_services)

            # Assert direct dependency edges
            app1_deps = dag.get_service_dependencies(app1_svc)
            self.assertEqual(app1_deps, [gw_svc])

            app2_deps = dag.get_service_dependencies(app2_svc)
            self.assertEqual(app2_deps, [gw_b_svc])

            # Assert topological ordering puts dependencies strictly before dependents
            sorted_svcs = dag.topological_sort([app1_svc, gw_svc])
            self.assertEqual(sorted_svcs[0], gw_svc)
            self.assertEqual(sorted_svcs[1], app1_svc)

            sorted_b = dag.topological_sort([app2_svc, gw_b_svc])
            self.assertEqual(sorted_b[0], gw_b_svc)
            self.assertEqual(sorted_b[1], app2_svc)

    def test_cycle_detection_raises_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Service A depends on container B
            svc_a_dir = tmppath / "svc_a"
            svc_a_dir.mkdir()
            (svc_a_dir / "docker-compose.yml").write_text(
                "services:\n  a:\n    container_name: container-a\n    network_mode: container:container-b\n",
                encoding="utf-8",
            )
            svc_a = ServiceMetadata(
                name="svc_a",
                rel_dir="svc_a",
                abs_dir=svc_a_dir,
                category="Tools",
                vps="A",
            )

            # Service B depends on container A
            svc_b_dir = tmppath / "svc_b"
            svc_b_dir.mkdir()
            (svc_b_dir / "docker-compose.yml").write_text(
                "services:\n  b:\n    container_name: container-b\n    network_mode: container:container-a\n",
                encoding="utf-8",
            )
            svc_b = ServiceMetadata(
                name="svc_b",
                rel_dir="svc_b",
                abs_dir=svc_b_dir,
                category="Tools",
                vps="A",
            )

            dag = NetworkDAG([svc_a, svc_b])
            with self.assertRaises(CyclicDependencyError):
                dag.topological_sort([svc_a, svc_b])


class TestRoutingUtilities(unittest.TestCase):
    """Test routing fix and native reset wrappers."""

    @patch("subprocess.run")
    def test_apply_routing_fix_invokes_script(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Routing fixed", stderr="")
        res = apply_routing_fix()
        self.assertTrue(res.success)
        self.assertEqual(res.action, "apply_routing_fix")

    def test_reset_tailscale_state_with_empty_services_list(self):
        """Passing an explicit empty list must not load manifest or reset services."""
        res = reset_tailscale_state(services=[], yes=True)
        self.assertTrue(res.success)
        self.assertIn("No matching gateway services found", res.message)

    def test_reset_tailscale_state_non_interactive_without_yes_fails(self):
        with patch("sys.stdin.isatty", return_value=False):
            res = reset_tailscale_state(services=[], yes=False)
            self.assertFalse(res.success)
            self.assertIn("Non-interactive shell requires --yes", res.message)

    def test_reset_tailscale_state_interactive_prompt_declined(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="n"):
            res = reset_tailscale_state(services=[], yes=False)
            self.assertFalse(res.success)
            self.assertIn("cancelled by user", res.message)

    def test_native_reset_tailscale_state_preserves_gluetun_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            gw_dir = tmppath / "Media" / "comics" / "gateway"
            ts_state = gw_dir / "state" / "tailscale"
            ts_state.mkdir(parents=True)
            (ts_state / "tailscaled.state").write_text("ts_state_content", encoding="utf-8")

            gluetun_state = gw_dir / "state" / "gluetun"
            gluetun_state.mkdir(parents=True)
            (gluetun_state / "wireguard.conf").write_text("wg_config", encoding="utf-8")

            (gw_dir / "docker-compose.yml").write_text(
                "services:\n"
                "  gluetun:\n"
                "    container_name: media-comics-gluetun\n"
                "  tailscale:\n"
                "    container_name: media-comics-tailscale\n"
                "    network_mode: service:gluetun\n",
                encoding="utf-8",
            )

            gw_svc = ServiceMetadata(
                name="gateway",
                rel_dir="Media/comics/gateway",
                abs_dir=gw_dir,
                category="Network (Gateways)",
                vps="A",
                tier=ServiceTier.GATEWAY,
            )

            mock_client = MagicMock()
            mock_client.get_container_status.return_value = ContainerStatus.RUNNING
            mock_client.is_container_running.return_value = True
            mock_client.stop_containers.return_value = ExecutionResult(
                service=gw_svc,
                action="stop",
                success=True,
                exit_code=0,
            )

            with patch("orchestrator.network.routing.REPO_ROOT", tmppath):
                res = reset_tailscale_state(services=[gw_svc], yes=True, client=mock_client)
                self.assertTrue(res.success)
                # Only tailscale container stopped, NOT gluetun
                mock_client.stop_containers.assert_called_with(["media-comics-tailscale"], timeout=10)
                # Tailscale state purged, Gluetun state preserved!
                self.assertFalse(ts_state.exists())
                self.assertTrue(gluetun_state.exists())
                self.assertTrue((gluetun_state / "wireguard.conf").is_file())

    def test_native_reset_tailscale_state_stops_unhealthy_container(self):
        """Unhealthy running containers must be stopped before state deletion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            gw_dir = tmppath / "Media" / "comics" / "gateway"
            ts_state = gw_dir / "state" / "tailscale"
            ts_state.mkdir(parents=True)
            (ts_state / "tailscaled.state").write_text("state_content", encoding="utf-8")

            (gw_dir / "docker-compose.yml").write_text(
                "services:\n"
                "  tailscale:\n"
                "    container_name: media-comics-tailscale\n",
                encoding="utf-8",
            )

            gw_svc = ServiceMetadata(
                name="gateway",
                rel_dir="Media/comics/gateway",
                abs_dir=gw_dir,
                category="Network (Gateways)",
                vps="A",
                tier=ServiceTier.GATEWAY,
            )

            mock_client = MagicMock()
            mock_client.get_container_status.return_value = ContainerStatus.UNHEALTHY
            mock_client.stop_containers.return_value = ExecutionResult(
                service=gw_svc,
                action="stop",
                success=True,
                exit_code=0,
            )

            with patch("orchestrator.network.routing.REPO_ROOT", tmppath):
                res = reset_tailscale_state(services=[gw_svc], yes=True, client=mock_client)
                self.assertTrue(res.success)
                mock_client.stop_containers.assert_called_with(["media-comics-tailscale"], timeout=10)
                self.assertFalse(ts_state.exists())

    def test_reset_tailscale_state_fails_closed_on_container_stop_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            gw_dir = tmppath / "Media" / "comics" / "gateway"
            ts_state = gw_dir / "state" / "tailscale"
            ts_state.mkdir(parents=True)
            (ts_state / "tailscaled.state").write_text("tailscale_state_content", encoding="utf-8")

            (gw_dir / "docker-compose.yml").write_text(
                "services:\n  tailscale:\n    container_name: media-comics-tailscale\n",
                encoding="utf-8",
            )
            gw_svc = ServiceMetadata(
                name="gateway",
                rel_dir="Media/comics/gateway",
                abs_dir=gw_dir,
                category="Network (Gateways)",
                vps="A",
                tier=ServiceTier.GATEWAY,
            )

            mock_client = MagicMock()
            mock_client.get_container_status.return_value = ContainerStatus.RUNNING
            mock_client.is_container_running.return_value = True
            mock_client.stop_containers.return_value = ExecutionResult(
                service=gw_svc,
                action="stop",
                success=False,
                exit_code=1,
                message="Docker daemon error",
            )

            with patch("orchestrator.network.routing.REPO_ROOT", tmppath):
                res = reset_tailscale_state(services=[gw_svc], yes=True, client=mock_client)
                self.assertFalse(res.success)
                self.assertIn("Failed to stop container", res.message)
                # State must remain untouched when container stop fails
                self.assertTrue(ts_state.exists())
                self.assertTrue((ts_state / "tailscaled.state").is_file())

    def test_reset_tailscale_state_fails_closed_on_daemon_inspection_error(self):
        """When Docker daemon is unreachable during inspect, real client returns ERROR and skips deletion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            gw_dir = tmppath / "Media" / "comics" / "gateway"
            ts_state = gw_dir / "state" / "tailscale"
            ts_state.mkdir(parents=True)
            (ts_state / "tailscaled.state").write_text("tailscale_state_content", encoding="utf-8")

            (gw_dir / "docker-compose.yml").write_text(
                "services:\n  tailscale:\n    container_name: media-comics-tailscale\n",
                encoding="utf-8",
            )
            gw_svc = ServiceMetadata(
                name="gateway",
                rel_dir="Media/comics/gateway",
                abs_dir=gw_dir,
                category="Network (Gateways)",
                vps="A",
                tier=ServiceTier.GATEWAY,
            )

            # Use real DockerClient instance with subprocess returning daemon socket error
            from orchestrator.docker.client import DockerClient
            real_client = DockerClient()

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?",
                )
                with patch("orchestrator.network.routing.REPO_ROOT", tmppath):
                    res = reset_tailscale_state(services=[gw_svc], yes=True, client=real_client)
                    self.assertFalse(res.success)
                    self.assertIn("Docker inspection error", res.message)
                    # State must remain completely untouched
                    self.assertTrue(ts_state.exists())
                    self.assertTrue((ts_state / "tailscaled.state").is_file())


if __name__ == "__main__":
    unittest.main()
