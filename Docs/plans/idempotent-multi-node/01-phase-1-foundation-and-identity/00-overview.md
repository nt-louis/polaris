# Phase 1: Foundation & Identity Primitives

> **Phase:** 1 of 5  
> **Target:** Manifest Schema, Node Resolution & Dynamic Discovery Engine  
> **Status:** Draft / Actionable  

---

## 1. Overview & Objective

Phase 1 establishes the core foundational primitives for multi-node operations without altering any running containers or moving any compose files on disk yet.

By the end of Phase 1:
1. The repository has a validated declarative manifest ([`topology.yaml`](topology.yaml)) defining all nodes, tags, Doppler projects, and network endpoints.
2. The runtime engine has a deterministic node resolver (`get_active_node_id()`) that resolves identity from CLI flags, env vars, host `.node_id` files, or hostname fallbacks.
3. The discovery engine ([`Scripts/deploy/core/discovery.py`](Scripts/deploy/core/discovery.py)) scans the retained `Network/`, `Media/`, and `Utilities/` roots and classifies every project through `topology.yaml`.
4. Comprehensive unit tests validate all parsing, fallbacks, and discovery logic.

---

## 2. Granular Task Breakdown

| Document | Focus Area | Deliverable |
| :--- | :--- | :--- |
| [`1a-topology-manifest-spec.md`](./1a-topology-manifest-spec.md) | Central Manifest | `topology.yaml` specification, schema, and Python loader. |
| [`1b-node-identity-resolver.md`](./1b-node-identity-resolver.md) | Node Identity | `get_active_node_id()` & `.node_id` resolution hierarchy in `utils.py`. |
| [`1c-dynamic-discovery-refactoring.md`](./1c-dynamic-discovery-refactoring.md) | Discovery Engine | `discovery.py` refactoring with topology-driven scanning and legacy fallbacks. |
| [`1d-unit-tests-and-validation.md`](./1d-unit-tests-and-validation.md) | Verification | Unit tests for topology loader, node resolver, and discovery matrix. |

---

## 3. Definition of Done (DoD) Checklist

- [ ] `topology.yaml` is committed to the repository root.
- [ ] `Scripts/deploy/core/topology.py` exists with `load_topology()` and schema validation.
- [ ] `get_active_node_id()` in `Scripts/deploy/core/utils.py` handles `--node`, `NET_STREAM_NODE`, `.node_id`, and hostname.
- [ ] `discovery.py` discovers projects for `vps-a` and `vps-b` without hardcoded path checks.
- [ ] All unit tests in `Scripts/deploy/core/test_topology.py` and `test_discovery.py` pass.
- [ ] Zero regression on existing CLI commands (`./manage.py status`, `./manage.py doctor`).
