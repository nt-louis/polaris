# Phase 1: CI Setup, Data Contracts, Manifest, Resolver & Golden Parity Test

> **Branch:** `feat/orchestrator-phase1-registry` (off `epic/modular-orchestrator`)  
> **Status:** Complete (Verified 100% Golden Parity across all 79 services)

---

## 1. Objectives

1. Enable CI linting, pytest, and manifest drift validation for `orchestrator/**` on GitHub Actions and GitLab CI from Day 1.
2. Implement core data contracts (`models.py`, `constants.py`).
3. Construct the central `services.yaml` declarative manifest capturing all 79 compose services with extensible multi-node support (`nodes:` with `{id, name}` objects).
4. Implement the zero-dependency manifest loader (`manifest.py`), 3-tier resolver (`resolver.py`), and discovery helper (`discovery.py`).
5. Write the golden parity test suite (`test_registry_parity.py`) asserting 100% field-by-field equality against legacy `discovery.py`.

---

## 2. Technical Specification & File Architecture

### 2.1 File Map
```
orchestrator/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── constants.py       # REPO_ROOT, EXCLUDE_DIRS
│   └── models.py          # ServiceTier, ContainerStatus, ServiceMetadata, ActionContext, ExecutionResult
├── registry/
│   ├── __init__.py
│   ├── services.yaml      # Declarative service manifest (79 services)
│   ├── manifest.py        # Manifest loader & schema validation (PyYAML + stdlib only)
│   ├── resolver.py        # 3-tier target resolution engine
│   └── discovery.py       # discover_appdata_paths() & directory scan
└── tests/
    ├── __init__.py
    ├── test_registry_parity.py # 79/79 project golden parity vs discovery.py
    ├── test_manifest.py        # Schema validation & drift tests
    └── test_resolver.py        # Target resolution unit tests
```

### 2.2 Schema Contract (`services.yaml`)
```yaml
schema_version: 1

defaults:
  compose_file: docker-compose.yml
  vps: A
  tier: 2

# Supported VPS/Node targets (extensible to any arbitrary count)
nodes:
  - id: A
    name: Primary Core & Media Stack
  - id: B
    name: Secondary Stremio & Tooling Node

services:
  # -------------------------------------------------------------
  # Network Gateways
  # -------------------------------------------------------------
  - name: gateway-core
    path: Media/local-media/gateway
    category: Network (Gateways)
    tier: 0
    custom_project: network-media-local-media-gateway
    vps: A

  - name: gateway-b
    path: Utilities/gateway-b
    category: Network (Gateways)
    tier: 0
    custom_project: network-utilities-gateway-b
    vps: B

  # -------------------------------------------------------------
  # Core Infrastructure & Auth
  # -------------------------------------------------------------
  - name: pocketid
    path: Utilities/auth/pocketid
    category: Utilities (Auth)
    tier: 1
    vps: A

  - name: oauth2-proxy
    path: Utilities/auth/oauth2-proxy
    category: Utilities (Auth)
    tier: 1
    vps: A

  # -------------------------------------------------------------
  # Local Media Stack
  # -------------------------------------------------------------
  - name: bazarr
    path: Media/local-media/managers/bazarr
    category: Media/local-media (Managers)
    tier: 2
    vps: A
    network_dependency: media-gateway-core-gluetun

  - name: jellyfin
    path: Media/local-media/players/jellyfin
    category: Media/local-media (Players)
    tier: 2
    vps: A
    network_dependency: media-gateway-core-gluetun

  - name: aiostreams
    path: Media/stremio/addons/aiostreams
    category: Media/stremio
    tier: 2
    vps: B
    network_dependency: stremio-addons-gateway-gluetun
```

---

## 3. Commit Milestone Checklist

- [x] **Milestone 1.1: CI Multi-Engine Setup & Epic Branch Triggers**
  - Update `.github/workflows/python-ci.yml`:
    - Add `epic/modular-orchestrator` and `"epic/**"` to `push.branches` and `pull_request.branches`.
    - Add `orchestrator/**` to `paths:`.
    - Add `orchestrator/` to `pytest` and `ruff check`.
  - Update `.github/workflows/validate-compose.yml`:
    - Add `epic/modular-orchestrator` and `"epic/**"` to `push.branches` and `pull_request.branches`.
    - Add `orchestrator/registry/services.yaml` to `paths:`.
    - Add Manifest Drift Validation step running PyYAML check.
  - Update `.gitlab-ci.yml`:
    - Add `orchestrator/**` to paths, ruff check, and test discovery.
    - Add `services.yaml` trigger and manifest drift check to `validate-compose`.
  - **Commit:** `ci(workflows): add orchestrator paths, epic triggers, and manifest drift checks to github and gitlab ci`

- [x] **Milestone 1.2: Core Constants & Domain Models**
  - Create `orchestrator/__init__.py` and `orchestrator/core/__init__.py`.
  - Implement `orchestrator/core/constants.py` defining `REPO_ROOT` and `EXCLUDE_DIRS`.
  - Implement `orchestrator/core/models.py` defining `ServiceTier`, `ContainerStatus`, `ServiceMetadata`, `ActionContext`, `ExecutionResult`.
  - **Commit:** `feat(core): implement core constants and domain models`

- [x] **Milestone 1.3: Central Declarative Services Manifest**
  - Implement `orchestrator/registry/services.yaml` capturing all 79 active compose projects across `Network/`, `Utilities/`, `Media/`.
  - Populate explicit `vps`, `category`, `tier`, and `custom_project`.
  - **Commit:** `feat(registry): create central declarative services.yaml manifest`

- [x] **Milestone 1.4: Manifest Loader & Schema Validator**
  - Implement `orchestrator/registry/manifest.py` with `load_manifest(path)` and `validate_manifest(data)`.
  - Enforce zero third-party dependencies outside stdlib + `PyYAML`.
  - **Commit:** `feat(registry): implement manifest loader and schema validation`

- [x] **Milestone 1.5: 3-Tier Target Query Resolver & Discovery Helper**
  - Implement `orchestrator/registry/resolver.py` supporting exact path, custom name, and directory suffix resolution.
  - Implement `orchestrator/registry/discovery.py` supporting `discover_appdata_paths()` and drift detection.
  - **Commit:** `feat(registry): implement target query resolver and discovery helpers`

- [x] **Milestone 1.6: Golden Parity Test Suite & Verification**
  - Implement `orchestrator/tests/test_registry_parity.py` asserting 100% field equality across all 79 services against legacy `discovery.py`.
  - Implement `orchestrator/tests/test_manifest.py` and `orchestrator/tests/test_resolver.py`.
  - Run `python3 -m unittest discover -s orchestrator/tests` and verify all tests pass.
  - **Commit:** `test(registry): add golden parity and manifest resolution test suites`
