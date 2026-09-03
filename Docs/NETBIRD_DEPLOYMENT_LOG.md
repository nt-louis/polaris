# NetBird & CrowdSec Deployment Log
**Date**: July 25, 2026

> [!WARNING]
> This is a historical, VPS-specific incident log, not the active network
> architecture or a guaranteed current configuration. Tailscale remains the
> active mesh. Verify every claim against the current compose files and
> scripts before applying it.

This document contains a comprehensive record of all changes, troubleshooting steps, and configurations applied to resolve the self-hosted NetBird control plane and CrowdSec security stack on **VPS A**.

---

## 1. OIDC, PocketID & Redirect Loops
* **The Problem (Dashboard Loop)**: The NetBird browser dashboard crashed in an infinite redirect loop on startup. 
  * **The Cause**: The dashboard OIDC client redirect endpoints were set to `/` and `/silent-start`. The dashboard code interpreted root-path `/` requests as OIDC login tokens, creating a loop.
  * **The Fix**: Updated `Utilities/netbird-server/docker-compose.yml` to change redirect URIs to NetBird's standard `/nb-auth` and `/nb-silent-auth` endpoints.
* **The Problem (Invalid Client Error)**: Logins failed with `invalid_client` at the OAuth token endpoint.
  * **The Cause**: PocketID was expecting a secure Client Secret, but NetBird uses a public client authentication flow. 
  * **The Fix**: Updated PocketID's client configuration to **Public Client: On** and restarted PocketID to flush the cache.

---

## 2. Bypassing Cloudflare Tunnel Limitations (gRPC)
* **The Problem (Closed Streams)**: Client connections repeatedly failed with `server closed the stream without sending trailers`.
  * **The Cause**: NetBird relies heavily on gRPC streams (HTTP/2). Cloudflare Tunnels default to HTTP/1.1 when routing back to origin servers, which immediately strips and breaks active gRPC streams.
  * **The Fix**: 
    1. Bypassed Cloudflare's proxy servers entirely for NetBird.
    2. Configured a **DNS Only (Grey Cloud)** A Record pointing directly to the VPS public IP.
    3. Exposed ports **80** and **443** in the VPS firewall.
    4. Changed Caddy's configuration to use native HTTPS (`netbird.example.com`) so Caddy could obtain a real Let's Encrypt certificate directly on the VPS.

---

## 3. Fixing Caddy Protocol & Handshake Failures
* **The Problem (Error 525 / Handshake Failed)**: The dashboard would not load initially after opening ports.
  * **The Cause**: Caddy was still listening on port 80 (`http://netbird.example.com`), but requests were hitting port 443.
  * **The Fix**: Updated the Caddy domain block to listen on port 443 (by removing the `http://` prefix) and reloaded Caddy.
* **The Problem (`tls: no application protocol` ALPN error)**: The NetBird client could connect to the dashboard in the browser, but the CLI client failed TLS handshakes with Caddy.
  * **The Cause**: Caddy's global configuration in `/etc/caddy/snippets/base-utilities` was restricted to `protocols h1 h2c`. Since `h2c` is HTTP/2 cleartext, Caddy was prohibited from speaking standard encrypted HTTP/2 over TLS (`h2`) with the client.
  * **The Fix**: Updated Caddy's global options block to support modern TLS protocols:
    ```caddy
    servers {
        protocols h1 h2 h3
    }
    ```

---

## 4. Multiplexing the Signal Service & Desktop SSO Support
* **The Problem (Signal Connection Timeout)**: The client successfully connected to the Management service, but signal was disconnected with `dial tcp ...:10000: i/o timeout`.
  * **The Cause**: The NetBird server defaulted to telling clients that the Signal service was on port `10000`. Since port 10000 was blocked by the firewall, the client timed out.
  * **The Fix**: Updated `management.json` to configure the Signal service to use `https` on port `443`. This allowed Caddy to intercept `/signalexchange.SignalExchange/*` paths and proxy them locally to port 10000.
* **The Problem ("No SSO returned from management" on Windows)**: The Windows app connected to the server but blocked logins with an SSO configuration error.
  * **The Cause**: NetBird desktop/CLI client apps require OIDC PKCE/Device Authorization Flows to prompt browser logins. The server configuration file `management.json` was missing the `DeviceAuthorizationFlow` block.
  * **The Fix**: Added the missing `DeviceAuthorizationFlow` configuration block to `management.json` mapping to your PocketID OIDC endpoints and client configurations.

