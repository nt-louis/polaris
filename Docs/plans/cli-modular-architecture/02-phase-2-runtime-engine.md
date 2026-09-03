# Phase 2: Complete Execution Runtime (Docker Engine, Network DAG & Secrets)

> **Branch:** `feat/orchestrator-phase2-runtime` (off `epic/modular-orchestrator`)  
> **Status:** Complete (Merged into `epic/modular-orchestrator`)

---

## 1. Objectives

1. Build the typed Docker client (`client.py`) and compose runner (`compose.py`).
2. Implement healthcheck probe and container readiness polling (`readiness.py`).
3. Implement container logs resolver and stream runner (`logs.py`).
4. Implement sidecar network dependency DAG (`graph.py`) and interface routing state (`routing.py`).
5. Implement Doppler CLI process wrapper (`doppler.py`) and transient 0600 `.env` manager (`transient.py`).
6. Implement SOPS key path resolver (`sops.py`, omitting binary downloader) and runtime unit tests.

---

## 2. Technical Specification & File Architecture

### 2.1 File Map
```
orchestrator/
├── docker/
│   ├── __init__.py
│   ├── client.py           # Typed Docker CLI wrapper (ps, stop, inspect, container status)
│   ├── compose.py          # Compose executor (up, down, pull, build, config)
│   ├── readiness.py        # Health probe and container readiness wait loops
│   └── logs.py             # Container log resolver and streaming
├── network/
│   ├── __init__.py
│   ├── graph.py            # Sidecar dependency DAG & topological sorter
│   └── routing.py          # reset_tailscale_state() & apply_routing_fix()
├── secrets/
│   ├── __init__.py
│   ├── doppler.py          # Doppler CLI wrapper & process variable injection
│   ├── transient.py        # Secure 0600 .env materialization & cleanup
│   └── sops.py             # setup_age_key_env() key resolution
└── tests/
    ├── test_docker.py      # Docker client and compose engine mock tests
    ├── test_network.py     # DAG dependency sorter tests
    └── test_secrets.py     # Doppler wrapper and transient env tests
```

---

## 3. Commit Milestone Checklist

- [x] **Milestone 2.1: Typed Docker CLI Wrapper**
  - Implement `orchestrator/docker/client.py` (`get_container_status`, `inspect_container`, `stop_containers`).
  - **Commit:** `feat(docker): implement typed docker cli client`

- [x] **Milestone 2.2: Compose Executor & Readiness Poller**
  - Implement `orchestrator/docker/compose.py` (`compose_up`, `compose_down`, `compose_pull`, `compose_build`, `compose_config`).
  - Implement `orchestrator/docker/readiness.py` (polling health checks with configurable timeouts).
  - **Commit:** `feat(docker): implement compose executor and readiness polling engine`

- [x] **Milestone 2.3: Container Log Streamer**
  - Implement `orchestrator/docker/logs.py` (resolving short service names to container names and streaming logs).
  - **Commit:** `feat(docker): implement container logs streaming handler`

- [x] **Milestone 2.4: Network Dependency DAG & Routing Utilities**
  - Implement `orchestrator/network/graph.py` (DAG topological sorter replacing procedural sort keys).
  - Implement `orchestrator/network/routing.py` (`reset_tailscale_state()`, `apply_routing_fix()`).
  - **Commit:** `feat(network): implement dependency graph DAG and routing engine`

- [x] **Milestone 2.5: Doppler CLI Wrapper & Transient 0600 `.env` Manager**
  - Implement `orchestrator/secrets/doppler.py` (wrapping compose commands with Doppler credentials).
  - Implement `orchestrator/secrets/transient.py` (creating 0600 `.env` for `env_file` services with guaranteed context-manager cleanup).
  - **Commit:** `feat(secrets): implement doppler wrapper and transient env manager`

- [x] **Milestone 2.6: SOPS Key Resolver & Runtime Unit Tests**
  - Implement `orchestrator/secrets/sops.py` (absorbing `setup_age_key_env()`, omitting binary downloader).
  - Implement `orchestrator/tests/test_docker.py`, `test_network.py`, and `test_secrets.py` with mock subprocess runners.
  - Run all tests and verify passing status.
  - **Commit:** `feat(secrets): implement sops key resolver and runtime unit tests`
