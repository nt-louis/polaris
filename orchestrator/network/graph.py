"""Network dependency graph and topological DAG sorter.

Resolves container sidecar network dependencies (network_mode: service:<gateway>
or container:<container_name>) and external bridge network dependencies,
providing deterministic deployment and shutdown orderings.
"""

import logging
import re
from collections import defaultdict, deque

import yaml

from orchestrator.core.models import ServiceMetadata
from orchestrator.docker.readiness import extract_container_names

logger = logging.getLogger(__name__)

NETWORK_MODE_PATTERN = re.compile(
    r"""^\s*network_mode:\s*["']?(?:container:|service:)?([^\s"']+)["']?""",
    re.MULTILINE,
)
EXTERNAL_NETWORK_MAP: dict[str, str] = {
    "vps_b_net": "Utilities/gateway-b",
    "vps_a_net": "Utilities/gateway",
    "stremio_network": "Media/stremio/addons/gateway",
    "network_default": "Network",
}


class CyclicDependencyError(ValueError):
    """Raised when a circular network dependency is detected among services."""
    pass


class NetworkDAG:
    """Dependency graph for container network sidecars and cluster gateways."""

    def __init__(self, all_services: list[ServiceMetadata]):
        self.all_services = all_services
        self._services_by_path: dict[str, ServiceMetadata] = {
            s.rel_dir: s for s in all_services
        }
        self._container_to_service: dict[str, ServiceMetadata] = {}
        self._index_containers()

    def _index_containers(self) -> None:
        """Map declared container names to the owning ServiceMetadata."""
        for s in self.all_services:
            for name in extract_container_names(s):
                self._container_to_service[name.lower()] = s

    def get_service_dependencies(self, service: ServiceMetadata) -> list[ServiceMetadata]:
        """Return direct prerequisite services that must be active before this service starts."""
        deps: list[ServiceMetadata] = []
        compose_path = service.compose_path
        if not compose_path.is_file():
            return deps

        try:
            content = compose_path.read_text(encoding="utf-8", errors="ignore")
            # 1. Inspect network_mode dependencies
            for match in NETWORK_MODE_PATTERN.finditer(content):
                target = match.group(1).strip().lower()
                if target in ("host", "bridge", "none", "default"):
                    continue

                # Check if target matches a declared container name
                provider = self._container_to_service.get(target)
                if provider and provider.rel_dir != service.rel_dir:
                    if provider not in deps:
                        deps.append(provider)

            # 2. Inspect external networks structurally via YAML parser
            try:
                data = yaml.safe_load(content)
                if isinstance(data, dict) and "networks" in data and isinstance(data["networks"], dict):
                    for net_key, net_val in data["networks"].items():
                        if isinstance(net_val, dict) and net_val.get("external"):
                            declared_name = str(net_val.get("name") or net_key).strip()
                            provider_path = EXTERNAL_NETWORK_MAP.get(declared_name)
                            if provider_path:
                                provider = self._services_by_path.get(provider_path)
                                if provider and provider.rel_dir != service.rel_dir and provider not in deps:
                                    deps.append(provider)
            except Exception as yaml_err:
                logger.debug("Failed parsing YAML networks in %s: %s", service.name, yaml_err)

            # 3. Explicit ServiceMetadata.network_dependency field
            if service.network_dependency:
                provider = self._container_to_service.get(service.network_dependency.lower())
                if provider and provider.rel_dir != service.rel_dir and provider not in deps:
                    deps.append(provider)

        except Exception as e:
            logger.debug("Failed to calculate dependencies for %s: %s", service.name, e)

        return deps

    def topological_sort(
        self,
        targets: list[ServiceMetadata],
    ) -> list[ServiceMetadata]:
        """Order a list of target services so that dependencies always precede dependents.

        Ties are broken stably by ServiceTier ascending, then alphabetically by relative path.
        """
        if not targets:
            return []

        target_paths = {s.rel_dir for s in targets}
        target_map = {s.rel_dir: s for s in targets}

        # Build in-degree graph strictly scoped to the target set (and their target dependencies)
        adj_list: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = {s.rel_dir: 0 for s in targets}

        for s in targets:
            deps = self.get_service_dependencies(s)
            for dep in deps:
                if dep.rel_dir in target_paths:
                    adj_list[dep.rel_dir].append(s.rel_dir)
                    in_degree[s.rel_dir] += 1

        # Kahn's algorithm with priority queue tie-breaking (tier, path)
        def sort_key(rel_p: str) -> tuple[int, str]:
            svc = target_map[rel_p]
            return (int(svc.tier), svc.rel_dir)

        zero_in_degree = [p for p, deg in in_degree.items() if deg == 0]
        zero_in_degree.sort(key=sort_key)

        queue = deque(zero_in_degree)
        sorted_paths: list[str] = []

        while queue:
            # Pop smallest element based on priority
            curr = queue.popleft()
            sorted_paths.append(curr)

            # Reduce in-degree for dependents
            newly_zero = []
            for neighbor in adj_list[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    newly_zero.append(neighbor)

            if newly_zero:
                newly_zero.sort(key=sort_key)
                queue.extend(newly_zero)
                # Keep queue ordered
                queue = deque(sorted(queue, key=sort_key))

        # If cyclic or unresolvable dependencies exist, abort with an explicit error
        if len(sorted_paths) < len(targets):
            unresolved = [s.rel_dir for s in targets if s.rel_dir not in sorted_paths]
            raise CyclicDependencyError(
                f"Cyclic or unresolvable network dependency detected among services: {unresolved}"
            )

        return [target_map[p] for p in sorted_paths]
