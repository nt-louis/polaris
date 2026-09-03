"""Unit tests for DoctorAction pre-flight diagnostics."""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from orchestrator.actions.doctor import (
    DoctorAction,
    check_disk_space,
    check_routing_rules,
    check_secrets_auth,
    check_tailscale,
    main,
)
from orchestrator.core.models import (
    ActionContext,
    ContainerStatus,
    ServiceMetadata,
    ServiceTier,
)


class TestDoctorAction(unittest.TestCase):
    @patch("subprocess.run")
    def test_check_secrets_auth(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc
        ok, msg = check_secrets_auth()
        self.assertTrue(ok)
        self.assertIn("authenticated", msg)

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_check_tailscale_missing_cli(self, mock_run):
        ok, msg = check_tailscale("A", is_remote=False)
        self.assertFalse(ok)
        self.assertIn("not installed", msg)

    @patch("subprocess.run")
    def test_check_tailscale_local(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({
            "Self": {"HostName": "vps", "TailscaleIPs": ["100.64.0.1"]},
            "Peer": {},
        })
        mock_run.return_value = mock_proc
        ok, msg = check_tailscale("A", is_remote=False)
        self.assertTrue(ok)
        self.assertIn("100.64.0.1", msg)

    @patch("subprocess.run")
    def test_check_tailscale_remote_exact_matching(self, mock_run):
        # Ensure peer 'vps' does NOT falsely match 'vps2'
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({
            "Self": {"HostName": "vps", "TailscaleIPs": ["100.64.0.1"]},
            "Peer": {
                "node1": {
                    "HostName": "vps2",
                    "DNSName": "vps2.tailnet.ts.net.",
                    "Online": True,
                    "TailscaleIPs": ["100.64.0.2"],
                    "OS": "linux",
                }
            },
        })
        mock_run.return_value = mock_proc
        with patch("orchestrator.actions.doctor.get_node_tailscale_name", return_value="vps"):
            # Target is 'vps', peer is 'vps2' -> must not match
            ok, msg = check_tailscale("A", is_remote=True)
            self.assertFalse(ok)
            self.assertIn("not found", msg)

        with patch("orchestrator.actions.doctor.get_node_tailscale_name", return_value="vps2"):
            # Target is 'vps2', peer is 'vps2' -> exact match
            ok, msg = check_tailscale("B", is_remote=True)
            self.assertTrue(ok)
            self.assertIn("Online", msg)
            self.assertIn("100.64.0.2", msg)

    @patch("subprocess.run")
    def test_check_tailscale_missing_metadata(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({"Self": {"HostName": "vps1", "TailscaleIPs": ["100.64.0.1"]}})
        mock_run.return_value = mock_proc
        with patch("orchestrator.actions.doctor.get_node_tailscale_name", return_value=None):
            ok, msg = check_tailscale("C", is_remote=True)
            self.assertFalse(ok)
            self.assertIn("no 'tailscale_name' declared", msg)

    @patch("subprocess.run")
    def test_check_routing_rules_local(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "50: from all fwmark 0x1 lookup 52"
        mock_run.return_value = mock_proc
        ok, msg = check_routing_rules(is_remote=False, target_vps="A")
        self.assertTrue(ok)
        self.assertIn("Policy routing", msg)

    def test_check_routing_rules_remote(self):
        ok, msg = check_routing_rules(is_remote=True, target_vps="B", remote_online=True)
        self.assertFalse(ok)
        self.assertIn("[WARN]", msg)
        self.assertIn("cannot be verified", msg)

        ok_off, msg_off = check_routing_rules(is_remote=True, target_vps="B", remote_online=False)
        self.assertFalse(ok_off)
        self.assertIn("offline", msg_off)

    @patch("shutil.disk_usage")
    def test_check_disk_space_local(self, mock_usage):
        mock_usage.return_value = MagicMock(free=50 * (1024 ** 3), total=100 * (1024 ** 3))
        ok, msg = check_disk_space(is_remote=False, target_vps="A")
        self.assertTrue(ok)
        self.assertIn("free space", msg)

    def test_check_disk_space_remote(self):
        ok, msg = check_disk_space(is_remote=True, target_vps="B", remote_online=True)
        self.assertFalse(ok)
        self.assertIn("[WARN]", msg)
        self.assertIn("cannot be verified", msg)

        ok_off, msg_off = check_disk_space(is_remote=True, target_vps="B", remote_online=False)
        self.assertFalse(ok_off)
        self.assertIn("offline", msg_off)

    @patch("orchestrator.actions.doctor.load_services")
    def test_check_gateway_clusters_local(self, mock_load):
        gw_svc = ServiceMetadata(
            name="gateway",
            rel_dir="Media/local-media/gateway",
            abs_dir=Path("/mock/Media/local-media/gateway"),
            category="Media",
            vps="A",
            tier=ServiceTier.GATEWAY,
            custom_project_name="media-gateway-core",
        )
        mock_load.return_value = [gw_svc]

        action = DoctorAction()
        with patch.object(action.docker_client, "list_running_containers", return_value=["media-gateway-core-gluetun"]), \
             patch.object(action.docker_client, "get_container_status", return_value=ContainerStatus.HEALTHY):
            ok, msg = action.check_gateway_clusters("A", is_remote=False)
            self.assertTrue(ok)
            self.assertIn("1 active gateway cluster(s) healthy", msg)

        with patch.object(action.docker_client, "list_running_containers", return_value=["media-gateway-core-gluetun"]), \
             patch.object(action.docker_client, "get_container_status", return_value=ContainerStatus.UNHEALTHY):
            ok, msg = action.check_gateway_clusters("A", is_remote=False)
            self.assertFalse(ok)
            self.assertIn("Gateway cluster issues", msg)

    def test_check_gateway_clusters_remote(self):
        action = DoctorAction()
        ok, msg = action.check_gateway_clusters("B", is_remote=True, remote_online=True)
        self.assertFalse(ok)
        self.assertIn("[WARN]", msg)
        self.assertIn("cannot be verified", msg)

        ok_off, msg_off = action.check_gateway_clusters("B", is_remote=True, remote_online=False)
        self.assertFalse(ok_off)
        self.assertIn("offline", msg_off)

    @patch("orchestrator.actions.doctor.check_git_hooks", return_value=(True, "OK"))
    @patch("orchestrator.actions.doctor.check_secrets_auth", return_value=(True, "OK"))
    @patch("orchestrator.actions.doctor.check_secrets_integrity", return_value=(True, "OK"))
    @patch("orchestrator.actions.doctor.check_sops_snapshots", return_value=(True, "OK"))
    @patch("orchestrator.actions.doctor.check_tailscale", return_value=(True, "OK"))
    @patch("orchestrator.actions.doctor.check_routing_rules", return_value=(True, "OK"))
    @patch("orchestrator.actions.doctor.check_disk_space", return_value=(True, "OK"))
    def test_doctor_action_all_pass(self, m_disk, m_route, m_ts, m_snap, m_sec_int, m_sec, m_git):
        action = DoctorAction()
        with patch.object(action, "check_gateway_clusters", return_value=(True, "OK")):
            ctx = ActionContext(vps="A", json_output=True)
            res = action.execute(ctx)
            self.assertTrue(res.success)
            self.assertEqual(res.exit_code, 0)
            self.assertIn("All diagnostic probes passed", res.message)

    @patch("orchestrator.actions.doctor.check_git_hooks", return_value=(True, "OK"))
    @patch("orchestrator.actions.doctor.check_secrets_auth", return_value=(False, "Failed"))
    @patch("orchestrator.actions.doctor.check_secrets_integrity", return_value=(True, "OK"))
    @patch("orchestrator.actions.doctor.check_sops_snapshots", return_value=(True, "OK"))
    @patch("orchestrator.actions.doctor.check_tailscale", return_value=(True, "OK"))
    @patch("orchestrator.actions.doctor.check_routing_rules", return_value=(True, "OK"))
    @patch("orchestrator.actions.doctor.check_disk_space", return_value=(True, "OK"))
    def test_doctor_action_failure(self, m_disk, m_route, m_ts, m_snap, m_sec_int, m_sec, m_git):
        action = DoctorAction()
        with patch.object(action, "check_gateway_clusters", return_value=(True, "OK")):
            ctx = ActionContext(vps="A", json_output=True)
            res = action.execute(ctx)
            self.assertFalse(res.success)
            self.assertEqual(res.exit_code, 1)

    def test_main_cli_invalid_vps(self):
        with patch("sys.stderr"), patch("orchestrator.registry.manifest.get_valid_node_ids", return_value={"A", "B"}):
            code = main(["--vps", "INVALID"])
            self.assertEqual(code, 2)

    def test_main_cli_missing_vps_value(self):
        with patch("sys.stderr"):
            code = main(["--vps"])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
