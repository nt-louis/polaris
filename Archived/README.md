# 🗄️ Archived Services Index

This directory holds the configuration files and local state of services that were disabled to optimize performance and reduce stack clutter. 

These directories have been completely moved out of the active stack. They will **not** be scanned or deployed by the stack manager (`manage.py`).

---

## 📋 Archived Services List

The following services have been archived:

| Service | Original Relative Path | Category | VPS | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Homepage** | `Utilities/admin/homepage` | Dashboard | VPS A | Static web portal / dashboard. |
| **Portainer** | `Utilities/admin/portainer` | Docker Management | VPS A | Container GUI console (replaced by Dockhand). |
| **Emby** | `Media/local-media/players/emby` | Media Server | VPS A | Catalog & player server (replaced by Jellyfin). |
| **aMuTorrent** | `Media/local-media/download-clients/amutorrent` | Downloader | VPS A | BitTorrent & eMule client (replaced by qBittorrent). |
| **Readarr Books** | `Media/local-media/managers/readarr-books` | Book Manager | VPS A | Automated ebook manager (replaced by Shelfmark). |
| **Readarr Audiobooks** | `Media/local-media/managers/readarr-audiobooks` | Book Manager | VPS A | Automated audiobook manager (replaced by Shelfmark). |
| **Pingvin Share** | `Utilities/files/pingvin-share` | File Sharing | VPS A | Custom file sharing tool (replaced by Nextcloud). |
| **Kavita** | `Media/comics/kavita` | Book/Comic Reader | VPS A | Comic/manga/epub reader (replaced by Grimmory/Audiobookshelf). |
| **Jackettio** | `Media/stremio/addons/jackettio` | Stremio Addon | VPS B | Torrent addon for Stremio (replaced by Comet). |
| **Changedetection** | `Utilities/information/changedetection` | Monitoring | VPS A | Webpage change detection engine. |
| **Filebrowser** | `Utilities/files/filebrowser` | Web Client | VPS A | Simple web-based file manager for repository folders. |
| **ConvertX** | `Utilities/tools/convertx` | Web Utility | VPS A | File format conversion dashboard. |
| **Authentik** | `Utilities/auth/authentik` | SSO Portal | VPS A | Heavy enterprise IDP authentication suite. |
| **WUD** | `Utilities/monitoring/wud` | Monitoring | VPS A | What's Up Docker update monitoring agent. |
| **Komodo** | `Utilities/admin/komodo` | Administration | VPS A | Project orchestration dashboard. |
| **UsenetStreamer** | `Media/stremio/addons/usenetstreamer` | Stremio Addon | VPS B | Direct streaming engine for Usenet files. |
| **DMM** | `Media/stremio/utilities/dmm` | Web Client | VPS B | Debrid Media Manager interface portal. |
| **Arr Dashboard** | `Media/local-media/tools/arr-dashboard` | Web Portal | VPS A | Unified dashboard monitoring Arr servers. |
| **Plex** | `Media/local-media/players/plex` | Media Server | VPS A | Proprietary media streaming server option. |
| **Decypharr** | `Media/local-media/managers/decypharr` | Subtitle helper | VPS A | Subtitle decrypter agent for media downloads. |

---

## 🛠️ How to Restore an Archived Service

If you ever want to re-enable one of these services:

1. **Move the folder back** to its original path relative to the repository root.
2. **Rename the compose file** inside it back to `docker-compose.yml` (if it has a `.disabled` extension).
3. **Deploy the service** using the stack manager:
   ```bash
   ./manage.py deploy
   ```

### Quick Commands to Restore a Service

Run these commands from the repository root:

*   **Homepage**:
    ```bash
    mv Archived/Utilities/admin/homepage Utilities/admin/homepage
    ```
*   **Portainer**:
    ```bash
    mv Archived/Utilities/admin/portainer Utilities/admin/portainer
    ```
*   **Emby**:
    ```bash
    mv Archived/Media/local-media/players/emby Media/local-media/players/emby
    ```
*   **aMuTorrent**:
    ```bash
    mv Archived/Media/local-media/download-clients/amutorrent Media/local-media/download-clients/amutorrent
    ```
*   **Readarr (Books)**:
    ```bash
    mv Archived/Media/local-media/managers/readarr-books Media/local-media/managers/readarr-books
    ```
*   **Readarr (Audiobooks)**:
    ```bash
    mv Archived/Media/local-media/managers/readarr-audiobooks Media/local-media/managers/readarr-audiobooks
    ```
*   **Pingvin Share**:
    ```bash
    mv Archived/Utilities/files/pingvin-share Utilities/files/pingvin-share
    ```
*   **Kavita**:
    ```bash
    mv Archived/Media/comics/kavita Media/comics/kavita
    ```
*   **Jackettio**:
    ```bash
    mv Archived/Media/stremio/addons/jackettio Media/stremio/addons/jackettio
    ```
*   **Plex**:
    ```bash
    mv Archived/Media/local-media/players/plex Media/local-media/players/plex
    # Rename compose
    mv Media/local-media/players/plex/docker-compose.yml.disabled Media/local-media/players/plex/docker-compose.yml
    ```
