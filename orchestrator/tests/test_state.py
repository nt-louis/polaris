"""Unit tests for orchestrator state tracking and audit history logging."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.core.history import (
    format_action_history_text,
    load_action_history,
    log_action_event,
    prune_action_history,
)
from orchestrator.core.models import ServiceMetadata
from orchestrator.core.state import (
    get_active_vps,
    get_last_deploy_path,
    load_last_deploy_services,
    save_last_deploy_services,
    set_active_vps,
)


class TestStateContext(unittest.TestCase):
    def test_get_active_vps_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            with patch("orchestrator.core.state.ACTIVE_VPS_FILE", tmppath / ".active_vps"):
                with patch.dict("os.environ", {}, clear=True):
                    self.assertEqual(get_active_vps(), "A")

    def test_get_active_vps_from_env(self):
        with patch.dict("os.environ", {"NET_STREAM_VPS": "B"}):
            self.assertEqual(get_active_vps(), "B")

    def test_get_active_vps_ignores_invalid_env(self):
        with patch.dict("os.environ", {"NET_STREAM_VPS": "INVALID_NODE"}):
            self.assertEqual(get_active_vps(), "A")

    def test_get_active_vps_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vps_file = Path(tmpdir) / ".active_vps"
            vps_file.write_text("B\n", encoding="utf-8")
            with patch("orchestrator.core.state.ACTIVE_VPS_FILE", vps_file):
                with patch.dict("os.environ", {}, clear=True):
                    self.assertEqual(get_active_vps(), "B")

    def test_get_active_vps_ignores_invalid_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vps_file = Path(tmpdir) / ".active_vps"
            vps_file.write_text("INVALID_NODE\n", encoding="utf-8")
            with patch("orchestrator.core.state.ACTIVE_VPS_FILE", vps_file):
                with patch.dict("os.environ", {}, clear=True):
                    self.assertEqual(get_active_vps(), "A")

    def test_set_active_vps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vps_file = Path(tmpdir) / ".active_vps"
            with patch("orchestrator.core.state.ACTIVE_VPS_FILE", vps_file):
                set_active_vps("b")
                self.assertEqual(vps_file.read_text(encoding="utf-8").strip(), "B")

    def test_set_active_vps_rejects_invalid_node(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vps_file = Path(tmpdir) / ".active_vps"
            with patch("orchestrator.core.state.ACTIVE_VPS_FILE", vps_file):
                with self.assertRaises(ValueError) as ctx:
                    set_active_vps("INVALID")
                self.assertIn("Invalid VPS node ID", str(ctx.exception))

    def test_get_last_deploy_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            with patch("orchestrator.core.state.REPO_ROOT", tmppath), \
                 patch("orchestrator.core.state.LAST_DEPLOY_FILE", tmppath / ".last_deploy"):
                self.assertEqual(get_last_deploy_path("A"), tmppath / ".last_deploy_a")
                self.assertEqual(get_last_deploy_path("B"), tmppath / ".last_deploy_b")
                self.assertEqual(get_last_deploy_path(None), tmppath / ".last_deploy")

    def test_save_and_load_last_deploy_services(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            s1 = ServiceMetadata(
                name="jellyfin",
                rel_dir="Media/local-media/players/jellyfin",
                abs_dir=tmppath / "Media/local-media/players/jellyfin",
                category="Media/local-media (Players)",
                vps="A",
            )
            s2 = ServiceMetadata(
                name="sonarr",
                rel_dir="Media/local-media/managers/sonarr",
                abs_dir=tmppath / "Media/local-media/managers/sonarr",
                category="Media/local-media (Managers)",
                vps="A",
            )
            s3 = ServiceMetadata(
                name="radarr",
                rel_dir="Media/local-media/managers/radarr",
                abs_dir=tmppath / "Media/local-media/managers/radarr",
                category="Media/local-media (Managers)",
                vps="A",
            )

            state_file_a = tmppath / ".last_deploy_a"
            with patch("orchestrator.core.state.REPO_ROOT", tmppath):
                # Save s1 and s2
                save_last_deploy_services([s1, s2], vps="A")
                self.assertTrue(state_file_a.is_file())

                # Load with full pool [s1, s2, s3] -> should return [s1, s2]
                loaded = load_last_deploy_services([s1, s2, s3], vps="A")
                self.assertEqual(len(loaded), 2)
                self.assertEqual({s.name for s in loaded}, {"jellyfin", "sonarr"})

    def test_log_stream_mode_persistence_and_scoping(self):
        from orchestrator.core.state import (
            get_log_stream_mode,
            get_log_stream_path,
            set_log_stream_mode,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            with patch("orchestrator.core.state.REPO_ROOT", tmppath), \
                 patch("orchestrator.core.state.LOG_STREAM_MODE_FILE", tmppath / ".log_stream_mode"):
                # 1. Default when no file exists
                self.assertEqual(get_log_stream_mode("A"), "native")
                self.assertEqual(get_log_stream_path("A"), tmppath / ".log_stream_mode_a")
                self.assertEqual(get_log_stream_path("B"), tmppath / ".log_stream_mode_b")

                # 2. Set node-specific mode
                set_log_stream_mode("piped", vps="A")
                self.assertEqual(get_log_stream_mode("A"), "piped")
                self.assertEqual(get_log_stream_mode("B"), "native")

                # 3. Set node B mode
                set_log_stream_mode("native", vps="B")
                self.assertEqual(get_log_stream_mode("B"), "native")

                # 4. Env var override
                with patch.dict("os.environ", {"NET_STREAM_LOG_MODE": "piped"}):
                    self.assertEqual(get_log_stream_mode("B"), "piped")

                # 5. Invalid mode rejected
                with self.assertRaises(ValueError):
                    set_log_stream_mode("invalid_mode", vps="A")

    def test_log_stream_mode_prompt_if_missing(self):
        from orchestrator.core.state import get_log_stream_mode

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            with patch("orchestrator.core.state.REPO_ROOT", tmppath), \
                 patch("orchestrator.core.state.LOG_STREAM_MODE_FILE", tmppath / ".log_stream_mode"), \
                 patch("orchestrator.core.guards.is_test_environment", return_value=False), \
                 patch("sys.stdin.isatty", return_value=True), \
                 patch("builtins.input", return_value="2"):
                mode = get_log_stream_mode("A", prompt_if_missing=True)
                self.assertEqual(mode, "piped")
                # Subsequent retrieval reads from persisted file without prompt
                self.assertEqual(get_log_stream_mode("A"), "piped")


class TestHistoryAuditLog(unittest.TestCase):
    def test_log_and_load_action_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_file = Path(tmpdir) / "state" / "action_history.jsonl"

            # Log 3 events
            log_action_event("DEPLOY", vps="A", exit_code=0, duration_sec=4.5, command="deploy jellyfin", history_file=hist_file)
            log_action_event("STOP", vps="A", exit_code=1, duration_sec=1.2, details="container error", history_file=hist_file)
            log_action_event("REDEPLOY", vps="B", exit_code=0, duration_sec=2.8, history_file=hist_file)

            self.assertTrue(hist_file.is_file())

            # Load records
            records = load_action_history(limit=10, history_file=hist_file)
            self.assertEqual(len(records), 3)
            self.assertEqual(records[0]["action"], "DEPLOY")
            self.assertEqual(records[0]["status"], "SUCCESS")
            self.assertEqual(records[1]["action"], "STOP")
            self.assertEqual(records[1]["status"], "FAILED")
            self.assertEqual(records[2]["action"], "REDEPLOY")

            # Limit records
            limited = load_action_history(limit=2, history_file=hist_file)
            self.assertEqual(len(limited), 2)
            self.assertEqual(limited[0]["action"], "STOP")

    def test_format_action_history_text(self):
        records = [
            {
                "timestamp": "2026-08-19T07:00:00.000000+00:00",
                "action": "DEPLOY",
                "vps": "A",
                "exit_code": 0,
                "status": "SUCCESS",
                "duration_sec": 5.12,
                "command": "deploy jellyfin",
            }
        ]
        output = format_action_history_text(records)
        self.assertIn("Polaris Persistent Action Audit History", output)
        self.assertIn("DEPLOY", output)
        self.assertIn("VPS A", output)
        self.assertIn("SUCCESS", output)

    def test_prune_action_history_age_cutoff(self):
        import json
        from datetime import datetime, timedelta, timezone

        with tempfile.TemporaryDirectory() as tmpdir:
            hist_file = Path(tmpdir) / "action_history.jsonl"
            now = datetime.now(timezone.utc)
            old_time = (now - timedelta(days=45)).isoformat()
            recent_time = (now - timedelta(days=5)).isoformat()

            old_event = {"timestamp": old_time, "action": "DEPLOY", "vps": "A", "status": "SUCCESS"}
            recent_event = {"timestamp": recent_time, "action": "STOP", "vps": "A", "status": "SUCCESS"}

            with hist_file.open("w", encoding="utf-8") as f:
                f.write(json.dumps(old_event) + "\n")
                f.write(json.dumps(recent_event) + "\n")

            pruned = prune_action_history(max_age_days=30, max_records=1000, history_file=hist_file)
            self.assertEqual(pruned, 1)

            records = load_action_history(limit=10, history_file=hist_file)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["action"], "STOP")

    def test_prune_action_history_max_records_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_file = Path(tmpdir) / "action_history.jsonl"
            for i in range(10):
                log_action_event("DEPLOY", command=f"deploy-{i}", history_file=hist_file, max_records=100)

            # Enforce max 3 records
            pruned = prune_action_history(max_age_days=365, max_records=3, history_file=hist_file)
            self.assertEqual(pruned, 7)

            records = load_action_history(limit=10, history_file=hist_file)
            self.assertEqual(len(records), 3)
            self.assertEqual(records[-1]["command"], "deploy-9")

    def test_prune_action_history_preserves_file_permissions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_file = Path(tmpdir) / "action_history.jsonl"
            for i in range(5):
                log_action_event("DEPLOY", command=f"deploy-{i}", history_file=hist_file, max_records=100)

            # Set specific permissions on history file
            hist_file.chmod(0o664)

            # Prune and ensure permissions are preserved (not reset to 0600 default of NamedTemporaryFile)
            prune_action_history(max_age_days=365, max_records=2, history_file=hist_file)
            current_mode = hist_file.stat().st_mode & 0o777
            self.assertEqual(current_mode, 0o664)

    def test_root_execution_chowns_to_repo_owner(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_file = Path(tmpdir) / "state" / "action_history.jsonl"
            mock_stat = MagicMock()
            mock_stat.st_uid = 1001
            mock_stat.st_gid = 1001

            mock_root = MagicMock()
            mock_root.stat.return_value = mock_stat

            with patch("os.geteuid", return_value=0), \
                 patch("orchestrator.core.history.REPO_ROOT", mock_root), \
                 patch("os.chown") as mock_chown:
                log_action_event("BACKUP", command="backup", history_file=hist_file)
                # Verify chown was invoked with repo owner's UID and GID
                self.assertTrue(mock_chown.called)
                mock_chown.assert_any_call(hist_file, 1001, 1001)

    def test_history_cli_prune(self):
        from orchestrator.actions.history import main as history_main

        with tempfile.TemporaryDirectory() as tmpdir:
            hist_file = Path(tmpdir) / "action_history.jsonl"
            log_action_event("DEPLOY", command="deploy-1", history_file=hist_file)
            with patch("orchestrator.core.history.HISTORY_FILE", hist_file):
                code = history_main(["--prune", "--max-age", "30", "--max-records", "1000"])
                self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
