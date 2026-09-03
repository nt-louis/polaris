# 2c: TUI Dashboard & Control Center Updates

> **Sub-Phase:** 2c  
> **Target:** `Scripts/deploy/core/tui.py`  

---

## 1. Objective

Upgrade the interactive Text User Interface (TUI) dashboard to:
1. Display the active **Node ID** in the top header banner (e.g. `[NODE: vps-a]`).
2. Add a **Node Switcher** shortcut (`[N]` or dropdown) to filter services by node.
3. Update keybindings and help screens to reflect the node-centric architecture.
4. Treat non-local node selections as inventory-only in Phase 2; runtime state remains
   `unknown/unqueried` until the Phase 4 diagnostic agent is available.

---

## 2. Implementation: `tui.py` Enhancements

### A. Header Rendering
Update dashboard header in [`Scripts/deploy/core/tui.py`](Scripts/deploy/core/tui.py):
```python
def render_header(active_node):
    topology = load_topology()
    node_name = topology.get("nodes", {}).get(active_node, {}).get("name", active_node)
    title = f"Polaris Control Center  •  Node: [{active_node.upper()}] ({node_name})"
    # Renders banner using Rich Panel
```

### B. Node Filtering & Keybinding (`[N]`)
Add hotkey `[N]` / `[n]` in `interactive_dashboard`:
```python
elif key in (ord('n'), ord('N')):
    # Cycles through registered nodes: vps-a -> vps-b -> all -> vps-a
    active_node_index = (active_node_index + 1) % (len(all_nodes) + 1)
    # Re-renders project menu filtered by selected node
```

### C. Footer Keybindings
Update footer prompt text:
```
[D] Doctor  [S] Status  [L] Logs  [N] Switch Node  [Q] Quit
```

---

## 3. Verification Criteria
* Launching `./manage.py` displays `Node: [VPS-A]` in the header.
* Pressing `[N]` cycles the service list smoothly between node views.
* Pressing `[D]` launches node-scoped doctor diagnostics.
