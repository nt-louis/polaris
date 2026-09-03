# Phase 3: Core Action Orchestrators, Deploy Forwarding Shim & Strangler-Fig Router

> **Branch:** `feat/orchestrator-phase3-actions-shim` (off `epic/modular-orchestrator`)  
> **Status:** Queued (Blocked by Phase 2)

---

## 1. Objectives

1. Implement core state tracking (`state.py`) and audit logging (`history.py`).
2. Implement core action orchestrators (`base.py`, `deploy.py`, `stop.py`, `redeploy.py`, `status.py`, `logs.py`, `history.py`, `dependency_report.py`).
3. Convert `Scripts/deploy/deploy.py` into a thin forwarding shim that delegates `sys.argv[1:]` verbatim to `orchestrator.actions.deploy.main()`, immediately unifying local `./manage.py deploy` and production CI `deploy.yml` with zero drift.
4. Refactor `manage.py` into a strangler-fig hybrid router dispatching migrated actions directly to `orchestrator.actions.*`, removing the dead `utils env` stub, and normalizing deprecated CLI aliases (§7.4).

---

## 2. Technical Specification & File Architecture

### 2.1 File Map
```
orchestrator/
├── core/
│   ├── state.py            # .active_vps context & .last_deploy_<vps> state tracking
│   └── history.py          # Action audit logging & persistence (.history.jsonl)
├── actions/
│   ├── __init__.py
│   ├── base.py             # BaseAction abstract contract
│   ├── deploy.py           # Deploy workflow (gateways -> core infra -> standard apps)
│   ├── stop.py             # Stop workflow (targeted, VPS-scoped, global)
│   ├── redeploy.py         # Active container refresh & recreate workflow
│   ├── status.py           # Real-time container health & port inspection action
│   ├── logs.py             # Stream container logs action
│   ├── history.py          # Operation audit log viewer action
│   └── dependency_report.py# Container dependency report generator action
manage.py                   # Strangler-fig hybrid router dispatching to orchestrator.actions.*
Scripts/deploy/deploy.py    # Zero-drift forwarding shim delegating verbatim to orchestrator.actions.deploy
```

### 2.2 Forwarding Shim Implementation (`Scripts/deploy/deploy.py`)
```python
#!/usr/bin/env python3
import sys
from pathlib import Path

# Ensure repo root is at the head of sys.path when executed directly by CI runners or external callers
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.actions.deploy import main

if __name__ == "__main__":
    sys.exit(main())
```

---

## 3. Commit Milestone Checklist

- [x] **Milestone 3.1: Core State Tracking & Audit History Persistence**
  - Implement `orchestrator/core/state.py` (`get_active_vps`, `set_active_vps`, `get_last_deploy_services`, `save_last_deploy_services`).
  - Implement `orchestrator/core/history.py` (structured append-only `.history.jsonl` audit logging).
  - **Commit:** `feat(core): implement state context and operation history audit persistence`

- [x] **Milestone 3.2: Base Action Contract, Stop, Status, Logs & History Actions**
  - Implement `orchestrator/actions/base.py` (`BaseAction` interface).
  - Implement `orchestrator/actions/stop.py`, `orchestrator/actions/status.py`, `orchestrator/actions/logs.py`, `orchestrator/actions/history.py`.
  - **Commit:** `feat(actions): implement stop, status, logs, and history action orchestrators`

- [x] **Milestone 3.3: Deploy & Redeploy Orchestrators**
  - Implement `orchestrator/actions/deploy.py` (consuming DAG graph, Doppler injection, transient env, readiness waits).
  - Implement `orchestrator/actions/redeploy.py` (refreshing active containers with build/recreate flags).
  - **Commit:** `feat(actions): implement deploy and redeploy orchestrators`

- [x] **Milestone 3.4: Dependency Report Action**
  - Implement `orchestrator/actions/dependency_report.py` (generating Markdown table of container images and upstream tags).
  - **Commit:** `feat(actions): implement dependency report action orchestrator`

- [x] **Milestone 3.5: Production Zero-Drift Deploy Forwarding Shim**
  - Convert `Scripts/deploy/deploy.py` into a thin forwarding shim with `sys.path` anchoring that delegates `sys.argv[1:]` verbatim to `orchestrator.actions.deploy.main()` and preserves exit codes.
  - Verify the forwarding shim locally via `python3 Scripts/deploy/deploy.py --dry-run --vps A` and `./manage.py deploy --dry-run --vps A` from a clean checkout, ensuring complete `argv` fidelity and zero regression.
  - **Commit:** `feat(deploy): convert legacy deploy.py into orchestrator forwarding shim`

- [x] **Milestone 3.6: Strangler-Fig Hybrid Router & CLI Alias Normalization**
  - Refactor `manage.py` to route core commands (`deploy`, `stop`, `redeploy`, `status`, `logs`, `history`, `dependency-report`) directly to `orchestrator.actions.*`.
  - Remove dead `manage.py utils env` stub.
  - Normalize all six legacy aliases in `manage.py` (§7.4):
    1. `./manage.py deploy --redeploy` → `./manage.py redeploy`
    2. `./manage.py deploy --stop` → `./manage.py stop`
    3. `./manage.py utils report` → `./manage.py utils dependency-report`
    4. `./manage.py secrets sync-snapshots` → `./manage.py secrets sync-branch`
    5. `./manage.py network fix-routing` → `./manage.py network fix`
    6. `./manage.py network reset-tailscale` → `./manage.py network reset`
  - **Commit:** `refactor(cli): implement strangler-fig hybrid router in manage.py and normalize aliases`
