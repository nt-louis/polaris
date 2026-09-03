# 4a: Dynamic GitOps Matrix Deployment (`deploy.yml`)

> **Sub-Phase:** 4a  
> **Target:** `.github/workflows/deploy.yml`  

---

## 1. Objective

Replace hardcoded per-VPS workflow jobs with a **2-stage dynamic matrix deployment workflow**:
1. **Stage 1 (`determine-nodes`):** Uses the exact event SHA range and the topology
   placement resolver to map changed functional paths to node IDs. Shared control-plane
   changes fan out to every node.
2. **Stage 2 (`deploy`):** Executes in parallel across `[self-hosted, ${{ matrix.node }}]` runners using GitHub Environments for node-specific variables.

---

## 2. Implementation: Dynamic Matrix Workflow

Add a tested `Scripts/deploy/ci_plan.py` helper. Given `--before`, `--after`, and an
optional requested node, it validates SHAs and node IDs, classifies changed Compose
directories through `topology.yaml`, and emits compact JSON. Workflow expressions are
passed through environment variables, never interpolated into executable shell text.

```yaml
name: Deploy Infrastructure

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      node:
        description: "Target Node to deploy (e.g. 'vps-a', 'vps-b', 'all')"
        required: true
        default: "all"
      mode:
        description: "Deployment mode ('changed' for targeted modified services, 'all' for full restart)"
        required: true
        default: "changed"
        type: choice
        options:
          - changed
          - all
      dry_run:
        description: "Simulate deployment without modifying live containers"
        required: false
        default: false
        type: boolean

concurrency:
  group: deploy-${{ github.ref }}
  cancel-in-progress: false

jobs:
  determine-nodes:
    name: Determine Target Nodes
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.detect.outputs.matrix }}
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - run: python3 -m pip install -r requirements.txt

      - name: Detect Modified Nodes
        id: detect
        env:
          BEFORE_SHA: ${{ github.event.before }}
          AFTER_SHA: ${{ github.sha }}
          REQUESTED_NODE: ${{ inputs.node }}
          EVENT_NAME: ${{ github.event_name }}
        run: |
          python3 Scripts/deploy/ci_plan.py matrix \
            --event "$EVENT_NAME" --before "$BEFORE_SHA" --after "$AFTER_SHA" \
            --requested-node "${REQUESTED_NODE:-all}" >> "$GITHUB_OUTPUT"

  deploy:
    name: Deploy (${{ matrix.node }})
    needs: determine-nodes
    if: ${{ needs.determine-nodes.outputs.matrix != '[]' }}
    strategy:
      matrix:
        node: ${{ fromJson(needs.determine-nodes.outputs.matrix) }}
      fail-fast: false
    runs-on: [self-hosted, "${{ matrix.node }}"]
    environment: "${{ matrix.node }}"
    steps:
      - name: Run Node Deployment
        env:
          PROD_DIR: ${{ vars.PROD_DIR }}
          DOPPLER_TOKEN: ${{ secrets.DOPPLER_TOKEN }}
          TARGET_SHA: ${{ github.sha }}
          BEFORE_SHA: ${{ github.event.before }}
          TARGET_NODE: ${{ matrix.node }}
          DEPLOY_MODE: ${{ inputs.mode || 'changed' }}
          DRY_RUN: ${{ inputs.dry_run || 'false' }}
        run: |
          "$PROD_DIR/Scripts/deploy/ci_deploy.sh"
```

### Production runner contract

`ci_deploy.sh` consolidates, rather than removes, the safeguards in the current two
jobs. It must:

1. Require `PROD_DIR`, verify the checkout and deployment entry point, and verify that
   `.node_id` equals `TARGET_NODE`.
2. Preserve the existing tracked-dirty-tree autostash and exit trap (or fail closed by
   an explicitly approved policy); never discard untracked files or operator state.
3. Fetch and reset only to the immutable `TARGET_SHA`, retaining authenticated GitHub
   fetch behavior. Compute changes from the event's `BEFORE_SHA..TARGET_SHA`, including
   multi-commit pushes and the all-zero first-push case.
4. Re-run `ci_plan.py services --node "$TARGET_NODE"` after synchronization. Deploy
   only changed Compose projects assigned to that node; shared deployment code changes
   synchronize all runners but do not restart unrelated containers.
5. Preserve the environment-scoped Doppler token, dependency installation failure
   handling, dry-run behavior, full `--last` mode, exit status, and logs. It must not
   suppress dependency failures with `|| true`.
6. Use argument arrays for service paths and validate each path against discovery before
   invoking `manage.py`; no whitespace-delimited command construction.

---

## 3. Verification Criteria
* Pushing a Jellyfin Compose change maps its retained `Media/...` path through topology
  and runs deployment only on the assigned runner.
* One push changing functional paths assigned to both nodes runs both matrix entries.
* Workflow dispatch with `node: "all"` fans out across all nodes.
* Tests cover multi-commit pushes, deleted/renamed Compose files, topology changes,
  shared scripts, invalid requested nodes, zero SHAs, dirty production checkouts, and
  paths containing spaces.
