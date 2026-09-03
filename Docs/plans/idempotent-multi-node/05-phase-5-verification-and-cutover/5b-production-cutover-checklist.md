# 5b: Production Cutover Checklist

> **Sub-Phase:** 5b  
> **Target:** Step-by-Step Production Migration Execution  

---

## 1. Pre-Cutover Safeguards
1. Run pre-cutover backup:
   ```bash
   ./manage.py backup run --node vps-a
   ./manage.py backup run --node vps-b
   ```
   Record and verify the exact snapshot and repository IDs for every stateful workload;
   a successful command without verified snapshot IDs is not a recovery point.
2. Refresh offline secrets snapshot:
   ```bash
   ./manage.py secrets snapshot --node vps-a
   ./manage.py secrets snapshot --node vps-b
   ./manage.py secrets sync-branch
   ```

---

## 2. Cutover Execution Sequence

1. Confirm the topic branch passed all required PR checks and merge it through the
   protected-branch pull-request process. Record the pre-cutover and target SHAs.
2. GitOps deployment workflow (`deploy.yml`) triggers matrix deployment on `vps-a` and `vps-b`.
3. Verify live container health:
   ```bash
   # On VPS A
   ./manage.py status

   # On VPS B
   ./manage.py status
   ```
4. Verify external ingress and reverse proxy routing:
   * Test Jellyfin stream playback (`https://jellyfin.<tailnet>.ts.net`)
   * Test Authelia / PocketID authentication
   * Test Stremio addon endpoints (`https://stremio.<tailnet>.ts.net`)
5. For every migrated stateful workload, compare the recorded data manifest and run its
   application-native integrity check before accepting cutover. Keep the source stopped
   but intact throughout the acceptance window.

---

## 3. Post-Cutover Verification
* `./manage.py doctor` passes all 8 diagnostic checks.
* Restic backup check (`./manage.py backup check`) reports clean snapshots.
* The diagnostic agent is authenticated and fresh on every node; the old source remains
  available for rollback until the signed acceptance record is complete.
* Any required write quiescence is treated as a measured, approved maintenance window;
  the plan does not claim zero downtime for stateful moves that require a stop.
