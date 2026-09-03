# Phase 5: UI Modularization, Shell Migration, Script Internals Fix, Legacy Deletion & Docs Sweep

> **Branch:** `feat/orchestrator-phase5-ui-legacy-cleanup` (off `epic/modular-orchestrator`)  
> **Status:** Complete (Merged into epic/modular-orchestrator)

---

## 1. Objectives

1. Decompose `Scripts/deploy/core/tui.py` into `orchestrator/ui/` (`dashboard.py`, `inspector.py`, `prompts.py`).
2. Move remaining bash scripts from `Scripts/` to `orchestrator/scripts/` and fix internal depth anchors (`/../../..`), explicit hook paths, and embedded Python imports (`discover_appdata_paths`).
3. Run the final golden parity test run (`test_registry_parity.py`), delete all 14 legacy `Scripts/deploy/core/*.py` modules + 9 colocated tests, delete legacy bash scripts replaced by Python (`reset-tailscale.sh`, `sync-snapshots.sh`), and convert `test_registry_parity.py` into a static snapshot regression test.
4. Sweep operational docs in `Docs/`, rebase `Docs/plans/idempotent-multi-node/`, update CI workflows (`deploy.yml`, `.gitlab-ci.yml`), and verify root crontabs across both VPS nodes.

---

## 2. Technical Specification & File Architecture

### 2.1 File Map
```
orchestrator/
├── ui/
│   ├── __init__.py
│   ├── dashboard.py        # Interactive Rich TUI dashboard engine
│   ├── inspector.py        # Live container health & port inspection table
│   └── prompts.py          # Confirmation gates & terminal raw-mode context
└── scripts/
    ├── backup/             # backup-all.sh, restore-all.sh, backup-check.sh, backup-prune.sh, backup-stats.sh, pre-backup-hook.sh, post-backup-hook.sh
    ├── network/            # fix-routing.sh
    ├── utils/              # build-local-app.sh, update-netbird-server.sh
    └── hooks/              # pre-commit, install-hooks.sh
```

### 2.2 Complete Legacy Deletion Inventory (14 Non-Test Modules + Tests)
- `Scripts/deploy/core/discovery.py`
- `Scripts/deploy/core/tui.py`
- `Scripts/deploy/core/doppler_manager.py`
- `Scripts/deploy/core/snapshot_manager.py`
- `Scripts/deploy/core/updater.py`
- `Scripts/deploy/core/check_upgrades.py`
- `Scripts/deploy/core/utils.py`
- `Scripts/deploy/core/validator.py`
- `Scripts/deploy/core/logs.py`
- `Scripts/deploy/core/status.py`
- `Scripts/deploy/core/history.py`
- `Scripts/deploy/core/commands.py`
- `Scripts/deploy/core/doctor.py`
- `Scripts/deploy/core/sops_bootstrap.py`
- 9 colocated tests (`Scripts/deploy/core/test_*.py`)
- `Scripts/test_manage_backup.py` and `Scripts/test_manage_secrets.py`
- Legacy bash scripts replaced by Python: `Scripts/network/reset-tailscale.sh`, `Scripts/utils/sync-snapshots.sh`

---

## 3. Commit Milestone Checklist

- [x] **Milestone 5.1: Presentation Layer Decomposition**
  - Refactor `Scripts/deploy/core/tui.py` into `orchestrator/ui/dashboard.py`, `inspector.py`, `prompts.py`.
  - Wire `./manage.py` default entrypoint (no args) to `orchestrator.ui.dashboard`.
  - **Commit:** `feat(ui): decompose tui into modular presentation components`

- [x] **Milestone 5.2: Shell Scripts Relocation & Internal Fixes**
  - Move remaining bash scripts to `orchestrator/scripts/`.
  - Fix directory depth anchors (`/../..` -> `/../../..`) in `build-local-app.sh`, `backup-all.sh`, `restore-all.sh`, `update-netbird-server.sh`.
  - Fix internal hook and helper paths (`backup-all.sh:368,446` -> `orchestrator/scripts/backup/pre-backup-hook.sh`, `install-hooks.sh:29` -> `orchestrator/scripts/hooks/pre-commit`).
  - Fix embedded Python imports in `backup-all.sh:301` and `pre-backup-hook.sh:50` to `from orchestrator.registry.discovery import discover_appdata_paths`.
  - Update all 24 `manage.py` subprocess paths to point to `orchestrator/scripts/...`.
  - **Commit:** `refactor(scripts): move shell scripts to orchestrator/scripts/ and fix internal paths`

- [x] **Milestone 5.3: Final Parity Verification & Legacy Module Deletion**
  - Run the final golden parity test run (`test_registry_parity.py`).
  - Delete all 14 legacy Python non-test modules under `Scripts/deploy/core/*.py` + 9 colocated tests + top-level legacy tests.
  - Delete legacy shell scripts replaced by native Python (`reset-tailscale.sh`, `sync-snapshots.sh`).
  - Convert `test_registry_parity.py` into a static snapshot regression test against `services.yaml`.
  - **Commit:** `chore(legacy): purge legacy Scripts/deploy/core modules and convert parity test`

- [x] **Milestone 5.4: Docs Sweep, CI Sync & Full System Verification**
  - Update `AGENTS.md` and active operational guides in `Docs/` (`BACKUP_RESTORE_GUIDE.md`, `DOPPLER_OPERATIONS_GUIDE.md`, `NETWORK_ARCHITECTURE.md`, `NETBIRD_SELFHOSTING.md`, `RENOVATE_AUTOMATION_GUIDE.md`, `SOPS_DOPPLER_SNAPSHOT_PLAN.md`).
  - Rebase `Docs/plans/idempotent-multi-node/` to target `orchestrator/` packages.
  - Update `.github/workflows/deploy.yml` change-detection regex to `^orchestrator/|^manage\.py|^\.env\.example`.
  - Update `.gitlab-ci.yml` path filters and test commands to drop `Scripts/`.
  - Verify root backup crontabs across both VPS nodes execute `./manage.py backup run`.
  - Run complete unit test and validation suites across the repository.
  - **Commit:** `docs(sweep): sweep operational guides and synchronize ci workflows for orchestrator`
