# SOPS + Doppler Snapshot Fallback — Implementation Plan

## Problem

Doppler SaaS is the sole secret source at deploy time. If Doppler is
unreachable (outage, auth token expiry on a fresh clone, network partition),
`doppler run` fails and no deployment can proceed. The entire deploy pipeline
has a hard external dependency on a SaaS endpoint being online.

## Decision

Keep Doppler as the **single write surface and source of truth**. Add
SOPS-encrypted snapshots committed to git as a **read-only cold backup layer**.
`manage.py deploy` falls back to these snapshots automatically when Doppler is
unreachable. No dual write paths, no Infisical migration.

Doppler's security posture (SOC 2 Type II, dedicated security engineering,
secret-zero handling) is better than anything self-hosted. The goal is
resilience against availability failures, not a migration away from Doppler.

---

## Architecture

```
                  ┌──────────────────────────────────────┐
                  │         Doppler SaaS (authoritative)  │
                  │   net-stream-vps-a / net-stream-vps-b │
                  └──────────────┬───────────────────────┘
                                 │  doppler secrets download
                                 │  (on snapshot command)
                                 ▼
                  ┌──────────────────────────────────────┐
                  │   SOPS + age encrypted snapshots      │
                  │   .snapshots/<project>/<config>.env.enc │
                  │   committed to git                    │
                  └──────────────┬───────────────────────┘
                                 │  fallback: age -d → inject into subprocess env
                                 ▼
                  ┌──────────────────────────────────────┐
                  │   docker compose                      │
                  │   (doppler run  OR  snapshot fallback)│
                  └──────────────────────────────────────┘
```

---

## Components

### 1. `.snapshots/` directory

- Layout: `.snapshots/net-stream-vps-a/<config>.env.enc`, `.snapshots/net-stream-vps-b/<config>.env.enc`
- One encrypted file per Doppler config (mirrors the `project/config` namespace exactly)
- Committed to git — pre-commit hook must cover this directory to block plaintext `.env` files from leaking in
- `.sops.yaml` restored at repo root with the existing age public key (`age1f8wtud5d8ss9kenyytvzfa0y09kxfxg2zlmw9jv9v7suj6d8w5xskq9672`, recoverable from git history per `Docs/DOPPLER_MIGRATION_COMMIT_REFERENCE.md`)

### 2. `orchestrator/secrets/snapshots.py` (snapshot module)

Key functions:

- `snapshot_all(vps_context)` — exports all Doppler configs for a VPS via `doppler secrets download --format env`, encrypts each with `age`, writes to `.snapshots/`. Auto-commits with message `chore(secrets): refresh <vps> snapshot YYYY-MM-DD`.
- `snapshot_config(project, config)` — single-config snapshot for use after rotating a specific secret.
- `restore_env_from_snapshot(project, config) -> dict` — decrypts a snapshot file in-memory using `age -d`, returns a `key→value` dict. **No disk write.**
- `is_snapshot_available(project, config) -> bool` — checks whether a snapshot file exists for a given config.
- `list_snapshots()` — prints snapshot inventory with timestamps sourced from `git log`.

The private age key location follows the same resolution order as the old `sops_manager.py`: `keys.txt` in repo root, then `~/.config/sops/age/keys.txt`, then `$SOPS_AGE_KEY_FILE`.

### 3. `orchestrator/secrets/doppler.py` — fallback in `wrap_compose_command`

Current behaviour: if `is_doppler_enabled()` returns False, returns the raw command unwrapped (no secrets injected).

New behaviour:

```python
def wrap_compose_command(cmd, rel_dir, service_name, category_name="", vps_context="A"):
    if is_doppler_enabled():
        materialize_transient_env(...)   # existing path — no change
        return doppler_prefix + cmd

    # Fallback: inject from snapshot
    project = get_doppler_project(vps_context)
    config  = get_doppler_config(rel_dir, service_name, category_name)
    if snapshot_manager.is_snapshot_available(project, config):
        log("[WARN] Doppler unavailable — falling back to SOPS snapshot")
        # Caller passes snapshot_env into subprocess via env= kwarg
        # wrap_compose_command returns (cmd, snapshot_env) in fallback mode
        snapshot_env = snapshot_manager.restore_env_from_snapshot(project, config)
        return cmd, snapshot_env

    raise RuntimeError(
        f"Doppler unavailable and no snapshot found for {config}. "
        f"Run: ./manage.py secrets snapshot --vps {vps_context}"
    )
```

`deploy.py` already passes `env=` to subprocess calls — augment it with `snapshot_env` when the fallback tuple form is returned.

For services that declare `env_file:` in compose, `materialize_transient_env` gains a parallel fallback path: decrypt snapshot → write transient `0600` `.env` → register for cleanup on exit.

### 4. `manage.py secrets` — two new subcommands

| Subcommand | Behaviour |
|---|---|
| `./manage.py secrets snapshot [--vps A\|B]` | Full snapshot of all configs for a VPS. Encrypts and commits. |
| `./manage.py secrets snapshot-config <config> [--vps A\|B]` | Single-config snapshot. Useful immediately after rotating a secret. |

Both are read-only with respect to Doppler (download only). Neither writes plaintext to disk beyond the transient download buffer.

---

## Snapshot workflow (normal operations)

### After rotating a secret

```bash
# 1. Rotate in Doppler dashboard
# 2. Refresh snapshot
./manage.py secrets snapshot --vps A
# → auto-commits: chore(secrets): refresh vps-a snapshot 2026-08-15
# 3. Redeploy affected service
./manage.py redeploy <service>
```

### Periodic refresh (recommended: weekly or after any secret change)

```bash
./manage.py secrets snapshot --vps A
./manage.py secrets snapshot --vps B
```

The snapshot commit timestamp in `git log` tells you exactly how stale the fallback is.

### Emergency fallback (Doppler unreachable)

No manual steps needed — `manage.py deploy` detects Doppler failure and switches to snapshot injection automatically. A `[WARN]` line is printed to make the fallback visible in logs.

---

## What the snapshots do NOT replace

- Doppler remains the write surface. Never edit `.snapshots/` files directly.
- Snapshots are bounded by their last refresh — if you rotated a secret and did not re-snapshot, the fallback will inject the old value. The git commit timestamp makes staleness explicit.
- Raw `docker compose` commands (discouraged per AGENTS.md) will not benefit from snapshot fallback — only `manage.py` flows do.

---

## Pre-commit hook update

The existing hook blocks `.env` and `.env.vps-*` files. It must be extended to also block any plaintext file under `.snapshots/` (i.e. files matching `.snapshots/**` that are not `*.env.enc`).

---

## Implementation order

1. Restore `.sops.yaml` at repo root (age public key only — no private key in repo)
2. Verify age private key is present on both VPS hosts at expected path
3. Implement `orchestrator/secrets/snapshots.py`
4. Add `secrets snapshot` and `secrets snapshot-config` subcommands to `manage.py`
5. Update `wrap_compose_command` fallback in `orchestrator/secrets/doppler.py`
6. Update `materialize_transient_env` fallback for `env_file:` services
7. Extend pre-commit hook to cover `.snapshots/`
8. Run initial snapshot for VPS A and VPS B
9. Update `Docs/DOPPLER_OPERATIONS_GUIDE.md` and `AGENTS.md` with snapshot workflow

---

## Key references in git history

The old `sops_manager.py` (commit `e642532`, last mature SOPS state before Doppler migration) contains the `encrypt_file`, `decrypt_file`, and `setup_env` primitives that `snapshot_manager.py` can reuse directly. See `Docs/DOPPLER_MIGRATION_COMMIT_REFERENCE.md` for restore commands.
