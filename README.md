# Polaris

**Self-Hosted Media and Utilities Infrastructure**

Polaris is a containerized, self-hosted media ecosystem and utility platform featuring Jellyfin, the *Arr suite, Stremio add-ons, AI tools, and productivity applications. It employs a **Nested Gateway** network architecture using VPN sidecars (Gluetun, Tailscale, and Caddy) for network isolation, encrypted mesh connectivity, and zero-trust access control.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
  - [Network Topology](#network-topology)
  - [Localhost Binding Rule](#localhost-binding-rule)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Secrets and Environment](#secrets-and-environment)
- [Service Architecture](#service-architecture)
  - [Core Media](#core-media)
  - [Stremio Ecosystem](#stremio-ecosystem)
  - [Books & Anime](#books--anime)
  - [Utilities & Infrastructure](#utilities--infrastructure)
  - [DNS & Authentication](#dns--authentication)
- [Management CLI](#management-cli)
- [Documentation Directory](#documentation-directory)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Polaris provides a production-grade infrastructure model for orchestrating self-hosted workloads across isolated network perimeters. Rather than exposing container ports directly or placing all services on a single bridge network, Polaris groups applications into dedicated network gateways backed by WireGuard/Gluetun VPN sidecars and Tailscale mesh nodes.

---

## Key Features

- **Nested Gateway Isolation**: Workload clusters run within dedicated network namespaces provided by Gluetun VPN and Tailscale sidecars (`core`, `util`, `stremio-util`, `addons`, `comics`, `proton`, `cloud`, `dns-gateway`), plus the Tailscale-only `util-b` bridge and host-network services.
- **Tailnet MagicDNS Integration**: Internal services are accessed via Tailscale MagicDNS (`https://<gateway>.<tailnet>.ts.net`) with automated TLS certificate provisioning.
- **Dual Exit Node Routing**: Hybrid egress utilizing a bare-metal WireGuard (`wg0`) exit node (~260 Mbps) along with containerized fallback exit nodes.
- **Unified Management CLI**: Full lifecycle orchestration, interactive deployment, environment synchronization, and automated disaster recovery via `./manage.py`.
- **Zero-Trust SSO Authentication**: Integrated PocketID (OpenID Connect) and OAuth2-Proxy middleware for centralized access control.

---

## Architecture

### Network Topology

Traffic is routed through isolated gateway perimeters before reaching application services:

```text
                  ┌────────────────────────────────────────────────────────┐
                  │                 Tailscale Mesh Network                 │
                  └───────────────────────────┬────────────────────────────┘
                                              │
Internet ──> Cloudflare ──> Host Caddy ───────┼──> Gateway (Gluetun VPN)
                                              │         │
                                              │         ├──> App 1 (127.0.0.1:port)
                                              │         └──> App 2 (127.0.0.1:port)
```

### Localhost Binding Rule

> [!IMPORTANT]
> **Container Networking Requirement**: Because services within a gateway cluster share Gluetun's network namespace (`network_mode: service:<gateway>`), standard Docker container DNS resolution (e.g. `http://jellyfin:8096`) does not apply across services in the same cluster. Inter-service communications within a gateway must use `127.0.0.1:<port>`.

For detailed network routing specifications, refer to [Docs/NETWORK_ARCHITECTURE.md](Docs/NETWORK_ARCHITECTURE.md).

---

## Prerequisites

Before deploying Net-Stream, verify that the host machine satisfies the following operational requirements:

- **Linux Kernel & Network Utilities**: `wireguard`, `iptables`, and `ip6tables` enabled.
- **Tailscale**: Tailscale daemon installed and active on the host machine.
- **Docker & Docker Compose**: Docker Engine 24.0+ and Compose v2.x.
- **Python**: Python 3.10+ (for running `./manage.py`).
- **Python packages**: Install runtime dependencies with `python3 -m pip install -r requirements.txt`.

For host kernel configuration details, refer to the [Host Prerequisites section of Docs/NETWORK_ARCHITECTURE.md](Docs/NETWORK_ARCHITECTURE.md#host-prerequisites).

---

## Quick Start

### 1. Clone and Authenticate Doppler

Clone the repository and authenticate the Doppler CLI. Production secrets are
stored in Doppler; `.env.example` files document required variable names and
are not production secret stores.

```bash
git clone https://github.com/nt-louis/net-stream.git
cd net-stream
doppler --version
doppler login
./manage.py secrets verify
```

If the CLI is not authenticated, install it and run `doppler login`. Then create
or populate the matching VPS project/configs as described in
[Docs/DOPPLER_OPERATIONS_GUIDE.md](Docs/DOPPLER_OPERATIONS_GUIDE.md).

### 2. Install System-Wide CLI Wrapper (Optional but Recommended)

Install the `net-stream` CLI wrapper to run management commands from any working directory on the host:

```bash
./install-cli.sh
net-stream cli verify
```

See [Docs/CLI_GETTING_STARTED_GUIDE.md](Docs/CLI_GETTING_STARTED_GUIDE.md) for the complete setup guide and command reference.

### 3. Enable Tailscale HTTPS

In the [Tailscale Admin Console -> DNS](https://login.tailscale.com/admin/dns), enable:
1. **MagicDNS**
2. **HTTPS Certificates**

### 4. Stack Deployment

Launch the interactive stack management interface:

```bash
net-stream deploy    # or ./manage.py deploy
```

For local linting and tests, install the development dependencies:

```bash
python3 -m pip install -r requirements-dev.txt
```

Select the desired service gateways to build, configure, and start the containers.

The manager selects `net-stream-vps-a` or `net-stream-vps-b` from the VPS
context, injects values with `doppler run`, and cleans up any transient
`.env` files required by compose `env_file` declarations. Do not run direct
`docker compose` commands for production deployment.

## Secrets and Environment

Net-Stream utilizes a layered secrets architecture:
1. **Primary Write Surface & Runtime Injection (Doppler SaaS)**: One project per VPS (`net-stream-vps-a` and `net-stream-vps-b`) with configs mapped to compose stacks. Secrets are injected at runtime via process memory with zero plaintext disk exposure.
2. **Offline Resilience & Cold Backup (SOPS + age Encrypted Snapshots)**: Committed ciphertext snapshots under `.snapshots/<project>/<config>.env.enc` encrypted with `age`. If Doppler is unreachable or during disaster recovery, the CLI automatically and transparently decrypts the snapshots in-memory using your private key (`keys.txt`).

Refer to [Docs/DOPPLER_OPERATIONS_GUIDE.md](Docs/DOPPLER_OPERATIONS_GUIDE.md) for configuration rules, rotation workflows, snapshot management (`./manage.py secrets snapshot`), and automated branch synchronization (`./manage.py secrets sync-branch`).

The `./manage.py utils env` command is a development utility that copies
missing `.env.example` templates. It is not used to populate production secrets.

---

## Service Architecture

Services are grouped into logical gateway clusters. Expand any section below for port mappings and service descriptions, or refer to [Docs/TAILSCALE_URLS.md](Docs/TAILSCALE_URLS.md) for the complete port matrix.

<details>
<summary><b>Core Media Cluster (<code>core</code> gateway)</b></summary>

| Service | Internal Port | Description |
|---|---|---|
| **Jellyfin** | 8096 | Primary media streaming server |
| **Monochrome** | 4173 | Music streaming player |
| **Seerr** | 5055 | Media request and discovery management |
| **Radarr / Sonarr** | 7878 / 8989 | Movie and TV series automation |
| **Prowlarr / Bazarr** | 9696 / 6767 | Indexer management and subtitle automation |
| **qBittorrent / SABnzbd** | 8080 / 8085 | BitTorrent and Usenet download clients |
| **Tracearr / Remux** | 3015 / 3000 | Download activity tracking and media remuxing |

</details>

<details>
<summary><b>Stremio Ecosystem (<code>stremio-util</code> and <code>addons</code> gateways)</b></summary>

| Gateway | Services | Description |
|---|---|---|
| `stremio-util` | Syncio, Jackett, MediaFlow Proxy, VPS-B agents | Add-on utilities, indexer proxying, and remote monitoring |
| `addons` | Comet, AIOStreams, Watchly, StremThru, StreamNZB, NZBDav, NZBHydra2 | Multi-source streaming providers and watch history synchronization |
| `proton` | AIO Manager, AIO Metadata | Isolated addon utility services |

</details>

<details>
<summary><b>Books & Audiobooks (<code>comics</code> gateway)</b></summary>

| Gateway | Services | Description |
|---|---|---|
| `comics` | Audiobookshelf, Grimmory, Suwayomi, Shelfmark, Athenaeum, Bindery | Audiobooks, comics, e-books, and manga reader services |

</details>


<details>
<summary><b>Utilities & Infrastructure (<code>util</code>, <code>util-b</code>, and host network)</b></summary>

| Category | Key Services |
|---|---|
| **Management** | Homarr, Dockhand, Hawser, Infisical |
| **Productivity** | Paperless-ngx, Linkwarden, Memos, FreshRSS |
| **Tools** | Apprise, Stirling-PDF, BentoPDF, IT-Tools, n8n, Open WebUI |
| **Monitoring** | Uptime Kuma, Beszel, Dozzle |
| **Cloud gateway** | Nextcloud and its Rclone mount (`cloud`) |
| **VPS B bridge** | Penpot, Supabase, Excalidraw (`util-b`, `vps_b_net`) |
| **Host network** | Hawser, Dockhand, Beszel Agent, Cloudflare Tunnel |

</details>

<details>
<summary><b>DNS & Authentication (<code>dns-gateway</code> and Host Network)</b></summary>

| Gateway / Network | Service | Description |
|---|---|---|
| `dns-gateway` | AdGuard Home (53 / 3000) | Network DNS resolution and ad-blocking |
| Host Network | PocketID (3055) + OAuth2-Proxy (4180) + Vaultwarden (8088) | OpenID Connect, authentication proxy, and password vault |
| `cloud` | Nextcloud (8080) | File storage and collaboration through the dedicated cloud gateway |
| `util` | Paperless-ngx (8084) | Document management in the utility Gluetun namespace |

</details>

---

## Management CLI

The repository includes `manage.py`, a Python management tool providing interactive TUI and command-line interfaces for stack orchestration:

| Command | Description |
|---|---|
| `./manage.py` | Launches the interactive TUI menu for container lifecycle management. |
| `./manage.py deploy` | Starts deployment wizard or deploys specific services/stacks (`[svc ...]`, `--services DIR/APP...`, `--vps A|B`, `--last`, `--force-gateways`). |
| `./manage.py redeploy` | Rebuilds and recreates active container instances (`[svc ...]`, `--services DIR/APP...`, `--build`, `--recreate`). |
| `./manage.py stop` | Gracefully stops containers (all, by `--vps A|B`, or by specific service names/paths `[svc ...]`, `--services DIR/APP...`). |
| `./manage.py backup` | Runs automated snapshot backups and disaster recovery (`run`, `restore`, `snapshots`, `check`). |
| `./manage.py status` | Real-time container health, state, and port inspector (`[targets]`, `--search query`, `--state`, `--category`, `--vps A|B|all`, `--json`). |
| `./manage.py logs` | Stream container logs by short service or gateway name (`<service>`, `-f`, `--tail=N`). |
| `./manage.py doctor` | Run automated pre-flight infrastructure diagnostics (Doppler, VPN, Tailscale, disk). |
| `./manage.py validate` | Validate Docker Compose syntax and Caddy routing across stacks (`--vps A or B`). |
| `./manage.py history` | View persistent operation audit history log of executed stack actions (`--json`). |
| `./manage.py update` | Check and apply container image updates (`--check`, `--list-backups`, `--min-age N`, `--backup-days N`). |
| `./manage.py secrets` | Verifies Doppler authentication or opens the Doppler dashboard (`verify`, `open`). |
| `./manage.py network` | Repair Tailscale/gateway network routing or reset interface state (`fix`, `reset`). |
| `./manage.py utils` | Repository setup and custom build utilities (`env`, `fmhy`, `monochrome`, `build`, `netbird-server`, `dependency-report`). |
| `./manage.py hooks` | Installs or verifies git pre-commit hooks (`install`, `verify`) for secret protection. |
| `./manage.py cli` | Installs, verifies, or uninstalls the system-wide `net-stream` CLI wrapper (`install`, `verify`, `status`, `uninstall`, or `./install-cli.sh`). |

> [!NOTE]
> **Global `--yes` / `-y` Flag**: The flag auto-confirms destructive confirmation gates and applicable deploy/update prompts (e.g. `./manage.py stop --yes` or `./manage.py redeploy --build --yes`). Read-only commands such as `status`, `logs`, `doctor`, `validate`, and `secrets` do not need it.


---

## Documentation Directory

| Category | Document | Description |
|---|---|---|
| **Networking** | [NETWORK_ARCHITECTURE.md](Docs/NETWORK_ARCHITECTURE.md) | Nested gateway pattern, WireGuard setup, and host routing table |
| | [TAILSCALE_URLS.md](Docs/TAILSCALE_URLS.md) | Complete port matrix and internal Tailscale domain list |
| | [CLOUDFLARE_TUNNEL.md](Docs/CLOUDFLARE_TUNNEL.md) | Cloudflare Tunnel configuration and reverse proxy routing |
| | [ADGUARD_SETUP.md](Docs/ADGUARD_SETUP.md) | DNS configuration and ad-blocking policy configuration |
| **Operations** | [CLI_GETTING_STARTED_GUIDE.md](Docs/CLI_GETTING_STARTED_GUIDE.md) | System-wide CLI wrapper setup, interactive TUI guide, and CLI command reference |
| | [BACKUP_RESTORE_GUIDE.md](Docs/BACKUP_RESTORE_GUIDE.md) | Automated backups and disaster recovery runbook |
| **Secrets** | [DOPPLER_OPERATIONS_GUIDE.md](Docs/DOPPLER_OPERATIONS_GUIDE.md) | Doppler projects/configs, runtime injection, onboarding, rotation, and recovery |
| | [DOPPLER_MIGRATION_COMMIT_REFERENCE.md](Docs/DOPPLER_MIGRATION_COMMIT_REFERENCE.md) | Git commit reference for SOPS-to-Doppler migration and legacy `.env.enc` restoration |
| | [SOPS_DOPPLER_SNAPSHOT_PLAN.md](Docs/SOPS_DOPPLER_SNAPSHOT_PLAN.md) | Implementation plan for SOPS+age encrypted snapshot fallback layer on top of Doppler |
| | [VPS_SERVICES_UPGRADE_GUIDE.md](Docs/VPS_SERVICES_UPGRADE_GUIDE.md) | Host maintenance and service upgrading procedures |
| | [RENOVATE_AUTOMATION_GUIDE.md](Docs/RENOVATE_AUTOMATION_GUIDE.md) | Renovate Bot GitHub setup, JSON rules, and dependency automation |
| | [UPTIME_KUMA_GUIDE.md](Docs/UPTIME_KUMA_GUIDE.md) | Monitoring topology and alert notification integrations |
| **Integrations** | [DEBRID_ZURG_SETUP.md](Docs/DEBRID_ZURG_SETUP.md) | Real-Debrid WebDAV mounting via Zurg and Rclone |
| | [NEXTCLOUD_OIDC_GUIDE.md](Docs/NEXTCLOUD_OIDC_GUIDE.md) | Nextcloud OpenID Connect (OIDC) single sign-on configuration |
| | [PocketID Auth](Utilities/auth/pocketid/) | Lightweight OpenID Connect identity provider configuration |
| | [OAuth2-Proxy](Utilities/auth/oauth2-proxy/) | Authentication proxy middleware configuration |
| **Research** | [NETBIRD_COMPARISON.md](Docs/NETBIRD_COMPARISON.md) | Technical comparison between NetBird and Tailscale mesh architectures |
| | [NETBIRD_SELFHOSTING.md](Docs/NETBIRD_SELFHOSTING.md) | Step-by-step self-hosted NetBird Control Plane setup with PocketID OIDC |
| | [NETBIRD_DEPLOYMENT_LOG.md](Docs/NETBIRD_DEPLOYMENT_LOG.md) | Historical incident and deployment log for self-hosted NetBird and CrowdSec |
| | [K8S_VPS_LEARNING_ROADMAP.md](Docs/K8S_VPS_LEARNING_ROADMAP.md) | Practical 2-node k3s Kubernetes cluster learning roadmap over Tailscale |
| | [ARCHIVED_GUIDE.md](Docs/ARCHIVED_GUIDE.md) | Historical split-horizon DNS architecture reference |

---

## Contributing

Contributions, bug reports, and feature requests are welcome. Please ensure that pull requests follow existing project standards and include updated documentation where appropriate.

---

## License

This project is provided for personal and educational use. See individual service licenses for underlying containerized components.
