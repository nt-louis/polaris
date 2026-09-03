# 2e: SnapshotManager & Doppler Node Support

> **Sub-Phase:** 2e  
> **Target:** `Scripts/deploy/core/snapshot_manager.py` & `doppler_manager.py`  

---

## 1. Objective

Upgrade `SnapshotManager` and `doppler_manager.py` to:
1. Map node IDs to Doppler projects dynamically via `topology.yaml` (`get_node_config(node_id)["doppler_project"]`).
2. Store and retrieve encrypted SOPS snapshots dynamically at `.snapshots/<doppler_project>/<config>.env.enc`.
3. Support in-memory decryption from `origin/snapshots/sync` for any node without hardcoded `vps-a` / `vps-b` constraints.

---

## 2. Implementation: `doppler_manager.py` & `snapshot_manager.py`

### A. Doppler Project Resolution (`doppler_manager.py`)
```python
from topology import get_node_config

def get_doppler_project(node_id):
    """Retrieve Doppler project name for a given Node ID."""
    node_cfg = get_node_config(node_id)
    return node_cfg["doppler_project"]
```

Missing mappings are schema errors; secret operations never synthesize a project name
or fall back to another node. Tests compare key presence and required equality without
printing or retaining values.

### B. Dynamic Snapshot Operations (`snapshot_manager.py`)
```python
def snapshot_node(self, node_id):
    """Snapshot all Doppler configs for a specific Node ID."""
    project = get_doppler_project(node_id)
    # Fetches all configs for project from Doppler API and encrypts with SOPS
    ...

def list_snapshots(self, node_id=None):
    """List snapshots filtered by node or across all nodes."""
    target_project = get_doppler_project(node_id) if node_id else None
    # Lists .snapshots/ matching target_project
    ...
```

---

## 3. Verification Criteria
* `./manage.py secrets snapshot --node vps-a` refreshes VPS A snapshots in `.snapshots/`.
* `./manage.py secrets snapshots --node vps-a` lists VPS A snapshots.
* In-memory decryption from `origin/snapshots/sync` passes unit tests across all node projects.
