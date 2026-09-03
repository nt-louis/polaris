# Polaris VPS A & B Service Intricacies & Upgrades Guide

This document serves as the master reference guide for managing, maintaining, and upgrading containerized services deployed across **VPS A** and **VPS B**. Both servers pull from the same repository branch but run different workloads based on their hardware, network context, and resource footprints.

> [!IMPORTANT]
> Compose files and Renovate are the source of truth for image tags. The
> versions below are a maintenance snapshot and must be checked against the
> adjacent `docker-compose.yml` before an upgrade. Archived services are not
> covered by this active guide.

---

## Golden Rules of Upgrades

1. **Never Automated-Upgrade Major DB Releases**:
   PostgreSQL (`n8n`, `linkwarden`, `yamtrack`, `penpot`, `infisical`, `supabase`) and MariaDB (`nextcloud`, `grimmory`) **cannot** be upgraded across major version tags (e.g. `16` -> `18`) without manual database migrations. Doing so will crash-loop the container and prevent service recovery.
2. **Respect Compose Label Constraints**:
   Services like `nextcloud-db` are explicitly locked to specific version series using labels:
   ```yaml
   labels:
     - "wud.tag.include=^10\\.11(\\.\\d+)*$"
   ```
   Always check compose labels before changing database tags.
3. **Verify Renovate Exclusions (`renovate.json`)**:
   Some upstream project tags (such as `lostb1t/remux:1.0.0`) are legacy or broken. The repository uses `renovate.json` version constraint filters (like `allowedVersions: <1.0.0` for remux) to protect these files from accidental upgrades.
4. **Coordinated Service Group Updates**:
   Critical infrastructure services (Gateways, OIDC auth layers, database backends) must be updated in isolated batches rather than a global "upgrade all" to prevent routing or authentication disconnects.

---

## VPS A: Core Stack & Media Services

VPS A hosts local media players, media managers, indexers, download clients, and document/collaboration clouds.

### 1. Cloud & Document Collaboration
#### **Nextcloud** (`Utilities/cloud-docs/nextcloud`)
* **Core Image**: `nextcloud:34.0.2`
* **Database**: `mariadb:10.11` (Locked to `10.11` LTS release via `wud.tag.include` regex).
* **Caching**: `redis:8-alpine`
* **Storage Mount**: `rclone/rclone:1.75.0` (Mounts decrypted crypt remote to `/data`).
* **Intricacies**:
  - Apache is rebound to port `8080` internally inside the container to hand off to the root Caddy proxy.
  - Nextcloud major upgrades (e.g. `33` -> `34`) must be done sequentially; never skip major releases. Back up the database before major version upgrades.

