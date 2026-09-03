"""Immutable data contracts and domain models for orchestrator."""

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from pathlib import Path
from typing import Optional


class ServiceTier(IntEnum):
    """Execution and readiness sequencing tier."""
    GATEWAY = 0      # Network gateways (Gluetun + Tailscale)
    CORE_INFRA = 1   # Auth, SSO, Cloudflare Tunnel, Vaultwarden
    STANDARD = 2     # Default applications
    MONITORING = 3   # Uptime-Kuma, Dozzle


class ContainerStatus(str, Enum):
    """Normalized container runtime lifecycle status."""
    RUNNING = "running"
    EXITED = "exited"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"
    DEAD = "dead"
    UNKNOWN = "unknown"
    NOT_FOUND = "not_found"
    ERROR = "error"


@dataclass(frozen=True)
class NodeMetadata:
    """Immutable contract describing a registered server node."""
    id: str
    name: str
    tailscale_name: Optional[str] = None
    description: Optional[str] = None


@dataclass(frozen=True)
class ServiceMetadata:
    """Immutable contract describing a single managed compose service."""
    name: str
    rel_dir: str
    abs_dir: Path
    compose_file: str = "docker-compose.yml"
    category: str = "Other"
    vps: str = ""                         # Concrete node identifier: "A", "B", etc.
    tier: ServiceTier = ServiceTier.STANDARD
    custom_project_name: Optional[str] = None
    network_dependency: Optional[str] = None
    is_build_heavy: bool = False           # Explicit build indicator (monochrome, fmhy, custom context)
    env_file_required: bool = False
    appdata_paths: list[Path] = field(default_factory=list)

    @property
    def project_name(self) -> Optional[str]:
        """Return explicit custom Compose project name if defined, else None.
        
        When None, Compose uses the default directory basename (e.g. 'jellyfin'),
        preserving existing runtime container names and state without forced recreation.
        """
        return self.custom_project_name

    @property
    def is_gateway(self) -> bool:
        """Return True if service is a gateway tier or sidecar container.
        
        Note: Substring checks are transitional for backwards-compatibility and will
        be fully superseded once all gateway definitions carry explicit tier == ServiceTier.GATEWAY.
        """
        return self.tier == ServiceTier.GATEWAY or "gateway" in self.name or "exit-node" in self.name

    @property
    def compose_path(self) -> Path:
        """Return the absolute path to the docker-compose.yml file."""
        return Path(self.abs_dir) / self.compose_file

    @property
    def is_local_build(self) -> bool:
        """Return True if service is locally built and does not pull from a remote registry."""
        if self.is_build_heavy:
            return True
        if self.compose_path.is_file():
            try:
                content = self.compose_path.read_text(encoding="utf-8")
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("image:") and "local/" in stripped:
                        return True
            except Exception:
                pass
        return False


@dataclass
class ActionContext:
    """Standardized runtime invocation options passed from CLI/TUI to action orchestrators."""
    targets: list[str] = field(default_factory=list)
    vps: Optional[str] = None        # If None, dynamically resolves via state.get_active_vps()
    dry_run: bool = False
    yes: bool = False
    recreate: bool = False
    build: bool = False
    pull: bool = False
    force_gateways: bool = False
    last: bool = False
    json_output: bool = False
    follow: bool = False
    tail: int = 100
    min_age: float = 0.0
    backup_days: int = 7
    resume_from: Optional[str] = None
    check: bool = False
    list_backups: bool = False
    fix: bool = False
    allow_dev: bool = False
    interactive: bool = False
    state: Optional[str] = None
    category: Optional[str] = None
    query: Optional[str] = None
    stream_mode: Optional[str] = None


@dataclass
class ExecutionResult:
    """Standardized result returned by all orchestration operations."""
    service: Optional[ServiceMetadata]
    action: str
    success: bool
    exit_code: int = 0
    message: str = ""
    duration_seconds: float = 0.0

    def __bool__(self) -> bool:
        """Evaluate truthiness based on success status."""
        return bool(self.success)


@dataclass
class ContainerState:
    """Snapshot of a container's runtime state from Docker."""
    container_id: str
    name: str
    status: ContainerStatus
    is_active: bool
    ports: list[str] = field(default_factory=list)
