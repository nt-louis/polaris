"""Orchestrator service registry, declarative manifest loader, and query resolver."""

from orchestrator.registry.discovery import (
    ACTIVE_COMPOSE_FILENAMES,
    detect_manifest_drift,
    discover_appdata_paths,
)
from orchestrator.registry.manifest import (
    DEFAULT_MANIFEST_PATH,
    ManifestValidationError,
    get_default_node_id,
    get_node,
    get_node_tailscale_name,
    get_registered_nodes,
    get_valid_node_ids,
    load_manifest_raw,
    load_services,
    validate_manifest,
)
from orchestrator.registry.resolver import resolve_all_services, resolve_targets

__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "ACTIVE_COMPOSE_FILENAMES",
    "ManifestValidationError",
    "load_manifest_raw",
    "validate_manifest",
    "load_services",
    "get_registered_nodes",
    "get_node",
    "get_default_node_id",
    "get_valid_node_ids",
    "get_node_tailscale_name",
    "resolve_targets",
    "resolve_all_services",
    "discover_appdata_paths",
    "detect_manifest_drift",
]
