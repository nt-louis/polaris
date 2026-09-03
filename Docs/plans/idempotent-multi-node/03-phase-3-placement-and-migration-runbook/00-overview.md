# Phase 3: Placements & Automated State Migration Engine

> **Phase:** 3 of 5  
> **Target:** Dual-Level Placements, Migration Hooks & Namespace Invariants  
> **Status:** Draft / Actionable  

---

## 1. Overview & Objective

Phase 3 establishes the **workload placement engine** and **automated volume migration pipeline** without requiring disruptive physical directory restructuring:

1. **Logical Organization Retained:** Services remain neatly organized by functional domain (`Media/local-media/`, `Media/stremio/`, `Utilities/auth/`, `Network/`).
2. **Dual-Level Placement:** Supports moving complete shared-namespace consistency
   groups or relocating individual services with explicit network rebinding.
3. **Automated State Migration Hook (`manage.py migrate-workload`):** Implements a
   journaled transaction with pre-flight/locking, source quiescence, an exact verified
   snapshot, staged target restore, health-gated cutover, and automatic source recovery.
4. **Namespace Invariant Validation:** `./manage.py validate` resolves both
   `network_mode: service:<service>` and `network_mode: container:<container-name>`,
   checks co-location, and enforces declared per-namespace listen-port ownership.

---

## 2. Granular Task Breakdown

| Document | Focus Area | Deliverable |
| :--- | :--- | :--- |
| [`3a-cluster-and-service-placements.md`](./3a-cluster-and-service-placements.md) | Placements | Dual-level placement modeling in `topology.yaml` & network rebinding rules. |
| [`3b-state-migration-hook-pipeline.md`](./3b-state-migration-hook-pipeline.md) | Migration Hook | Journaled, rollback-capable state migration (`./manage.py migrate-workload`). |
| [`3c-namespace-invariants-and-validation.md`](./3c-namespace-invariants-and-validation.md) | Invariant Guard | Linter rules in `manage.py validate` for network co-location and port collisions. |

---

## 3. Definition of Done (DoD) Checklist

- [ ] `topology.yaml` defines every real namespace owner and every workload placement.
- [ ] `./manage.py migrate-workload <service|cluster> --from <nodeA> --to <nodeB>` executes the stop ➔ backup ➔ restore ➔ start pipeline.
- [ ] `./manage.py validate` detects and flags any illegal cross-node gateway dependencies.
- [ ] Every declared repository-local or external state mapping transfers by exact
  snapshot ID with checksum, ownership, and application-consistency verification.
