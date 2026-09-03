"""Docker container update engine with age-gating and image backup tagging."""

import concurrent.futures
import json
import logging
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from orchestrator.core.constants import REPO_ROOT
from orchestrator.registry.manifest import ServiceMetadata
from orchestrator.secrets.doppler import DopplerClient

logger = logging.getLogger(__name__)


def get_host_platform() -> str:
    """Detect host OS and architecture for registry matching."""
    os_name = "linux"
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine in ("i386", "i686", "x86"):
        arch = "386"
    elif "armv7" in machine or "armhf" in machine:
        arch = "arm"
    else:
        arch = machine
    return f"{os_name}/{arch}"


def parse_iso_datetime(s: str) -> datetime:
    """Safe parser for Docker/OCI created timestamp."""
    s = s.replace("Z", "+00:00")
    if "." in s:
        base, tz = s.split(".", 1)
        tz_char = "+" if "+" in tz else "-"
        frac, tz_offset = tz.split(tz_char, 1)
        frac = frac[:6]
        s = f"{base}.{frac}{tz_char}{tz_offset}"
    return datetime.fromisoformat(s)


def format_age(days: float) -> str:
    if days < 1:
        hours = days * 24
        return f"{hours:.1f} hours"
    return f"{days:.1f} days"


def is_service_container_active(service: ServiceMetadata) -> bool:
    """Check if the service container is currently running."""
    cmd = ["docker", "compose"]
    if service.custom_project_name:
        cmd += ["-p", service.custom_project_name]
    cmd += ["-f", service.compose_file, "ps", "-q"]
    try:
        res = subprocess.run(cmd, cwd=str(service.abs_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return bool(res.stdout.strip())
    except Exception:
        return False


def check_service_update(service: ServiceMetadata, service_name: str, cid: str, active_image_id: str, image_tag: str, min_age_days: float):
    if "@sha256:" in image_tag:
        return None

    res_local = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image_tag],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    local_digests = []
    if res_local.returncode == 0 and res_local.stdout.strip():
        try:
            local_digests = json.loads(res_local.stdout.strip())
        except Exception:
            pass

    if not local_digests and (image_tag.startswith("local/") or "/" not in image_tag):
        return None

    logger.info("Checking registry: %s -> %s (%s)...", service.name, service_name, image_tag)

    res_remote_manifest = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", image_tag, "--format", "{{json .Manifest}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if res_remote_manifest.returncode != 0:
        return None

    try:
        remote_manifest = json.loads(res_remote_manifest.stdout.strip())
    except Exception:
        return None

    remote_digest = remote_manifest.get("digest")
    if not remote_digest:
        return None

    is_updated = True
    for ld in local_digests:
        if remote_digest in ld:
            is_updated = False
            break

    if not is_updated:
        return None

    too_recent = False
    age_days = 0.0
    if min_age_days > 0.0:
        res_remote_full = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", image_tag, "--format", "{{json .}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if res_remote_full.returncode == 0:
            try:
                remote_full = json.loads(res_remote_full.stdout.strip())
                host_platform = get_host_platform()
                platform_info = remote_full.get("image", {}).get(host_platform)

                if not platform_info:
                    host_arch = host_platform.split("/")[-1]
                    for plat_key, plat_val in remote_full.get("image", {}).items():
                        if host_arch in plat_key:
                            platform_info = plat_val
                            break

                if platform_info and "created" in platform_info:
                    created_str = platform_info["created"]
                    created_dt = parse_iso_datetime(created_str)
                    now_dt = datetime.now(timezone.utc)
                    age_seconds = (now_dt - created_dt).total_seconds()
                    age_days = age_seconds / 86400.0
                    if age_days < min_age_days:
                        too_recent = True
            except Exception as ex:
                logger.warning("[WARNING] Error checking release age for %s: %s", image_tag, ex)

    return {
        "service_metadata": service,
        "service": service_name,
        "image": image_tag,
        "active_image_id": active_image_id,
        "proj_name": service.custom_project_name,
        "remote_digest": remote_digest,
        "too_recent": too_recent,
        "age_days": age_days,
    }


def backup_image(image_tag: str, active_image_id: str) -> Optional[str]:
    if not active_image_id:
        return None

    if ":" in image_tag and not image_tag.startswith("sha256:"):
        base_name, _ = image_tag.rsplit(":", 1)
    else:
        base_name = image_tag

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_tag = f"{base_name}:backup-{timestamp}"

    logger.info("Creating backup tag for active image ID %s -> %s...", active_image_id[:12], backup_tag)
    res = subprocess.run(["docker", "tag", active_image_id, backup_tag], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode == 0:
        logger.info("[OK] Created backup tag: %s", backup_tag)
        return backup_tag
    else:
        logger.warning("[WARNING] Failed to create backup tag: %s", res.stderr.strip())
        return None


def restore_image(image_tag: str, backup_tag: str) -> bool:
    """Restore an image tag from the backup created before an update."""
    res = subprocess.run(
        ["docker", "tag", backup_tag, image_tag],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if res.returncode == 0:
        logger.info("[OK] Restored image tag %s from %s.", image_tag, backup_tag)
        return True
    logger.error("[ERROR] Failed to restore image tag %s: %s", image_tag, res.stderr.strip())
    return False


def prune_backups(keep_days: int) -> None:
    if keep_days <= 0:
        return
    logger.info("Pruning backup images older than %d days...", keep_days)
    res = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if res.returncode != 0:
        return

    now = datetime.now()
    pattern = re.compile(r":backup-(\d{8})-(\d{6})$")
    pruned_count = 0

    for line in res.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) < 1:
            continue
        image_ref = parts[0]

        match = pattern.search(image_ref)
        if match:
            date_str, time_str = match.groups()
            try:
                backup_time = datetime.strptime(f"{date_str}-{time_str}", "%Y%m%d-%H%M%S")
                age_days = (now - backup_time).days
                if age_days >= keep_days:
                    logger.info("Removing expired backup image: %s (age: %d days)...", image_ref, age_days)
                    subprocess.run(["docker", "rmi", image_ref], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    pruned_count += 1
            except Exception as e:
                logger.warning("Failed to parse or remove backup image %s: %s", image_ref, e)

    if pruned_count > 0:
        logger.info("[OK] Pruned %d expired backup images.", pruned_count)


def handle_updates(services: list, auto_confirm: bool = False, min_age_days: float = 0.0, backup_days: int = 7) -> None:
    """Evaluate and apply container image updates across active services."""
    doppler_client = DopplerClient()

    active_services = []
    for s in services:
        if isinstance(s, dict):
            # Compatibility with dict-based service models
            from orchestrator.registry.manifest import ServiceMetadata
            abs_dir = Path(s.get("abs_dir", REPO_ROOT / s.get("rel_dir", "")))
            s_obj = ServiceMetadata(
                name=s.get("name", abs_dir.name),
                rel_dir=s.get("rel_dir", str(abs_dir.relative_to(REPO_ROOT))),
                abs_dir=abs_dir,
                category=s.get("category", ""),
                vps=s.get("vps", "A"),
                custom_project_name=s.get("proj_name"),
            )
        else:
            s_obj = s

        if is_service_container_active(s_obj):
            active_services.append(s_obj)

    if not active_services:
        print("[INFO] No active compose services found running on this server. Nothing to update.")
        return

    print(f"[INFO] Discovered {len(active_services)} active services.")

    tasks = []
    for s in active_services:
        cmd = ["docker", "compose"]
        if s.custom_project_name:
            cmd += ["-p", s.custom_project_name]
        cmd += ["-f", s.compose_file, "ps", "-q"]

        res = subprocess.run(cmd, cwd=str(s.abs_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        container_ids = [cid.strip() for cid in res.stdout.strip().split("\n") if cid.strip()]

        for cid in container_ids:
            res_svc = subprocess.run(["docker", "inspect", "--format", '{{index .Config.Labels "com.docker.compose.service"}}', cid], stdout=subprocess.PIPE, text=True)
            service_name = res_svc.stdout.strip()

            res_img = subprocess.run(["docker", "inspect", "--format", "{{.Image}}", cid], stdout=subprocess.PIPE, text=True)
            active_image_id = res_img.stdout.strip()

            res_tag = subprocess.run(["docker", "inspect", "--format", "{{.Config.Image}}", cid], stdout=subprocess.PIPE, text=True)
            image_tag = res_tag.stdout.strip()

            if not service_name or not active_image_id or not image_tag:
                continue

            tasks.append((s, service_name, cid, active_image_id, image_tag))

    if not tasks:
        print("[INFO] No active containers found to inspect. Up to date.")
        return

    print(f"[INFO] Querying registries for {len(tasks)} containers asynchronously...")
    updates_all = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tasks), 16)) as executor:
        futures = {
            executor.submit(
                check_service_update, s, service_name, cid, active_image_id, image_tag, min_age_days
            ): (s.name, service_name, image_tag)
            for s, service_name, cid, active_image_id, image_tag in tasks
        }

        for future in concurrent.futures.as_completed(futures):
            s_name, svc_name, img_tag = futures[future]
            try:
                res = future.result()
                if res:
                    updates_all.append(res)
            except Exception as e:
                logger.error("[ERROR] Error checking updates for %s -> %s: %s", s_name, svc_name, e)

    updates_available = [u for u in updates_all if not u["too_recent"]]
    updates_deferred = [u for u in updates_all if u["too_recent"]]

    if not updates_all:
        print("[OK] All active containers are up to date! No updates available.")
        return

    if updates_available:
        print("\n\033[1;36m=========================================================================================")
        print("    Available Updates Summary")
        print("=========================================================================================\033[0m")
        for idx, up in enumerate(updates_available, 1):
            age_str = f" (Age: {format_age(up['age_days'])})" if up["age_days"] > 0 else ""
            print(f"  {idx}. {up['service_metadata'].name} -> {up['service']}: {up['image']}{age_str}")
        print("\033[1;36m=========================================================================================\033[0m\n")

    if updates_deferred:
        print("\n\033[1;33m=========================================================================================")
        print(f"    Deferred Updates (Age Gate: {min_age_days} days)")
        print("=========================================================================================\033[0m")
        for idx, up in enumerate(updates_deferred, 1):
            print(f"  {idx}. {up['service_metadata'].name} -> {up['service']}: {up['image']} (Released: {format_age(up['age_days'])} ago)")
        print("\033[1;33m=========================================================================================\033[0m\n")

    if not updates_available:
        print("[INFO] All available updates are currently deferred by the stability age gate.")
        return

    if not auto_confirm:
        if not sys.stdin.isatty():
            print("[INFO] Non-interactive mode. Use --yes/-y to auto-confirm updates.")
            return
        confirm = input(f"Apply updates to {len(updates_available)} service(s)? (y/N): ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Update cancelled.")
            return

    for up in updates_available:
        s = up["service_metadata"]
        service_name = up["service"]
        image_tag = up["image"]
        active_image_id = up["active_image_id"]

        print(f"\n[INFO] Updating {s.name} -> {service_name} ({image_tag})...")
        backup_tag = backup_image(image_tag, active_image_id)

        pull_cmd = doppler_client.wrap_command(
            ["docker", "compose", "-f", s.compose_file, "pull", service_name],
            service=s,
        )
        res_pull = subprocess.run(pull_cmd, cwd=str(s.abs_dir))
        if res_pull.returncode != 0:
            logger.error("[ERROR] Failed to pull %s for %s", image_tag, s.name)
            continue

        up_cmd = doppler_client.wrap_command(
            ["docker", "compose", "-f", s.compose_file, "up", "-d", "--force-recreate", service_name],
            service=s,
        )
        res_up = subprocess.run(up_cmd, cwd=str(s.abs_dir))
        if res_up.returncode == 0:
            print(f"[OK] Successfully updated {s.name} -> {service_name}!")
        else:
            logger.error("[ERROR] Failed to recreate %s; attempting rollback...", s.name)
            if backup_tag:
                restore_image(image_tag, backup_tag)

    prune_backups(backup_days)
