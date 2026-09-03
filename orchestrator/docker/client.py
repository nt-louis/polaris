"""Typed Docker CLI client wrapper.

Provides type-safe inspection of Docker containers, health status probes,
and lifecycle operations via the Docker CLI.
"""

import json
import logging
import subprocess
from typing import Optional

from orchestrator.core.models import ContainerState, ContainerStatus, ExecutionResult

logger = logging.getLogger(__name__)


class DockerClient:
    """Type-safe interface to Docker daemon via Docker CLI."""

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def is_available(self) -> bool:
        """Check if Docker CLI is installed and the daemon is reachable."""
        try:
            res = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout,
            )
            return res.returncode == 0
        except Exception:
            return False

    def image_exists(self, image_name: str) -> bool:
        """Check if a container image exists in the local Docker image store."""
        if not image_name:
            return False
        try:
            res = subprocess.run(
                ["docker", "image", "inspect", image_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout,
            )
            return res.returncode == 0
        except Exception:
            return False

    def get_container_status(self, container_name: str) -> ContainerStatus:
        """Inspect and return normalized ContainerStatus for a container."""
        if not container_name:
            return ContainerStatus.NOT_FOUND

        try:
            res = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",
                    container_name,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout,
            )
            if res.returncode != 0:
                err = res.stderr.lower()
                if any(p in err for p in ("no such container", "no such object", "error: no such", "not found")):
                    return ContainerStatus.NOT_FOUND
                logger.warning("Docker inspect error for '%s' (exit %d): %s", container_name, res.returncode, res.stderr.strip())
                return ContainerStatus.ERROR

            raw = res.stdout.strip().split("|")
            status_str = raw[0].strip().lower() if len(raw) > 0 else ""
            health_str = raw[1].strip().lower() if len(raw) > 1 else ""

            if health_str == "healthy":
                return ContainerStatus.HEALTHY
            elif health_str == "unhealthy":
                return ContainerStatus.UNHEALTHY
            elif health_str == "starting":
                return ContainerStatus.STARTING

            if status_str == "running":
                return ContainerStatus.RUNNING
            elif status_str in ("exited", "stopped"):
                return ContainerStatus.EXITED
            elif status_str in ("dead", "removing"):
                return ContainerStatus.DEAD

            return ContainerStatus.UNKNOWN
        except Exception as e:
            logger.error("Exception inspecting container '%s': %s", container_name, e)
            return ContainerStatus.ERROR

    def is_container_running(self, container_name: str) -> bool:
        """Return True if the container is currently running or active (including unhealthy)."""
        status = self.get_container_status(container_name)
        return status in (
            ContainerStatus.RUNNING,
            ContainerStatus.HEALTHY,
            ContainerStatus.STARTING,
            ContainerStatus.UNHEALTHY,
        )

    def inspect_container(self, container_name: str) -> Optional[ContainerState]:
        """Fetch complete runtime metadata for a container."""
        if not container_name:
            return None

        try:
            res = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{json .}}",
                    container_name,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout,
            )
            if res.returncode != 0:
                return None

            data = json.loads(res.stdout)
            cid = data.get("Id", "")[:12]
            name = data.get("Name", "").lstrip("/")
            status = self.get_container_status(container_name)
            is_active = status in (
                ContainerStatus.RUNNING,
                ContainerStatus.HEALTHY,
                ContainerStatus.STARTING,
            )

            ports: list[str] = []
            port_bindings = data.get("NetworkSettings", {}).get("Ports", {}) or {}
            for container_p, host_bindings in port_bindings.items():
                if host_bindings:
                    for b in host_bindings:
                        host_ip = b.get("HostIp", "0.0.0.0")
                        host_port = b.get("HostPort", "")
                        ports.append(f"{host_ip}:{host_port}->{container_p}")
                else:
                    ports.append(container_p)

            return ContainerState(
                container_id=cid,
                name=name,
                status=status,
                is_active=is_active,
                ports=ports,
            )
        except Exception as e:
            logger.debug("Failed to inspect container %s: %s", container_name, e)
            return None

    def list_running_containers(self) -> list[str]:
        """Return a list of currently running container names."""
        try:
            res = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout,
            )
            if res.returncode != 0:
                return []
            return [line.strip() for line in res.stdout.splitlines() if line.strip()]
        except Exception:
            return []

    def get_all_containers_info(self) -> list[dict]:
        """Return list of JSON-parsed container details from docker ps."""
        try:
            res = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{json .}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout,
            )
            if res.returncode != 0:
                return []
            containers = []
            for line in res.stdout.splitlines():
                line = line.strip()
                if line:
                    try:
                        containers.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return containers
        except Exception:
            return []

    def stop_containers(self, container_names: list[str], timeout: int = 10) -> ExecutionResult:
        """Stop one or more running containers."""
        if not container_names:
            return ExecutionResult(
                service=None,
                action="stop_containers",
                success=True,
                exit_code=0,
                message="No containers specified to stop.",
            )

        cmd = ["docker", "stop", "-t", str(timeout)] + container_names
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout + 30,
            )
            success = res.returncode == 0
            msg = res.stdout.strip() if success else res.stderr.strip()
            return ExecutionResult(
                service=None,
                action="stop_containers",
                success=success,
                exit_code=res.returncode,
                message=msg,
            )
        except Exception as e:
            return ExecutionResult(
                service=None,
                action="stop_containers",
                success=False,
                exit_code=1,
                message=str(e),
            )


# Default client instance
default_client = DockerClient()
