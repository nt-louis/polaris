# Backup & Restore Strategy

A self-hosted server is only as strong as its backup strategy. While your media downloads reside safely on third-party cloud systems (via Real-Debrid and Zurg), all your stack's custom settings, databases, watch progress, and automation configurations reside on your host VPSes.

This guide details the architecture of the **Polaris Restic-Based Universal Backup & Recovery System**, explaining how to set up repository secrets, configure off-site cloud remotes, run manual backups, schedule automatic nightly runs, browse snapshots, perform granular restores, and execute total disaster recovery.

---

## Architecture & Backup Scope

To minimize disk bloat while capturing 100% of your critical state, the backup system uses **Restic** with **native block-level deduplication**. Instead of heavy tarballs, backups are stored as deduplicated, encrypted snapshots in a remote Restic repository, organized by **Tags**:

1. **System Configurations (`configs`):**
   - Saves local configuration files, `.env.example` templates, and all stack configuration files.
   - Runtime service secrets are managed in Doppler SaaS (primary) and backed up offline in SOPS+age encrypted snapshots (`.snapshots/`), decryptable with your age private key (`keys.txt`).
   - Saves all `docker-compose.yml`, `Caddyfiles`, routing scripts, and templates across the entire repository.
2. **Active Databases & Volumes (`appdata`):**
   - Archives core media volumes under `/docker/appdata` (Jellyfin databases, watch history, Radarr/Sonarr SQLite databases, Prowlarr configs, etc.).
    - Recursively scans and archives **in-repo active data and state folders** (such as AdGuard Home's DNS configurations, Uptime Kuma monitors, and Tailscale machine state folders).
3. **Local Docker Images (`docker-images`):**
   - Saves locally built container images (e.g., `local/fmhy:latest`) to preserve custom builds.
4. **Media Share Boundary:**
    - The backup script does not expand `${MEDIA_SHARE}` as a backup source. A
      media share outside the repository and outside `BASE_PATH` is therefore
      not included. If a media path is placed inside the repository and is
      discovered as a relative compose mount, it can be included in `appdata`.
      Keep large media mounts outside the repository and verify with
      `./manage.py backup --dry-run`.

---

## Dual-VPS Architecture & Namespacing

Both VPS nodes share the same git repository but host distinct workload profiles
and environment configurations. The authoritative assignment is registered in
`orchestrator/registry/services.yaml`.

- **VPS A**: Core media, comics, the Network DNS gateway, authentication,
  cloud storage, utilities, NetBird server, and the Cloudflare Tunnel.
- **VPS B**: Stremio addons and utilities, the Proton gateway, the Tailscale-only
  `util-b` bridge, and VPS B development/AI tools.

Archived services, including the historical Coolify and Zurg stacks, are not
part of the active backup deployment profile.


The backup system auto-detects the active node by reading `.active_vps` (or using `--vps A|B`) and automatically namespaces the Restic repository path on the cloud remote:
- `rclone:gdrive:backups/polaris/vps-a`
- `rclone:gdrive:backups/polaris/vps-b`

---

## 1. Initial Configuration & Credentials Setup

Before executing backups or scheduling cron jobs, use the `backup` config in each Doppler project (`polaris-vps-a` and `polaris-vps-b`). Add these variables to the corresponding VPS config:

- `BACKUP_PASSWORD` — required Restic repository password.
- `RCLONE_REMOTE` — required primary repository remote.
- `RCLONE_REMOTE_SECONDARY` — optional secondary repository remote.

The backup commands inject these values through Doppler and elevate only the backup script to root. They do not write a plaintext `.env` file.

### Step 1: Set Up Backup Encryption Password
Restic enforces **mandatory AES-256 encryption** for all data at rest. Set `BACKUP_PASSWORD` in the active VPS Doppler `backup` config:

```env
# Restic Repository Password
BACKUP_PASSWORD="your-extremely-secure-passphrase"
```

On first run, the backup engine automatically initializes the Restic repository with this passphrase.

### Step 2: Configure Cloud Storage Remote (Rclone)
Configure your cloud remote (e.g., Google Drive, Hetzner Storage Box) using Rclone:

```bash
rclone config
```

In the active VPS Doppler `backup` config, define the repository remote:

```env
# Primary Cloud Target
RCLONE_REMOTE="gdrive:backups/polaris"

# Optional: Secondary Replication Remote
RCLONE_REMOTE_SECONDARY="hetzner:backups/polaris"

```

Retention defaults are `KEEP_DAILY=7`, `KEEP_WEEKLY=4`, and `KEEP_MONTHLY=6`. Override them in the shell environment only when a different policy is needed.

### Step 3: Choose Hot vs. Cold Backup Mode
- **Hot Backup (Default, `STOP_DURING_BACKUP="false"`)**: Containers remain online while live databases and volumes are snapshotted on-the-fly.
- **Cold Backup (`STOP_DURING_BACKUP="true"`)**: Gracefully pauses active containers during snapshotting to guarantee 100% database transaction consistency, then restarts containers automatically.

---

## 2. Executing Backups

### Manual Backup Run

To execute an incremental backup manually:

```bash
cd ~/polaris
./manage.py backup
```

### Dry-Run Verification

Preview folders to be snapshotted without writing data:

```bash
./manage.py backup --dry-run
```

---

## 3. Automatic Nightly Scheduling (Cron)

Schedule nightly automated backups requiring root privileges to access container volumes:

1. Open the **root user's** crontab. The manager securely reads the backup config through the repository owner's authenticated Doppler CLI before running the root-only backup script:
   ```bash
   sudo crontab -e
   ```
2. Add the nightly schedule (e.g., 4:00 AM):
   ```cron
   00 4 * * * cd ~/polaris && ./manage.py backup >/dev/null 2>&1
   ```
3. Save and exit. The cron daemon will manage incremental snapshots and retention policies automatically.

---

## 4. Inspecting Snapshots, Repository Stats & Pruning

### Query Available Snapshots
Browse all snapshots saved for the active or targeted VPS:

```bash
# List all snapshots in the repository for this VPS
./manage.py backup snapshots

# List snapshots for a specific VPS node
./manage.py backup snapshots --vps b
```

### Inspect Repository Storage & Compression Statistics
Inspect logical uncompressed data volume versus physical deduplicated cloud storage:

```bash
# Raw storage mode: see physical cloud space used vs uncompressed size
./manage.py backup stats --mode raw-data

# Restore size mode: see logical size of the latest snapshot
./manage.py backup stats latest

# Query statistics for a specific VPS node or tag
./manage.py backup stats --vps b --mode raw-data
./manage.py backup stats --vps a --tag appdata
```

### On-Demand Retention Enforcement & Pruning
The backup engine enforces continuous self-regulating maintenance (`--prune --max-unused 10%`) automatically during every scheduled backup run. You can also run retention enforcement and pruning manually:

```bash
# Prune unreferenced chunks and enforce retention on current VPS
./manage.py backup prune

# Prune with custom max-unused threshold on VPS B
./manage.py backup prune --vps b --max-unused 5%

# Simulate pruning without deleting data
./manage.py backup prune --vps a --dry-run
```

### Check Repository Integrity
Verify cryptographic chunk hashes and index health:

```bash
# Verify Restic repository integrity
./manage.py backup check
./manage.py backup check --vps b
```

---

## 5. Disaster Recovery & Restoring

### Total Disaster Recovery (1-Click Restore)

To restore a VPS following a crash or migration to a new host:

```bash
# Restore latest snapshots for the current VPS (prompts for confirmation)
./manage.py backup restore

# Non-interactive / automated script execution (auto-confirms confirmation prompt)
./manage.py backup restore --yes
```

#### How Restore Works:
1. **Halts Services**: Stops running Docker stacks to release file locks on databases.
2. **Restores Configs**: Overwrites compose files, Caddyfiles, and scripts from the `configs` snapshot. Production runtime secrets are injected dynamically from Doppler SaaS, with offline SOPS snapshots (`.snapshots/`) serving as cold backup.
3. **Restores Volumes & Databases**: Restores `/docker/appdata` and service state folders with original permissions intact.
4. **Restores Custom Images**: Re-loads saved local images (e.g. `local/fmhy:latest`).

#### Target Specific VPS or Snapshot:

```bash
# Restore specific snapshot ID
./manage.py backup restore --snapshot a1b2c3d4

# Restore VPS A from a fresh host
./manage.py backup restore --vps a

# Restore VPS B from a fresh host
./manage.py backup restore --vps b
```

### Granular File / Directory Restore

Restore individual corrupted configuration files or databases without touching the rest of the system:

```bash
# Restore only the Host Caddyfile
./manage.py backup restore --include "Network/Caddyfile"

# Restore only the Sonarr database directory
./manage.py backup restore --include "docker/appdata/sonarr"
```

---

## 6. Migration from Legacy Tar-based System

If migrating from old `.tar.gz.gpg` scripts:

1. **Keep Legacy Tarballs**: Retain old archives on cloud storage as a fallback.
2. **Install Restic**: Install Restic on both VPS hosts (`sudo apt install restic`).
3. **Configure Doppler**: Add `BACKUP_PASSWORD` and `RCLONE_REMOTE` to the VPS `backup` config.
4. **Initial Backup Run**: Run `./manage.py backup`. It will automatically initialize the new Restic repository on your cloud remote.
