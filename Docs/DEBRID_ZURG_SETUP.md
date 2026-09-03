# Debrid-Backed Media Libraries (Zurg & Rclone, Disabled Reference)

This guide explains how to set up and configure **Zurg** and **Rclone** in your Polaris stack to mount your entire Real-Debrid library as a virtual local directory on your VPS host. This enables both **Jellyfin** and **Emby** to index and stream 4K cached torrents instantly with **zero host disk space usage**.

> [!WARNING]
> `Media/zurg` is excluded from active compose discovery and currently has no
> deployable compose file. This document preserves the configuration concepts
> for a future reactivation; it is not an active deployment runbook.

---

## Architecture & Security

To protect your Real-Debrid account from multi-IP bans (which happen if you access the service from different public IPs simultaneously), the Zurg and Rclone containers are integrated directly into the **Nested Gateway Pattern**:

1.  **Outbound Traffic Isolation:** Zurg is configured with `network_mode: "container:media-gateway-core-gluetun"`.
2.  **Shared Exit IP:** All requests to the Real-Debrid API go through your core VPN gateway, matching the exit IP of all other media-related debrid and downloader tools in your stack.
3.  **Local Loopback Connection:** Rclone runs in the same network namespace and connects to Zurg over WebDAV using loopback (`http://127.0.0.1:9995`), meaning no ports are exposed to the public host or internet.
4.  **Mount Propagation:** Rclone mounts the WebDAV path inside the container and propagates it back to the host at `${MEDIA_SHARE}/zurg` using `:shared` mount propagation.

---

## Setup & Deployment

If this stack is reactivated, it must first receive an active compose file,
VPS assignment, Doppler config, and validation coverage. Do not start it from
this document while it remains disabled.

### Step 1: Create the Host Mount Point
Before starting the containers, you must create the directory on your host VPS that will receive the mount:
```bash
mkdir -p /path/to/your/media/share/zurg
sudo chown -R ubuntu:ubuntu /path/to/your/media/share/zurg
sudo chmod -R 775 /path/to/your/media/share/zurg
```
*(Replace `/path/to/your/media/share` with the actual path to your physical media folder on the VPS host, matching your `MEDIA_SHARE` environment variable).*


### Step 2: Set Up Configuration & Environment
1.  On the VPS, navigate to the Zurg directory:
    ```bash
    cd Media/zurg
    ```
2.  When the stack is reactivated, create the upstream Zurg `config.yml`
    according to the versioned Zurg release documentation.
3.  Set its Real-Debrid API token from the
    [Real-Debrid API Token Page](https://real-debrid.com/apitoken). Keep the
    generated file outside version control; the current repository does not
    provide a `config.yml.template`.
    ```yaml
    token: your_actual_token_here
    ```
    *(Note: `config.yml` is in the project's `.gitignore` to ensure your private token is never committed to Git).*
4.  Add `MEDIA_SHARE` from `.env.example` to the `media_zurg` config in the
    active VPS Doppler project. Set it to the absolute path to your media
    directory on the host VPS (e.g. `/mnt/media` or `/home/ubuntu/media`).

Do not create a production `.env`; see
[DOPPLER_OPERATIONS_GUIDE.md](DOPPLER_OPERATIONS_GUIDE.md) for the config
workflow. This stack is currently disabled in the repository, so confirm its
compose definition is active before deploying it.

### Step 3: Run the Stack After Reactivation

After the stack is reintroduced to active discovery, deploy it from the
repository root with `./manage.py deploy --vps A`. Until then, there is no
active Zurg container to start or verify.

### Step 4: Verify the Mount
Verify that the mount is active and the virtual directories are visible on your VPS host:
```bash
ls -la /path/to/your/media/share/zurg
```
You should see subdirectories like `shows` and `movies` reflecting your Real-Debrid cloud torrent library!

---

## Adding the Library to Jellyfin & Emby

Once the mount is verified, you can immediately add it to your media servers:

1.  Open **Jellyfin** or **Emby** in your web browser.
2.  Go to the **Dashboard** -> **Libraries** and click **Add Media Library**.
3.  Set the content type (e.g. Movies or TV Shows).
4.  Add the folder path: `/data/media/zurg/movies` or `/data/media/zurg/shows`.
    *(This is because your compose config mounts `${MEDIA_SHARE}` to `/data/media` inside the Jellyfin/Emby containers).*
5.  Click **OK** and let the server scan the library. It will gather metadata, subtitles, and backdrops while streaming the media instantly on demand!

---

## Troubleshooting

### 1. FUSE Mount Error / Permission Denied
If the Rclone container fails to boot and displays a mounting error in the logs (`docker logs media-zurg-rclone`), make sure the FUSE driver is active on your host kernel:
```bash
sudo modprobe fuse
```

### 2. Host Directory is Empty / Not Readable in Jellyfin or Emby
If the mount point is visible and readable on the host VPS (e.g. `ls -la /path/to/media/share/zurg` shows your files), but they appear empty or unreadable inside **Jellyfin** or **Emby**:
*   **FUSE Bind Propagation:** By default, Docker volume mounts are isolated (`private`). Since Rclone mounts the FUSE directory on the host *after* Docker starts or handles mount namespaces, the media containers will not see the virtual sub-mount unless **recursive slave propagation** (`rslave`) is configured.
*   **The Fix:** We have pre-configured Jellyfin and Emby in `Media/local-media/docker-compose.yml` to mount the media share using the `rslave` flag:
    ```yaml
    volumes:
      - ${MEDIA_SHARE}:/data/media:ro,rslave
    ```
*   **How to apply:** Simply restart your local-media stack to recreate the containers with the new mount propagation flags:
    ```bash
    cd ~/polaris
    ./manage.py redeploy --vps A --recreate
    ```

### 3. chown: cannot read directory ... Input/output error
If you receive an `Input/output error` when running `chown` or `chmod` on the `zurg` directory, it is because **the FUSE mount is currently active** and Rclone is virtualizing that path. You cannot modify ownership of the virtual files directly on a read-only WebDAV remote.
To fix this:
1. Stop the active managed stack that owns the mount to release the FUSE mount.
   Do not run a direct compose command from this disabled reference.
2. Now, set the ownership and permissions of the underlying physical host directory:
   ```bash
   sudo chown -R ubuntu:ubuntu /path/to/your/media/share/zurg
   sudo chmod -R 775 /path/to/your/media/share/zurg
   ```
3. After reactivation, start the stack through `./manage.py deploy`. Confirm
   the reactivated compose file still defines the documented Rclone UID/GID
   and umask flags before relying on them.
