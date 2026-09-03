# Comics Gateway (Gluetun + Tailscale + Caddy)

This gateway isolates manga/comics services behind their own VPN namespace.

- `/grimmory` is the active configured route.
- `/kavita` remains in the Caddyfile as a legacy route; Kavita is archived and
  is not an active compose project.

## Setup

1. Add the variables from `.env.example` to the Doppler config
   `network_media_comics_gateway` in the active VPS project.
2. From the repository root, verify and deploy with `./manage.py deploy`.
3. Start comics stacks that join this namespace through the same manager.

See [Docs/DOPPLER_OPERATIONS_GUIDE.md](../../../Docs/DOPPLER_OPERATIONS_GUIDE.md)
for project/config setup. Do not create a production `.env` or run direct
`docker compose up` commands.
