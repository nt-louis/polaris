"""3-Tier Target Query Resolution Engine.

Resolves arbitrary CLI and TUI target inputs (short service names, custom project names,
directory paths, or path suffixes) to concrete ServiceMetadata definitions with VPS awareness.
"""

import os
from typing import Optional

from orchestrator.core.models import ServiceMetadata


def resolve_all_services(
    services: list[ServiceMetadata],
    vps: Optional[str] = None,
) -> list[ServiceMetadata]:
    """Return all services from the list, optionally filtered by VPS node."""
    if not vps or vps.upper() == "ALL":
        return list(services)
    target_vps = vps.upper()
    return [s for s in services if s.vps.upper() == target_vps]


def resolve_targets(
    services: list[ServiceMetadata],
    target_queries: list[str],
    vps: Optional[str] = None,
    strict_vps: bool = True,
) -> tuple[list[ServiceMetadata], list[str]]:
    """Resolve a list of target queries to concrete ServiceMetadata objects.

    Matching tiers per query:
    1. Exact relative directory match (e.g. 'Media/local-media/managers/bazarr')
    2. Exact project name or custom project name match (e.g. 'bazarr', 'media-comics-gateway')
    3. Path suffix match (e.g. 'managers/bazarr', 'local-media/gateway')

    Args:
        services: Complete or candidate list of ServiceMetadata objects.
        target_queries: List of query strings provided via CLI arguments or TUI inputs.
        vps: Optional active VPS filter ('A', 'B', etc.).
        strict_vps: If True, queries matching services on other VPS nodes produce fatal errors.
                    If False, mismatched VPS services are filtered out silently without errors.

    Returns:
        tuple[list[ServiceMetadata], list[str]]: (resolved_services, error_messages)
    """
    if not target_queries:
        return [], []

    target_vps = vps.upper() if vps and vps.upper() != "ALL" else None
    resolved_services: list[ServiceMetadata] = []
    errors: list[str] = []
    seen_rel_dirs: set[str] = set()

    for raw_query in target_queries:
        q = raw_query.strip()
        if not q:
            continue

        norm_q = os.path.normpath(q)
        norm_q_lower = norm_q.lower()

        # Tier 1: Exact relative directory path match
        tier1_matches = [
            s for s in services
            if os.path.normpath(s.rel_dir).lower() == norm_q_lower
        ]

        # Tier 2: Exact service name or custom_project_name match
        tier2_matches = []
        if not tier1_matches:
            tier2_matches = [
                s for s in services
                if s.name.lower() == norm_q_lower
                or (s.custom_project_name and s.custom_project_name.lower() == norm_q_lower)
            ]

        # Tier 3: Path suffix match (e.g. 'managers/bazarr')
        tier3_matches = []
        if not tier1_matches and not tier2_matches:
            tier3_matches = [
                s for s in services
                if os.path.normpath(s.rel_dir).lower().endswith(os.sep + norm_q_lower)
                or os.path.normpath(s.rel_dir).lower().endswith("/" + norm_q_lower)
            ]

        candidates = tier1_matches or tier2_matches or tier3_matches

        # Handle VPS filtering and cross-VPS assignment detection
        if candidates and target_vps:
            vps_matching = [s for s in candidates if s.vps.upper() == target_vps]
            if vps_matching:
                candidates = vps_matching
            else:
                if strict_vps:
                    other_vps = ", ".join(sorted({s.vps for s in candidates}))
                    errors.append(
                        f"Service '{raw_query}' is assigned to VPS {other_vps}, but active filter is VPS {target_vps}."
                    )
                candidates = []

        if not candidates and not (target_vps and any(raw_query in e for e in errors)):
            # Check if query matches a project on a different VPS
            all_vps_matches = [
                s for s in services
                if s.name.lower() == norm_q_lower
                or (s.custom_project_name and s.custom_project_name.lower() == norm_q_lower)
                or os.path.normpath(s.rel_dir).lower() == norm_q_lower
                or os.path.normpath(s.rel_dir).lower().endswith(os.sep + norm_q_lower)
                or os.path.normpath(s.rel_dir).lower().endswith("/" + norm_q_lower)
            ]
            if all_vps_matches and target_vps:
                if strict_vps:
                    other_vps = ", ".join(sorted({s.vps for s in all_vps_matches}))
                    errors.append(
                        f"Service '{raw_query}' is assigned to VPS {other_vps}, but active filter is VPS {target_vps}."
                    )
            elif not any(raw_query in err for err in errors):
                errors.append(f"No compose project matching '{raw_query}' found in repository.")
        elif len(candidates) > 1:
            matched_dirs = ", ".join(sorted(s.rel_dir for s in candidates))
            errors.append(
                f"Ambiguous service target '{raw_query}'. Matches multiple projects: {matched_dirs}. "
                f"Please specify a more specific directory path (e.g. {candidates[0].rel_dir})."
            )
        elif len(candidates) == 1:
            matched_svc = candidates[0]
            if matched_svc.rel_dir not in seen_rel_dirs:
                seen_rel_dirs.add(matched_svc.rel_dir)
                resolved_services.append(matched_svc)

    return resolved_services, errors
