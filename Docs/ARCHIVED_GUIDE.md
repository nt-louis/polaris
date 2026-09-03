> [!WARNING]
> **DEPRECATED: This guide is archived for historical reference.**
> 
> The network architecture described here has been significantly evolved into a nested Gateway pattern. Please see [NETWORK_ARCHITECTURE.md](NETWORK_ARCHITECTURE.md) for the current, accurate documentation.

# The "Holy Grail" VPS Setup: Split-Horizon Networking

**Environment**: Ubuntu VPS (Oracle Cloud)
**Network model**: Split-horizon

- **Host and SSH**: Oracle network (direct, stable)
- **Tailscale clients**: VPN network (privacy exit node)
- **Docker containers**: VPN network (privacy for apps)

## 1. Prerequisites

### Oracle Cloud firewall

Ensure your Oracle VCN Security List allows:

- TCP 22: SSH (inbound)
- UDP 51820: WireGuard (inbound)
- UDP 41641: Tailscale (inbound, recommended for direct mesh)

### Install packages

```bash
sudo apt update && sudo apt install -y wireguard tailscale iproute2 iptables
```

## 2. Kernel configuration (persistent)

Enable IP forwarding and disable strict reverse path filtering (drops asymmetric VPN traffic).

Create the config file:

```bash
sudo tee /etc/sysctl.d/99-hybrid-routing.conf >/dev/null <<'EOF'
# Enable IP Forwarding
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 0

# Loose Reverse Path Filtering (Required for complex routing)
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.default.rp_filter = 2
net.ipv4.conf.enp0s6.rp_filter = 2
net.ipv4.conf.tailscale0.rp_filter = 2
net.ipv4.conf.docker0.rp_filter = 2
EOF
```

Apply immediately:

```bash
sudo sysctl --system
```

## 3. WireGuard configuration (the plumbing)

We will configure WireGuard to:

- Create the tunnel (wg0)
- Create the VPN routing table (51820)
- Handle NAT (masquerading) for both Tailscale and Docker traffic

Edit: `sudo nano /etc/wireguard/wg0.conf`

```ini
[Interface]
PrivateKey = <YOUR_PRIVATE_KEY>
Address = <YOUR_VPN_CLIENT_IP>/32
DNS = 1.1.1.1

# Prevent WireGuard from messing with the host routing table
Table = off

# --- PostUp: Create table and NAT ---
# 1. Create the VPN routing table (51820)
PostUp = ip route add default dev wg0 table 51820

# 2. NAT for Tailscale clients (100.64.0.0/10) -> VPN
PostUp = iptables -t nat -A POSTROUTING -s 100.64.0.0/10 -o wg0 -j MASQUERADE

# 3. NAT for Docker containers (172.16.0.0/12) -> VPN
PostUp = iptables -t nat -A POSTROUTING -s 172.16.0.0/12 -o wg0 -j MASQUERADE

# 4. MSS clamping (fixes HTTPS timeouts/stalls)
PostUp = iptables -t mangle -A FORWARD -o wg0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

# --- PreDown: Cleanup ---
PreDown = ip route del default dev wg0 table 51820
PreDown = iptables -t nat -D POSTROUTING -s 100.64.0.0/10 -o wg0 -j MASQUERADE
PreDown = iptables -t nat -D POSTROUTING -s 172.16.0.0/12 -o wg0 -j MASQUERADE
PreDown = iptables -t mangle -D FORWARD -o wg0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

[Peer]
PublicKey = <VPN_PROVIDER_PUBLIC_KEY>
Endpoint = <VPN_ENDPOINT_IP>:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

Enable WireGuard:

```bash
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0
```

## 4. Policy routing service (the brain)

This service decides who uses the VPN. It applies policy rules that route specific source IPs (Docker/Tailscale) to the VPN table while leaving the host untouched.

Create: `sudo nano /etc/systemd/system/hybrid-routing.service`

```ini
[Unit]
Description=Hybrid Routing: Direct Host, VPN Docker/Tailscale
After=network-online.target tailscaled.service wg-quick@wg0.service
Wants=tailscaled.service wg-quick@wg0.service

[Service]
Type=oneshot
RemainAfterExit=yes

# --- 1. Tailscale ingress (allow mesh to reach Docker) ---
# Incoming from Tailscale -> Destination Docker -> Use main table (local routing)
ExecStart=/sbin/ip rule add priority 95 iif tailscale0 to 172.16.0.0/12 lookup main

