"""Container log resolution and streaming engine.

Resolves arbitrary service queries to active container IDs or names
and streams stdout/stderr logs with tail and follow support.
"""

import logging
import subprocess
from typing import Optional

from orchestrator.core.models import ServiceMetadata
from orchestrator.docker.client import DockerClient, default_client
from orchestrator.docker.readiness import extract_container_names
from orchestrator.registry.resolver import resolve_targets

logger = logging.getLogger(__name__)


def resolve_container(
    query: str,
    services: Optional[list[ServiceMetadata]] = None,
    client: Optional[DockerClient] = None,
) -> Optional[str]:
    """Resolve a target query string to a concrete Docker container name.

    Resolution strategy:
    1. Exact container name match against running containers.
    2. Prefix/suffix container name match (e.g. 'jellyfin-1', 'media-jellyfin').
    3. Manifest service target resolution -> declared compose container_name lookup.
    4. Substring container name match against running containers.

    Args:
        query: User input query (e.g. 'jellyfin', 'media/local-media/managers/bazarr').
        services: Optional list of ServiceMetadata objects from the registry.
        client: Optional DockerClient instance.

    Returns:
        Optional[str]: Matched container name, or None if unresolvable.
    """
    if not query:
        return None

    docker = client or default_client
    running = docker.list_running_containers()
    q_lower = query.lower().strip()

    # 1. Exact match on running container name
    for name in running:
        if name.lower() == q_lower:
            return name

    # 2. Prefix/suffix match on running container name
    for name in running:
        n_lower = name.lower()
        if n_lower.startswith(f"{q_lower}-") or n_lower.endswith(f"-{q_lower}"):
            return name

    # 3. If service registry metadata is provided, resolve service and inspect container_names
    if services:
        matched_svcs, _ = resolve_targets(services, [query])
        if matched_svcs:
            for svc in matched_svcs:
                declared_names = extract_container_names(svc)
                for decl in declared_names:
                    # Check if declared container name is running
                    for name in running:
                        if name.lower() == decl.lower():
                            return name
                # If not running, return declared name if present
                if declared_names:
                    return declared_names[0]

    # 4. Substring match on running container name
    matches = [name for name in running if q_lower in name.lower()]
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        for m in matches:
            m_lower = m.lower()
            if m_lower.startswith(q_lower) or m_lower.endswith(q_lower):
                return m
        return matches[0]

    return None


def stream_logs(
    container_name: str,
    tail: int = 100,
    follow: bool = False,
    timestamps: bool = False,
) -> int:
    """Stream logs from a Docker container to stdout/stderr.

    Args:
        container_name: Name or ID of the container.
        tail: Number of trailing log lines to output.
        follow: Whether to follow/stream output live (-f).
        timestamps: Whether to include container log timestamps (-t).

    Returns:
        int: Process exit code.
    """
    if not container_name:
        return 1

    cmd = ["docker", "logs", f"--tail={tail}"]
    if follow:
        cmd.append("-f")
    if timestamps:
        cmd.append("-t")
    cmd.append(container_name)

    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        logger.error("Failed to stream logs for %s: %s", container_name, e)
        return 1
