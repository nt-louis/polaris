# Network Architecture: The Nested Gateway Pattern

This document is the authoritative technical reference for the network architecture, isolated gateway topologies, policy routing, and reverse proxy mechanisms utilized across the Polaris stack.

---

## Architecture Overview

Polaris implements a **Nested Gateway Pattern** to partition self-hosted application workloads across isolated network perimeters. Most application containers share network namespaces with specialized **Gluetun + Tailscale + Caddy** gateways, but not every workload uses that class. The active topology also includes a Tailscale-only bridge gateway, a dedicated cloud Gluetun gateway, host-network agents, and a separate NetBird control plane.

### Traffic Flow Diagram

```text
                  ┌────────────────────────────────────────────────────────┐
                  │                 Tailscale Mesh Network                 │
                  └───────────────────────────┬────────────────────────────┘
                                              │
Internet ──> Cloudflare ──> Host Caddy ───────┼──> Gateway namespace
                                              │    ├── Gluetun + Tailscale + Caddy
                                              │    ├── Tailscale + Caddy (bridge)
                                              │    └── Host-network / bridge exceptions
                                              │         ├──> App 1 (127.0.0.1:port)
                                              │         └──> App 2 (127.0.0.1:port)
```

1. **Public Ingress**: Internet traffic passes through Cloudflare Tunnels (or Cloudflare DNS) to Host Caddy on the VPS host.
2. **Tailnet Mesh Routing**: Host Caddy routes requests over private Tailscale MagicDNS FQDNs (`<gateway>.<tailnet>.ts.net`) directly to the target gateway node.
3. **Namespace Ingress/Egress**: Gluetun gateways receive ingress through their `tailscale0` interface and send internet egress through `tun0`. Tailscale-only and host-network services follow their own network rules documented below.

---

## Host Prerequisites & Policy Routing

Before launching gateway containers, the host Linux kernel requires system-level networking utilities and custom policy routing tables to support hybrid egress.

### Required Host Packages

```bash
sudo apt update && sudo apt install -y wireguard iproute2 iptables
```

### Tailscale Daemon (Host Ingress & Primary Exit Node)

Tailscale runs natively on the VPS host to manage mesh connectivity and serve as the primary egress exit node:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --advertise-exit-node --accept-dns=true
```

- **MagicDNS**: Host Caddy resolves gateway targets using MagicDNS names (e.g., `core`, `util`, `stremio-util`).
- **Primary Exit Node**: Routes Tailnet client traffic through the host's WireGuard tunnel (`wg0`).

### Bare-Metal WireGuard Egress (`wg0`)

The host establishes a WireGuard connection (`wg0`) to a VPN provider. Client traffic routed through the Tailscale exit node is masqueraded over `wg0` rather than leaking the VPS public IP.

`/etc/wireguard/wg0.conf` configuration snippet:

```ini
[Interface]
PrivateKey = <YOUR_PRIVATE_KEY>
Address = <YOUR_VPN_CLIENT_IP>/32
DNS = 1.1.1.1
Table = off

# --- PostUp: Create routing table & NAT ---
PostUp = ip route add default dev wg0 table 51820
PostUp = iptables -t nat -A POSTROUTING -s 100.64.0.0/10 -o wg0 -j MASQUERADE
PostUp = iptables -t mangle -A FORWARD -o wg0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
PostUp = resolvectl domain wg0 ""

# --- PreDown: Cleanup ---
PreDown = ip route del default dev wg0 table 51820
PreDown = iptables -t nat -D POSTROUTING -s 100.64.0.0/10 -o wg0 -j MASQUERADE
PreDown = iptables -t mangle -D FORWARD -o wg0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
PreDown = resolvectl default-route tailscale0 true

[Peer]
PublicKey = <VPN_PROVIDER_PUBLIC_KEY>
Endpoint = <VPN_ENDPOINT_IP>:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

- **`Table = off`**: Prevents WireGuard from overriding the default host routing table (preserving SSH access).
- **NAT Masquerade**: Maps Tailscale subnets (`100.64.0.0/10`) out `wg0`.
- **MSS Clamping**: Adjusts TCP maximum segment size to prevent HTTPS stalls caused by MTU overhead.

### Kernel Sysctl Configuration

