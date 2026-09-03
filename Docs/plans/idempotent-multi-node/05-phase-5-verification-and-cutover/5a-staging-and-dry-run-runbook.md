# 5a: Staging & Dry-Run Runbook

> **Sub-Phase:** 5a  
> **Target:** Pre-Cutover Verification & Smoke Testing  

---

## 1. Objective

Simulate the complete deployment and discovery pipeline across both nodes in dry-run mode before modifying running containers.

---

## 2. Dry-Run Verification Procedure

Execute sequentially on each host:

### Step 1: Initialize Host Node Identity
```bash
# Run on each host with its topology node ID.
./manage.py node set <node-id>
./manage.py node current
```

### Step 2: Validate Discovery & Secrets Resolution
```bash
# Verify node resolves properly
./manage.py node current

# Run doctor pre-flight diagnostics
./manage.py doctor
./manage.py doctor --cluster-transport

# Verify required secret keys structurally without displaying values
./manage.py secrets verify

# Validate compose syntax across all projects
./manage.py validate
```

### Step 3: Run Simulated Deployments
```bash
# Simulate deploy for local node
./manage.py deploy --dry-run

# Verify status inspects local containers without errors
./manage.py status
./manage.py status --cluster
```

### Step 4: Rehearse State and Failure Recovery

On a disposable staging workload, execute a migration with failure injection after
each durable journal stage. Confirm the target is cleaned, any prior target state is
restored, and the source restarts healthy. Restore the exact newly created snapshot ID
to staging and compare checksums, ownership, and application/database checks.

---

## 3. Pass/Fail Exit Criteria
* All commands exit with return code `0`.
* Zero missing environment variables or unresolvable secrets.
* `./manage.py status` matches live running containers accurately.
* Every remote diagnostic observation has the expected node identity and a fresh
  timestamp; unavailable nodes are `unknown`, never falsely `exited`.
* The migration rollback drill passes at every failure boundary and records exact
  recovery point objectives and measured recovery times.
