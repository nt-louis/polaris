# Stremio Utilities Gateway (Gluetun + Tailscale + Caddy)

This gateway isolates stremio utility services behind their own VPN namespace.

## Routed services

- `/jackett`
- `/mediaflow`
- `/syncio`

The Caddyfile retains `/dmm` as a legacy route, but no active compose project
currently provides that service. Open WebUI and the VPS B agents share this
gateway namespace but are reached by their configured ports rather than these
paths.

## Setup

1. Add the variables from `.env.example` to the Doppler config
   `network_media_stremio_utilities_gateway` in the active VPS project.
2. From the repository root, verify and deploy with `./manage.py deploy`.
3. Start utility stacks that join this namespace through the same manager.

See [Docs/DOPPLER_OPERATIONS_GUIDE.md](../../../../Docs/DOPPLER_OPERATIONS_GUIDE.md)
for project/config setup. Do not create a production `.env` or run direct
`docker compose up` commands.