Enable IP forwarding and set reverse-path filtering to loose (`2`) to allow asymmetric VPN packet routing:

```bash
sudo tee /etc/sysctl.d/99-hybrid-routing.conf >/dev/null <<'EOF'
net.ipv4.ip_forward = 1
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.default.rp_filter = 2
net.ipv4.conf.tailscale0.rp_filter = 2
EOF
sudo sysctl --system
```

---

## Gateway Container Classes

### Gluetun + Tailscale + Caddy

The standard gateway stack (for example `Media/local-media/gateway`,
`Utilities/gateway`, and `Network`) instantiates an isolated network stack
comprising:

1. **Gluetun**: Creates the primary container network namespace, connects to WireGuard VPN (`tun0`), and maintains an automatic firewall kill-switch.
2. **Tailscale Sidecar**: Attaches to Gluetun's network namespace (`network_mode: "service:gluetun"`) to provide encrypted Tailnet ingress/egress.

### Tailscale Sidecar Entrypoint Routing Fix

To resolve conflict between Gluetun's VPN default route and Tailscale's mesh routing table, Tailscale sidecars execute a custom startup command:

```yaml
entrypoint: ["/bin/sh", "-c"]
command: ["ip rule add lookup 52 priority 50 2>/dev/null; iptables-nft -I INPUT -i tailscale0 -j ACCEPT 2>/dev/null; iptables -P FORWARD ACCEPT 2>/dev/null; iptables-nft -P FORWARD ACCEPT 2>/dev/null; exec /usr/local/bin/containerboot"]
```

- **`ip rule add lookup 52 priority 50`**: Forces Tailscale's routing table (`52`) to be evaluated prior to Gluetun's VPN catch-all rule, ensuring Tailnet response packets return via `tailscale0`. The repository repair script also uses priority `50`.
- **`iptables-nft -I INPUT -i tailscale0 -j ACCEPT`**: Whitelists Tailnet ingress traffic through Gluetun's nftables firewall.

---

## The Shared Namespace Rule (Localhost Binding)

When deploying workload containers (e.g., Jellyfin, Radarr, or Homarr), they are attached directly to their gateway container namespace:

```yaml
# Example: Media/local-media/players/jellyfin/docker-compose.yml
network_mode: "container:media-gateway-core-gluetun"
```

### Critical Container Networking Constraints

1. **No Port Mappings**: Workload compose files **must not** define `ports:`. All listening ports are contained within the gateway namespace.
2. **No Docker DNS**: Standard container-to-container DNS resolution (`http://jellyfin:8096`) **does not work** across services in the same gateway. All containers share the same network stack.
3. **Localhost Binding**: Inter-service communication inside a gateway cluster must bind to **`127.0.0.1:<port>`**.

---

## Gateway Topology & Repository Structure

### Active Gateway Matrix

| Gateway Path | Tailscale Hostname | Key Workload Services | Egress Pathway |
|---|---|---|---|
| `Media/local-media/gateway` | `core` | Jellyfin, Seerr, Radarr, Sonarr, Prowlarr, qBittorrent, SABnzbd, Tracearr, Remux | Gluetun VPN |
| `Media/stremio/utilities/gateway` | `stremio-util` | Syncio, Jackett, MediaFlow Proxy, Open WebUI, Scrob | Gluetun VPN |
| `Media/stremio/addons/gateway` | `addons` | Comet, Watchly, AIOStreams, StremThru, StreamNZB, NZBDav, NZBHydra2 | Gluetun VPN |
| `Media/stremio/addons/gateway-proton` | `proton` | AIO Manager, AIO Metadata | Gluetun VPN |

| `Media/comics/gateway` | `comics` | Audiobookshelf, Grimmory, Suwayomi, Shelfmark, Athenaeum, Bindery | Gluetun VPN |
| `Utilities/gateway` | `util` | Apprise, Beszel, Dozzle, FMHY, FreshRSS, Memos, n8n, SearXNG, Stirling-PDF, Uptime Kuma, and utility tools | Gluetun VPN |
| `Network` | `dns-gateway` | AdGuard Home (Port 53 / 3000) | Local / Gateway |
| `Utilities/exit-node` | `exit-node` | Containerized Tailscale Backup Exit Node | Gluetun VPN |
| `Utilities/cloud-docs/nextcloud/gateway` | `cloud` | Nextcloud and its Rclone mount | Gluetun VPN |
| `Utilities/gateway-b` | `util-b` | Penpot, Excalidraw, Supabase, and VPS B bridge services | Tailscale-only bridge (`vps_b_net`) |
| `Utilities/netbird-server` | `host` / `netbird_net` | NetBird dashboard, management, signal, relay, and Coturn | Docker bridge plus host-mode Coturn |

