"""Declarative manifest loader and schema validator.

Zero-dependency implementation (stdlib + PyYAML only) suitable for lightweight
CI environments, compose validators, and runtime orchestrator commands.
"""

from pathlib import Path
from typing import Any, Optional

import yaml

from orchestrator.core.constants import REPO_ROOT
from orchestrator.core.models import NodeMetadata, ServiceMetadata, ServiceTier

DEFAULT_MANIFEST_PATH: Path = REPO_ROOT / "orchestrator" / "registry" / "services.yaml"


class ManifestValidationError(ValueError):
    """Raised when services.yaml fails schema validation."""
    pass


def load_manifest_raw(manifest_path: Optional[Path] = None) -> dict[str, Any]:
    """Read and parse the raw YAML dictionary from services.yaml."""
    path = manifest_path or DEFAULT_MANIFEST_PATH
    if not path.is_file():
        raise FileNotFoundError(f"Services manifest not found at: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ManifestValidationError(f"Root of manifest must be a mapping, got {type(data).__name__}")

    return data


def validate_manifest(data: dict[str, Any]) -> list[str]:
    """Validate raw manifest data against the schema specification.

    Returns:
        list[str]: A list of human-readable error descriptions. Empty if valid.
    """
    errors: list[str] = []

    # Schema version
    version = data.get("schema_version")
    if version != 1:
        errors.append(f"Unsupported schema_version: {version!r} (expected 1)")

    # Nodes
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append("'nodes' must be a non-empty list of node definitions")
        valid_node_ids: set[str] = set()
    else:
        valid_node_ids = set()
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                errors.append(f"Node at index {idx} must be a dictionary")
                continue
            node_id = node.get("id")
            if not node_id or not isinstance(node_id, str):
                errors.append(f"Node at index {idx} missing required string 'id'")
            else:
                valid_node_ids.add(node_id)
            if not node.get("name") or not isinstance(node["name"], str):
                errors.append(f"Node at index {idx} missing required string 'name'")

    # Services
    services = data.get("services")
    if not isinstance(services, list) or not services:
        errors.append("'services' must be a non-empty list of service definitions")
    else:
        seen_paths: set[str] = set()
        for idx, svc in enumerate(services):
            if not isinstance(svc, dict):
                errors.append(f"Service at index {idx} must be a dictionary")
                continue

            svc_name = svc.get("name")
            if not svc_name or not isinstance(svc_name, str):
                errors.append(f"Service at index {idx} missing required string 'name'")
            # Note: Multiple services sharing the same name (e.g. 'gateway' in different stacks)
            # is intentional and legacy-compatible; uniqueness is enforced on path, while query
            # ambiguity is resolved via the 3-tier target resolver.

            svc_path = svc.get("path")
            if not svc_path or not isinstance(svc_path, str):
                errors.append(f"Service '{svc_name or idx}' missing required string 'path'")
            else:
                norm_path = str(Path(svc_path))
                if norm_path in seen_paths:
                    errors.append(f"Duplicate service path detected: '{norm_path}'")
                seen_paths.add(norm_path)

            svc_vps = svc.get("vps", data.get("defaults", {}).get("vps", "A"))
            if valid_node_ids and svc_vps not in valid_node_ids:
                errors.append(
                    f"Service '{svc_name}' references unregistered node '{svc_vps}'. "
                    f"Registered nodes: {sorted(valid_node_ids)}"
                )

            svc_tier = svc.get("tier", data.get("defaults", {}).get("tier", 2))
            if not isinstance(svc_tier, int) or svc_tier not in (0, 1, 2, 3):
                errors.append(f"Service '{svc_name}' invalid tier: {svc_tier!r} (must be 0, 1, 2, or 3)")

    return errors


def load_services(
    manifest_path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    vps: Optional[str] = None,
) -> list[ServiceMetadata]:
    """Load and validate services.yaml, returning typed ServiceMetadata instances."""
    data = load_manifest_raw(manifest_path)
    errors = validate_manifest(data)
    if errors:
        raise ManifestValidationError(
            f"Failed to validate manifest ({len(errors)} error(s)):\n" + "\n".join(f"  - {e}" for e in errors)
        )

    root = repo_root or REPO_ROOT
    defaults = data.get("defaults", {})
    default_compose = defaults.get("compose_file", "docker-compose.yml")
    default_vps = defaults.get("vps", "")
    default_tier = defaults.get("tier", 2)

    services_list: list[ServiceMetadata] = []

    for svc in data.get("services", []):
        rel_dir = str(Path(svc["path"]))
        abs_dir = root / rel_dir

        raw_tier = svc.get("tier", default_tier)
        tier = ServiceTier(raw_tier)

        metadata = ServiceMetadata(
            name=svc["name"],
            rel_dir=rel_dir,
            abs_dir=abs_dir,
            compose_file=svc.get("compose_file", default_compose),
            category=svc.get("category", "Other"),
            vps=svc.get("vps", default_vps),
            tier=tier,
            custom_project_name=svc.get("custom_project"),
            network_dependency=svc.get("network_dependency"),
            is_build_heavy=svc.get("is_build_heavy", False),
            env_file_required=svc.get("env_file_required", False),
        )
        services_list.append(metadata)

    if vps and vps.strip().upper() != "ALL":
        target = vps.strip().upper()
        services_list = [s for s in services_list if s.vps.upper() == target]

    return services_list


def get_registered_nodes(manifest_path: Optional[Path] = None) -> list[NodeMetadata]:
    """Return the list of node definitions registered in services.yaml as NodeMetadata."""
    try:
        data = load_manifest_raw(manifest_path)
        raw_nodes = data.get("nodes", [])
        nodes: list[NodeMetadata] = []
        for n in raw_nodes:
            if isinstance(n, dict) and "id" in n and "name" in n:
                nodes.append(
                    NodeMetadata(
                        id=str(n["id"]).strip().upper(),
                        name=str(n["name"]).strip(),
                        tailscale_name=str(n["tailscale_name"]).strip() if n.get("tailscale_name") else None,
                        description=str(n["description"]).strip() if n.get("description") else None,
                    )
                )
        return nodes
    except Exception:
        return []


def get_node(node_id: str, manifest_path: Optional[Path] = None) -> Optional[NodeMetadata]:
    """Retrieve declarative NodeMetadata for a specific node ID."""
    target_id = node_id.strip().upper()
    for node in get_registered_nodes(manifest_path):
        if node.id == target_id:
            return node
    return None


def get_default_node_id(manifest_path: Optional[Path] = None) -> str:
    """Return the default node ID declared in services.yaml defaults or the first registered node."""
    try:
        data = load_manifest_raw(manifest_path)
        defaults = data.get("defaults", {})
        default_vps = defaults.get("vps")
        if default_vps and isinstance(default_vps, str):
            return default_vps.strip().upper()
        nodes = get_registered_nodes(manifest_path)
        if nodes:
            return nodes[0].id
    except Exception:
        pass
    return ""


def get_valid_node_ids(manifest_path: Optional[Path] = None) -> set[str]:
    """Return the set of valid uppercase node IDs declared in services.yaml."""
    return {node.id for node in get_registered_nodes(manifest_path)}


def get_node_tailscale_name(node_id: str, manifest_path: Optional[Path] = None) -> Optional[str]:
    """Return the configured Tailscale hostname for a given node ID from services.yaml."""
    node = get_node(node_id, manifest_path)
    return node.tailscale_name if node else None
