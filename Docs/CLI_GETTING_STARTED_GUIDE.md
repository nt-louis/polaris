# Net-Stream CLI & TUI Getting Started Guide

Comprehensive operator and developer guide for the unified Net-Stream orchestration engine (`./manage.py` and the `net-stream` system-wide CLI wrapper).

---

## Table of Contents

- [Overview](#overview)
- [System-Wide Setup (Getting Started)](#system-wide-setup-getting-started)
  - [Prerequisites](#prerequisites)
  - [1. Install the System-Wide CLI](#1-install-the-system-wide-cli)
  - [2. Verify PATH Configuration](#2-verify-path-configuration)
  - [3. Verify CLI Health](#3-verify-cli-health)
  - [Managing and Updating the CLI](#managing-and-updating-the-cli)
- [Interactive TUI Dashboard](#interactive-tui-dashboard)
  - [Launching the Dashboard](#launching-the-dashboard)
  - [Navigation and Shortcuts](#navigation-and-shortcuts)
  - [Tabulated Views and Search](#tabulated-views-and-search)
  - [Interactive Checklist Selector](#interactive-checklist-selector)
  - [Submenu Detail Views and Steppers](#submenu-detail-views-and-steppers)
- [CLI Reference & Daily Workflows](#cli-reference--daily-workflows)
  - [Status, Health, and Logs](#status-health-and-logs)
  - [Deploy, Redeploy, and Stop](#deploy-redeploy-and-stop)
  - [Container Updates & Rollback](#container-updates--rollback)
  - [Validation and Audit History](#validation-and-audit-history)
  - [Secrets Management (Doppler & SOPS)](#secrets-management-doppler--sops)
  - [Automated Backups & Disaster Recovery](#automated-backups--disaster-recovery)
  - [Network Repairs](#network-repairs)
  - [Git Hooks Guard](#git-hooks-guard)
- [Multi-Node Context (VPS A vs VPS B)](#multi-node-context-vps-a-vs-vps-b)
- [Troubleshooting & FAQs](#troubleshooting--faqs)

---

## Overview

Net-Stream includes a unified Python orchestration engine that automates container lifecycle operations, secret injection, dependency resolution, backup/restore, and network configuration.

Key capabilities:
- **Dual Execution Interfaces**: An interactive Text User Interface (TUI) dashboard for visual management and a robust Command-Line Interface (CLI) for scripts, CI/CD, and power users.
- **Dynamic Repository Discovery**: Run `net-stream` from any directory on the host machine without needing to switch back to the repository root.
- **Zero-Secret Disk Exposure**: Process-level Doppler secret injection with automated transient `.env` materialization and cleanup.
- **Topological Dependency Ordering**: Automatic graph sequencing ensuring gateways and network sidecars start before dependent services.
- **Dual-Node Awareness**: Isolated configuration contexts for VPS A and VPS B with automatic node targeting.

---

## System-Wide Setup (Getting Started)

### Prerequisites

Before installing the CLI wrapper, verify that the host machine satisfies:
- **Python**: Python 3.10 or newer (`python3 --version`).
- **Dependencies**: Install runtime requirements:
  ```bash
  python3 -m pip install -r requirements.txt
  ```
- **Docker & Compose**: Docker Engine 24.0+ and Docker Compose v2.x.
- **Doppler CLI**: Authenticated via `doppler login`.

### 1. Install the System-Wide CLI

From the repository root, run the installer script:

```bash
./install-cli.sh
```

Alternatively, install through `manage.py`:

```bash
./manage.py cli install
```

This creates a symlink pointing to the launcher wrapper at `~/.local/bin/net-stream`.

### 2. Verify PATH Configuration

Ensure `~/.local/bin` is in your shell's `PATH` environment variable.

Check with:
```bash
echo "$PATH" | grep -q "$HOME/.local/bin" && echo "PATH OK" || echo "PATH missing ~/.local/bin"
```

If it is not present, add it to your shell configuration (`~/.bashrc` or `~/.zshrc`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then reload your shell configuration:
```bash
source ~/.bashrc
```

### 3. Verify CLI Health

Verify the installation status from any directory:

```bash
net-stream cli verify
```

Expected output:
```text
net-stream CLI is properly installed and active at /home/ubuntu/.local/bin/net-stream
```

You can now run `net-stream` anywhere on the system (e.g. from `/home/ubuntu`, `Media/jellyfin`, or `/tmp`).

### Managing and Updating the CLI

- **Check CLI Status**:
  ```bash
  net-stream cli status
  ```
- **Uninstall the Wrapper**:
  ```bash
  net-stream cli uninstall
  ```
- **Updating**: Since `~/.local/bin/net-stream` is a symbolic link to the repository launcher, running `git pull` in your repository instantly updates the CLI across your system with zero reinstallation required.

---

## Interactive TUI Dashboard

### Launching the Dashboard

Run `net-stream` or `./manage.py` with no arguments to launch the full-screen terminal dashboard:

```bash
net-stream
```

### Navigation and Shortcuts

| Key / Action | Description |
|---|---|
| `Up` / `Down` or `k` / `j` | Move selection up and down in menus. |
| `1` - `9` | Direct numeric shortcut to execute or open a menu option. |
| `Enter` or `Space` | Select or execute the highlighted option. |
| `/` | Open the instant Command Palette / Search Filter. |
| `?` | Toggle keybindings and shortcut help modal. |
| `Esc` or `q` | Go back to parent menu, close popup, or exit dashboard. |
| `Ctrl+C` | Gracefully terminate the dashboard and restore terminal state. |

### Tabulated Views and Search

All main menus and submenus use a tabulated grid layout:
- **Columns**: Fixed-width Option Number (`#`), Title/Action Name, and Description.
- **Section Dividers**: Clean separators between operational categories (e.g. Core Lifecycle, Maintenance, Disaster Recovery).
- **Command Palette (`/`)**: Type any keyword (e.g. `backup`, `sonarr`, `verify`, `doctor`) to instantly filter and jump directly to commands.

### Live Status Inspector Controls

When viewing real-time container health via the TUI Status Inspector (`S` or Option 1):
- `/`: Activate real-time type-to-filter search (filters by service, container name, category, or port).
- `Enter`: Lock search query filter.
- `Esc`: Clear search query or exit inspector.
- `F`: Cycle lifecycle state filter (`ALL` → `HEALTHY` → `RUNNING` → `STOPPED`).
- `N`: Cycle target node filter (`Active Node` → `Node B` → `All Nodes`).
- `C`: Clear all active search and state filters.
- `V` / `Tab`: Toggle between Metric Overview and Full Scrollable Services Table.
- `R`: Force an immediate background refresh of Docker container states.
- `Up` / `Down` or `PageUp` / `PageDown`: Scroll through services table.

### Interactive Checklist Selector

When running deployment, redeployment, or service-level actions without arguments, the interactive checklist selector opens:

- **Metric Summary Cards**: Displays total projects, selected count, active VPS node, and estimated execution sequence.
- **Two-Pane Layout**:
  - *Left Pane*: Category list showing completion progress (e.g. `Media/local-media (3/5)`).
  - *Right Pane*: Service checklist showing service name, custom project ID, container status, and repository path.
- **Checklist Controls**:
  - `Space`: Toggle selection of highlighted service.
  - `a`: Select all services across the active VPS node.
  - `c`: Clear all selections.
  - `Enter`: Confirm selection and proceed with execution.
  - `Esc` / `q`: Cancel operation.

### Submenu Detail Views and Steppers

Submenus with numerical inputs (such as image stability age-gates or backup retention days) feature interactive steppers:
- `Left` / `Right` arrows or `-` / `+`: Decrease or increase values.
- `Enter`: Confirm value.

---

## CLI Reference & Daily Workflows

### Status, Health, and Logs

Inspect real-time container health, network bindings, and ports:

```bash
# View active containers on current host node
net-stream status

# Explicitly inspect VPS A, VPS B, or all nodes
net-stream status --vps A
net-stream status --vps B
net-stream status --vps all

# Search services by project name, container, or network port
net-stream status --search jellyfin
net-stream status -q paperless

# Filter by container health/lifecycle state
net-stream status --state healthy
net-stream status --state running
net-stream status --state stopped

# Filter by category name
net-stream status --category Utilities
net-stream status -c Media

# Machine-readable JSON output for monitoring scripts
net-stream status --json

# Pre-flight infrastructure diagnostics (Doppler, VPN namespaces, Tailscale, Disk)
net-stream doctor

# Stream live container logs by short service name
net-stream logs jellyfin -f --tail=100
net-stream logs sonarr
```

### Deploy, Redeploy, and Stop

Deploy, restart, or stop workloads with dependency ordering:

```bash
# Interactive deployment selector
net-stream deploy

# Deploy specific services by short name, project name, or directory path
net-stream deploy jellyfin sonarr bazarr
net-stream deploy Utilities/auth/pocketid

# Deploy last saved selection directly without prompts
net-stream deploy --last

# Deploy with dry-run simulation (verifies configuration with zero restarts)
net-stream deploy --dry-run

# Force recreation of network gateway sidecars
net-stream deploy --force-gateways

# Redeploy active containers with image builds
net-stream redeploy --build

# Recreate running containers
net-stream redeploy --recreate

# Gracefully stop containers
net-stream stop jellyfin
net-stream stop --vps B
```

> [!TIP]
> **Headless Execution (`--yes` / `-y`)**: Add `-y` to bypass confirmation gates in automation scripts and CI pipelines (e.g. `net-stream stop --vps B -y`).

### Container Updates & Rollback

Perform safe, transactional container updates with automated backups and image rollback:

```bash
# Check for available image updates without modifying containers
net-stream update --check

# Dry-run update evaluation with 2-day stability age-gate
net-stream update --dry-run --min-age 2

# Apply updates with 7-day image backup retention
net-stream update --min-age 1 --backup-days 7 --yes

# List currently backed-up images available for rollback
net-stream update --list-backups
```

### Validation and Audit History

Ensure repository and container configurations are error-free:

```bash
# Validate Docker Compose syntax, Caddyfiles, and manifest sync
net-stream validate

# Automatically register untracked compose projects into the manifest
net-stream validate --fix

# View audit history of past CLI operations
net-stream history
net-stream history --json
```

### Secrets Management (Doppler & SOPS)

Manage centralized runtime secrets and encrypted offline backups:

```bash
# Verify Doppler CLI authentication
net-stream secrets verify

# Open the Doppler web management dashboard
net-stream secrets open

# Create encrypted SOPS/age offline fallback snapshots
net-stream secrets snapshot
net-stream secrets snapshot --vps B

# List offline snapshot inventory
net-stream secrets snapshots

# Synchronize snapshots to dedicated git branch via worktree
net-stream secrets sync-branch
```

### Automated Backups & Disaster Recovery

Manage Restic encrypted volume backups:

```bash
# Run immediate volume backup snapshot
net-stream backup run
net-stream backup run --vps B

# List backup snapshots
net-stream backup snapshots

# Inspect repository storage statistics and compression
net-stream backup stats --mode raw-data

# Enforce retention policy and prune unused repository data
net-stream backup prune --max-unused 10%

# Test repository integrity
net-stream backup check

# Interactive disaster recovery restoration
net-stream backup restore

# Restore specific snapshot non-interactively
net-stream backup restore --snapshot <snapshot_id> --yes
```

### Network Repairs

Diagnose and repair network sidecars and routing:

```bash
# Automatically diagnose and repair Tailscale MagicDNS and gateway state
net-stream network fix

# Reset network routing interfaces
net-stream network reset
```

### Git Hooks Guard

Protect against accidental secret and state file commits:

```bash
# Install the pre-commit secret/state guard
net-stream hooks install

# Verify pre-commit hook installation
net-stream hooks verify
```

---

## Multi-Node Context (VPS A vs VPS B)

Net-Stream operates across dual VPS targets:
- **Active Node Tracking**: The CLI tracks your active context in `.active_vps` (e.g. `A` or `B`).
- **Global Flag Override**: Pass `--vps A` or `--vps B` on any command to target a specific node without switching your persistent context.
- **GitOps Integration**: In automated CI/CD (`deploy.yml`), the deployment runner on VPS A only deploys services assigned to Node A, while the runner on VPS B only deploys services assigned to Node B. If a commit modifies services on the other node, the runner skips cleanly and logs an informative notice.

---

## Troubleshooting & FAQs

### `Error: Could not locate net-stream repository root`
- **Cause**: The launcher could not find `manage.py` and `orchestrator/` in the current directory or parent paths.
- **Solution**: Set the `NET_STREAM_ROOT` environment variable in your shell profile:
  ```bash
  export NET_STREAM_ROOT="~/polaris"
  ```

### `net-stream: command not found`
- **Cause**: `~/.local/bin` is missing from your `$PATH`.
- **Solution**: Add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc` and run `source ~/.bashrc`.

### `Doppler Error: Unable to authenticate`
- **Cause**: Doppler service token or CLI session expired.
- **Solution**: Run `doppler login` followed by `net-stream secrets verify`.

### `Service 'X' is assigned to VPS A, but active filter is VPS B`
- **Cause**: You requested a service on Node B that is configured for Node A in `manifest.yaml`.
- **Solution**: Use the correct node filter (e.g. `net-stream deploy X --vps A`) or update node assignment in `orchestrator/registry/manifest.yaml` if migrating workloads.