### Repository Directory Hierarchy

```text
polaris/
├── Media/
│   ├── comics/
│   │   └── gateway/                ← Tailscale hostname: comics
│   ├── local-media/
│   │   └── gateway/                ← Tailscale hostname: core
│   ├── stremio/

│   │   ├── addons/
│   │   │   ├── gateway/            ← Tailscale hostname: addons
│   │   │   └── gateway-proton/     ← Tailscale hostname: proton
│   │   └── utilities/
│   │       └── gateway/            ← Tailscale hostname: stremio-util
│   └── zurg/                       ← Disabled Real-Debrid reference stack
├── Network/
│   └── docker-compose.yml          ← Tailscale hostname: dns-gateway
└── Utilities/
    ├── admin/                      ← Homarr, Dockhand, Hawser, Infisical
    ├── auth/                       ← PocketID (3055), OAuth2-Proxy (4180), Vaultwarden
    ├── bookmarks-notes/            ← Linkwarden (3000), Memos (5230)
    ├── cloud-docs/                 ← Nextcloud (8080), Paperless-ngx (8000)
    ├── exit-node/                  ← Backup Tailscale Exit Node
    ├── gateway/                    ← Tailscale hostname: util
    ├── gateway-b/                  ← Tailscale hostname: util-b, VPS B bridge
    ├── monitoring/                 ← Uptime Kuma (3005), Beszel, Dozzle (8086)
    ├── search/                     ← SearXNG (8082)
    └── tools/                      ← Apprise, Stirling-PDF (8083), BentoPDF, IT-Tools, n8n, Open WebUI, Penpot, Supabase, Excalidraw
```

---

## Host-Network Services & Auth Proxying

Services that require ultra-low latency or handle authentication proxying run directly on the host network bound to `127.0.0.1`.

### Network Exceptions

| Service class | Active examples | Network boundary |
|---|---|---|
| Host network agents | `Utilities/admin/hawser`, `Utilities/admin/dockhand`, `Utilities/monitoring/beszel-agent`, Cloudflare Tunnel | Shares the VPS host network. Host bindings and firewall rules apply directly. |
| Tailscale-only bridge | `Utilities/gateway-b` and its VPS B applications | Containers share `vps_b_net`; Caddy reaches services by Docker DNS names. It has no Gluetun VPN namespace. |
| Cloud gateway | `Utilities/cloud-docs/nextcloud/gateway` and Nextcloud | Shares the `cloud` Gluetun namespace and uses `127.0.0.1` for Nextcloud services. |
| NetBird control plane | `Utilities/netbird-server` | Services use `netbird_net`; Coturn uses host networking. Host Caddy and external firewall rules are required. |

### Homarr Tailnet Access

Homarr shares the `utilities-gateway-gluetun` namespace instead of using host
network mode. This gives its server-side integrations access to Tailscale
MagicDNS and the `100.64.0.0/10` Tailnet while avoiding global host listeners.
Host Caddy proxies traffic via `util.<tailnet-domain>.ts.net:7575`.

### PocketID & OAuth2-Proxy (OIDC Authentication)

- **PocketID** (`127.0.0.1:3055`): Lightweight OIDC Identity Provider.
- **OAuth2-Proxy** (`127.0.0.1:4180`): Handles reverse-proxy forward auth (`/oauth2/auth`) for legacy applications lacking native OIDC support.

#### Forward Auth Request Sequence

```text
User Request ──> Host Caddy ──> OAuth2-Proxy (127.0.0.1:4180)
                                      │
              ┌───────────────────────┴───────────────────────┐
              ▼                                               ▼
     Session Valid (200 OK)                        Session Invalid (401)
              │                                               │
              ▼                                               ▼
  Proxy to Gateway Target                      Redirect to PocketID Login
```

