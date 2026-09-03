# NetBird vs Tailscale: Comparison & Integration Guide

> [!NOTE]
> **Status Notice**: Tailscale remains the primary active mesh network for the Net-Stream stack. This document preserves the architectural comparison and side-by-side evaluation conducted with NetBird.

This guide compares **NetBird** and **Tailscale** in the context of the Net-Stream stack and provides instructions for running them side-by-side in the `exit-node` gateway stack for testing.

---

## High-Level Comparison

| Feature | Tailscale | NetBird |
|---|---|---|
| **Control Plane** | Closed-Source SaaS (SaaS default, Headscale is unofficial/community) | **Fully Open-Source** (First-class self-hosting with Management & Signal servers) |
| **Data Plane** | WireGuard (User-space `wireguard-go` by default in containers) | WireGuard (**Kernel-space preferred**; falls back to user-space) |
| **NAT Traversal** | DERP Relays + STUN | **WebRTC (Signal/ICE)** + STUN/TURN (CoTURN) |
| **Authentication / SSO** | Proprietary SaaS authentication hooks | **First-class OIDC** (Keycloak, Authentik, Zitadel, PocketID) |
| **Access Control** | Declarative HuJSON ACL file | Interactive **Access Groups & Policies** in Web UI |
| **Routing / Subnets** | Subnet Routers & Exit Nodes | **Routing Peers** with optional Masquerading (NAT) |
| **Throughput / Latency** | Excellent (~260 Mbps bare-metal) | **Superior inside containers** due to direct kernel WireGuard usage |

---

## Parallel Exit Node Architecture

We have integrated NetBird directly into the existing `Utilities/exit-node` stack. Both clients now run **side-by-side** inside the same **Gluetun VPN network namespace**:

```
                  +----------------------------------------------+
                  |            exit-node (Compose Stack)         |
                  |                                              |
                  |                +------------+                |
                  |                |  Gluetun   |                |
                  |                | (VPN Client|                |
                  |                +-----+------+                |
                  |                      | (Shared Network Namespace)
                  |       +--------------+--------------+        |
                  |       |                             |        |
                  | +-----+------+                +-----+------+ |
                  | | Tailscale  |                |  NetBird   | |
                  | | (exit-node)|                | (netbird)  | |
                  | +------------+                +------------+ |
                  +-------+-----------------------------+--------+
                          |                                     |
                (tailscale0 interface)                  (wt0 interface)
                          |                                     |
                          v                                     v
                  Tailnet Mesh IP                    NetBird Mesh IP
```

### Key Benefits of this Side-by-Side Configuration
1. **Zero Interference**: Both clients manage their own virtual interfaces (`tailscale0` and `wt0`) and routing tables.
2. **Identical Egress Paths**: Any traffic initiated by either client or routed through them to the internet will exit through Gluetun's VPN connection, guaranteeing a consistent public IP.
3. **No Service Disruption**: The existing Tailscale network and exit node routing remain 100% active and untouched.

---

## Activation & Setup Instructions

### 1. Configure NetBird Credentials (Optional)
If you have a NetBird setup key, add it to your active environment variables. 

Add or update environment variables directly in the VPS A Doppler project,
config `network_utilities_exit_node` (environment `network`):
```ini
# NetBird Configurations (Optional)
NB_SETUP_KEY=your-setup-key-here
NB_HOSTNAME=exit-node-netbird
```
Run verification audit when finished:
```bash
./manage.py secrets verify
```

> [!NOTE]
> If you do not have a setup key, you can leave it empty. The NetBird daemon will generate an interactive browser login link in the container logs.

### 2. Deploy/Rebuild the Stack
To boot the updated stack and pull the NetBird client image:
```bash
./manage.py deploy --force-gateways
```
*(Select the Exit Node group to spin up the updated containers).*

### 3. Authenticate the Node (If no Setup Key was used)
Check the container logs to find the registration URL:
```bash
docker logs utilities-exit-node-netbird
```
Look for an output similar to:
```
To sign in, please open: https://login.netbird.io/activate?user_code=ABCD-EFGH
```
Copy and open the URL in your browser, log in, and authorize the device to join your NetBird network.

---

## Benchmarking & Comparison Tests

Now that both mesh networks are running on the same VPS, you can run tests to compare them.

### 1. Network Path & Peer-to-Peer Check
Run `tailscale status` and `netbird status` on your client machine to verify if they establish a direct Peer-to-Peer (P2P) connection to the VPS or fallback to relays (DERP/TURN):
```bash
# On your local client machine
tailscale status
netbird status
```

### 2. Latency Benchmarks
Ping the VPS host over both interfaces from your local machine:
```bash
# Ping over Tailscale
ping exit-node.your-tailnet.ts.net

# Ping over NetBird
ping exit-node-netbird.netbird.cloud  # Or use NetBird IP
```

### 3. Throughput Benchmarks (iperf3)
You can run an `iperf3` server inside the gateway namespace to test network bandwidth:

1. Start `iperf3` server on the exit-node container:
   ```bash
   docker exec -it utilities-exit-node-tailscale iperf3 -s -p 5201
   ```
2. Run throughput tests from your local machine:
   ```bash
   # Benchmark over Tailscale
   iperf3 -c <TAILSCALE_IP_OF_EXIT_NODE> -p 5201

   # Benchmark over NetBird
   iperf3 -c <NETBIRD_IP_OF_EXIT_NODE> -p 5201
   ```
Observe differences in CPU utilization and throughput. NetBird's kernel-space acceleration typically yields higher speeds and lower CPU usage in containerized gateways.

---

## Configuring NetBird as an Exit Node

To route your client traffic through this NetBird exit node:
1. Go to your **NetBird Web Console**.
2. Navigate to **Network Routes**.
3. Click **Add Route**.
4. Configure the route:
   - **Network Range**: `0.0.0.0/0` (Matches all traffic for exit node behavior).
   - **Routing Peer**: Select `exit-node-netbird`.
   - **Masquerade (NAT)**: **Enabled** (Required to forward internet traffic).
5. In your local client client NetBird settings, enable **Route Traffic through Peer** and select this route.
