# Phase 4: Maintenance Orchestrators, Worktree Sync & Router Expansion

> **Branch:** `feat/orchestrator-phase4-maintenance` (off `epic/modular-orchestrator`)  
> **Status:** Queued (Blocked by Phase 3)

---

## 1. Objectives

1. Implement update action orchestrator (`update.py`) wrapping registry check, age-gating, and container restart.
2. Implement backup and restore action orchestrator (`backup.py`) preserving the post-backup auto-sync chain (`manage.py:466-471`).
3. Implement secrets action (`secrets.py`) and native Python git worktree snapshot sync (`snapshots.py`, absorbing `sync-snapshots.sh`).
4. Implement doctor diagnostic probes (`doctor.py`) and manifest drift validation (`validate.py` with `--fix`).
5. Migrate top-level CLI tests (`test_manage_backup.py`, `test_manage_secrets.py`) to `orchestrator/tests/`.
6. Expand `manage.py` strangler-fig router for maintenance commands and audit/migrate user snapshot crontabs on VPS A and VPS B.

---

## 2. Technical Specification & File Architecture

### 2.1 File Map
```
orchestrator/
├── secrets/
│   └── snapshots.py        # Native Python git worktree sync for .snapshots/ to secrets-snapshots branch
├── actions/
│   ├── update.py           # Image upgrade, age-gate, and container refresh action
│   ├── backup.py           # Restic backup & restore orchestrator (with auto-sync chain)
│   ├── secrets.py          # Doppler SaaS & snapshot management action
│   ├── doctor.py           # Pre-flight infrastructure diagnostic probes
│   └── validate.py         # Compose, Caddyfile, and Manifest drift verification
└── tests/
    ├── test_manage_backup.py  # Migrated backup router tests
    └── test_manage_secrets.py # Migrated secrets router tests
```

---

## 3. Commit Milestone Checklist

- [x] **Milestone 4.1: Update & Image Upgrade Action**
  - Implement `orchestrator/actions/update.py` (wrapping registry inspection, image age gating, and container restart).
  - **Commit:** `feat(actions): implement update action orchestrator with age-gating`

- [x] **Milestone 4.2: Backup & Restore Action**
  - Implement `orchestrator/actions/backup.py` (Restic orchestration: run, restore, snapshots, check, prune, stats).
  - Guarantee post-backup auto-sync chain: on backup success, trigger snapshot sync via `secrets/snapshots.py`.
  - **Commit:** `feat(actions): implement backup and restore action orchestrator`

- [x] **Milestone 4.3: Secrets Action & Offline Git Worktree Snapshot Sync**
  - Implement `orchestrator/secrets/snapshots.py` (absorbing `sync-snapshots.sh` git worktree logic into native Python).
  - Implement `orchestrator/actions/secrets.py` (open, verify, sync, audit, prune, snapshot, snapshots, sync-branch).
  - **Commit:** `feat(actions): implement secrets action orchestrator and worktree snapshot sync`

- [x] **Milestone 4.4: Pre-flight Doctor & Manifest Drift Validator**
  - Implement `orchestrator/actions/doctor.py` (Doppler, Tailscale, Docker, VPN pre-flight probes).
  - Implement `orchestrator/actions/validate.py` (Compose syntax, Caddy routing, and `services.yaml` drift `--fix`).
  - **Commit:** `feat(actions): implement doctor and manifest drift validation actions`

- [x] **Milestone 4.5: Migrate CLI Tests & Expand Router**
  - Migrate `Scripts/test_manage_backup.py` and `Scripts/test_manage_secrets.py` to `orchestrator/tests/`.
  - Expand `manage.py` router to dispatch `update`, `backup`, `doctor`, `validate`, and `secrets` to `orchestrator.actions.*`.
  - Audit and migrate user snapshot crontabs on VPS A and VPS B to `./manage.py secrets sync-branch`.
  - **Commit:** `refactor(cli): expand hybrid router for maintenance actions and migrate cli test suite`
