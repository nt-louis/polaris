# SOPS + Doppler Snapshot Fallback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement an offline, read-only SOPS/age encrypted snapshot fallback layer for Doppler secrets, ensuring zero-downtime deployment resilience during SaaS outages or network partitions without compromising security.

**Architecture:** Doppler SaaS remains the exclusive write surface and source of truth. Offline snapshots are exported via `doppler secrets download`, encrypted with `age` via SOPS (`.sops.yaml`), and stored under `.snapshots/<project>/<config>.env.enc` committed to git. When Doppler is unreachable, `manage.py deploy` and `doppler_manager.py` transparently decrypt snapshots in-memory, inject variables into process execution, and write transient `0600` `.env` files for services requiring `env_file:`. Missing binaries (`sops` / `age`) are bootstrapped automatically to `bin/`.

**Tech Stack:** Python 3.10+, SOPS v3.9+, age v1.2+, Docker Compose v2, Git pre-commit hook.

---

### Task 1: Restore `.sops.yaml` and Bootstrap Binary Helper

**Files:**
- Create: `.sops.yaml`
- Create: `Scripts/deploy/core/sops_bootstrap.py`
- Test: `Scripts/deploy/core/test_sops_bootstrap.py`

**Step 1: Write failing test for binary bootstrap locator**

```python
# Scripts/deploy/core/test_sops_bootstrap.py
import unittest
from unittest.mock import patch
import os
from Scripts.deploy.core.sops_bootstrap import find_binary, ensure_sops_age_binaries

class TestSopsBootstrap(unittest.TestCase):
    @patch("shutil.which")
    def test_find_binary_system(self, mock_which):
        mock_which.return_value = "/usr/local/bin/sops"
        self.assertEqual(find_binary("sops"), "/usr/local/bin/sops")

    @patch("shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    def test_find_binary_local_bin(self, mock_exists, mock_which):
        path = find_binary("sops")
        self.assertTrue(path.endswith(os.path.join("bin", "sops")))
```

**Step 2: Run test to verify it fails**
Run: `python3 -m unittest Scripts/deploy/core/test_sops_bootstrap.py`
Expected: FAIL (module not found)

**Step 3: Implement `.sops.yaml` and `sops_bootstrap.py`**
- Create `.sops.yaml` at repo root with `age1f8wtud5d8ss9kenyytvzfa0y09kxfxg2zlmw9jv9v7suj6d8w5xskq9672`.
- Implement `find_binary`, `ensure_sops_age_binaries`, and platform-aware download helpers targeting the local `bin/` directory.

**Step 4: Run test to verify it passes**
Run: `python3 -m unittest Scripts/deploy/core/test_sops_bootstrap.py`
Expected: PASS

**Step 5: Commit**
```bash
git add .sops.yaml Scripts/deploy/core/sops_bootstrap.py Scripts/deploy/core/test_sops_bootstrap.py
git commit -m "feat(secrets): add .sops.yaml configuration and binary bootstrap helper"
```

---

### Task 2: Implement Core `SnapshotManager` Engine

**Files:**
- Create: `Scripts/deploy/core/snapshot_manager.py`
- Test: `Scripts/deploy/core/test_snapshot_manager.py`

**Step 1: Write failing test for snapshot operations**

```python
# Scripts/deploy/core/test_snapshot_manager.py
import unittest
from unittest.mock import patch, MagicMock
from Scripts.deploy.core.snapshot_manager import SnapshotManager

class TestSnapshotManager(unittest.TestCase):
    @patch("subprocess.run")
    def test_is_snapshot_available(self, mock_run):
        sm = SnapshotManager()
        # Test availability check against .snapshots path
        self.assertFalse(sm.is_snapshot_available("net-stream-vps-a", "nonexistent_cfg"))

    @patch("subprocess.run")
    def test_restore_env_from_snapshot_in_memory(self, mock_run):
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "FOO=bar\nBAZ=qux\n"
        mock_run.return_value = mock_res
        
        sm = SnapshotManager()
        with patch("os.path.exists", return_value=True):
            env_dict = sm.restore_env_from_snapshot("net-stream-vps-a", "test_cfg")
            self.assertEqual(env_dict, {"FOO": "bar", "BAZ": "qux"})
```

**Step 2: Run test to verify it fails**
Run: `python3 -m unittest Scripts/deploy/core/test_snapshot_manager.py`
Expected: FAIL (module not found)

**Step 3: Implement `snapshot_manager.py`**
Implement the `SnapshotManager` class:
- `get_snapshot_path(project, config)` -> `.snapshots/<project>/<config>.env.enc`
- `is_snapshot_available(project, config)`
- `snapshot_config(project, config)` (downloads via `doppler secrets download`, encrypts via `sops --encrypt`, writes ciphertext)
- `snapshot_all(vps_context)` (loops through all configs in project, snapshots each)
- `restore_env_from_snapshot(project, config)` (decrypts in-memory via `sops --decrypt`, parses dotenv into dict without writing to disk)
- `get_snapshot_timestamp(project, config)` (queries git log for creation date of the encrypted file)

**Step 4: Run test to verify it passes**
Run: `python3 -m unittest Scripts/deploy/core/test_snapshot_manager.py`
Expected: PASS

**Step 5: Commit**
```bash
git add Scripts/deploy/core/snapshot_manager.py Scripts/deploy/core/test_snapshot_manager.py
git commit -m "feat(secrets): implement core snapshot manager for SOPS/age encrypted backups"
```

