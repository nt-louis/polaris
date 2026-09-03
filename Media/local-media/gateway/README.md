# Core Media Gateway (Gluetun + Tailscale + Caddy)

This stack provides the core-media shared namespace and reverse proxy entrypoint for Media/local-media services.

## What it does

- Gluetun: VPN egress + kill-switch.
- Tailscale: tailnet ingress to the shared namespace.
- Caddy: routes incoming requests to services on localhost.

## Why localhost and not container names

When a service uses `network_mode: container:media-gateway-core-gluetun`, it joins the exact same network namespace as Gluetun/Caddy/Tailscale. Inside that namespace, all services are reached by `127.0.0.1:<internal-port>`.

Container names are used for Docker bridge networking, not shared namespaces.

## Setup

1. Add the variables from `.env.example` to the Doppler config
   `network_media_local_media_gateway` in the active VPS project.
2. From the repository root, verify and deploy with `./manage.py deploy`.
3. Start stacks that join this namespace (for example `Media/local-media`)
   through the same manager.

See [Docs/DOPPLER_OPERATIONS_GUIDE.md](../../../Docs/DOPPLER_OPERATIONS_GUIDE.md)
for project/config setup. Do not create a production `.env` or run direct
`docker compose up` commands.

## Routing notes

- Current routes are path-based (`/jellyfin`, `/prowlarr`, `/radarr`, `/sonarr`, `/qbittorrent`, `/sabnzbd`, `/seerr`, `/flaresolverr`, `/tracearr`, `/remux`) on the gateway Tailnet FQDN.
- The Caddyfile retains disabled or legacy route comments for Bazarr, Lidarr,
  Autobrr, Dispatcharr, and other services. A route comment is not an active
  deployment.
- Other categories now run in dedicated nested gateways:
   - `Media/comics/gateway`
   - `Media/stremio/utilities/gateway`
   - `Media/stremio/addons/gateway`
- Some apps need a base path set in app settings to work perfectly behind a subpath.
- If you prefer host-based routing later, switch to separate hostnames and update DNS accordingly.
