"""Unit tests for Doppler client, transient 0600 .env materialization, and SOPS key resolution."""

import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from orchestrator.core.models import ServiceMetadata
from orchestrator.secrets.doppler import (
    DopplerClient,
    clean_slug,
    get_doppler_config,
    get_doppler_project,
    get_short_category_slug,
)
from orchestrator.secrets.sops import find_sops_binary, setup_age_key_env
from orchestrator.secrets.transient import materialize_transient_env


class TestDopplerClient(unittest.TestCase):
    """Test Doppler naming conventions and command wrapping."""

    def setUp(self):
        self.client = DopplerClient()

    def test_clean_slug(self):
        self.assertEqual(clean_slug("Media/local-media"), "media_local_media")
        self.assertEqual(clean_slug("Utilities (Auth)"), "utilities_auth")
        self.assertEqual(clean_slug("---abc---def---"), "abc_def")

    def test_get_short_category_slug(self):
        self.assertEqual(get_short_category_slug("Network (Gateways)", "Media/comics/gateway"), "network")
        self.assertEqual(get_short_category_slug("Utilities (Auth)", "Utilities/auth/pocketid"), "auth")
        self.assertEqual(get_short_category_slug("Media/local-media (Players)", "Media/local-media/players/jellyfin"), "local_media")
        self.assertEqual(get_short_category_slug("Media/stremio", "Media/stremio/addons/aiostreams"), "stremio")

    def test_get_doppler_project(self):
        self.assertEqual(get_doppler_project("A"), "polaris-vps-a")
        self.assertEqual(get_doppler_project("B"), "polaris-vps-b")

    def test_get_doppler_config(self):
        self.assertEqual(
            get_doppler_config("Utilities/auth/pocketid", "pocketid", "Utilities (Auth)"),
            "auth_pocketid",
        )
        self.assertEqual(
            get_doppler_config("Media/comics/gateway", "gateway", "Network (Gateways)"),
            "network_media_comics_gateway",
        )

    def test_wrap_command(self):
        service = ServiceMetadata(
            name="pocketid",
            rel_dir="Utilities/auth/pocketid",
            abs_dir=Path("/repo/Utilities/auth/pocketid"),
            category="Utilities (Auth)",
            vps="A",
        )
        cmd = self.client.wrap_command(["docker", "compose", "up", "-d"], service=service)
        self.assertEqual(
            cmd,
            ["doppler", "run", "--project", "polaris-vps-a", "--config", "auth_pocketid", "--", "docker", "compose", "up", "-d"],
        )


