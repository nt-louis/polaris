# Stremio Addons Gateway (Gluetun + Tailscale + Caddy)

This gateway isolates stremio addon services behind their own VPN namespace.

## Routed services

- /watchly
- /stremthru
- /aiostreams
- /nzbdav
- /jackettio
- /nzbhydra2
- /streamnzb

AI Manager and AI Metadata use the separate `proton` gateway, not this
namespace. Comet is reached on its direct gateway port and is not a Caddy path
in the active file.

## Setup

1. Add the variables from `.env.example` to the Doppler config
   `network_media_stremio_addons_gateway` in the active VPS project.
2. From the repository root, verify and deploy with `./manage.py deploy`.
3. Start addon stacks that join this namespace through the same manager.

See [Docs/DOPPLER_OPERATIONS_GUIDE.md](../../../../Docs/DOPPLER_OPERATIONS_GUIDE.md)
for project/config setup. Do not create a production `.env` or run direct
`docker compose up` commands.
