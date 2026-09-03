"""Filesystem discovery and runtime appdata directory resolution."""

import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from orchestrator.core.constants import EXCLUDE_DIRS, REPO_ROOT
from orchestrator.registry.manifest import (
    DEFAULT_MANIFEST_PATH,
    load_manifest_raw,
    load_services,
)

ACTIVE_COMPOSE_FILENAMES: tuple[str, ...] = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "mongo.compose.yaml",
)


def discover_appdata_paths(
    target_vps: str = "A",
    base_path: str = "/docker/appdata",
    repo_root: Optional[Path] = None,
) -> list[str]:
    """Discover application data directories strictly scoped to the assigned VPS node.

    Ensures that only data folders belonging to services actively assigned to the
    target VPS are backed up, preventing cross-node duplication.

    Args:
        target_vps: 'A', 'B', or 'ALL'
        base_path: Root host appdata directory (default: /docker/appdata)
        repo_root: Optional repository root override

    Returns:
        Sorted list of existing absolute directory paths scoped to target_vps.
    """
    root = repo_root or REPO_ROOT
    target = target_vps.upper() if target_vps else "ALL"

    services = load_services(repo_root=root, vps=target)

    appdata_paths: set[str] = set()
    mount_pattern = re.compile(r"^\s*-\s*([^:]+):")

    for svc in services:
        proj_abs = str(svc.abs_dir)
        proj_name = svc.name

        # 1. Primary: Check in-repo standard data/state/config folders
        for sub in ("data", "state", "config", "db", "postgres-data", "storage-data", "aio-data", "aio-db-data"):
            cand = os.path.join(proj_abs, sub)
            if os.path.isdir(cand):
                appdata_paths.add(cand)

        # 2. Parse compose file for explicit volume mounts
        compose_file_path = str(svc.compose_path)
        if os.path.isfile(compose_file_path):
            try:
                with open(compose_file_path, "r", encoding="utf-8", errors="ignore") as cf:
                    for line in cf:
                        match = mount_pattern.match(line)
                        if match:
                            src = match.group(1).strip()
                            if src.startswith("./") or src.startswith("../"):
                                full = os.path.normpath(os.path.join(proj_abs, src))
                                if os.path.isdir(full) and full.startswith(str(root)):
                                    appdata_paths.add(full)
                            elif base_path and "${BASE_PATH" in src:
                                subpath = re.sub(r"\$\{BASE_PATH[^}]*\}", "", src).lstrip("/")
                                full = os.path.join(base_path, subpath)
                                if os.path.isdir(full):
                                    appdata_paths.add(full)
                            elif base_path and src.startswith(base_path) and os.path.isdir(src):
                                appdata_paths.add(src)
            except Exception:
                pass

        # 3. Optional fallback: Check central BASE_PATH subfolder matching project name
        if base_path and os.path.isdir(base_path):
            candidate_base = os.path.join(base_path, proj_name)
            if os.path.isdir(candidate_base):
                appdata_paths.add(candidate_base)

    # Special core stacks (e.g. Network gateway state on VPS A)
    if target in ("A", "ALL"):
        net_state = os.path.join(str(root), "Network", "state")
        if os.path.isdir(net_state):
            appdata_paths.add(net_state)

    # Filter out cache, streaming VFS, git, and decommissioned folders
    cleaned_paths: list[str] = []
    for p in sorted(appdata_paths):
        if any(ign in p for ign in ("cache-rd", "cache-tb", "vfsMeta", ".venv", "node_modules", "Archived")):
            continue
        cleaned_paths.append(p)

    return cleaned_paths


def discover_compose_dirs_on_disk(repo_root: Optional[Path] = None) -> set[str]:
    """Scan for all active docker compose directory paths, including untracked files."""
    root = repo_root or REPO_ROOT
    on_disk: set[str] = set()

    # Fast path: query tracked + untracked files via git (skips gitignored/permission-denied caches)
    try:
        res_tracked = subprocess.run(
            ["git", "ls-files"], cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        res_untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        all_files = (res_tracked.stdout or "").splitlines() + (res_untracked.stdout or "").splitlines()
        for f in all_files:
            if os.path.basename(f) in ACTIVE_COMPOSE_FILENAMES and not f.startswith("Archived/"):
                dir_name = os.path.dirname(os.path.normpath(f))
                if dir_name:
                    on_disk.add(dir_name)
        if on_disk:
            return on_disk
    except Exception:
        pass

    # Fallback: scan only service stack directories, pruning caches and FUSE mounts
    service_roots = [root / "Network", root / "Media", root / "Utilities"]
    for s_root in service_roots:
        if not s_root.is_dir():
            continue
        for r, dirs, files in os.walk(str(s_root), followlinks=False, onerror=lambda err: None):
            dirs[:] = [
                d for d in dirs
                if d not in EXCLUDE_DIRS
                and not d.startswith("cache")
                and not d.startswith(".")
                and d not in ("Archived", "state", "data", "node_modules", ".venv", "vfs", "vfsMeta")
            ]
            for f in files:
                if f in ACTIVE_COMPOSE_FILENAMES:
                    rel_p = os.path.relpath(r, str(root))
                    if not rel_p.startswith("Archived") and rel_p != ".":
                        on_disk.add(os.path.normpath(rel_p))

    return on_disk


def detect_manifest_drift(
    manifest_path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> tuple[set[str], set[str]]:
    """Compare registered services in services.yaml against active compose files on disk.

    Returns:
        tuple[set[str], set[str]]: (missing_in_manifest, extra_in_manifest)
    """
    root = repo_root or REPO_ROOT
    m_path = manifest_path or DEFAULT_MANIFEST_PATH

    data = load_manifest_raw(m_path)
    registered = {os.path.normpath(svc["path"]) for svc in data.get("services", []) if "path" in svc}

    on_disk = discover_compose_dirs_on_disk(root)

    missing = on_disk - registered
    extra = registered - on_disk
    return missing, extra
