# 5d: Developer & Operator Guide

> **Sub-Phase:** 5d  
> **Target:** Updating AGENTS.md, README.md, and Operations Guides  

---

## 1. Objective

Update repository operational documentation to codify the new multi-node architecture, CLI flags, and standards.

---

## 2. Updates to `AGENTS.md`

1. Document the retained `Network/`, `Media/`, and `Utilities/` functional layout and
   topology-driven physical placement.
2. Update CLI command cheat-sheet to feature `--node <id>`.
3. Document `topology.yaml` as the central cluster source of truth.
4. Add the **New Node Addition Checklist**:
   1. Register node in `topology.yaml` (name, Doppler project, Tailscale FQDN, backup repo).
   2. Add explicit placement, namespace, listen-port, state, and diagnostic records for
      workloads assigned to the node; do not create a node-owned repository tree.
   3. Provision GitHub runner with labels `[self-hosted, <node-id>]`.
   4. Create Doppler project `polaris-<node-id>` inheriting from root `prd`.
   5. Set host `.node_id` file via `./manage.py node set <node-id>`.

---

## 3. Updates to `README.md` & Architecture Docs
* Update `Docs/NETWORK_ARCHITECTURE.md` with multi-node mesh topology.
* Update `Docs/BACKUP_RESTORE_GUIDE.md` with multi-node Restic repository paths.
* Document exact snapshot selection, state mappings, reverse migration, split-brain
  fencing, and encrypted-secret recovery drills.