# 1.5 Local Bypass (Crucial for Reverse Proxy)
ExecStart=/sbin/ip rule add priority 96 from 172.16.0.0/12 to 172.16.0.0/12 lookup main
ExecStart=/sbin/ip rule add priority 96 from 172.16.0.0/12 to 127.0.0.1 lookup main

# --- 2. Docker replies (reply to mesh) ---
# From Docker -> Destination Tailscale -> Use Tailscale table (52)
ExecStart=/sbin/ip rule add priority 97 from 172.16.0.0/12 to 100.64.0.0/10 lookup 52

# --- 3. Tailscale general (exit node traffic) ---
# From Tailscale -> Internet -> Use VPN table (51820)
ExecStart=/sbin/ip rule add priority 98 iif tailscale0 lookup 51820

# --- 4. Docker egress (privacy for containers) ---
# From Docker subnets -> Internet -> Use VPN table (51820)
# Note: 172.16.0.0/12 covers 172.16.x.x through 172.31.x.x (standard Docker range)
ExecStart=/sbin/ip rule add priority 99 from 172.16.0.0/12 lookup 51820

# --- 5. Kill-switch (safety net) ---
# If VPN is down (table 51820 empty), these block traffic from leaking via Oracle
ExecStart=/sbin/ip rule add priority 101 from 172.16.0.0/12 unreachable
ExecStart=/sbin/ip rule add priority 102 iif tailscale0 unreachable

# --- Cleanup (reverse order) ---
ExecStop=/sbin/ip rule del priority 102 iif tailscale0 unreachable
ExecStop=/sbin/ip rule del priority 101 from 172.16.0.0/12 unreachable
ExecStop=/sbin/ip rule del priority 99 from 172.16.0.0/12 lookup 51820
ExecStop=/sbin/ip rule del priority 98 iif tailscale0 lookup 51820
ExecStop=/sbin/ip rule del priority 97 from 172.16.0.0/12 to 100.64.0.0/10 lookup 52
ExecStop=/sbin/ip rule del priority 96 from 172.16.0.0/12 to 172.16.0.0/12 lookup main
ExecStop=/sbin/ip rule del priority 96 from 172.16.0.0/12 to 127.0.0.1 lookup main
ExecStop=/sbin/ip rule del priority 95 iif tailscale0 to 172.16.0.0/12 lookup main

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hybrid-routing.service
```

## 5. Tailscale exit node setup

Configure Tailscale to act as an exit node (so your phone/laptop can use the VPS as a VPN).

```bash
sudo tailscale up --advertise-exit-node --accept-dns=true
```

Note: No extra NAT flags needed here; we handled NAT in step 3.

## 6. Docker DNS configuration

Since Docker containers route via VPN, they should not use the local Oracle DNS (which might be unreachable or leak info). Force them to use public DNS.

Edit: `sudo nano /etc/docker/daemon.json`

```json
{
  "dns": ["1.1.1.1", "8.8.8.8"]
}
```

Restart Docker:

```bash
sudo systemctl restart docker
```

## 7. Verification steps

Perform these tests to confirm the setup.

### Test A: SSH safety (host check)

From your terminal, check the host public IP:

```bash
curl https://ipinfo.io/ip
```

Result: Oracle Cloud IP.
Meaning: SSH is direct and safe. You will not get locked out if VPN fails.

### Test B: Docker privacy (container check)

Run a temporary container to check Docker's public IP:

```bash
docker run --rm curlimages/curl curl https://ipinfo.io/ip
```

Result: VPN provider IP.
Meaning: All your apps are private.

### Test C: Tailscale exit node (client check)

Connect your phone/laptop to Tailscale, enable Exit Node (select your VPS), then visit ipinfo.io.

Result: VPN provider IP.
Meaning: Your personal devices are securely routed through the VPS VPN.

### Test D: Kill-switch

Stop WireGuard and try to ping from Docker:

```bash
sudo systemctl stop wg-quick@wg0
docker run --rm alpine ping -c 2 8.8.8.8
```

Result: Network is unreachable or 100% packet loss.
Meaning: No leaks. Safety confirmed.

## 8. Summary of network flow

| Traffic Source | Destination | Routing Table | Exit Interface | IP Seen by World |
| --- | --- | --- | --- | --- |
| SSH / Host system | Internet | main | enp0s6 | Oracle IP |
| Docker containers | Internet | 51820 (via rule 99) | wg0 | VPN IP |
| Tailscale clients | Internet | 51820 (via rule 98) | wg0 | VPN IP |
| Tailscale clients | Docker apps | main (via rule 95) | docker0 | Internal |
| Docker apps | Tailscale clients | 52 (via rule 97) | tailscale0 | Internal |
