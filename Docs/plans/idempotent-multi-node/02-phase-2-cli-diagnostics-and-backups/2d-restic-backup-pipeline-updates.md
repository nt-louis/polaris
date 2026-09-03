# 2d: Restic Backup Pipeline: Service & Cluster Tagging

> **Sub-Phase:** 2d  
> **Target:** `Scripts/backup/backup-all.sh`, `restore-all.sh`, and `backup-check.sh`  

---

## 1. Objective

Upgrade the Restic backup pipeline from a monolithic host bucket to a **portable, dual-level tagged backup model**:
1. **Service-Level Snapshots (`--tag service:<id>`):** Back up the exact state paths
   declared for a topology placement, including repository-relative bind mounts and
   explicitly declared external paths. There is no assumption that state lives under
   `/docker/appdata/<service>`.
2. **Namespace-Level Snapshots (`--tag cluster:<namespace-id>`):** Backs up the declared
   consistency group for one real shared network namespace together.
3. **Host Tagging (`--tag host:<node_id>`):** Records originating host for audit trails.

---

## 2. Multi-Level Tagging Matrix

Each placement declares stable state mappings. Restore paths are explicit and remain
relative to a checked-out repository when the source is repository-local:

```yaml
placements:
  - path: "Media/local-media/players/jellyfin"
    service_id: "jellyfin"
    node: "vps-a"
    gateway: "media-core"
    state:
      - source: "Media/local-media/players/jellyfin/config"
        restore: "Media/local-media/players/jellyfin/config"
        consistency: "service-stopped"
        ownership: {uid_key: "PUID", gid_key: "PGID"}
```

The backup command receives resolved paths as an argument vector rather than building
a shell command from a service name:
```bash
restic backup --json /srv/polaris/Media/local-media/players/jellyfin/config \
  --tag "service:jellyfin" \
  --tag "cluster:media-core" \
  --tag "host:vps-a"
```

### Why Dual-Level Tagging Enables Zero-Touch Migration:
* **Whole Cluster Restore:** Resolve all mappings in the selected namespace and restore
  the exact snapshot IDs recorded by the backup operation.
* **Individual Service Restore:** Restore the captured snapshot ID into a staging
  directory, verify it, then install each declared source-to-target mapping.
* `latest` is allowed only for an interactive disaster-recovery selection after the
  operator has reviewed candidate metadata. Automation must never restore `latest`.

---

## 3. Implementation: Script Updates

### A. Snapshot Record Contract

Move orchestration into Python so paths are validated against `REPO_ROOT`, command
arguments are not shell-interpolated, and Restic JSON can be parsed. For every backup:

1. Resolve all `state` mappings from topology and reject missing, escaping, overlapping,
   or undeclared paths.
2. Select and record the **source node's repository identifier** before stopping the
   workload. A migration restores from that repository; it must not silently switch to
   the target node's repository.
3. Parse the successful Restic JSON summary and persist its exact `snapshot_id`,
   repository identifier, source paths, tags, timestamp, and topology revision in the
   migration journal.
4. Run `restic check` for the selected repository and verify the captured snapshot is
   addressable by ID. If repositories are node-isolated, explicitly `restic copy` that
   ID to the destination repository and record the copied ID as a separate field.
5. Generate a file manifest for restored-path checksum, type, mode, UID, and GID
   comparison. Databases remain stopped for the entire snapshot and verification
   window; service-specific consistency hooks may add an application-native check.

### B. Targeted Service Restore in `restore-all.sh`
```bash
# SNAPSHOT_ID and SOURCE_REPOSITORY are selected and validated by manage.py.
restic --repo "$SOURCE_REPOSITORY" restore "$SNAPSHOT_ID" --target "$STAGING_DIR"
```

The restore command refuses an empty or `latest` snapshot ID in non-interactive mode.
It verifies checksums, ownership, free space, and destination boundaries before an
atomic install. Existing target state is first snapshotted and retained until cutover
is accepted.

---

## 4. Verification Criteria
* `./manage.py backup snapshots --tag service:jellyfin` lists all Jellyfin state snapshots.
* `./manage.py backup restore --service jellyfin --dry-run` previews restoring Jellyfin state safely on any host.
* Tests cover repository-relative bind mounts, external mappings, multiple paths per
  service, missing paths, path traversal, exact snapshot selection, checksum/ownership
  mismatch, and restore into a non-empty destination.
