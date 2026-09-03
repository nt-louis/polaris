# 2b: Status & Doctor Diagnostic Scoping

> **Sub-Phase:** 2b  
> **Target:** `Scripts/deploy/core/status.py` & `Scripts/deploy/core/doctor.py`  

---

## 1. Objective

Ensure that `./manage.py status` and `./manage.py doctor`:
1. **Scope to Local Active Node by Default:** Query Docker daemon only for services that belong to the active host node (`.node_id`), eliminating false "Stopped" records.
2. **Support a truthful cluster inventory (`--cluster` / `--all-nodes`):** Group
   projects by node, but report remote runtime state as `unknown/unqueried` until the
   authenticated Phase 4 remote probe is available.
3. **Verify Node-Specific Health:** `doctor.py` checks Tailscale IP, Gluetun gateways, policy routing, and disk space for the specific active node.

---

## 2. Implementation: `status.py` Scoping

Update [`Scripts/deploy/core/status.py`](Scripts/deploy/core/status.py):

```python
def inspect_stack_status(node=None, cluster=False, json_output=False):
    """Inspect and report status of stack services.
    
    If cluster=False (default), scopes discovery strictly to the active node.
    If cluster=True, displays all nodes across the cluster.
    """
    active_node = node or get_active_node_id()
    
    projects = (
        discover_compose_projects()
        if cluster
        else discover_compose_projects(node_filter=active_node)
    )

    containers = get_docker_containers()
    container_map = {c.get("Names"): c for c in containers}

    status_rows = []
    for p in projects:
        if p["node"] != active_node:
            status_rows.append({
                "project": p["name"],
                "node": p["node"],
                "state": "unknown",
                "status": "unqueried",
                "source": "inventory-only",
            })
            continue

        # Match container from local Docker socket
        matched = match_container(p, container_map)
        
        status_rows.append({
            "project": p["name"],
            "node": p["node"],
            "category": p["category"],
            "container": matched.get("Names", p["name"]),
            "state": matched.get("State", "exited"),
            "status": matched.get("Status", "Stopped"),
            "ports": matched.get("Ports", ""),
        })

    if json_output:
        print(json.dumps(status_rows, indent=2))
        return 0

    render_status_table(status_rows, active_node=active_node, cluster=cluster)
    return 0
```

---

## 3. Implementation: `doctor.py` Node Checks

Update [`Scripts/deploy/core/doctor.py`](Scripts/deploy/core/doctor.py):

```python
def check_node_identity():
    """Verify active node resolution and topology registration."""
    node_id = get_active_node_id()
    topology = load_topology()
    if node_id not in topology.get("nodes", {}):
        return False, f"Node '{node_id}' is not registered in topology.yaml."
    node_name = topology["nodes"][node_id].get("name", node_id)
    return True, f"Active Node: {node_id} ({node_name})"

def check_tailscale_routing(node_id):
    """Verify Tailscale routing and policy tables for this specific node."""
    # Verifies local mesh identity against the node's configured FQDN/aliases.
    node_cfg = get_node_config(node_id)
    expected_fqdn = node_cfg["tailscale_fqdn"]
    # Validates policy routing priority 50 table 52
    ...
```

---

## 4. Verification Criteria
* Running `./manage.py status` on `vps-a` shows only `vps-a` services (all running/healthy).
* During Phase 2, `./manage.py status --cluster` shows full inventory but labels every
  remote runtime state `unknown/unqueried`; it never infers `exited` from the local
  Docker socket.
* After Phase 4, authenticated remote observations replace `unknown/unqueried` and
  include an observation timestamp and node identity.
* Running `./manage.py doctor` reports `[OK] Node Identity: vps-a` and passes all checks.