#### **Paperless-ngx** (`Utilities/cloud-docs/paperless-ngx`)
* **Core Image**: `ghcr.io/paperless-ngx/paperless-ngx:3.0.5`
* **Database**: SQLite (built-in file-based, low maintenance).
* **Caching**: `redis:8-alpine` (runs on custom internal port `6380` to prevent collision with Homarr's embedded Redis in the shared utilities gateway).
* **Intricacies**:
  - Redis listens on internal port `6380`; `PAPERLESS_REDIS` is configured as `redis://127.0.0.1:6380`.
  - Compose currently expects `HTTP_X_AUTHENTIK_USERNAME`, while the public Caddy OAuth2-Proxy snippet copies `X-Auth-Request-Preferred-Username` to `X-WebAuth-User`. Treat Paperless SSO as an unresolved integration that must be reconciled before relying on header authentication.

---

### 2. Authentication & Admin Panel
#### **Vaultwarden** (`Utilities/auth/vaultwarden`)
* **Core Image**: `vaultwarden/server:latest` (or pinned version).
* **Database**: SQLite. Keep backed up regularly.
* **Intricacies**: Lightweight Bitwarden implementation. Updates are backward-compatible.

#### **PocketID** (`Utilities/auth/pocketid`)
* **Core Image**: `ghcr.io/pocket-id/pocket-id:v2.13.0`
* **Intricacies**: Serves as the identity broker (OIDC) for modern login configurations.

#### **OAuth2-Proxy** (`Utilities/auth/oauth2-proxy`)
* **Core Image**: `oauth2-proxy:v7.15.3`
* **Intricacies**: Handles forward auth redirects for legacy apps.

---

### 3. Workflow Automation & Search
#### **n8n** (`Utilities/tools/n8n`)
* **Core Image**: `n8nio/n8n:2.31.2`
* **Database**: `postgres:16-alpine`
* **Intricacies**:
  - Uses PostgreSQL on a custom port (`5433`).
  - Major PostgreSQL upgrades will crash the database container. Do not upgrade Postgres beyond version `16` without performing `pg_dumpall`.

#### **Linkwarden** (`Utilities/bookmarks-notes/linkwarden`)
* **Core Image**: `linkwarden:v2.15.1`
* **Database**: `postgres:16-alpine`
* **Intricacies**: Uses PostgreSQL for storage. Upgrades are database-sensitive.

---

### 4. Local Media Stack (Downloads & Indexers)
#### **Jellyfin / Monochrome** (`Media/local-media/players/`)
* **Jellyfin Image**: `jellyfin/jellyfin`
* **Monochrome Image**: `local/monochrome` (Locally built. Excluded from upstream tag checking).
* **Intricacies**: Requires hardware acceleration (e.g. `/dev/dri`) mapping when running on hardware that supports transcoding.

#### **Sonarr, Radarr, Lidarr, Bazarr, Prowlarr** (`Media/local-media/managers/`)
* **Images**: `linuxserver` wrappers (e.g., `prowlarr:2.4.0.5397-ls153`).
* **Database**: SQLite database files (located in their config folders).
* **Intricacies**: Ensure that standard media path permissions (UID/GID 1000) are uniform across all managers and download clients.

#### **Yamtrack** (`Media/local-media/tools/yamtrack`)
* **Core Image**: `yamtrack:0.25.3`
* **Database**: `postgres:16-alpine`
* **Caching**: `redis:8-alpine`
* **Intricacies**: Requires PostgreSQL. Avoid major Postgres upgrades.

---

## VPS B: Development & AI Addons

VPS B hosts heavy dev engines, design applications, self-hosting administration panels, Stremio addons, and their supporting gateway/proxy infrastructure.

### 1. Dev Engines & Secret Management
#### **Supabase** (`Utilities/tools/supabase`)
* **Database (`supabase-db`)**: `supabase/postgres:15.14.1.148`
* **Meta API (`supabase-meta`)**: `supabase/postgres-meta:v0.96.6`
* **API Rest (`supabase-rest`)**: `postgrest/postgrest:v12.2.12`
* **Authentication (`supabase-auth`)**: `supabase/gotrue:v2.193.1`
* **Storage (`supabase-storage`)**: `supabase/storage-api:v1.67.7`
* **API Gateway (`supabase-kong`)**: `kong/kong:3.9.3`
* **Studio (`supabase-studio`)**: `supabase/studio` (Uses specific sha digest).
* **Intricacies**:
  - **CRITICAL**: The database is a customized version of PostgreSQL packaged with custom extensions (`pgvector`, `postgrest`, etc.). **Never** change this image to a standard library `postgres` tag.
  - Supabase upgrades must be done as a coordinated group following official self-hosted Supabase migration paths.
  - Kong and Studio are part of the coordinated upgrade group — always upgrade all Supabase components together.

#### **Infisical** (`Utilities/admin/infisical`)
* **Core Image**: `infisical/infisical:v0.162.16`
* **Database (`infisical-db`)**: `postgres:14-alpine`
* **Caching (`infisical-redis`)**: `redis:7-alpine`
* **Intricacies**: Secret manager dashboard. Ensure secrets database is locked to `postgres:14-alpine`.

---

### 2. Design & Workspace Tools
#### **Penpot** (`Utilities/tools/penpot`)
* **Backend & Frontend & Exporter**: `penpotapp/backend:2.16.2`, `penpotapp/frontend:2.16.2`, `penpotapp/exporter:2.16.2`
* **Database (`penpot-postgres`)**: `postgres:15-alpine`
* **Caching (`penpot-redis`)**: `redis:7-alpine`
* **Intricacies**: Make sure backend, frontend, and exporter versions remain exactly matched.

#### **Open-WebUI** (`Utilities/tools/open-webui`)
* **Core Image**: `ghcr.io/open-webui/open-webui` (Uses specific sha digest).
* **Intricacies**: SQLite database backend. Safe to upgrade minor/patch tags.

#### **Excalidraw** (`Utilities/tools/excalidraw`)
* **Core Image**: `excalidraw/excalidraw:latest`
* **Intricacies**: Stateless whiteboard tool. No database. Safe to upgrade freely. Connects to `vps_b_net`.

---

### 3. Administration & Monitoring Agents
#### **Hawser** (`Utilities/admin/hawser`)
* **Core Image**: `ghcr.io/finsys/hawser:0.2.46`
* **Intricacies**: Docker monitoring agent. Runs on `network_mode: host` and mounts `/var/run/docker.sock` read-only. Requires `HAWSER_TOKEN` env var.

#### **Dockhand** (`Utilities/admin/dockhand`)
* **Core Image**: `fnsys/dockhand:latest`
* **Database**: SQLite (file-based at `/app/data/dockhand.db`).
* **Intricacies**: Runs on `network_mode: host`. Mounts Docker socket read-only. Safe to upgrade minor/patch.

#### **VPS B Agents** (`Media/stremio/utilities/vps-b-agents`)
* **Dozzle Agent (`dozzle-agent-vps-b`)**: `amir20/dozzle:v10.6.14`
* **Docker Socket Proxy (`docker-socket-proxy-vps-b`)**: `tecnativa/docker-socket-proxy:v0.5.0`
* **Intricacies**: Both mount `/var/run/docker.sock` read-only. Socket proxy restricts API to read-only (`POST=0`). Both route through `media-gateway-stremio-utilities-gluetun`.

#### **Beszel Agent**
* **Core Image**: `henrygd/beszel-agent:0.18.7`
* **Intricacies**: Lightweight system metrics agent. Safe to upgrade.

---

### 4. Stremio Addons & Proxies
#### **Comet** (`Media/stremio/addons/comet`)
* **Core Image**: `g0ldyy/comet:latest`
* **Database (`comet-postgres`)**: `postgres:18-alpine`
* **Intricacies**: Uses PostgreSQL 18. Keep it locked to major version 18.

#### **Aiomanager** (`Media/stremio/addons/aiomanager`)
* **Core Image**: `ghcr.io/sonicx161/aiomanager:1.8.5`
* **Database (`aiomanager-db`)**: `postgres:16-alpine`
* **Intricacies**: Uses PostgreSQL. Avoid major Postgres upgrades without `pg_dumpall`.

#### **AIOMetadata** (`Media/stremio/addons/aiometadata`)
* **Core Image**: `ghcr.io/cedya77/aiometadata` (Pinned by sha256 digest).
* **Caching (`aiometadata_redis`)**: `redis:8-alpine`
* **Intricacies**: Routes through `media-gateway-proton-gluetun`. Has a commented-out Postgres container — if re-enabled, treat it as a database-sensitive service. Depends on `aiometadata_redis` being healthy.

#### **AIOStreams** (`Media/stremio/addons/aiostreams`)
* **Core Image**: `ghcr.io/viren070/aiostreams:latest`
* **Intricacies**: Stateless addon. No database. Routes through `media-gateway-stremio-addons-gluetun`. Safe to upgrade.

#### **StreamNZB** (`Media/stremio/addons/streamnzb`)
* **Core Image**: `ghcr.io/gaisberg/streamnzb:latest`
* **Intricacies**: Stateless addon. Routes through `media-gateway-stremio-addons-gluetun`. Safe to upgrade.

#### **StremThru** (`Media/stremio/addons/stremthru`)
* **Core Image**: `muniftanjim/stremthru:latest`
* **Intricacies**: Stateless debrid proxy. Routes through `media-gateway-stremio-addons-gluetun`. Safe to upgrade.

#### **Watchly** (`Media/stremio/addons/watchly`)
* **Core Image**: `ghcr.io/timilsinabimal/watchly:1.11.1`
* **Caching (`watchly-redis`)**: `redis:7-alpine` (Locked via `wud.tag.include=^7(\\.\\d+)*-alpine$`).
* **Intricacies**: Redis runs on custom port `6380`. Both containers route through `media-gateway-stremio-addons-gluetun`.

#### **NZBDav** (`Media/stremio/addons/nzbdav`)
* **Core Image**: `ghcr.io/infinidysk/infinidysk:latest`
* **Rclone Mount (`nzbdav_rclone`)**: `rclone/rclone:1.75.0`
* **Intricacies**: Rclone requires `SYS_ADMIN` capability and `/dev/fuse` device for FUSE mounts. Rclone depends on NZBDav being healthy. Both route through `media-gateway-stremio-addons-gluetun`.

#### **NZBHydra2** (`Media/stremio/addons/nzbhydra2`)
* **Core Image**: `ghcr.io/hotio/nzbhydra2:release-8.9.0`
* **Intricacies**: Usenet meta-search indexer. Uses file-based config. Routes through `media-gateway-stremio-addons-gluetun`. Safe to upgrade.

---


### 5. Stremio Utilities & Proxies
#### **Jackett & Trawl** (`Media/stremio/utilities/jackett`)
* **Jackett (`jackett`)**: `ghcr.io/linuxserver/jackett:latest` (has `AUTO_UPDATE=true`).
* **Trawl (`trawl`)**: `ghcr.io/germondai/trawl:latest`
* **Caching (`jackett-redis-1`)**: `redis:7-alpine` (runs on port `6382`).
* **Intricacies**: Trawl is a browser-based scraper with `shm_size: 1gb` and `mem_limit: 3g` — resource-heavy. All route through `media-gateway-stremio-utilities-gluetun`. Trawl depends on Redis.

#### **MediaFlow Proxy** (`Media/stremio/utilities/mediaflow-proxy`)
* **Core Image (`mfp`)**: `mhdzumair/mediaflow-proxy:latest` (Not pinned; review before production upgrades).
* **Caching (`mfp-redis`)**: `redis:7-alpine` (Locked via `wud.tag.include=^7(\\.\\d+)*-alpine$`).
* **Intricacies**: Proxy for media streams. Digest-pinned for stability. Routes through `media-gateway-stremio-utilities-gluetun`. Depends on `mfp-redis` being healthy.

#### **SyncIO** (`Media/stremio/utilities/syncio`)
* **Core Image**: `ghcr.io/iamneur0/syncio:private`
* **Intricacies**: Private instance with JWT auth and encryption. Runs frontend on port `3000` and backend on `4000`. Routes through `media-gateway-stremio-utilities-gluetun`.

#### **Scrob** (`Media/stremio/utilities/scrob`)
* **Core Image (`scrob`)**: `bellamy/scrob:latest`
* **Database (`scrob-db`)**: `postgres:16.8-alpine`
* **Intricacies**: Self-hosted media scrobbler and watch history sync app for Jellyfin, Plex, Emby. Runs web service on port `7330` with PostgreSQL 16 database. Routes through `media-gateway-stremio-utilities-gluetun`.

---

### 6. Gateway Stacks (VPN + Tailscale + Reverse Proxy)
All gateway stacks follow the same three-container pattern: **Gluetun** (VPN tunnel) → **Tailscale** (mesh network) → **Caddy** (reverse proxy). Other services attach to the gateway via `network_mode: "container:<gluetun-container>"`.

#### **Stremio Addons Gateway** (`Media/stremio/addons/gateway`)
* **Gluetun**: `qmcgaw/gluetun:latest`
* **Tailscale**: `tailscale/tailscale:v1.98.10`
* **Caddy**: `caddy:2.11.4-alpine` (Locked via `wud.tag.include=^2(\\.\\d+)*-alpine$`).
* **Serves**: AIOStreams, StreamNZB, StremThru, Watchly, NZBDav, NZBHydra2.

#### **Proton Gateway** (`Media/stremio/addons/gateway-proton`)
* **Gluetun**: `qmcgaw/gluetun:latest`
* **Tailscale**: `tailscale/tailscale:v1.98.10`
* **Caddy**: `caddy:2.11.4-alpine` (Locked via `wud.tag.include=^2(\\.\\d+)*-alpine$`).
* **Serves**: AIOMetadata and AIO Manager.


#### **Stremio Utilities Gateway** (`Media/stremio/utilities/gateway`)
* **Gluetun**: `qmcgaw/gluetun:latest`
* **Tailscale**: `tailscale/tailscale:v1.98.10`
* **Caddy**: `caddy:2.11.4-alpine` (Locked via `wud.tag.include=^2(\\.\\d+)*-alpine$`).
* **Serves**: Jackett/Trawl, MediaFlow Proxy, SyncIO, Scrob, VPS B Agents.

#### **Utilities Gateway B** (`Utilities/gateway-b`)
* **Tailscale**: `tailscale/tailscale:v1.98.10`
* **Caddy**: `caddy:2.11.4-alpine` (Locked via `wud.tag.include=^2(\\.\\d+)*-alpine$`).
* **Serves**: Penpot, Open-WebUI, Excalidraw, and other `vps_b_net` services.
* **Intricacies**: No Gluetun (no VPN). Direct Tailscale mesh exposure only.

**Gateway Intricacies (All)**:
  - Gluetun requires `NET_ADMIN` capability and `/dev/net/tun`. Tailscale requires `NET_ADMIN` + `NET_RAW`.
  - Caddy versions are locked to `2.x-alpine` via WUD labels. Tailscale uses explicit version pins.
  - **CRITICAL**: Restarting or upgrading a gateway disconnects **all** services that use `network_mode: "container:<gateway>"`. Always coordinate gateway changes with dependent services.
  - Gateways are protected by `renovate.json` critical-infra rules — never auto-merged.

---

## Step-by-Step Major Upgrades Instructions

### PostgreSQL Migration Procedure (e.g. Postgres 16 -> 18)
When upgrading database engines like PostgreSQL, follow this sequence:

1. **Suspend the Application**:
   ```bash
   # Example: n8n
   docker stop n8n
   ```
2. **Perform SQL Dump**:
   ```bash
   docker exec n8n-postgres pg_dumpall -U n8n > n8n_backup.sql
   ```
3. **Wipe Existing Volume & Update Tag**:
   - Move or delete the old data volume folder `./postgres-data`.
   - Update `postgres:16-alpine` to `postgres:18-alpine` in the compose file.
4. **Boot Empty Database through the manager**:
    ```bash
    ./manage.py deploy --services Utilities/tools/n8n
    ```
5. **Restore SQL Dump**:
   ```bash
   cat n8n_backup.sql | docker exec -i n8n-postgres psql -U n8n -d n8n
   ```
6. **Start Application**:
    ```bash
    ./manage.py redeploy --services Utilities/tools/n8n --recreate
    ```

---

### MariaDB LTS Upgrades
Keep MariaDB databases pinned to their specific LTS branches (e.g. `10.11` or `11.4`). If an upgrade is absolutely required:
1. Run `mariadb-dump` to back up the database schemas.
2. Bump the docker image tag.
3. Once booted, execute `mariadb-upgrade` inside the database container to reconcile system tables:
   ```bash
   docker exec -it nextcloud-db mariadb-upgrade -u root -p[root_password]
   ```
