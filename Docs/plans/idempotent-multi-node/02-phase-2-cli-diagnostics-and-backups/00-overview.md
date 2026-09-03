# Phase 2: CLI, Diagnostics & Backup Engine Refactoring

> **Phase:** 2 of 5  
> **Target:** Scoped Management, Health Probes, Restic Pipeline & Offline Snapshots  
> **Status:** Draft / Actionable  

---

## 1. Overview & Objective

Phase 2 refactors the CLI, status inspectors, doctor diagnostics, Restic backups, and SOPS snapshot managers to be fully **node-aware and scoped to the active environment**.

By the end of Phase 2:
1. `./manage.py` accepts `--node <id>` / `-n <id>` universally (while keeping `--vps A|B` as aliases).
2. `./manage.py status` queries only the active node's containers by default, eliminating false "Stopped" alerts for foreign containers.
3. `./manage.py doctor` validates node-specific network rules and gateway configurations.
4. The TUI dashboard displays active node identity and enables seamless node switching.
5. The Restic backup engine (`backup-all.sh`, `restore-all.sh`) namespaces volume repositories dynamically per node identity.
6. `SnapshotManager` handles arbitrary `net-stream-<node-id>` project mappings with zero hardcoded assumptions.

---

## 2. Granular Task Breakdown

| Document | Focus Area | Deliverable |
| :--- | :--- | :--- |
| [`2a-manage-py-cli-refactoring.md`](./2a-manage-py-cli-refactoring.md) | Universal CLI | `--node` flag parsing, command routing, and backward-compatible `--vps` aliasing. |
| [`2b-status-and-doctor-scoping.md`](./2b-status-and-doctor-scoping.md) | Diagnostics | Scoped status inspector, `--cluster` mode, and node-aware pre-flight doctor checks. |
| [`2c-tui-control-center-updates.md`](./2c-tui-control-center-updates.md) | Interactive TUI | Node identity header, cluster filter menu, and multi-node status rendering. |
| [`2d-restic-backup-pipeline-updates.md`](./2d-restic-backup-pipeline-updates.md) | Backup & Disaster Recovery | `backup-all.sh`, `restore-all.sh`, and `backup-check.sh` node namespacing. |
| [`2e-snapshot-manager-node-support.md`](./2e-snapshot-manager-node-support.md) | Secrets Snapshots | SOPS snapshot cold fallback supporting dynamic `net-stream-<node-id>` projects. |

---

## 3. Definition of Done (DoD) Checklist

- [ ] `./manage.py deploy --node vps-a` and `./manage.py deploy --node vps-b` execute accurately.
- [ ] `./manage.py status` on `vps-a` only reports status for `vps-a` services.
- [ ] `./manage.py doctor` reports active node and verifies node-specific network rules.
- [ ] `./manage.py backup run --node <id>` runs backups namespaced to that node's repository.
- [ ] `SnapshotManager` list/snapshot operations work across arbitrary node IDs.
- [ ] Unit tests pass for all updated CLI modules.
