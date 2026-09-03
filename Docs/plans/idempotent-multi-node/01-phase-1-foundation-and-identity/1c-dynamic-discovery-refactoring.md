# 1c: Dynamic Service Discovery Refactoring

> **Sub-Phase:** 1c  
> **Target:** `Scripts/deploy/core/discovery.py`  

---

## 1. Objective

Refactor [`Scripts/deploy/core/discovery.py`](Scripts/deploy/core/discovery.py) to:
1. Eliminate hardcoded arrays (`VPS_B_PREFIXES`, `get_vps_assignment`).
2. Scan the retained functional roots declared in `repository.compose_roots` exactly
   once, then classify each Compose project through `resolve_placement()`.
3. Fail validation on unmatched or ambiguous projects instead of silently assigning
   them to a default node.
4. Return standardized project dictionaries containing:
   * `name`: Project/Service name
   * `node`: Assigned Node ID (e.g. `vps-a`)
   * `doppler_project`: Associated Doppler project (e.g. `net-stream-vps-a`)
   * `category`: Formatted human-readable category
   * `abs_dir`: Absolute path to compose directory
   * `rel_dir`: Relative path from repository root
   * `file`: Compose filename (`docker-compose.yml`)

---

## 2. Implementation: `discovery.py`

```python
import os
from topology import load_topology, resolve_placement
from utils import EXCLUDE_DIRS, REPO_ROOT

def get_service_category(rel_dir):
    """Derive clean human-readable category from directory structure."""
    parts = rel_dir.split(os.sep)
    if len(parts) >= 2:
        return f"{parts[0]} ({parts[1].replace('-', ' ').title()})"
    return "General"

def discover_compose_projects(node_filter=None):
    """Discover all docker-compose projects across the cluster or for a specific node.
    
    Args:
        node_filter (str, optional): If specified, only return projects for this Node ID.
    """
    topology = load_topology()
    nodes = topology.get("nodes", {})
    if node_filter is not None and node_filter not in nodes:
        raise ValueError(f"Unknown node: {node_filter}")

    discovered = []
    for rel_root in topology["repository"]["compose_roots"]:
        base_path = os.path.join(REPO_ROOT, rel_root)
        for root, dirs, files in os.walk(base_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                if f in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml", "compose.yml", "mongo.compose.yaml"):
                    rel_dir = os.path.relpath(root, REPO_ROOT)
                    proj_name = os.path.basename(root)

                    placement = resolve_placement(rel_dir)
                    node_id = placement["node"]
                    if node_filter is not None and node_id != node_filter:
                        continue
                    node_cfg = nodes[node_id]

                    discovered.append({
                        "name": proj_name,
                        "node": node_id,
                        # Backward-compatible 'vps' key for legacy callers during migration:
                        "vps": "A" if node_id == "vps-a" else "B" if node_id == "vps-b" else node_id,
                        "doppler_project": node_cfg["doppler_project"],
                        "gateway": placement.get("gateway"),
                        "category": get_service_category(rel_dir),
                        "abs_dir": root,
                        "rel_dir": rel_dir,
                        "file": f,
                    })

    return discovered
```

---

## 3. Verification Criteria
* `discover_compose_projects(node_filter="vps-a")` returns only VPS A services.
* `discover_compose_projects(node_filter="vps-b")` returns only VPS B services.
* `discover_compose_projects()` returns every active project under the declared roots
  without duplicates; the expected count is derived from the repository fixture rather
  than hardcoded as 79.
* Contains backward-compatible `p["vps"]` field so existing TUI/CLI scripts don't break during migration.
* Adding a Compose project without a placement causes topology validation to fail.
