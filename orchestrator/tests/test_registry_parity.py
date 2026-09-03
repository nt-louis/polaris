"""Golden Registry Static Regression Test Suite.

Asserts static snapshot integrity, field completeness, node distribution,
and query resolution behavior for all 80 registered services in services.yaml
without importing legacy Scripts/deploy/core modules.
"""

import sys
import unittest
from pathlib import Path

# Anchor paths
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.registry.discovery import discover_appdata_paths
from orchestrator.registry.manifest import get_valid_node_ids, load_services
from orchestrator.registry.resolver import resolve_all_services, resolve_targets


class TestRegistryGoldenSnapshot(unittest.TestCase):
    """Test static snapshot integrity of services.yaml and orchestrator registry resolution."""

    def setUp(self):
        self.services = load_services()

    def test_total_service_count(self):
        """Ensure services.yaml contains exactly 80 active services."""
        self.assertEqual(len(self.services), 80)

    def test_node_distribution(self):
        """Verify services are mapped to valid nodes (A and B)."""
        valid_nodes = get_valid_node_ids()
        self.assertEqual(valid_nodes, {"A", "B", "C"})

        services_a = resolve_all_services(self.services, vps="A")
        services_b = resolve_all_services(self.services, vps="B")
        services_c = resolve_all_services(self.services, vps="C")

        self.assertEqual(len(services_a) + len(services_b) + len(services_c), 80)
        self.assertTrue(len(services_a) > 0)
        self.assertTrue(len(services_b) > 0)
        for s in self.services:
            self.assertIn(s.vps, valid_nodes)

    def test_all_services_have_valid_compose_files(self):
        """Verify every registered service points to an existing directory and compose file."""
        for s in self.services:
            self.assertTrue(
                s.abs_dir.is_dir(),
                f"Directory does not exist for service {s.name}: {s.abs_dir}",
            )
            self.assertTrue(
                s.compose_path.is_file(),
                f"Compose file missing for service {s.name}: {s.compose_path}",
            )
            self.assertTrue(len(s.name) > 0)
            self.assertTrue(len(s.rel_dir) > 0)
            self.assertTrue(len(s.category) > 0)

    def test_custom_project_names(self):
        """Verify known custom compose project overrides."""
        by_rel = {s.rel_dir: s for s in self.services}

        self.assertIn("Media/comics/gateway", by_rel)
        self.assertEqual(by_rel["Media/comics/gateway"].custom_project_name, "media-comics-gateway")

        if "Media/local-media/managers/bazarr" in by_rel:
            self.assertEqual(by_rel["Media/local-media/managers/bazarr"].name, "bazarr")

    def test_target_resolution_exact_queries(self):
        """Test exact name and path resolutions."""
        test_cases = [
            ("bazarr", "Media/local-media/managers/bazarr"),
            ("jellyfin", "Media/local-media/players/jellyfin"),
            ("Media/comics/gateway", "Media/comics/gateway"),
            ("Utilities/tools/supabase", "Utilities/tools/supabase"),
            ("Network", "Network"),
        ]

        for query, expected_rel in test_cases:
            matches, errors = resolve_targets(self.services, [query])
            self.assertEqual(len(errors), 0, f"Unexpected error for query '{query}': {errors}")
            self.assertEqual(len(matches), 1, f"Expected 1 match for query '{query}'")
            self.assertEqual(matches[0].rel_dir, expected_rel)

    def test_target_resolution_ambiguous_query(self):
        """Verify ambiguous queries return structured error explanations."""
        matches, errors = resolve_targets(self.services, ["gateway"])
        self.assertEqual(len(matches), 0)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("Ambiguous" in err for err in errors))

    def test_appdata_paths_discovery(self):
        """Verify appdata paths discovery for backup and doctor actions."""
        paths_a = discover_appdata_paths(target_vps="A", base_path="/docker/appdata")
        paths_b = discover_appdata_paths(target_vps="B", base_path="/docker/appdata")
        paths_all = discover_appdata_paths(target_vps="ALL", base_path="/docker/appdata")

        self.assertIsInstance(paths_a, list)
        self.assertIsInstance(paths_b, list)
        self.assertIsInstance(paths_all, list)
        self.assertEqual(set(paths_all), set(paths_a) | set(paths_b))
        for p in paths_all:
            self.assertTrue(Path(p).is_absolute())


if __name__ == "__main__":
    unittest.main()
