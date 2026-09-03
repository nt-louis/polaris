# Doppler Operations Guide

Polaris uses Doppler SaaS as the source of truth for runtime environment
variables and secrets. The repository contains `.env.example` files only as
variable-name documentation and as a schema for compose validation. Do not
copy them to `.env` or fill them with production values as part of the normal
deployment workflow.

## Required Topology

Create one Doppler project for each VPS:

| VPS | Doppler project | Repository assignment |
|---|---|---|
| A | `polaris-vps-a` | Core media, utilities, network, and default services |
| B | `polaris-vps-b` | Stremio, AI/development, and services listed in `VPS_B_PREFIXES` |

Each project contains one config per compose project. Configs are grouped in
Doppler environments by category, while config names are derived from the
repository path and service name by
`orchestrator/secrets/doppler.py`. The same config name may exist in
both projects when the service is deployed on both VPS nodes; values remain
isolated between projects.

Child configs inherit universal root secrets directly from the project root `prd`
config (e.g., `TZ`, `PUID`, `PGID`, `MEDIA_SHARE`, `TAILNET_SUFFIX`). In Doppler SaaS,
environment roots are organizational groupings, so inheritance flows from `prd` to child
configs. For offline resilience, encrypted snapshots in `.snapshots/` preserve the fully
resolved secrets for each config.

### Config Name Examples

| Repository path | Doppler environment | Config name |
|---|---|---|
| `Network/` | `network` | `network_exit_node` |
| `Media/local-media/gateway/` | `network` | `network_media_local_media_gateway` |
| `Media/comics/gateway/` | `network` | `network_media_comics_gateway` |
| `Media/stremio/addons/gateway/` | `network` | `network_media_stremio_addons_gateway` |
| `Media/stremio/addons/comet/` | `stremio` | `stremio_comet` |
| `Media/comics/shelfmark/` | `comics` | `comics_shelfmark` |
| `Utilities/auth/pocketid/` | `auth` | `auth_pocketid` |
| `Utilities/cloud-docs/nextcloud/` | `cloud_docs` | `cloud_docs_nextcloud` |
| `Utilities/tools/open-webui/` | `tools` | `tools_open_webui` |
| `Utilities/cloudflare-tunnel/` | `network` | `network_cloudflare_tunnel` |
| `Media/zurg/` | `media_zurg` | `media_zurg` |

The deployment code lowercases names, replaces non-alphanumeric characters
with underscores, collapses repeated underscores, and limits the final config
name to 60 characters. If a service is renamed or moved, its config name may
change. Create and populate the new config before deploying it.

The first component also identifies the Doppler environment used to group the
config. Current environments include `network`, `auth`, `admin`, `monitoring`,
`cloud_docs`, `tools`, `comics`, `stremio`, and `local_media`. The environment
is organizational; the manager still fetches the named service config directly.
Do not put a required service value only in the root `prd` config; it will not
automatically be available to a service config.

The authoritative VPS assignment is in
`orchestrator/registry/services.yaml`. Use `./manage.py deploy --vps A` or
`./manage.py deploy --vps B` rather than maintaining a second assignment list
in Doppler.

## Initial Setup

### 1. Install and authenticate the CLI

