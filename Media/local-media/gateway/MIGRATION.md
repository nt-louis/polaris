# Gateway Migration Playbook

Use this to move compose projects behind categorized Media gateways.

## Core rule

For services that should route through VPN + Tailscale + Caddy:

- Add `network_mode: "container:<gateway-gluetun-container-name>"`
- Remove `ports:` from that service
- Add a Caddy route to `127.0.0.1:<internal-port>`

## Collision handling

If two services listen on the same internal port, they cannot run at the same time in one shared namespace without changing one app's internal listen port.

Resolved collisions in this repository:

- `3000`: moved `usenetstack/aiostreams` to `3004` via `PORT=3004`
- `8000`: moved `watchly` to `8010` via `PORT=8010`
- `8000`: moved `comet` to `8800` via `FASTAPI_PORT=8800`
- `7000`: moved `usenetstreamer` to `7002` via `PORT=7002`

## Gateway categories

1. Core media gateway: `Media/gateway` for `Media/local-media`
2. Comics gateway: `Media/gateway-comics` for `Media/comics/*`
3. Stremio utilities gateway: `Media/gateway-stremio-utilities` for `Media/stremio/utilities/*`
4. Stremio addons gateway: `Media/gateway-stremio-addons` for `Media/stremio/addons/*`

## Current internal port map

- `jellyfin`: `8096`
- `kavita`: `5000`
- `aiomanager`: `1610`
- `aiometadata`: `3232`
- `watchly`: `8010`
- `streamnzb`: `7000`
- `stremthru`: `8080`
- `aiostreams`: `3004`
- `nzbdav`: `3000`
- `usenetstreamer`: `7002`
- `comet`: `8800`
- `jackett`: `9117`
- `jackettio`: `4000`
- `mediaflow-proxy`: `8888`

## Per-stack checklist

1. Confirm internal app port.
2. Confirm no conflict with currently joined services.
3. Add `network_mode`.
4. Remove host port mapping.
5. Add Caddy path route.
6. Restart the corresponding gateway and target stack.
7. Verify from tailnet via `http://TAILNET_FQDN/<service>/`.

## Notes about container names

In shared namespace mode, use `127.0.0.1:<port>` for Caddy upstreams.

Container names are only useful when Caddy and services communicate over a Docker bridge network.
