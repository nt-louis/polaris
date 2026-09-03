# 1d: Unit Tests & Phase 1 Validation

> **Sub-Phase:** 1d  
> **Target:** Test Suite for Topology, Node Identity, and Dynamic Discovery  

---

## 1. Test Suite: `Scripts/deploy/core/test_topology.py`

Create `Scripts/deploy/core/test_topology.py` to validate:
1. `topology.yaml` loads correctly and caches result.
2. Missing or malformed keys raise clear exceptions.
3. `get_active_node_id()` correctly prioritizes CLI flag > Env Var > File > Hostname,
   rejects invalid values at each authoritative source, and defaults only when a
   read-only caller explicitly opts in.
4. `discover_compose_projects()` scans retained functional roots and rejects unmatched
   or ambiguous placements.

```python
import os
import unittest
from unittest.mock import patch, mock_open
import topology
import utils
import discovery

class TestTopologyAndIdentity(unittest.TestCase):

    def test_load_topology_success(self):
        topo = topology.load_topology(force_reload=True)
        self.assertIn("nodes", topo)
        self.assertIn("vps-a", topo["nodes"])
        self.assertIn("vps-b", topo["nodes"])

    def test_get_node_config_invalid_node_raises(self):
        with self.assertRaises(KeyError):
            topology.get_node_config("non-existent-node")

    def test_get_active_node_id_cli_arg_precedence(self):
        # Explicit CLI arg wins over env var and file
        with patch.dict(os.environ, {"NET_STREAM_NODE": "vps-b"}):
            self.assertEqual(utils.get_active_node_id("vps-a"), "vps-a")
            self.assertEqual(utils.get_active_node_id("A"), "vps-a")
            self.assertEqual(utils.get_active_node_id("B"), "vps-b")

    def test_get_active_node_id_env_var(self):
        with patch.dict(os.environ, {"NET_STREAM_NODE": "vps-b"}):
            self.assertEqual(utils.get_active_node_id(), "vps-b")

    def test_invalid_env_identity_fails_closed(self):
        with patch.dict(os.environ, {"NET_STREAM_NODE": "unknown"}):
            with self.assertRaises(ValueError):
                utils.get_active_node_id()

    def test_unresolved_mutating_identity_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True), patch("os.path.exists", return_value=False), patch("socket.gethostname", return_value="unknown"):
            with self.assertRaises(RuntimeError):
                utils.get_active_node_id()

    @patch("os.path.exists", return_value=True)
    def test_get_active_node_id_from_file(self, mock_exists):
        with patch("builtins.open", mock_open(read_data="vps-a")):
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(utils.get_active_node_id(), "vps-a")

    def test_discover_compose_projects_node_scoping(self):
        all_projs = discovery.discover_compose_projects()
        vps_a_projs = discovery.discover_compose_projects(node_filter="vps-a")
        vps_b_projs = discovery.discover_compose_projects(node_filter="vps-b")

        self.assertTrue(len(all_projs) > 0)
        self.assertTrue(len(vps_a_projs) > 0)
        self.assertTrue(len(vps_b_projs) > 0)
        self.assertEqual(len(all_projs), len(vps_a_projs) + len(vps_b_projs))
```

---

## 2. Phase 1 Verification Checklist
Run:
```bash
python3 -m unittest discover -s Scripts/deploy/core -p "test_topology.py"
python3 -m unittest discover -s Scripts/deploy/core
./manage.py doctor
```
All tests and diagnostics must pass cleanly before starting Phase 2.
