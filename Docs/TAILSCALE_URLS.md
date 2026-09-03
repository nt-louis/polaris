# Net-Stream Tailscale URLs

This is the current configured Tailnet route matrix. Replace
`<tailnet>.ts.net` with the Tailnet suffix configured in Doppler. Path entries
come from active gateway Caddyfiles; direct-port entries are services
listening in a shared namespace without a Caddy path. A configured Caddy route
may still be legacy if its backing compose project is archived or disabled.

## Core Media

**Gateway:** `core.<tailnet>.ts.net`

- Jellyfin: `https://core.<tailnet>.ts.net/jellyfin/`
- Seerr: `https://core.<tailnet>.ts.net/seerr/`
- Radarr: `https://core.<tailnet>.ts.net/radarr/`
- Sonarr: `https://core.<tailnet>.ts.net/sonarr/`
- Prowlarr: `https://core.<tailnet>.ts.net/prowlarr/`
- qBittorrent: `https://core.<tailnet>.ts.net/qbittorrent/`
- SABnzbd: `https://core.<tailnet>.ts.net/sabnzbd/`
- FlareSolverr: `https://core.<tailnet>.ts.net/flaresolverr/`
- Tracearr: `https://core.<tailnet>.ts.net/tracearr/`
- Remux: `https://core.<tailnet>.ts.net/remux/`
- Nodecast TV: `http://core.<tailnet>.ts.net:3010`
- Monochrome: `http://core.<tailnet>.ts.net:4173`

## Comics

**Gateway:** `comics.<tailnet>.ts.net`

- Grimmory: `https://comics.<tailnet>.ts.net/grimmory/`
- Audiobookshelf: `http://comics.<tailnet>.ts.net:13378`
- Shelfmark: `http://comics.<tailnet>.ts.net:8084`
- Athenaeum: `http://comics.<tailnet>.ts.net:8741`
- Bindery: `http://comics.<tailnet>.ts.net:8787`
- Suwayomi: `http://comics.<tailnet>.ts.net:4567`

Legacy configured route: `/kavita/` (Kavita is archived).

## Stremio Addons

**Gateway:** `addons.<tailnet>.ts.net`

- AIOStreams: `https://addons.<tailnet>.ts.net/aiostreams/`
- Watchly: `https://addons.<tailnet>.ts.net/watchly/`
- StreamThru: `https://addons.<tailnet>.ts.net/stremthru/`
- StreamNZB: `https://addons.<tailnet>.ts.net/streamnzb/`
- NZBDav: `https://addons.<tailnet>.ts.net/nzbdav/`
- NZBHydra2: `https://addons.<tailnet>.ts.net/nzbhydra2/`
- Comet: `http://addons.<tailnet>.ts.net:8800`

## Proton Addons

**Gateway:** `proton.<tailnet>.ts.net`

- AIO Manager: `https://proton.<tailnet>.ts.net/aiomanager/`
- AIO Metadata: `https://proton.<tailnet>.ts.net/aiometadata/`
- StreamPicker: `http://proton.<tailnet>.ts.net:8000`

## Stremio Utilities

**Gateway:** `stremio-util.<tailnet>.ts.net`

- Jackett: `https://stremio-util.<tailnet>.ts.net/jackett/`
- MediaFlow Proxy: `https://stremio-util.<tailnet>.ts.net/mediaflow/`
- Syncio: `https://stremio-util.<tailnet>.ts.net/syncio/`
- Scrob: `https://stremio-util.<tailnet>.ts.net/scrob/`
- Open WebUI: `http://stremio-util.<tailnet>.ts.net:8080`

Legacy configured route: none. The current gateway Caddyfile does not provide
Comet or Jackettio paths here.

## Utilities

**Gateway:** `util.<tailnet>.ts.net`

- Apprise: `https://util.<tailnet>.ts.net/apprise/`
- FMHY: `https://util.<tailnet>.ts.net/fmhy/`
- Uptime Kuma: `https://util.<tailnet>.ts.net/uptime-kuma/`
- Dozzle: `https://util.<tailnet>.ts.net/dozzle/`
- IT-Tools: `https://util.<tailnet>.ts.net/it-tools/`
- Memos: `https://util.<tailnet>.ts.net/memos/`
- Beszel: `https://util.<tailnet>.ts.net/beszel`

Additional configured utility routes:

- Homarr: `https://util.<tailnet>.ts.net/homepage/`
- Portainer: `https://util.<tailnet>.ts.net/portainer/` (verify the backing
  service is active before use)
- n8n: dedicated domain configured by `N8N_DOMAIN`, not `/n8n`.

## Cloud Gateway

**Gateway:** `cloud.<tailnet>.ts.net`

- Nextcloud: `https://cloud.<tailnet>.ts.net/`
- CalDAV/CardDAV discovery: `https://cloud.<tailnet>.ts.net/.well-known/caldav`
  and `https://cloud.<tailnet>.ts.net/.well-known/carddav`

## VPS B Bridge Gateway

**Gateway:** `util-b.<tailnet>.ts.net`

The bridge gateway uses host-based routing on the configured domain suffix:

- Penpot: `https://penpot.<domain-suffix>`
- Excalidraw: `https://excalidraw.<domain-suffix>`
- Supabase Studio: `https://supabase.<domain-suffix>`
- Supabase API: `https://supabase-api.<domain-suffix>`
- Infisical: `https://infisical.<domain-suffix>`

The Caddyfile still contains a Coolify route, but Coolify is archived and is
not an active compose project.

## Global Network

**Gateway:** `dns-gateway.<tailnet>.ts.net`

- AdGuard Dashboard: `https://dns-gateway.<tailnet>.ts.net/adguard/`
- DNS-over-HTTPS: `https://dns-gateway.<tailnet>.ts.net/dns-query`
