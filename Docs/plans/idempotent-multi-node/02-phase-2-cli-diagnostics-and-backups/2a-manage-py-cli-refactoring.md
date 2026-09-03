# 2a: Unified CLI Refactoring (`manage.py`)

> **Sub-Phase:** 2a  
> **Target:** `manage.py` Argument Parsing & Subcommand Routing  

---

## 1. Objective

Upgrade [`manage.py`](manage.py) to support `--node <id>` and `-n <id>` across all subcommands (`deploy`, `redeploy`, `stop`, `update`, `status`, `doctor`, `backup`, `secrets`, `node`), while preserving full backward-compatibility for legacy `--vps A|B` arguments.

---

## 2. Implementation: `manage.py` Routing Updates

### A. Argument Extraction Helper
Use `argparse` (or the existing parser abstraction) rather than a permissive hand-rolled
loop. The parser must reject missing values, repeated/conflicting `--node` and `--vps`
flags, unknown node IDs, and bare positional `A`/`B` values. Legacy aliases normalize
only after syntax validation and emit a deprecation notice.

The following illustrates normalization after parsing, not a replacement parser:
```python
def normalize_node_arg(node=None, legacy_vps=None):
    if node is not None and legacy_vps is not None:
        raise UsageError("--node and --vps are mutually exclusive")
    candidate = node or {"A": "vps-a", "B": "vps-b"}.get(legacy_vps)
    if candidate is not None and candidate not in get_all_node_ids():
        raise UsageError("unknown topology node")
    return candidate
```

### B. Subcommand Routing Updates
Update subcommands to forward the resolved `node_id`:
* **`./manage.py deploy [--node <id>]`** ➔ calls `deploy.py --node <node_id>`
* **`./manage.py status [--node <id>] [--cluster]`** ➔ calls `status.inspect_stack_status(node=node_id, cluster=is_cluster)`
* **`./manage.py doctor [--node <id>]`** ➔ calls `doctor.run_diagnostics(node=node_id)`
* **`./manage.py backup [run|restore|check] [--node <id>]`** ➔ passes `--node <id>` to shell scripts
* **`./manage.py secrets [snapshot|snapshots|prune] [--node <id>]`** ➔ passes `node_id` to Doppler and Snapshot managers

### C. Node Management Subcommand (`./manage.py node`)
Add dedicated node configuration helpers:
```bash
./manage.py node current       # Prints currently resolved active Node ID and source
./manage.py node list          # Lists all nodes defined in topology.yaml with IPs and status
./manage.py node set <id>      # Sets local .node_id file
```

---

## 3. Verification Criteria
* `./manage.py deploy --node vps-a --dry-run` runs successfully.
* `./manage.py deploy --vps A --dry-run` behaves identically (backward compatibility verified).
* `./manage.py node current` prints the active node ID and resolution source.
* Parser tests cover missing values, conflicting aliases, repeated flags, unknown nodes,
  accidental bare positional values, and option ordering for every affected subcommand.