---

### Task 3: Integrate Transparent Snapshot Fallback in `doppler_manager.py`

**Files:**
- Modify: `Scripts/deploy/core/doppler_manager.py`
- Test: `Scripts/deploy/core/test_doppler_manager.py`

**Step 1: Write failing test for transparent fallback execution**

```python
# In Scripts/deploy/core/test_doppler_manager.py
@patch("Scripts.deploy.core.doppler_manager.is_doppler_enabled", return_value=False)
@patch("Scripts.deploy.core.snapshot_manager.SnapshotManager.is_snapshot_available", return_value=True)
@patch("Scripts.deploy.core.snapshot_manager.SnapshotManager.restore_env_from_snapshot", return_value={"FALLBACK_VAR": "true"})
def test_wrap_compose_command_fallback(self, mock_restore, mock_avail, mock_doppler):
    cmd = ["docker", "compose", "up", "-d"]
    wrapped = wrap_compose_command(cmd, "Utilities/auth/authelia", "authelia", "auth", "A")
    self.assertEqual(wrapped, cmd)
    self.assertEqual(os.environ.get("FALLBACK_VAR"), "true")
```

**Step 2: Run test to verify it fails**
Run: `python3 -m unittest Scripts/deploy/core/test_doppler_manager.py`
Expected: FAIL

**Step 3: Update `doppler_manager.py`**
- In `wrap_compose_command`: When `not is_doppler_enabled()`, query `SnapshotManager`.
- If snapshot is available:
  - Log `[WARN] Doppler unavailable — falling back to SOPS snapshot (YYYY-MM-DD)`.
  - Inject decrypted dictionary into `os.environ` for subprocess inheritance.
  - If service requires `env_file:`, write transient `0600` `.env` with `atexit` cleanup.
  - Return `cmd` cleanly (maintaining signature consistency across callers).
- If snapshot is unavailable, raise informative `RuntimeError` directing user to run snapshot command.

**Step 4: Run test to verify it passes**
Run: `python3 -m unittest Scripts/deploy/core/test_doppler_manager.py`
Expected: PASS

**Step 5: Commit**
```bash
git add Scripts/deploy/core/doppler_manager.py Scripts/deploy/core/test_doppler_manager.py
git commit -m "feat(deploy): wire transparent SOPS snapshot fallback into wrap_compose_command"
```

---

### Task 4: Expose `secrets snapshot` Subcommands in CLI and TUI

**Files:**
- Modify: `manage.py`
- Modify: `Scripts/deploy/core/tui.py`
- Test: `Scripts/test_manage.py`

**Step 1: Write failing test for `manage.py secrets snapshot`**

```python
# In Scripts/test_manage.py
@patch("Scripts.deploy.core.snapshot_manager.SnapshotManager.snapshot_all", return_value=True)
def test_secrets_snapshot_subcommand(self, mock_snapshot_all):
    res = run_manage(["secrets", "snapshot", "--vps", "A"])
    self.assertEqual(res.returncode, 0)
    mock_snapshot_all.assert_called_once_with("A")
```

**Step 2: Run test to verify it fails**
Run: `python3 -m unittest Scripts/test_manage.py`
Expected: FAIL

**Step 3: Implement CLI and TUI bindings**
- Add `snapshot`, `snapshot-config`, and `snapshots` (list) subcommands to `manage.py secrets`.
- Add snapshot actions to TUI secrets management dashboard in `Scripts/deploy/core/tui.py`.

**Step 4: Run test to verify it passes**
Run: `python3 -m unittest Scripts/test_manage.py`
Expected: PASS

**Step 5: Commit**
```bash
git add manage.py Scripts/deploy/core/tui.py Scripts/test_manage.py
git commit -m "feat(cli): add secrets snapshot subcommands and TUI actions"
```

---

### Task 5: Update Pre-Commit Guard, Documentation, and Take Initial Snapshots

**Files:**
- Modify: `Scripts/utils/hooks/pre-commit`
- Modify: `Docs/DOPPLER_OPERATIONS_GUIDE.md`
- Modify: `AGENTS.md`
- Create: `.snapshots/net-stream-vps-a/*.env.enc` & `.snapshots/net-stream-vps-b/*.env.enc`

**Step 1: Update Pre-Commit Hook**
- Ensure `Scripts/utils/hooks/pre-commit` allows `.snapshots/**/*.env.enc` while blocking any unencrypted files under `.snapshots/`.

**Step 2: Execute Initial Snapshot Generation**
- Run `./manage.py secrets snapshot --vps A`
- Run `./manage.py secrets snapshot --vps B`

**Step 3: Update Architecture Documentation**
- Document the snapshot fallback workflow, age key resolution, and rotation refresh steps in `Docs/DOPPLER_OPERATIONS_GUIDE.md` and `AGENTS.md`.

**Step 4: Run Full Repository Validation**
- Run: `python3 -m unittest discover -s Scripts/deploy/core && python3 -m unittest discover -s Scripts`
- Run: `./manage.py validate`
- Run: `./manage.py hooks verify`

**Step 5: Commit**
```bash
git add Scripts/utils/hooks/pre-commit Docs/DOPPLER_OPERATIONS_GUIDE.md AGENTS.md .snapshots/
git commit -m "chore(secrets): take initial SOPS snapshots and document fallback operations"
```
