# Self-Hosting NetBird Control Plane with PocketID & Caddy

> [!NOTE]
> **Status Notice**: Tailscale is the active mesh network for the Net-Stream stack. This guide documents historical research and self-hosting procedures for running an independent NetBird control plane.

> [!WARNING]
> The NetBird stack is an optional, host-specific control plane and is not
> required for the active Tailscale deployment. Confirm the compose project and
> external routing prerequisites before using this runbook.

This guide walks you through deploying a fully self-hosted NetBird Control Plane (Dashboard, Management, Signal, Relay, and Coturn) on your VPS host. It integrates directly with your **PocketID** OIDC authentication server and **Host Caddy** reverse proxy.

---

## Architecture Overview

The self-hosted NetBird control plane services run locally in a Docker network. Public traffic (HTTPS/gRPC) is routed through your **Host Caddy** on the VPS host using HTTP/2 Cleartext (h2c) for gRPC connections:

```
                          Internet (Clients & Browser)
                                       |
                                       v
                                   Host Caddy
                                       |
        +------------------------------+------------------------------+
        | (HTTPS / HTTP)               | (gRPC over h2c)              | (gRPC over h2c)
        v                              v                              v
    Dashboard                      Management                       Signal
(Port 30080)                      (Port 33073)                   (Port 10000)
```

---

## Deployment Steps

### Step 1: Create an OIDC Client in PocketID
Before deploying, you must register NetBird as an OpenID Connect (OIDC) client in your **PocketID** administration panel:

1. Log in to your PocketID admin dashboard (usually `https://auth.example.com`).
2. Create a new **Client** with the following details:
   - **Client ID**: `netbird`
   - **Client Name**: `NetBird Mesh VPN`
   - **Client Secret**: *(Generate a secure client secret)*
   - **Redirect URIs**:
     - `https://netbird.example.com/`
     - `https://netbird.example.com/silent-start`
   - **Allowed Scopes**: `openid`, `profile`, `email`
   - **Token Signing Algorithm**: `RS256`

---

### Step 2: Configure Environment Variables
We need to define the domain names, secrets, and OIDC credentials in Doppler
SaaS under project `net-stream-vps-a`, config `network_netbird_server`,
environment `network`. `Utilities/netbird-server` is assigned to VPS A by the
repository discovery rules.

Configure the active values in that Doppler config. Enter secret values in the
Doppler dashboard or with an interactive `doppler secrets set` prompt; do not
commit this example or create a production `.env`:
```ini
NETBIRD_DOMAIN=netbird.example.com             # Your NetBird public domain
NETBIRD_RELAY_SECRET=your-relay-random-secret  # Random string for TURN auth

OIDC_ISSUER=https://auth.example.com           # Your PocketID URL
OIDC_DOMAIN=auth.example.com                   # PocketID domain name
OIDC_CLIENT_ID=netbird                         # PocketID Client ID
OIDC_CLIENT_SECRET=your-pocketid-client-secret

NB_PROXY_TOKEN=your-proxy-cluster-token        # Setup Token for NetBird App Proxy
```

Run verification audit when finished:
```bash
./manage.py secrets verify
```

---

### Step 3: Deploy the Server Stack
Boot the NetBird control plane stack using the Stack Manager:
```bash
./manage.py deploy
```
*(Select the `netbird-server` service group in the TUI checklist).*

The deployment script will automatically execute the hook at [orchestrator/scripts/utils/update-netbird-server.sh](orchestrator/scripts/utils/update-netbird-server.sh), generating the configuration files (`management.json` and `turnserver.conf`) from your env variables before starting the containers.

---

### Step 4: Configure Host Caddy
The Caddy routing configuration has been generated and appended to [public-caddyfile-snippet.txt](public-caddyfile-snippet.txt).

1. Copy the `http://netbird.example.com` site block and the global `servers` block options from [public-caddyfile-snippet.txt](public-caddyfile-snippet.txt) into your active VPS Caddyfile (usually at `/etc/caddy/Caddyfile`).
2. Replace `netbird.example.com` and `auth.example.com` with your actual domain names.
3. Reload Caddy to apply the changes:
   ```bash
   sudo systemctl reload caddy
   ```

---

### Step 5: Connect Client Peers
To connect client peers (like your exit node or your local laptop) to your self-hosted NetBird Control Plane:

#### For containerized clients (like the `utilities-exit-node-netbird` container):
1. Add `NB_MANAGEMENT_URL` in the VPS A Doppler project under config
   `network_utilities_exit_node`:
   ```ini
   NB_MANAGEMENT_URL=https://netbird.example.com
   ```
2. Start the client container:
   ```bash
   ./manage.py deploy --force-gateways
   ```
3. Check the logs to retrieve the login code:
   ```bash
   docker logs utilities-exit-node-netbird
   ```
   Open the printed registration link, which will redirect you to your **PocketID** login portal. Once authorized, the device will connect to your self-hosted NetBird mesh!

#### For local desktop or mobile clients:
Simply use the NetBird client CLI or app and specify your self-hosted management URL:
```bash
netbird up --management-url https://netbird.example.com
```
When prompted, log in via PocketID.
