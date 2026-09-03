# Renovate Bot & GitOps Automation Guide

This guide provides a walkthrough for the repository's automated Docker image dependency updates, GitOps deployments, and security scanning using **Renovate Bot** and **self-hosted GitHub Action runners**. The repository currently has 77 active compose projects; `Archived/` and the automation scripts are excluded from Renovate scanning.

---

## Overview & Strategy

Renovate Bot automatically scans all `docker-compose.yml` files across the repository to detect outdated container image tags.

To avoid notification fatigue, issue spam, and breaking changes, this repository uses a **Hybrid Minimal Strategy**:

* **Non-critical Patch Auto-Merge**: Patch updates and digest refreshes are grouped into the `Weekly Non-Critical Patch Updates` PR and may auto-merge after repository checks pass.
* **Reviewed Minor and Major PRs**: Non-critical minor and major updates are grouped separately and require review. The repository config does not define a Monday schedule; any scheduling is controlled by the Renovate installation.
* **Zero Issue Spam**: GitHub Issue creation and the Dependency Dashboard issue are completely disabled (`dependencyDashboard: false`).
* **3-Day Stability Buffer**: Renovate waits 3 days after an image release before opening PRs to protect against buggy 0-day releases.
* **Critical Infrastructure Safeguard**: Core infrastructure services (Gateways, Infisical, Auth, Exit-Node, Network, and the Proton gateway) **never** auto-merge and always require explicit manual review.

---

## Step 1: GitHub Web Setup (Zero External Apps)

This repository uses self-hosted GitHub Actions workflows. It runs automatically on scheduled crons or triggers and requires **no external app installations** or third-party accounts.

### 1. Enable GitHub Actions Permissions
1. Navigate to your repository on GitHub.
2. Go to **Settings** -> **Actions** -> **General**.
3. Under **Workflow permissions**, select **Read and write permissions**.
4. Check the box for **Allow GitHub Actions to create and approve pull requests**.
5. Click **Save**.

### 2. Enable Auto-Merge in GitHub Settings
For silent patch auto-merges to function:
1. Go to **Settings** -> **General** -> **Pull Requests**.
2. Check the box for **Allow auto-merge**.
3. *(Optional)* Under **Automatically delete head branches**, check the box to automatically clean up merged branches.

---

## Step 2: Repository Configuration (`renovate.json`)

The entire Renovate behavior is controlled by [`renovate.json`](renovate.json) located at the root of the repository.

### Configuration File Anatomy

