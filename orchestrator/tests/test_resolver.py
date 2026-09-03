"""Unit tests for 3-tier target query resolution."""

import unittest

from orchestrator.registry.manifest import load_services
from orchestrator.registry.resolver import resolve_all_services, resolve_targets


class TestTargetResolver(unittest.TestCase):
    """Test 3-tier resolution: exact path, short name/custom project, and suffix matching."""

    @classmethod
    def setUpClass(cls):
        cls.services = load_services()

    def test_tier1_exact_relative_path(self):
        """Tier 1: Query by full relative directory path."""
        res, errors = resolve_targets(self.services, ["Media/local-media/managers/bazarr"])
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].name, "bazarr")
        self.assertEqual(res[0].rel_dir, "Media/local-media/managers/bazarr")

    def test_tier2_exact_service_name(self):
        """Tier 2: Query by short service name."""
        res, errors = resolve_targets(self.services, ["jellyfin"])
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].name, "jellyfin")

    def test_tier2_custom_project_name(self):
        """Tier 2: Query by custom compose project name."""
        res, errors = resolve_targets(self.services, ["media-comics-gateway"])
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].rel_dir, "Media/comics/gateway")

    def test_tier3_path_suffix(self):
        """Tier 3: Query by path suffix."""
        res, errors = resolve_targets(self.services, ["managers/sonarr"])
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].name, "sonarr")

    def test_case_insensitivity(self):
        """Resolution must be case-insensitive."""
        res, errors = resolve_targets(self.services, ["JELLYFIN", "media/LOCAL-media/managers/BAZARR"])
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(res), 2)

    def test_unknown_service_returns_error(self):
        """Unknown queries return clean error messages."""
        res, errors = resolve_targets(self.services, ["nonexistent-service"])
        self.assertEqual(len(res), 0)
        self.assertEqual(len(errors), 1)
        self.assertIn("No compose project matching 'nonexistent-service'", errors[0])

    def test_cross_vps_mismatch_detection(self):
        """Querying a VPS B service with an active VPS A filter returns an informative error when strict_vps=True."""
        res, errors = resolve_targets(self.services, ["aiostreams"], vps="A", strict_vps=True)
        self.assertEqual(len(res), 0)
        self.assertEqual(len(errors), 1)
        self.assertIn("assigned to VPS B, but active filter is VPS A", errors[0])

    def test_cross_vps_non_strict_filtering(self):
        """Querying with strict_vps=False silently filters out other node services without errors."""
        # pocketid is on VPS A, aiostreams is on VPS B
        res_a, errors_a = resolve_targets(
            self.services,
            ["Utilities/auth/pocketid", "Media/stremio/addons/aiostreams"],
            vps="A",
            strict_vps=False,
        )
        self.assertEqual(len(errors_a), 0)
        self.assertEqual(len(res_a), 1)
        self.assertEqual(res_a[0].name, "pocketid")

        res_b, errors_b = resolve_targets(
            self.services,
            ["Utilities/auth/pocketid", "Media/stremio/addons/aiostreams"],
            vps="B",
            strict_vps=False,
        )
        self.assertEqual(len(errors_b), 0)
        self.assertEqual(len(res_b), 1)
        self.assertEqual(res_b[0].name, "aiostreams")

        # When no services match the target node with strict_vps=False
        res_empty, errors_empty = resolve_targets(
            self.services,
            ["Utilities/auth/pocketid"],
            vps="B",
            strict_vps=False,
        )
        self.assertEqual(len(errors_empty), 0)
        self.assertEqual(len(res_empty), 0)

    def test_duplicate_query_suppression(self):
        """Duplicate queries in the same invocation are cleanly deduplicated."""
        res, errors = resolve_targets(self.services, ["bazarr", "Media/local-media/managers/bazarr", "bazarr"])
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].name, "bazarr")

    def test_resolve_all_services_filtering(self):
        """resolve_all_services correctly filters by node."""
        all_svcs = resolve_all_services(self.services)
        self.assertEqual(len(all_svcs), 80)

    def test_deploy_workflow_target_filtering_scenarios(self):
        """Simulate deploy.yml workflow target filtering logic across multiple change scenarios."""
        # 1. VPS A only change (e.g. pocketid)
        dirs_a = ["Utilities/auth/pocketid"]
        matched_a, _ = resolve_targets(self.services, dirs_a, vps="A", strict_vps=False)
        matched_b, _ = resolve_targets(self.services, dirs_a, vps="B", strict_vps=False)
        self.assertEqual([s.name for s in matched_a], ["pocketid"])
        self.assertEqual(len(matched_b), 0)

        # 2. VPS B only change (e.g. aiostreams)
        dirs_b = ["Media/stremio/addons/aiostreams"]
        matched_a, _ = resolve_targets(self.services, dirs_b, vps="A", strict_vps=False)
        matched_b, _ = resolve_targets(self.services, dirs_b, vps="B", strict_vps=False)
        self.assertEqual(len(matched_a), 0)
        self.assertEqual([s.name for s in matched_b], ["aiostreams"])

        # 3. Mixed changes across VPS A and VPS B
        dirs_mixed = ["Utilities/auth/pocketid", "Utilities/admin/hawser"]
        matched_a, _ = resolve_targets(self.services, dirs_mixed, vps="A", strict_vps=False)
        matched_b, _ = resolve_targets(self.services, dirs_mixed, vps="B", strict_vps=False)
        self.assertEqual([s.name for s in matched_a], ["pocketid"])
        self.assertEqual([s.name for s in matched_b], ["hawser"])


if __name__ == "__main__":
    unittest.main()
