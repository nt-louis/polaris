"""Docker client, compose execution engine, readiness polling, and log streaming."""

from orchestrator.docker.client import DockerClient, default_client
from orchestrator.docker.compose import ComposeEngine, default_compose_engine
from orchestrator.docker.logs import resolve_container, stream_logs
from orchestrator.docker.readiness import (
    extract_container_names,
    extract_gluetun_container,
    wait_for_container_ready,
    wait_for_gluetun_ready,
    wait_for_service_ready,
)

__all__ = [
    "DockerClient",
    "default_client",
    "ComposeEngine",
    "default_compose_engine",
    "extract_container_names",
    "extract_gluetun_container",
    "wait_for_container_ready",
    "wait_for_gluetun_ready",
    "wait_for_service_ready",
    "resolve_container",
    "stream_logs",
]