`renovate.json` is the source of truth. The embedded example below is for
orientation only; update the repository file itself rather than copying this
section over it.

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended", "helpers:pinGitHubActionDigests"],

  // 1. Disable Issue Spam
  "dependencyDashboard": false,

  // 2. Stability Filter (Wait 3 days after release)
  "minimumReleaseAge": "3 days",

  // 3. Excluded Paths
  "ignorePaths": [
    "**/Archived/**",
    "**/orchestrator/**",
    ".github/workflows/**"
  ],

   // 4. PR Limits
   "prConcurrentLimit": 5,
  "prHourlyLimit": 0,
   "rebaseWhen": "behind-base-branch",

  "commitMessagePrefix": "chore(deps):",
  "commitMessageAction": "update",
  "labels": ["renovate", "dependencies"],

  "docker-compose": {
    "enabled": true,
    "managerFilePatterns": ["/(^|/)docker-compose\\.yml$/"]
  },

  "packageRules": [
    {
      "description": "Disable updates for locally-built images",
      "matchPackageNames": ["local/monochrome", "local/fmhy"],
      "enabled": false
    },
    {
      "description": "Ignore legacy 1.0.0 tag for lostb1t/remux",
      "matchPackageNames": ["ghcr.io/lostb1t/remux"],
      "allowedVersions": "<1.0.0"
    },
    {
       "description": "Group all non-critical patch & digest updates into 1 single auto-merging PR",
      "matchManagers": ["docker-compose"],
      "matchUpdateTypes": ["patch", "digest"],
       "automerge": true,
       "automergeType": "pr",
       "automergeStrategy": "squash",
       "groupName": "Weekly Non-Critical Patch Updates",
       "groupSlug": "weekly-non-critical-patch-updates"
     },
     {
       "description": "Group all non-critical minor updates into 1 single PR requiring review",
       "matchManagers": ["docker-compose"],
       "matchUpdateTypes": ["minor"],
       "automerge": false,
       "groupName": "Weekly Non-Critical Minor Updates",
       "groupSlug": "weekly-non-critical-minor-updates",
       "labels": ["renovate", "dependencies", "needs-review"]
     },
     {
       "description": "Group all non-critical major updates into 1 single PR requiring review",
       "matchManagers": ["docker-compose"],
       "matchUpdateTypes": ["major"],
       "automerge": false,
       "groupName": "Weekly Non-Critical Major Updates",
       "groupSlug": "weekly-non-critical-major-updates",
       "labels": ["renovate", "dependencies", "needs-review", "major-upgrade"]
     },
    {
      "description": "Never auto-merge infrastructure-critical services — always require review",
      "matchManagers": ["docker-compose"],
      "matchFileNames": [
        "Utilities/admin/coolify/**",
        "Utilities/admin/infisical/**",
        "Utilities/auth/**",
        "Utilities/exit-node/**",
        "Utilities/gateway/**",
        "Utilities/gateway-b/**",
        "Utilities/cloud-docs/nextcloud/gateway/**",
         "Media/stremio/utilities/gateway/**",
         "Media/stremio/addons/gateway/**",
         "Media/stremio/addons/gateway-proton/**",
        "Media/local-media/gateway/**",
        "Media/comics/gateway/**",
        "Network/**"
      ],
      "automerge": false,
      "labels": ["renovate", "dependencies", "needs-review", "critical-infra"]
    }
  ]
}
```

---

## Step 3: Self-Hosted Runner Auto-Deployment (`deploy.yml`)

The repository includes [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml), which deploys changed compose projects after pushes to `main` that modify compose files, deployment code, or `.env.example`, and supports manual `workflow_dispatch` runs.

### Production Directory Context (`~/polaris`)
To ensure Docker Compose volume mounts (`./data`, `./config`, `${MEDIA_SHARE}`) bind to your **real production databases and data directories**, the workflow explicitly switches to `~/polaris` before running `git` or `deploy.py`:

```bash
PROD_DIR="~/polaris"
cd "$PROD_DIR"
git fetch origin main
git reset --hard origin/main
python3 manage.py deploy --services <changed_dirs> --vps B
```

### Targeted Deployment & Trigger Rules

1. **Trigger Filter**: Push deployments are path-filtered by the workflow. Any matching push to `main`, including a developer commit, can trigger the deployment jobs; manual runs can target VPS A, VPS B, or both.
2. **Targeted Service Bumps**: Uses `git diff "$BEFORE_SHA" "$AFTER_SHA"` to isolate exact modified compose directories. Only the changed container is restarted (e.g. `seanime`).
3. **Gateway Child Self-Healing**: If a Gateway VPN container is updated, `deploy.py` automatically detects all active child services attached via `network_mode: container:<gateway>` and recreates both the gateway and its children to restore network connectivity.

### Runner Setup on VPS A and VPS B

1. Go to GitHub -> **Settings** -> **Actions** -> **Runners** -> **New self-hosted runner** (Linux / x64).
2. On **VPS A**, run:
   ```bash
   cd ~/polaris
   mkdir -p actions-runner && cd actions-runner
   curl -o actions-runner-linux-x64-2.317.0.tar.gz -L https://github.com/actions/runner/releases/download/v2.317.0/actions-runner-linux-x64-2.317.0.tar.gz
   tar xzf ./actions-runner-linux-x64-2.317.0.tar.gz
   ./config.sh --url https://github.com/nt-louis/polaris --token YOUR_TOKEN --labels vps-a --unattended
   sudo ./svc.sh install && sudo ./svc.sh start
   ```
3. On **VPS B**, run the same commands using `--labels vps-b`:
   ```bash
   ./config.sh --url https://github.com/nt-louis/polaris --token YOUR_TOKEN --labels vps-b --unattended
   sudo ./svc.sh install && sudo ./svc.sh start
   ```

---

## Step 4: Security Workflows & Vulnerability Scans

### 1. Compose Validation & Secret Leak Protection ([`validate-compose.yml`](.github/workflows/validate-compose.yml))
* Runs **PyYAML** syntax validation on all active compose files.
* Runs **Gitleaks** on every commit and PR to prevent accidental credential leaks.

### 2. Trivy Vulnerability Scanner ([`security-scan.yml`](.github/workflows/security-scan.yml))
* Scans repository Compose and infrastructure configuration on pull requests, `main` pushes, and manual runs for **HIGH** and **CRITICAL** findings.
* Image vulnerability scanning is intentionally deferred until its false-positive and failure-handling policy is established in [issue #88](https://github.com/nt-louis/polaris/issues/88).
* Outputs reports directly into GitHub Actions step summaries.

---

## Step 5: Container Dependency Report (`dependency-report.yml`)

You can generate an on-demand Markdown report detailing all container image release ages, dependency stats, and Renovate statuses anytime:

1. Open GitHub -> **Actions** tab.
2. Select **Container Dependency & Upgrade Report**.
3. Click **Run workflow** -> **Run workflow**.
4. View the generated report directly on the workflow run summary page or download `dependency-report.md`.

---

## Step 6: Local CLI & Maintenance Workflow

While Renovate and GitHub Actions manage updates remotely, you can inspect or apply updates locally anytime using [`manage.py`](manage.py).

### 1. Check for Pending Image Updates Locally
```bash
./manage.py update --check
# or shortcut:
./manage.py check-upgrades
```

### 2. Apply Container Updates
* **Interactive Update Selection**:
  ```bash
  ./manage.py update
  ```
* **Non-Interactive Batch Update**:
  ```bash
  ./manage.py update --yes
  ```
* **Conservative Update (Filter images < 7 days old)**:
  ```bash
  ./manage.py update --min-age 7 --yes
  ```

---

## Frequently Asked Questions & Troubleshooting

### Q: Why did Renovate fail to pull a Docker image with `429 Too Many Requests`?
**A**: Docker Hub limits unauthenticated pulls to 100 pulls per 6 hours per IP. If Renovate or your server hits this limit, wait 1–2 hours for the window to reset, or run `docker login` with a free Docker Hub account to double the rate limit.

### Q: How do I disable Renovate for a specific container image?
**A**: Add a new rule under `packageRules` in [`renovate.json`](renovate.json):
```json
{
  "description": "Disable updates for my-app",
  "matchPackageNames": ["my-org/my-app"],
  "enabled": false
}
```

### Q: How do I prevent major database upgrades (PostgreSQL / MariaDB)?
**A**: Major database upgrades should never be auto-merged due to data migration requirements. Major updates are already blocked from auto-merging under `matchUpdateTypes: ["major"]` and critical infrastructure rules.

---

## Related References
* **[Docs/VPS_SERVICES_UPGRADE_GUIDE.md](Docs/VPS_SERVICES_UPGRADE_GUIDE.md)** — Master guide for database migrations and container upgrade intricacies.
* **[Docs/NETWORK_ARCHITECTURE.md](Docs/NETWORK_ARCHITECTURE.md)** — Architecture and gateway documentation.
