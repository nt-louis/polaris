"""Unit tests for services.yaml manifest loader, validator, and drift detection."""

import unittest

from orchestrator.registry.discovery import detect_manifest_drift
from orchestrator.registry.manifest import (
    get_default_node_id,
    get_node,
    get_node_tailscale_name,
    get_registered_nodes,
    get_valid_node_ids,
    load_services,
    validate_manifest,
)


class TestManifestValidation(unittest.TestCase):
    """Test schema validation edge cases and error messages."""

    def test_valid_manifest_loads_cleanly(self):
        """Standard services.yaml must validate with 0 errors and produce 80 services."""
        services = load_services()
        self.assertEqual(len(services), 80)
        nodes = get_registered_nodes()
        self.assertEqual(len(nodes), 3)
        node_ids = {n.id for n in nodes}
        self.assertEqual(node_ids, {"A", "B", "C"})

        node_a = get_node("A")
        self.assertIsNotNone(node_a)
        self.assertEqual(node_a.id, "A")
        self.assertEqual(node_a.tailscale_name, "vps")

        node_b = get_node("B")
        self.assertIsNotNone(node_b)
        self.assertEqual(node_b.id, "B")
        self.assertEqual(node_b.tailscale_name, "vps2")

        node_c = get_node("C")
        self.assertIsNotNone(node_c)
        self.assertEqual(node_c.id, "C")
        self.assertEqual(node_c.tailscale_name, "vps-c")

        self.assertEqual(get_node_tailscale_name("A"), "vps")
        self.assertEqual(get_node_tailscale_name("B"), "vps2")
        self.assertEqual(get_node_tailscale_name("C"), "vps-c")
        self.assertIsNone(get_node_tailscale_name("NONEXISTENT"))

        self.assertEqual(get_default_node_id(), "A")
        self.assertEqual(get_valid_node_ids(), {"A", "B", "C"})

    def test_invalid_schema_version(self):
        """Schema version other than 1 should trigger a validation error."""
        data = {
            "schema_version": 2,
            "nodes": [{"id": "A", "name": "Node A"}],
            "services": [{"name": "test", "path": "Network"}],
        }
        errors = validate_manifest(data)
        self.assertTrue(any("Unsupported schema_version" in e for e in errors))

    def test_missing_nodes(self):
        """Manifest without nodes should fail validation."""
        data = {
            "schema_version": 1,
            "nodes": [],
            "services": [{"name": "test", "path": "Network"}],
        }
        errors = validate_manifest(data)
        self.assertTrue(any("'nodes' must be a non-empty list" in e for e in errors))

    def test_unregistered_node_reference(self):
        """A service pointing to an unlisted node must be rejected."""
        data = {
            "schema_version": 1,
            "nodes": [{"id": "A", "name": "Node A"}],
            "services": [
                {"name": "test", "path": "Network", "vps": "Z", "tier": 0}
            ],
        }
        errors = validate_manifest(data)
        self.assertTrue(any("references unregistered node 'Z'" in e for e in errors))

    def test_invalid_tier(self):
        """Tier out of bounds (0-3) must be rejected."""
        data = {
            "schema_version": 1,
            "nodes": [{"id": "A", "name": "Node A"}],
            "services": [
                {"name": "test", "path": "Network", "vps": "A", "tier": 99}
            ],
        }
        errors = validate_manifest(data)
        self.assertTrue(any("invalid tier: 99" in e for e in errors))

    def test_duplicate_service_path(self):
        """Two service entries pointing to the same path must fail validation."""
        data = {
            "schema_version": 1,
            "nodes": [{"id": "A", "name": "Node A"}],
            "services": [
                {"name": "test1", "path": "Network", "vps": "A", "tier": 0},
                {"name": "test2", "path": "Network", "vps": "A", "tier": 0},
            ],
        }
        errors = validate_manifest(data)
        self.assertTrue(any("Duplicate service path" in e for e in errors))

    def test_manifest_drift_is_zero(self):
        """Active filesystem compose projects must exactly match services.yaml."""
        missing, extra = detect_manifest_drift()
        self.assertEqual(missing, set(), f"Unregistered compose paths found on disk: {missing}")
        self.assertEqual(extra, set(), f"Dead paths registered in services.yaml: {extra}")


if __name__ == "__main__":
    unittest.main()
