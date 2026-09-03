# 5c: Rollback & Disaster Recovery Runbook

> **Sub-Phase:** 5c  
> **Target:** Emergency Reversal & Disaster Recovery  

---

## 1. Fast Rollback Strategy

Rollback has separate **control-plane** and **data-plane** tracks. A Git revert restores
code and placement intent but cannot reverse state already written on a new host.

```bash
# 1. Create a rollback topic branch and revert the cutover through a PR.
git switch -c revert/multi-node-cutover
git revert <CUTOVER_COMMIT_SHA>

# 2. After required checks and merge, redeploy the recorded pre-cutover placement.
./manage.py redeploy --node <source-node> --last
```

Never detach a production checkout with `git checkout <sha>` as the rollback mechanism.
If no stateful workload started on the target, stop target instances and restart the
preserved source state. If target writes occurred, stop the target consistency group,
snapshot it by exact ID, and choose one documented recovery path:

1. **Discard target writes:** Restore/restart the untouched source only after explicit
   approval that post-cutover writes may be lost.
2. **Reverse migrate:** Restore the exact target snapshot to the source mappings, verify
   checksums/ownership/database consistency, then start and health-check the source.
3. **Application reconciliation:** For systems requiring merge/replication semantics,
   use the application's native recovery procedure; do not file-copy a live database.

In every path, fence the target before starting the source to prevent split brain. Record
the selected snapshot IDs, repository IDs, topology revision, write-loss decision, and
health evidence in the migration journal.

---

## 2. Disaster Recovery: Restoring Volumes from Restic

If state corruption occurs on any host:

```bash
# List snapshots for target node
./manage.py backup snapshots --node vps-a

# Preview one explicitly selected recovery point
./manage.py backup restore --node vps-a --snapshot <snapshot-id> --dry-run

# Execute restore only after stopping the full consistency group
./manage.py backup restore --node vps-a --snapshot <snapshot-id>
```

Restore into staging first, verify the manifest and application consistency, snapshot
the current destination, then atomically install mapped paths. Never use `latest` in an
automated rollback.

---

## 3. Disaster Recovery: Secrets Restoration

If Doppler SaaS is unreachable during cutover, stop and follow the documented offline
snapshot recovery procedure. Automatic fallback is permitted only after an integration
test proves signature/decryption, freshness, node/config identity, least-privilege file
handling, and cleanup. Never print secret values while comparing or restoring keys.

## 4. Recovery Exercise Exit Criteria

* Quarterly drills restore one service and one multi-service consistency group to an
  isolated target using exact snapshot IDs.
* Drills verify no split brain, checksum/ownership/application consistency, diagnostic
  visibility, and measured RPO/RTO against declared objectives.
* Source and rollback snapshots are deleted only through a separate confirmed retention
  step after acceptance.
