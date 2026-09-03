"""Check for newer image release tags in registries across active pinned services."""

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Optional

from orchestrator.registry.manifest import ServiceMetadata, load_services

logger = logging.getLogger(__name__)


def parse_services_and_images(compose_content: str) -> dict[str, str]:
    services = {}
    current_service = None
    lines = compose_content.split("\n")
    in_services = False
    indent_level = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped == "services:":
            in_services = True
            continue

        if in_services:
            leading_spaces = len(line) - len(line.lstrip())
            if indent_level is None and leading_spaces > 0:
                indent_level = leading_spaces
            if indent_level is not None and leading_spaces < indent_level:
                in_services = False
                continue
            if leading_spaces == indent_level and stripped.endswith(":"):
                current_service = stripped[:-1].strip()
                services[current_service] = None
                continue
            if current_service and stripped.startswith("image:"):
                image_match = re.search(r'image:\s*["\']?([^\s"\'#]+)["\']?', stripped)
                if image_match:
                    services[current_service] = image_match.group(1)

    return {k: v for k, v in services.items() if v}


def parse_image_string(image_str: str) -> tuple[str, str, str]:
    if ":" in image_str:
        name_part, tag = image_str.rsplit(":", 1)
    else:
        name_part = image_str
        tag = "latest"

    if "/" in name_part:
        parts = name_part.split("/", 1)
        if "." in parts[0] or "localhost" in parts[0]:
            registry = parts[0]
            repo = parts[1]
        else:
            registry = "docker.io"
            repo = name_part
    else:
        registry = "docker.io"
        repo = f"library/{name_part}"

    return registry, repo, tag


def parse_version(tag: str) -> Optional[dict]:
    if tag.lower() in ("latest", "testing", "master", "main", "dev", "alpha", "beta"):
        return None

    match = re.match(r"^(?:v|release-)?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?(?:-([a-zA-Z0-9.]+))?$", tag)
    if not match:
        return None

    major = int(match.group(1))
    if major >= 1000:
        return None

    minor = int(match.group(2)) if match.group(2) else 0
    patch = int(match.group(3)) if match.group(3) else 0
    build = int(match.group(4)) if match.group(4) else 0
    suffix = match.group(5) if match.group(5) else ""
    return {
        "tuple": (major, minor, patch, build),
        "suffix": suffix.lower(),
    }


def get_docker_hub_tags(repo: str) -> list[str]:
    url = f"https://registry.hub.docker.com/v2/repositories/{repo}/tags?page_size=100"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.loads(res.read().decode("utf-8"))
            return [tag["name"] for tag in data.get("results", [])]
    except Exception:
        return []


def get_ghcr_tags(repo: str) -> list[str]:
    token_url = f"https://ghcr.io/token?scope=repository:{repo}:pull&service=ghcr.io"
    try:
        req = urllib.request.Request(token_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as res:
            token_data = json.loads(res.read().decode("utf-8"))
            token = token_data.get("token")

        tags_url = f"https://ghcr.io/v2/{repo}/tags/list"
        req_tags = urllib.request.Request(tags_url, headers={
            "User-Agent": "Mozilla/5.0",
            "Authorization": f"Bearer {token}",
        })
        with urllib.request.urlopen(req_tags, timeout=8) as res_tags:
            tags_data = json.loads(res_tags.read().decode("utf-8"))
            return tags_data.get("tags", [])
    except Exception:
        return []


def get_remote_tags(registry: str, repo: str) -> list[str]:
    if registry == "ghcr.io":
        return get_ghcr_tags(repo)
    elif registry == "docker.io":
        return get_docker_hub_tags(repo)
    return []


def is_prerelease(suffix: str) -> bool:
    return any(x in suffix for x in ["rc", "beta", "alpha", "dev", "pre", "testing", "unstable"])


def find_newer_versions(current_tag: str, remote_tags: list[str]) -> Optional[str]:
    current_ver = parse_version(current_tag)
    if not current_ver:
        return None

    pinned_tuple = current_ver["tuple"]
    pinned_suffix = current_ver["suffix"]
    pinned_is_prerelease = is_prerelease(pinned_suffix)

    better_versions = []
    for r_tag in remote_tags:
        r_ver = parse_version(r_tag)
        if not r_ver:
            continue

        r_tuple = r_ver["tuple"]
        r_suffix = r_ver["suffix"]

        if pinned_suffix:
            if pinned_suffix not in r_suffix:
                continue
        else:
            if r_suffix:
                continue

        if is_prerelease(r_suffix) and not pinned_is_prerelease:
            continue

        if r_tuple > pinned_tuple:
            better_versions.append((r_tuple, r_tag))

    if not better_versions:
        return None

    better_versions.sort()
    return better_versions[-1][1]


def check_upgrades(services: Optional[list[ServiceMetadata]] = None, vps: Optional[str] = None, json_output: bool = False) -> list[dict]:
    """Check for pinned image upgrades across active services."""
    all_services = services or load_services(vps=vps)

    from orchestrator.docker.updater import is_service_container_active
    active_services = [s for s in all_services if is_service_container_active(s)]

    if not active_services:
        if json_output:
            print(json.dumps({"upgrades": []}))
        else:
            print("[INFO] No active compose services found running on this server.")
        return []

    print(f"[INFO] Discovered {len(active_services)} active services. Scanning registries for upgrades...")
    upgrades = []

    for s in active_services:
        compose_path = s.compose_file_path
        if not compose_path.is_file():
            continue

        try:
            content = compose_path.read_text(encoding="utf-8")
            service_images = parse_services_and_images(content)
        except Exception as e:
            logger.warning("Error reading compose file %s: %s", compose_path, e)
            continue

        for svc_name, img_str in service_images.items():
            if img_str.startswith("local/"):
                continue

            registry, repo, tag = parse_image_string(img_str)
            current_ver = parse_version(tag)
            if not current_ver:
                continue

            logger.info("Scanning registry tags for %s -> %s (current: %s)...", s.name, svc_name, tag)
            remote_tags = get_remote_tags(registry, repo)
            if not remote_tags:
                continue

            newer_tag = find_newer_versions(tag, remote_tags)
            if newer_tag:
                upgrades.append({
                    "project": s.name,
                    "service": svc_name,
                    "image": img_str.split(":", 1)[0],
                    "current": tag,
                    "latest": newer_tag,
                    "abs_dir": str(s.abs_dir),
                    "file": s.compose_file,
                    "rel_dir": s.rel_dir,
                    "category": s.category,
                    "vps": s.vps,
                })

    if json_output:
        print(json.dumps({"upgrades": upgrades}))
        return upgrades

    if not upgrades:
        print("\n\033[1;32m[OK] All active pinned services are running the latest versions of their release tracks!\033[0m")
        return []

    print("\n\033[1;36m=========================================================================================")
    print("    Available Pinned Version Upgrades")
    print("=========================================================================================\033[0m")
    print(f" {'#':<3} | {'Project':<16} | {'Service':<14} | {'Current':<14} | {'Latest Available':<18}")
    print("\033[1;36m-----------------------------------------------------------------------------------------\033[0m")
    for idx, up in enumerate(upgrades, 1):
        print(f" {idx:<3} | {up['project']:<16} | {up['service']:<14} | \033[31m{up['current']:<14}\033[0m | \033[1;32m{up['latest']:<18}\033[0m")
    print("\033[1;36m=========================================================================================\033[0m\n")

    return upgrades
