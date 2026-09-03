"""Unit tests for DockerClient, ComposeEngine, readiness probes, and logs resolver."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from orchestrator.core.models import ContainerStatus, ServiceMetadata, ServiceTier
from orchestrator.docker.client import DockerClient
from orchestrator.docker.compose import ComposeEngine
from orchestrator.docker.logs import resolve_container
from orchestrator.docker.readiness import (
    extract_container_names,
    extract_gluetun_container,
    wait_for_container_ready,
    wait_for_service_ready,
)


class TestDockerClient(unittest.TestCase):
    """Test typed Docker CLI client inspection and status normalization."""

    def setUp(self):
        self.client = DockerClient()

    @patch("subprocess.run")
    def test_get_container_status_healthy(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="running|healthy\n")
        status = self.client.get_container_status("test-container")
        self.assertEqual(status, ContainerStatus.HEALTHY)

    @patch("subprocess.run")
    def test_get_container_status_unhealthy(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="running|unhealthy\n")
        status = self.client.get_container_status("test-container")
        self.assertEqual(status, ContainerStatus.UNHEALTHY)

    @patch("subprocess.run")
    def test_get_container_status_exited(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="exited|\n")
        status = self.client.get_container_status("test-container")
        self.assertEqual(status, ContainerStatus.EXITED)

    @patch("subprocess.run")
    def test_get_container_status_not_found(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error: No such container")
        status = self.client.get_container_status("nonexistent")
        self.assertEqual(status, ContainerStatus.NOT_FOUND)

    @patch("subprocess.run")
    def test_get_container_status_daemon_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
        )
        status = self.client.get_container_status("any-container")
        self.assertEqual(status, ContainerStatus.ERROR)

    @patch("subprocess.run")
    def test_inspect_container_parses_json(self, mock_run):
        mock_inspect = (
            '{"Id": "1234567890abcdef", "Name": "/jellyfin-app", '
            '"NetworkSettings": {"Ports": {"8096/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8096"}]}}}'
        )
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=mock_inspect),
            MagicMock(returncode=0, stdout="running|healthy\n"),
        ]
        state = self.client.inspect_container("jellyfin-app")
        self.assertIsNotNone(state)
        self.assertEqual(state.container_id, "1234567890ab")
        self.assertEqual(state.name, "jellyfin-app")
        self.assertTrue(state.is_active)
        self.assertIn("0.0.0.0:8096->8096/tcp", state.ports)


    @patch("subprocess.run")
    def test_image_exists(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        self.assertTrue(self.client.image_exists("local/monochrome:latest"))

        mock_run.return_value = MagicMock(returncode=1)
        self.assertFalse(self.client.image_exists("local/missing:latest"))
        self.assertFalse(self.client.image_exists(""))


class TestComposeEngine(unittest.TestCase):
    """Test Docker Compose command construction and execution metrics."""

    def setUp(self):
        self.engine = ComposeEngine()
        self.standard_service = ServiceMetadata(
            name="bazarr",
            rel_dir="Media/local-media/managers/bazarr",
            abs_dir=Path("/repo/Media/local-media/managers/bazarr"),
            category="Media/local-media (Managers)",
            vps="A",
            custom_project_name=None,
        )
        self.local_service = ServiceMetadata(
            name="monochrome",
            rel_dir="Media/local-media/players/monochrome",
            abs_dir=Path("/repo/Media/local-media/players/monochrome"),
            category="Media/local-media (Players)",
            vps="A",
            is_build_heavy=True,
        )
        self.custom_service = ServiceMetadata(
            name="gateway",
            rel_dir="Media/comics/gateway",
            abs_dir=Path("/repo/Media/comics/gateway"),
            category="Network (Gateways)",
            vps="A",
            custom_project_name="media-comics-gateway",
            tier=ServiceTier.GATEWAY,
        )

    def test_build_compose_cmd_standard_service_omits_p_flag(self):
        """Standard service without custom project name must NOT inject -p flag."""
        cmd = self.engine.build_compose_cmd(self.standard_service, ["up", "-d"])
        self.assertEqual(cmd, ["docker", "compose", "-f", "docker-compose.yml", "up", "-d"])

    def test_build_compose_cmd_custom_service_includes_p_flag(self):
        """Service with custom_project_name must include -p <custom_name>."""
        cmd = self.engine.build_compose_cmd(self.custom_service, ["up", "-d"])
        self.assertEqual(
            cmd,
            ["docker", "compose", "-p", "media-comics-gateway", "-f", "docker-compose.yml", "up", "-d"],
        )

    @patch("subprocess.run")
    def test_compose_up_flags(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Started", stderr="")
        res = self.engine.compose_up(self.standard_service, recreate=True, build=True, pull=True)
        self.assertTrue(res.success)
        called_cmd = mock_run.call_args[0][0]
        self.assertIn("--force-recreate", called_cmd)
        self.assertIn("--build", called_cmd)
        self.assertIn("-d", called_cmd)
        self.assertIn("--pull", called_cmd)
        self.assertIn("always", called_cmd)

    @patch("subprocess.run")
    def test_compose_up_local_build_skips_pull_flag(self, mock_run):
        """Locally built service must NOT include --pull always flag."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Started", stderr="")
        res = self.engine.compose_up(self.local_service, pull=True)
        self.assertTrue(res.success)
        called_cmd = mock_run.call_args[0][0]
        self.assertNotIn("--pull", called_cmd)
        self.assertNotIn("always", called_cmd)

    @patch("subprocess.run")
    def test_compose_pull_local_build_skips_command(self, mock_run):
        """Locally built service must skip docker compose pull completely."""
        res = self.engine.compose_pull(self.local_service)
        self.assertTrue(res.success)
        mock_run.assert_not_called()

    @patch("subprocess.run")
    @patch("orchestrator.docker.compose.is_test_environment", return_value=False)
    def test_run_command_native_streaming(self, mock_is_test, mock_run):
        mock_proc = MagicMock(returncode=0)
        mock_run.return_value = mock_proc

        res = self.engine._run_command(
            service=self.standard_service,
            action="compose_up",
            cmd=["docker", "compose", "up"],
            cwd=Path("/tmp"),
            stream_output=True,
            stream_mode="native",
        )
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        self.assertIn("live terminal output", res.message)
        # Verify stdout was not piped, ensuring direct TTY passthrough
        self.assertNotIn("stdout", mock_run.call_args.kwargs)

    @patch("subprocess.Popen")
    @patch("orchestrator.docker.compose.is_test_environment", return_value=False)
    def test_run_command_piped_streaming(self, mock_is_test, mock_popen):
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = ["Step 1/3\n", "Step 2/3\n", "Done\n", ""]
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        res = self.engine._run_command(
            service=self.standard_service,
            action="compose_up",
            cmd=["docker", "compose", "up"],
            cwd=Path("/tmp"),
            stream_output=True,
            stream_mode="piped",
        )
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        self.assertIn("Step 1/3", res.message)
        self.assertIn("Done", res.message)

    @patch("subprocess.run")
    def test_compose_ps_case_normalization(self, mock_run):
        """Ensure compose_ps queries lowercase variants for capitalized project names."""
        net_svc = ServiceMetadata(
            name="Network",
            rel_dir="Network",
            abs_dir=Path("/repo/Network"),
            category="Other",
            vps="A",
            custom_project_name=None,
        )

        def side_effect(cmd, **kwargs):
            if "label=com.docker.compose.project=network" in cmd:
                return MagicMock(returncode=0, stdout="cid-network-1\ncid-network-2\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        cids = self.engine.compose_ps(net_svc)
        self.assertEqual(cids, ["cid-network-1", "cid-network-2"])


class TestReadinessAndLogs(unittest.TestCase):
    """Test readiness wait loops, timeouts, and container logs resolution."""

    def test_wait_for_container_ready_success(self):
        mock_client = MagicMock()
        mock_client.get_container_status.side_effect = [
            ContainerStatus.STARTING,
            ContainerStatus.RUNNING,
        ]
        ok = wait_for_container_ready("test", timeout=5, interval=0.01, client=mock_client)
        self.assertTrue(ok)

    def test_wait_for_container_ready_fails_on_exited(self):
        mock_client = MagicMock()
        mock_client.get_container_status.side_effect = [
            ContainerStatus.STARTING,
            ContainerStatus.EXITED,
        ]
        ok = wait_for_container_ready("test", timeout=5, interval=0.01, client=mock_client)
        self.assertFalse(ok)

    def test_wait_for_container_ready_timeout(self):
        """Container stuck in starting must return False upon timeout."""
        mock_client = MagicMock()
        mock_client.get_container_status.return_value = ContainerStatus.STARTING
        ok = wait_for_container_ready("test", timeout=0.05, interval=0.01, client=mock_client)
        self.assertFalse(ok)

    def test_wait_for_service_ready_with_real_compose(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "docker-compose.yml").write_text(
                "services:\n"
                "  gluetun:\n"
                "    container_name: test-gluetun\n"
                "  app:\n"
                "    container_name: test-app\n",
                encoding="utf-8",
            )
            svc = ServiceMetadata(
                name="gateway",
                rel_dir="gateway",
                abs_dir=tmppath,
                category="Network (Gateways)",
                vps="A",
                tier=ServiceTier.GATEWAY,
            )

            names = extract_container_names(svc)
            self.assertEqual(names, ["test-gluetun", "test-app"])
            gluetun = extract_gluetun_container(svc)
            self.assertEqual(gluetun, "test-gluetun")

            mock_client = MagicMock()
            mock_client.get_container_status.return_value = ContainerStatus.HEALTHY

            ok = wait_for_service_ready(svc, timeout=5, interval=0.01, client=mock_client)
            self.assertTrue(ok)

    def test_resolve_container_exact_match(self):
        mock_client = MagicMock()
        mock_client.list_running_containers.return_value = ["jellyfin", "bazarr", "sonarr"]
        res = resolve_container("jellyfin", client=mock_client)
        self.assertEqual(res, "jellyfin")

    def test_resolve_container_prefix_suffix_match(self):
        mock_client = MagicMock()
        mock_client.list_running_containers.return_value = ["media-jellyfin-app", "media-bazarr"]
        res = resolve_container("bazarr", client=mock_client)
        self.assertEqual(res, "media-bazarr")


if __name__ == "__main__":
    unittest.main()