Install the [Doppler CLI](https://docs.doppler.com/docs/cli), then authenticate
as a user who can read both VPS projects:

```bash
doppler --version
doppler login
./manage.py secrets verify
```

Production and CI jobs use `DOPPLER_TOKEN` instead of an interactive login. The
token must have read access to the project/configs used by that job. Store it
in the host or GitHub environment secret store, never in the repository.

### 2. Synchronize configs

Run the sync tool to ensure Doppler has a matching config for every compose
project in the repository:

```bash
./manage.py secrets sync
```

This will iterate through all discovered projects and create missing configs
in the appropriate VPS project under the correct category environment.

### 3. Populate a config

Use the matching `.env.example` and compose file to identify required keys.
Enter real values in the Doppler dashboard or with `doppler secrets set`:

```bash
doppler secrets set \
  --project polaris-vps-a \
  --config network_exit_node \
  TZ=Etc/UTC \
  TS_HOSTNAME=dns-gateway
```

Do not upload `.env.example` directly. Its defaults may be placeholders, and
uploading it can overwrite valid values. For a large initial import, create a
temporary environment file outside the repository with mode `0600`, upload it
to the intended project/config, and remove it immediately after checking the
result. Never leave that file in the checkout or shell history.

### 4. Audit and deploy through the manager

Always run managed operations from the repository root:

```bash
./manage.py secrets verify
./manage.py secrets audit
./manage.py validate --vps A
./manage.py deploy --vps A
```

The `secrets audit` command (also included in `manage.py doctor`) performs a
deep check to ensure every variable key defined in a project's `.env.example`
has a matching value in Doppler.

Select the required stack in the deployment interface. For VPS B, replace
`A` with `B`. The manager resolves the project from the VPS context and wraps
compose commands as `doppler run --project ... --config ... -- ...`.

Do not use `docker compose up`, `docker compose pull`, or `docker compose
config` directly for production operations. Those commands bypass the
repository's VPS/config mapping and may run with missing or stale variables.

## How Runtime Injection Works

The full data flow for a managed deployment is:

1. `discovery.py` finds the compose project and supplies its repository path,
   service name, category, and VPS assignment.
2. `doppler_manager.py` maps the VPS assignment to
   `polaris-vps-a` or `polaris-vps-b`, then maps the path/category to the
   named service config such as `network_exit_node` or `tools_n8n`.
3. The manager starts the operation as
   `doppler run --project <project> --config <config> -- docker compose ...`.
   Doppler fetches the selected config and adds its values to the child
   process environment. The secrets are not copied into the repository by
   this step.
4. Docker Compose performs `${VARIABLE}` interpolation from that process
   environment and passes the resulting values into containers according to
   their compose definition.
5. The application reads the resulting container environment. It does not
   communicate with Doppler directly.

The deployment wrapper handles two compose patterns:

1. Services using `environment:` receive Doppler variables directly through
   Compose. Both `KEY=${KEY}` and bare `KEY` entries resolve from the injected
   process environment.
2. Services declaring `env_file: .env` receive a temporary `0600` `.env`
   downloaded from Doppler with `--no-file`. The file is removed after the
   managed command exits. Existing plaintext `.env` files are never
   overwritten or removed.

For the second pattern, the manager runs
`doppler secrets download --format env --no-file`, creates the file with
exclusive creation and mode `0600`, and lets Compose read it from the service
directory. This compatibility materialization is the only normal production
case where a plaintext environment file exists on disk, and it is process
scoped. It is not a persistent source of truth.

Custom update scripts, including the NetBird generator, are launched inside
the same `doppler run` process. NetBird uses injected values to generate
`Utilities/netbird-server/management.json` and `turnserver.conf`, while its
persistent datastore key remains under the service's ignored `data/` directory.
Those generated files and datastore state must be protected like runtime
secrets and recreated only through the managed utility.

If Doppler is unavailable, the CLI enters standalone fallback mode and may use
existing local `.env` files or the repository-root `.env`. This is retained for
offline recovery and development, not normal production setup. The
`./manage.py utils env` command only copies missing `.env.example` templates;
it does not configure Doppler and should not be used to bootstrap production
secrets.

## Secret Inheritance & Shared Values

Reduce duplication by moving shared variables (e.g., `TZ`, `PUID`, `PGID`) to
Doppler environment roots.

1. **Root Environments**: Current environments include `network`, `auth`, `admin`,
   `monitoring`, `cloud_docs`, `tools`, `comics`, `stremio`, and `local_media`.
2. **Inheritance**: Any secret set at the environment level is automatically
   available to all configs under that environment.
3. **Migration**: To move a shared variable to an environment root:
   - Set the value in the environment: `doppler secrets set TZ=Etc/UTC --project polaris-vps-a --config network`
   - Delete the redundant value from service configs: `doppler secrets delete TZ --project polaris-vps-a --config network_exit_node`

## Adding a New Service

1. Add the compose project and a `.env.example` containing every variable the
   compose file or service requires.
2. Run `./manage.py secrets sync` to create the matching Doppler config.
3. Populate the config with production values in the Doppler dashboard.
4. Run `./manage.py secrets audit` (or `manage.py doctor`) to verify all keys.
5. Deploy with `./manage.py deploy --vps A|B` and verify with
   `./manage.py status --vps A|B` and `./manage.py logs <service>`.
6. Update this guide or the relevant runbook if the service introduces a new
   secret type, routing rule, or recovery procedure.

## Rotation and Removal

Rotate a value in Doppler, then recreate the affected service so it receives
the new environment:

```bash
doppler secrets set --project polaris-vps-a --config auth_pocketid \
  OIDC_CLIENT_SECRET
./manage.py redeploy --vps A --recreate
```

Enter the new value at the Doppler prompt instead of placing it in shell
history.

Avoid printing secret values while checking access. This confirms access
without dumping values to the terminal:

```bash
doppler secrets download --project polaris-vps-a \
  --config auth_pocketid --format json --no-file >/dev/null
```

When removing a service, stop it first, remove its config only after confirming
that no backup or recovery process needs it, and retain any required recovery
notes. Do not delete a config merely because the service is temporarily
disabled.

## CI, Cron, and Recovery

- GitHub Actions passes `DOPPLER_TOKEN` from the VPS GitHub Environment to the
  self-hosted runner. Keep separate `vps-a` and `vps-b` environment controls and
  grant only the read access required by the deployment.
- Backup commands use the active VPS project and its `backup` config. When a
  cron job runs as root, `manage.py` reads the small backup config as the
  repository owner and passes only the required values to the root backup
  script.
- A fresh host needs the repository, Docker, the Doppler CLI, and access to the
  appropriate VPS project before services can be restored and redeployed. It
  also needs the host prerequisites in
  [NETWORK_ARCHITECTURE.md](NETWORK_ARCHITECTURE.md), Restic/Rclone for backup
  recovery, and FUSE support for services that mount remote storage.
- Runtime secrets are not expected to be recovered from a Restic config
  snapshot; recover them from Doppler. Generated NetBird files and datastore
  keys are runtime state and must be restored or regenerated according to the
  NetBird runbook.

## Offline Resilience & SOPS Snapshot Fallback

Doppler SaaS remains the authoritative write surface and source of truth. To ensure resilience against SaaS outages, rate limits, or network partitions, `polaris` maintains an offline, read-only cold backup layer using **SOPS + age encrypted snapshots** stored under `.snapshots/<project>/<config>.env.enc` committed to git.

### Automatic Fallback
When Doppler is unreachable (or in air-gapped recovery):
1. `manage.py deploy` and `wrap_compose_command` automatically detect Doppler failure.
2. `SnapshotManager` resolves the snapshot ciphertext in-memory: it prefers the latest snapshot from the Git tracking branch (`origin/snapshots/sync` or `snapshots/sync`), seamlessly falling back to local committed files under `.snapshots/` if git remote is unreachable.
3. The manager transparently decrypts the snapshot in-memory using the host's age private key (`keys.txt` or `~/.config/sops/age/keys.txt`). Active working tree files on `main` are never touched or dirtied.
4. Variables are injected into process memory, and transient `0600` `.env` files are materialized only for services declaring `env_file:`.

### Snapshot Operations
* **Take full VPS snapshot:** `./manage.py secrets snapshot [--vps A|B]`
* **Snapshot single config:** `./manage.py secrets snapshot-config <config> [--vps A|B]`
* **List snapshot inventory:** `./manage.py secrets snapshots [--vps A|B]`
* **Automated Sync to dedicated branch:** `./manage.py secrets sync-branch [--vps A|B|all]`

### Operational Best Practice & Automated Sync

#### 1. On-Demand (After secret rotations)
After rotating any secret in Doppler SaaS, refresh the snapshot:
```bash
./manage.py secrets snapshot --vps A
git add .snapshots/
git commit -m "chore(secrets): refresh snapshots after rotation"
```

#### 2. Automated Nightly Sync via Dedicated Branch (`snapshots/sync`)
Because GitHub branch protection blocks direct pushes to `main`, a dedicated branch `snapshots/sync` receives automated pushes from cron without requiring daily PRs.

The sync helper (`./manage.py secrets sync-branch`) uses an **isolated git worktree** in `/tmp/`:
- Active edits and checked-out branches in your local workspace are **never touched**.
- If no secrets drifted, it exits silently without creating empty commits.
- If drift is detected, it commits and pushes ciphertext directly to `origin snapshots/sync`.

**Recommended Nightly Cron (3:30 AM):**
```cron
30 3 * * * ~/polaris/manage.py secrets sync-branch >> /var/log/polaris-snapshots.log 2>&1
```

**Periodic Roll-Up to `main`:**
When convenient (e.g. weekly or monthly), open a single PR `snapshots/sync` ➔ `main`. Since `.snapshots/` is isolated from application code, the PR merges cleanly with zero conflicts.

For historical SOPS migration details, see
[DOPPLER_MIGRATION_COMMIT_REFERENCE.md](DOPPLER_MIGRATION_COMMIT_REFERENCE.md).