class TestTransientEnv(unittest.TestCase):
    """Test 0600 .env materialization, write failure cleanup, and context manager exit."""

    def test_materialize_and_cleanup_transient_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            compose_file = tmppath / "docker-compose.yml"
            compose_file.write_text("services:\n  app:\n    env_file: .env\n", encoding="utf-8")

            service = ServiceMetadata(
                name="testapp",
                rel_dir="testapp",
                abs_dir=tmppath,
                category="Utilities (Tools)",
                vps="A",
                env_file_required=True,
            )

            mock_client = MagicMock()
            mock_client.fetch_secrets.return_value = "SECRET_KEY=safe_test_value\n"

            with materialize_transient_env(service, doppler_client=mock_client) as env_path:
                self.assertIsNotNone(env_path)
                self.assertTrue(env_path.is_file())
                # Check permissions: 0600
                mode = env_path.stat().st_mode & 0o777
                self.assertEqual(mode, 0o600)

            # Assert file was removed immediately upon exit
            self.assertFalse(env_path.is_file())

    def test_write_failure_ensures_no_disk_leak(self):
        """If writing or chmod fails, the partially created file must be immediately deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            compose_file = tmppath / "docker-compose.yml"
            compose_file.write_text("services:\n  app:\n    env_file: .env\n", encoding="utf-8")

            service = ServiceMetadata(
                name="testapp",
                rel_dir="testapp",
                abs_dir=tmppath,
                category="Utilities (Tools)",
                vps="A",
                env_file_required=True,
            )

            mock_client = MagicMock()
            mock_client.fetch_secrets.return_value = "SECRET_KEY=test\n"

            with patch("os.chmod", side_effect=OSError("Simulated chmod failure")):
                with self.assertRaises(OSError):
                    with materialize_transient_env(service, doppler_client=mock_client):
                        pass

            # Verify no .env remains
            self.assertFalse((tmppath / ".env").exists())

    def test_write_and_unlink_combined_failure_raises_runtime_error(self):
        """If chmod fails AND subsequent unlink fails, must raise critical RuntimeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            compose_file = tmppath / "docker-compose.yml"
            compose_file.write_text("services:\n  app:\n    env_file: .env\n", encoding="utf-8")

            service = ServiceMetadata(
                name="testapp",
                rel_dir="testapp",
                abs_dir=tmppath,
                category="Utilities (Tools)",
                vps="A",
                env_file_required=True,
            )

            mock_client = MagicMock()
            mock_client.fetch_secrets.return_value = "SECRET_KEY=test\n"

            with patch("os.chmod", side_effect=OSError("Simulated chmod failure")), patch.object(
                Path, "unlink", side_effect=OSError("Simulated unlink failure")
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    with materialize_transient_env(service, doppler_client=mock_client):
                        pass
                self.assertIn("Failed to remove transient environment file", str(ctx.exception))
                self.assertIn("after write failure", str(ctx.exception))

    def test_cleanup_failure_raises_runtime_error(self):
        """If transient .env cannot be deleted upon exit, must fail visibly with RuntimeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            compose_file = tmppath / "docker-compose.yml"
            compose_file.write_text("services:\n  app:\n    env_file: .env\n", encoding="utf-8")

            service = ServiceMetadata(
                name="testapp",
                rel_dir="testapp",
                abs_dir=tmppath,
                category="Utilities (Tools)",
                vps="A",
                env_file_required=True,
            )

            mock_client = MagicMock()
            mock_client.fetch_secrets.return_value = "SECRET_KEY=test\n"

            with patch.object(Path, "unlink", side_effect=OSError("Simulated unlink failure")):
                with self.assertRaises(RuntimeError) as ctx:
                    with materialize_transient_env(service, doppler_client=mock_client):
                        pass
                self.assertIn("Failed to remove transient environment file", str(ctx.exception))

    def test_skip_when_env_file_not_declared(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            compose_file = tmppath / "docker-compose.yml"
            compose_file.write_text("services:\n  app:\n    image: test:1.0\n", encoding="utf-8")

            service = ServiceMetadata(
                name="testapp",
                rel_dir="testapp",
                abs_dir=tmppath,
                category="Utilities (Tools)",
                vps="A",
                env_file_required=False,
            )

            with materialize_transient_env(service) as env_path:
                self.assertIsNone(env_path)


class TestSopsKeySetup(unittest.TestCase):
    """Test SOPS Age key location resolver and executable binary checking."""

    def test_setup_age_key_with_existing_env(self):
        with tempfile.NamedTemporaryFile() as tmp:
            with patch.dict("os.environ", {"SOPS_AGE_KEY_FILE": tmp.name}):
                ok = setup_age_key_env()
                self.assertTrue(ok)

    def test_find_sops_binary_requires_executable_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            bin_dir = tmppath / "bin"
            bin_dir.mkdir()
            fake_sops = bin_dir / "sops"
            fake_sops.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

            # Non-executable file must be rejected
            fake_sops.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600 (no X_OK)
            with patch("shutil.which", return_value=None):
                found = find_sops_binary(repo_root=tmppath)
                self.assertIsNone(found)

                # Make executable (0755)
                fake_sops.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
                found_exec = find_sops_binary(repo_root=tmppath)
                self.assertIsNotNone(found_exec)


if __name__ == "__main__":
    unittest.main()