---

## 5. Exposing the Self-Hosted TCP/HTTPS Relay for UDP-Blocked Networks
* **The Problem (UDP hole-punching blocked on restricted Wi-Fi)**: When connecting from restrictive Wi-Fi networks (which block outbound UDP packets or restrict peer-to-peer UDP hole-punching), direct peer connections fail, and public NetBird relays are often blocked/unavailable (showing `Relays: 0/2 Available`).
  * **The Cause**: The Management service wasn't configured to advertise the self-hosted TCP/HTTPS relay service to connecting peers, leaving them without a fallback transport.
  * **The Fix**: 
    1. Configured the `"Relay"` block inside `management.json` with the secure `rels://relay.netbird.example.com:443` address, using your decrypted `NETBIRD_RELAY_SECRET` shared key. Note that we migrated this from the old subpath format `rels://netbird.example.com:443/relay` to a dedicated grey-clouded Cloudflare subdomain (`relay.netbird.example.com`) to prevent client-side port parsing errors and forward websocket handshakes cleanly to the root path.
    2. Updated the script `Scripts/utils/update-netbird-server.sh` to ensure `Relay` settings and the `https` `Signal` port are preserved dynamically on future server updates.
    3. Restarted the management and exit-node containers. The client now successfully registers the fallback relay and shows `Relays: 1/3 Available`.

---

## 6. Intrusion Prevention & Repository Cleanliness
* **The Problem (Security Exposure)**: Exposing ports 80/443 publicly invites immediate scanner attacks.
  * **The Fix**:
    1. Switched from Fail2Ban to **CrowdSec**.
    2. Configured Caddy to log JSON access logs to systemd journal by adding the `log` directive to your reusable `(base_security)` Caddy snippet (turning on logging globally across your domains in one edit).
    3. Verified that the `crowdsec-firewall-bouncer` is actively dropping packets from IPs attempting to scan your domains (4 scans were caught and banned instantly!).
* **The Problem (Securing the Repo)**: Creating `management.json` and `turnserver.conf` created plaintext files containing encryption keys and static auth secrets in the project root.
  * **The Fix**: Added the files and directories (`management.json`, `turnserver.conf`, `data/`) to `.gitignore`, encrypted the `.env` files with `sops`, and ran `secrets clean` to ensure no plaintext configuration leaks to GitHub.

---

## 7. NetBird Namespace Isolation & Peer Connectivity (Routing & Firewall Fixes)
* **The Problem (Relayed Packet Loss / Connection Timeout)**: The exit-node container and the Windows peer connected successfully via the HTTPS relay, but pings between their NetBird IPs timed out with 100% packet loss.
  * **The Cause 1 (Routing table)**: The `netbird` client shares `gluetun`'s network namespace. `gluetun`'s strict routing tables were routing all outbound traffic (including to the NetBird `100.91.0.0/16` subnet) through the commercial VPN interface (`tun0`) instead of routing it locally via `wt0`.
  * **The Cause 2 (Tailscale Firewall)**: Tailscale inserts dynamic rules in the legacy `ts-input` chain that drop all CGNAT IP traffic (`100.64.0.0/10`) not arriving on the `tailscale0` interface. Since NetBird shares the same IP range and interface type, its packets were dropped by Tailscale's legacy firewall.
  * **The Cause 3 (DNS Loop Deadlock)**: The Netbird client daemon dynamically hijacks `/etc/resolv.conf` to point queries to its own local resolver. Since the client starts up offline, it was unable to resolve `netbird.example.com`, causing a deadlock loop preventing it from ever getting online.
  * **The Fix**:
    1. **Routing Bypass**: Configured the `netbird` service command in `docker-compose.yml` to insert a high-priority policy routing rule `ip rule add to 100.91.0.0/16 lookup main priority 90` to keep local Netbird traffic on `wt0`.
    2. **Firewall Bypass**: Added a self-healing background script inside the `tailscale` container startup command that checks every 5 seconds and inserts `iptables-legacy -I ts-input 1 -i wt0 -j ACCEPT` to ensure NetBird traffic is accepted before Tailscale's drop rule runs.
    3. **DNS Deadlock Bypass**: Configured `"DisableDNS": true` in the container configuration so the NetBird client never hijacks `/etc/resolv.conf`, enabling it to boot and connect using public DNS servers.
    4. Bi-directional pings between the container and Windows client now run successfully with **0% packet loss**.

---

