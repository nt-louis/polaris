# Cloudflare Tunnel Setup Guide

This guide outlines how to deploy a **Cloudflare Tunnel (`cloudflared`)** to securely proxy your public domains (e.g., `*.example.com`) to your VPS host Caddy. This allows you to **completely close all inbound ports (80/443)** on your VPS firewall, making your server's IP address 100% invisible to port scanners and the public internet.

---

## 1. Cloudflare Dashboard Setup

Before running the tunnel container on your VPS, you need to create the tunnel in the Cloudflare Zero Trust Dashboard:

1. Log in to the [Cloudflare Dashboard](https://dash.cloudflare.com/).
2. In the left sidebar, click **Zero Trust**.
3. In the Zero Trust sidebar, go to **Networks -> Tunnels**.
4. Click **Create a tunnel**.
5. Select **cloudflared** and click Next.
6. Name your tunnel (e.g., `polaris-vps`) and click Save tunnel.
7. Under **Install and run a connector**, select **Docker**.
8. Copy the **Token** from the provided command (the long base64 string after `--token`). You will need this in the next step.

---

## 2. VPS Deployment

Now, add the tunnel token to Doppler and deploy the client on your VPS. This
stack maps to the `network_cloudflare_tunnel` config in the active VPS project.

1. From the repository root, verify Doppler access:
    ```bash
    cd ~/polaris
    ./manage.py secrets verify
    ```
2. Set `TUNNEL_TOKEN` in `network_cloudflare_tunnel` under the project for the
   VPS receiving the tunnel:
    ```bash
    doppler secrets set --project polaris-vps-a \
      --config network_cloudflare_tunnel \
      TUNNEL_TOKEN
    ```
    Paste the token when Doppler prompts for the value; do not put it in the
    command line or shell history.
3. Refresh the offline SOPS fallback snapshot:
    ```bash
    ./manage.py secrets snapshot-config network_cloudflare_tunnel --vps A
    ```
4. Deploy through the manager:
    ```bash
    ./manage.py deploy --vps A
    ```
5. Verify the tunnel started and connected successfully:
    ```bash
    docker logs cloudflare-tunnel
    ```
    *You should see output indicating it successfully registered and connected to multiple Cloudflare edge points.*

Do not create a production `.env` or run direct `docker compose up`; the
manager injects the token with Doppler and cleans any transient environment
file required by the compose definition.

---

## 3. Configure Public Hostname Routing

Now that the tunnel is running on your VPS, tell Cloudflare how to route your domain traffic:

1. Go back to your Cloudflare Zero Trust Tunnels page.
2. Click **Edit** on your running tunnel.
3. Go to the **Public Hostnames** tab.
4. Click **Add a public hostname**.
5. Configure your domain (e.g., `adguard.example.com`):
   * **Subdomain:** `adguard`
   * **Domain:** `example.com`
   * **Type:** `HTTP`
   * **URL:** `localhost:80` (or `127.0.0.1:80`)
6. Click **Save hostname**.
7. Repeat this for all other subdomains you wish to route through the tunnel (e.g. `home`, `portainer`, `uptime-kuma`).

*Note: You can also use a wildcard `*.example.com` if your Cloudflare plan/DNS settings support it, routing all subdomains to `localhost:80` in a single rule.*

---

## 4. Host Caddy SSL/TLS Simplification

Because you will be closing ports `80` and `443` on your VPS public firewall, Let's Encrypt's standard HTTP-01 challenge will no longer be able to connect to your host Caddy to verify domain ownership.

However, since the Cloudflare Tunnel itself is an **outbound-only, fully encrypted TLS tunnel** between Cloudflare and your VPS, encrypting the traffic again on `localhost` is redundant. 

### How to configure Caddy:
Update your VPS **host Caddyfile** to serve domains over plain HTTP. This bypasses Let's Encrypt completely while Cloudflare handles public HTTPS termination at the edge (so your users still see `https://`):

```caddy
http://adguard.example.com {
    import base_security
    reverse_proxy dns-gateway.<tailnet-domain>.ts.net:80 {
        import proxy_settings
    }
}

http://home.example.com {
    import base_security
    import protected core.<tailnet-domain>.ts.net:3000
}

http://portainer.example.com {
    import base_security
    import protected util.<tailnet-domain>.ts.net:9000
}
```

Make sure **SSL/TLS encryption mode** in Cloudflare is set to **Flexible** or **Full (not Strict)** if your host Caddy uses `http://` for local routing.

---

## 5. Close Your Public Ports!

The final and most satisfying step:

1. Go to your VPS cloud provider's firewall console (e.g., Oracle Cloud Security Lists, AWS Security Groups, DigitalOcean Firewalls).
2. **Remove the rules allowing inbound port 80 and port 443.**
3. Save the rules.

Your VPS is now a complete black hole to anyone trying to scan or ping it directly from the internet. All web traffic flows entirely and invisibly through the Cloudflare Tunnel outbound socket!
