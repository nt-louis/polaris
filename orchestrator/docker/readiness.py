"""Container health probes and readiness polling engine.

Monitors Docker container lifecycle transitions (starting -> running/healthy)
and provides fail-fast detection on container exit or unhealthy states.
"""

import logging
import re
import time
from typing import Optional

from orchestrator.core.models import ContainerStatus, ServiceMetadata
from orchestrator.docker.client import DockerClient, default_client

logger = logging.getLogger(__name__)

CONTAINER_NAME_PATTERN = re.compile(r"^\s*container_name:\s*([^\s#]+)", re.MULTILINE)
GLUETUN_CONTAINER_PATTERN = re.compile(r"^\s*container_name:\s*([^\s#]*gluetun[^\s#]*)", re.MULTILINE)


def extract_container_names(service: ServiceMetadata) -> list[str]:
    """Parse a compose file to find all declared container_name values."""
    path = service.compose_path
    if not path.is_file():
        return []

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        return CONTAINER_NAME_PATTERN.findall(content)
    except Exception as e:
        logger.debug("Failed to extract container names from %s: %s", path, e)
        return []


def extract_gluetun_container(service: ServiceMetadata) -> Optional[str]:
    """Parse a compose file to extract the Gluetun VPN container name if present."""
    path = service.compose_path
    if not path.is_file():
        return None

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        match = GLUETUN_CONTAINER_PATTERN.search(content)
        return match.group(1) if match else None
    except Exception as e:
        logger.debug("Failed to extract gluetun container from %s: %s", path, e)
        return None


def wait_for_container_ready(
    container_name: str,
    timeout: int = 120,
    interval: float = 2.0,
    client: Optional[DockerClient] = None,
) -> bool:
    """Poll a container until it reaches a running/healthy state or fails.

    Args:
        container_name: Name of the container to monitor.
        timeout: Maximum seconds to wait before giving up.
        interval: Polling frequency in seconds.
        client: DockerClient instance to use (defaults to default_client).

    Returns:
        bool: True if container reached RUNNING or HEALTHY status, False otherwise.
    """
    if not container_name:
        return False

    docker = client or default_client
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        status = docker.get_container_status(container_name)

        if status in (ContainerStatus.RUNNING, ContainerStatus.HEALTHY):
            return True

        if status in (ContainerStatus.DEAD, ContainerStatus.EXITED, ContainerStatus.UNHEALTHY):
            logger.warning(
                "Container '%s' entered terminal state '%s' during readiness check.",
                container_name,
                status.value,
            )
            return False

        time.sleep(interval)

    logger.warning("Timed out waiting for container '%s' to become ready (%ds).", container_name, timeout)
    return False


def wait_for_service_ready(
    service: ServiceMetadata,
    timeout: int = 120,
    interval: float = 2.0,
    client: Optional[DockerClient] = None,
) -> bool:
    """Wait for all explicit containers defined in a service's compose file to become ready."""
    container_names = extract_container_names(service)
    if not container_names:
        # No explicit container_names; allow short settle time
        time.sleep(min(3.0, float(timeout)))
        return True

    # If this is a gateway with Gluetun, prioritize the Gluetun container
    gluetun_c = extract_gluetun_container(service)
    if gluetun_c:
        if not wait_for_container_ready(gluetun_c, timeout=timeout, interval=interval, client=client):
            return False

    for name in container_names:
        if name == gluetun_c:
            continue
        if not wait_for_container_ready(name, timeout=timeout, interval=interval, client=client):
            return False

    return True


def wait_for_gluetun_ready(
    service: ServiceMetadata,
    timeout: int = 120,
    interval: float = 2.0,
    client: Optional[DockerClient] = None,
) -> bool:
    """Wait for Gluetun VPN container in a gateway service to reach a healthy/running state."""
    gluetun_c = extract_gluetun_container(service)
    if gluetun_c:
        return wait_for_container_ready(gluetun_c, timeout=timeout, interval=interval, client=client)
    return wait_for_service_ready(service, timeout=timeout, interval=interval, client=client)