## 8. Direct P2P Connection & Restricted Wi-Fi Nat Traversal
* **The Problem (Relay Bandwidth Cap & P2P Failure)**: NetBird fell back to the WebSocket relay (`Relay server address: rel://...`), resulting in high latency and capped speeds (~12 Mbps) compared to managed NetBird on a standalone VPS (100+ Mbps). Direct ICE negotiation was failing.
  * **The Cause**: The exit-node client was configured to listen on WireGuard port `51830/udp`. Restrictive Wi-Fi networks (and some NAT routers) block arbitrary high UDP ports, preventing the Windows client from completing ICE connectivity checks directly to port 51830. 
  * **The Fix**: 
    1. Re-configured the NetBird container WireGuard listener to port `500/udp` (standard IKE/IPsec VPN port, which is universally allowed through restrictive Wi-Fi firewalls).
    2. Updated `Utilities/exit-node/docker-compose.yml` to forward `500:500/udp` via Gluetun.
    3. Configured `NATExternalIPs` to point to the VPS public IP (`${VPS_PUBLIC_IP}`).
    4. Opened `500/udp` in UFW (`sudo ufw allow 500/udp`) and removed unused legacy port `51830/udp` from UFW and Oracle Cloud Infrastructure (OCI) Security Lists.
    5. The client successfully promoted the connection from **Relayed** to **P2P** (`ICE candidate: srflx/srflx`), reaching full bandwidth.

---

## 9. AdGuard Home Integration & Windows DNS Leak Prevention
* **The Problem (DNS Leaking / AdGuard Unreachable)**: When routing traffic through the NetBird exit node, Windows client DNS queries leaked to the local Wi-Fi provider DNS resolvers, bypassing AdGuard filtering and exposing domain lookups.
  * **The Cause**: 
    1. The exit-node container network stack was isolated from the `network_default` Docker bridge network where the `network-gateway-adguard` container resides (`172.28.0.2`), making AdGuard unreachable.
    2. Windows Smart Multi-Homed Name Resolution (SMHNR) sent parallel DNS requests across all network adapters (Wi-Fi + NetBird), while IPv6 fallback leaked raw domain queries.
  * **The Fix**:
    1. **Docker Network Bridge**: Connected `utilities-exit-node-gluetun` to the `network_default` external network in `Utilities/exit-node/docker-compose.yml`, allowing NetBird to forward client DNS requests directly to AdGuard at `172.28.0.2`.
    2. **NetBird DNS Rule**: Configured global NetBird Nameserver pointing to `172.28.0.2` with search domain `.` (Match all domains).
    3. **Windows Leak Fix**: Disabled Smart Multi-Homed Name Resolution (`DisableSmartNameResolution = 1`) and IPv6 DNS fallbacks on Windows.
    4. Verified zero DNS leaks via `nslookup doubleclick.net` returning `0.0.0.0` and `::` (AdGuard blocked).

---

## 10. Bare-Metal & Multi-VPS P2P Optimization (Standardized WireGuard Ports & Stateful Hole Punching)
* **The Problem (Asymmetric P2P Promotion & Relayed Host Clients)**:
  * The Docker container `netbird-exit-node` connected via **P2P** immediately because Docker published `500:500/udp` in raw `iptables`.
  * The bare-metal host client on VPS A started as **Relayed**, only switching to **P2P** after a client connected to the Docker exit node (which punched a stateful NAT hole on the remote router for `VPS_A_IP`).
  * The bare-metal host client on VPS B remained **Relayed** continuously.
* **The Cause**:
  * Unconfigured NetBird daemons on bare-metal hosts default to random dynamic WireGuard ports.
  * Stateful hypervisor firewalls (OCI Security Lists) drop unsolicited inbound UDP packets unless an active outbound UDP session has punched a dynamic stateful return entry for that port/IP pair.
* **The Fix**:
  1. Standardized the WireGuard port to **`4500/udp`** (standard IPsec NAT-Traversal, universally allowed on restrictive Wi-Fi / enterprise networks) in `/var/lib/netbird/default.json` across bare-metal hosts:
     ```json
     "WgPort": 4500
     ```
  2. Restarted the NetBird daemon (`sudo systemctl restart netbird`).
  3. Outbound UDP probes sent from port `4500` dynamically punch stateful return entries in both UFW and OCI hypervisor firewalls.
  4. Both VPS A host and VPS B host immediately promoted from **Relayed** to **Direct (P2P)** across all client connections without needing to expose open ingress ports in OCI Dashboard or UFW.
