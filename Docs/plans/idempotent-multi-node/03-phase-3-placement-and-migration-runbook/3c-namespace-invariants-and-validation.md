# 3c: Namespace Invariants & Placement Validation

> **Sub-Phase:** 3c  
> **Target:** Linter Rules & Invariant Enforcement in `manage.py validate`  

---

## 1. Objective

Add automated placement and namespace verification to [`manage.py validate`](manage.py) to prevent misconfigurations before deployment.

---

## 2. Invariant Rules Checked

### Rule 1: Gateway Co-Location Invariant
Every service using `network_mode: service:<service>` or
`network_mode: container:<container-name>` must be mapped to the exact same physical
node and topology namespace as its namespace owner.

```python
def validate_gateway_colocation(topology, projects):
    """Validate that all services sharing a gateway namespace reside on the same node."""
    errors = []
    owner_by_container = {}
    owner_by_project_service = {}
    for gw_id, gw_cfg in topology.get("gateways", {}).items():
        owner = gw_cfg["owner"]
        owner_by_container[owner["container_name"]] = (gw_id, gw_cfg["node"])
        owner_by_project_service[(owner["path"], owner["service"])] = (gw_id, gw_cfg["node"])

    for p in projects:
        compose_path = os.path.join(p["abs_dir"], p["file"])
        doc = load_compose_yaml(compose_path)
        for s_name, s_cfg in doc.get("services", {}).items():
            net_mode = s_cfg.get("network_mode", "")
            owner = None
            if net_mode.startswith("service:"):
                owner = owner_by_project_service.get((p["rel_dir"], net_mode.split(":", 1)[1]))
            elif net_mode.startswith("container:"):
                owner = owner_by_container.get(net_mode.split(":", 1)[1])
            if net_mode.startswith(("service:", "container:")) and owner is None:
                errors.append(f"Unknown namespace owner: {p['rel_dir']}:{s_name} -> {net_mode}")
            elif owner and (owner[1] != p["node"] or owner[0] != p.get("gateway")):
                errors.append(f"Namespace placement mismatch: {p['rel_dir']}:{s_name}")
    return errors
```

### Rule 2: Intra-Gateway Port Collision Invariant
No two services sharing the same gateway network namespace may listen on the same internal port on `127.0.0.1`.

Each placement therefore declares every TCP/UDP listening port for its services as
`listen_ports` (for example `[{port: 8096, protocol: tcp}]`). Validation builds a map
keyed by `(gateway_id, protocol, port)` and rejects duplicate owners. It also parses
Compose `ports`, `expose`, health checks, and known port environment keys to compare
observable configuration with declarations; an unexplained observed port or a service
without an audited declaration is an error, not an ignored warning. Gateway owner
published ports are checked against the same map because all members share its socket
table.

### Rule 3: Placement and state completeness

Every active Compose project must resolve to exactly one placement. Every relative
bind mount under a project's `data/`, `state/`, `config/`, database, or application-data
directory must be either included in a declared state mapping or explicitly marked
ephemeral/excluded with a reason. Source and restore paths must remain within approved
roots after symlink resolution.

---

## 3. Verification Criteria
* `./manage.py validate` detects and blocks illegal gateway splits with clear error messages.
* Passes cleanly on valid cluster configurations.
* Fixture tests cover both network-mode forms, unknown owners, gateway splits, TCP and
  UDP collisions, undeclared listeners, ambiguous placements, and missing state maps.