---

## Host Caddy Reverse Proxying

Host Caddy receives public traffic from Cloudflare Tunnels and proxies requests across the Tailnet using Tailscale MagicDNS FQDNs.

### TLS Termination & Plain HTTP Site Blocks

Because TLS/SSL is terminated upstream at Cloudflare's edge network, Host Caddy site blocks explicitly use the **`http://` scheme** (e.g. `http://jellyfin.example.com`).

#### Configuration Rules
1. **Bypasses Let's Encrypt**: Closed public firewall ports (80/443) prevent standard ACME HTTP-01/TLS-ALPN-01 challenges. `http://` prevents Caddy from attempting certificate issuance.
2. **Tailnet FQDN Routing**: Upstream proxy targets specify full Tailnet FQDNs (e.g., `core.<tailnet-domain>.ts.net:8096`) to prevent systemd-resolved search domain lookup timeouts.

```caddyfile
# Reusable Forward Auth Protection Snippet
(protected) {
    handle /oauth2/* {
        reverse_proxy 127.0.0.1:4180
    }
    handle {
        import oauth2-proxy
        reverse_proxy {args[0]} {
            import proxy_settings
        }
    }
}

# Protected Service Example
http://jellyfin.example.com {
    import base_security
    import protected core.<tailnet-domain>.ts.net:8096
}

# Public Service Example (No Forward Auth)
http://comet.example.com {
    import base_security
    import cors
    reverse_proxy stremio-util.<tailnet-domain>.ts.net:8800 {
        import proxy_settings
    }
}
```

Refer to [`public-caddyfile-snippet.txt`](../public-caddyfile-snippet.txt) for template site blocks.

---

## Exit Node Redundancy

| Exit Node | Target Host | Implementation | Throughput |
|---|---|---|---|
| **Bare-metal** | VPS Host | Host WireGuard (`wg0`) + Tailscale daemon | ~260 Mbps (**primary**) |
| **Docker** | `exit-node` | Gluetun container + Tailscale sidecar | ~220 Mbps (**backup**) |

Switching between exit nodes is performed dynamically in the [Tailscale Admin Console](https://login.tailscale.com/admin/machines).

---

## Network Troubleshooting Runbook

### 1. Host Caddy DNS Lookup Failures (`RCODE 2 / server misbehaving`)

- **Root Cause**: `systemd-resolved` directed short-name queries away from Tailscale MagicDNS (`100.100.100.100`).
- **Fix**:
  1. Execute `sudo tailscale up --accept-dns=true`.
  2. Verify resolution status: `resolvectl status tailscale0`.
  3. Ensure site blocks use complete Tailnet FQDNs (`core.<tailnet>.ts.net:8096`).

### 2. Tailnet Ingress Timeouts (`tailscale ping` succeeds, port times out)

- **Root Cause**: Gluetun's nftables firewall dropping non-VPN ingress packets on `tailscale0`.
- **Fix**: Verify iptables entrypoint rule inside the gateway:
  ```bash
  docker exec <gluetun-container> iptables -L INPUT -n -v
  ```
  If `tailscale0` is unlisted, run:
  ```bash
  docker exec <tailscale-container> iptables-nft -I INPUT -i tailscale0 -j ACCEPT
  ```

### 3. Exit Node Egress Failures

- **Root Cause**: Tailscale table `52` is not being evaluated before Gluetun's catch-all rule, causing return packets to loop into the VPN interface. The repository repair rule is table `52` at priority `50`.
- **Fix**: Inspect IP routing rules:
  ```bash
  ip rule list | grep -E 'lookup 52|priority 50'
  # Expected: a table 52 rule at priority 50
  ```
  Check active WireGuard state: `sudo wg show`. A host WireGuard table such as
  `51820` is external host configuration and is not installed by
  `orchestrator/scripts/network/fix-routing.sh` (or `./manage.py network fix`).

### 4. Inter-Service Connection Errors (`ENOTFOUND` / `Connection Refused`)

- **Root Cause**: Attempting to use Docker container names (e.g. `http://mariadb:3306`) inside a shared container namespace.
- **Fix**: Update connection target strings to `127.0.0.1:<port>`.
