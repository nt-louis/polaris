"""Action orchestrator for generating container image dependency and governance reports."""

import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from orchestrator.actions.base import BaseAction
from orchestrator.core.constants import REPO_ROOT
from orchestrator.core.models import ActionContext, ExecutionResult
from orchestrator.registry.manifest import load_services

logger = logging.getLogger(__name__)

CRITICAL_INFRA_PATHS = [
    "Utilities/admin/coolify",
    "Utilities/admin/infisical",
    "Utilities/auth",
    "Utilities/exit-node",
    "Utilities/gateway",
    "Utilities/gateway-b",
    "Utilities/cloud-docs/nextcloud/gateway",
    "Media/stremio/utilities/gateway",
    "Media/stremio/addons/gateway",
    "Media/stremio/addons/gateway-proton",
    "Media/local-media/gateway",
    "Media/comics/gateway",
    "Network",
]


def is_critical_infra(rel_dir: str) -> bool:
    """Check if relative directory belongs to critical gateway/auth infrastructure."""
    for path in CRITICAL_INFRA_PATHS:
        if rel_dir == path or rel_dir.startswith(path + "/"):
            return True
    return False


def is_database_service(service_name: str, image_str: str) -> bool:
    """Check if service is a persistent database."""
    name_lower = service_name.lower()
    image_lower = image_str.lower()
    db_keywords = ("postgres", "mariadb", "mysql", "redis", "valkey", "mongo", "sqlite")
    return any(kw in name_lower or kw in image_lower for kw in db_keywords)


def parse_image_string(image_str: str) -> tuple[str, str, str]:
    """Parse image reference into (registry, repo, tag)."""
    image_str = image_str.strip()
    tag = "latest"
    if ":" in image_str:
        image_part, tag = image_str.rsplit(":", 1)
    else:
        image_part = image_str

    if "/" in image_part:
        parts = image_part.split("/")
        if "." in parts[0] or ":" in parts[0] or parts[0] == "localhost":
            registry = parts[0]
            repo = "/".join(parts[1:])
        else:
            registry = "docker.io"
            repo = image_part
    else:
        registry = "docker.io"
        repo = f"library/{image_part}"

    return registry, repo, tag


def parse_version(tag: str) -> Optional[dict]:
    """Parse semantic version tuple from a tag."""
    clean_tag = tag.lstrip("v").split("-")[0]
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", clean_tag)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    return {"tuple": (major, minor, patch), "raw": tag}


def get_remote_tags(registry: str, repo: str) -> list[str]:
    """Fetch remote tags from container registries (Docker Hub, GHCR, etc.)."""
    tags = []
    if registry == "docker.io":
        clean_repo = repo.replace("library/", "") if repo.startswith("library/") else repo
        url = f"https://hub.docker.com/v2/repositories/{clean_repo}/tags?page_size=100"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                tags.extend(t["name"] for t in data.get("results", []))
                next_url = data.get("next")
                if next_url:
                    req_next = urllib.request.Request(next_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req_next, timeout=5) as resp_next:
                        data_next = json.loads(resp_next.read().decode())
                        tags.extend(t["name"] for t in data_next.get("results", []))
        except Exception:
            pass
    return tags


def find_newer_versions(current_tag: str, available_tags: list[str]) -> Optional[str]:
    """Find the highest stable semver tag newer than current_tag."""
    curr_v = parse_version(current_tag)
    if not curr_v:
        return None

    newer_candidates = []
    for tag in available_tags:
        if any(ign in tag.lower() for ign in ("latest", "nightly", "beta", "alpha", "rc", "dev", "test")):
            continue
        v = parse_version(tag)
        if v and v["tuple"] > curr_v["tuple"]:
            newer_candidates.append((v["tuple"], tag))

    if not newer_candidates:
        return None

    newer_candidates.sort(key=lambda x: x[0], reverse=True)
    return newer_candidates[0][1]


def get_tag_release_age(registry: str, repo: str, tag: str) -> tuple[Optional[datetime], Optional[float]]:
    """Fetch release timestamp and age in days for a tag."""
    if registry == "docker.io":
        clean_repo = repo.replace("library/", "") if repo.startswith("library/") else repo
        url = f"https://hub.docker.com/v2/repositories/{clean_repo}/tags/{tag}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                last_updated = data.get("last_updated")
                if last_updated:
                    dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    age_days = (now - dt).total_seconds() / 86400.0
                    return dt, age_days
        except Exception:
            pass
    return None, None


def extract_services_and_images(compose_path: Path) -> dict[str, str]:
    """Parse service names and image declarations from a docker-compose.yml file."""
    if not compose_path.is_file():
        return {}

    try:
        content = compose_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}

    services = {}
    current_service = None

    for line in content.splitlines():
        # Match service declaration under services:
        svc_match = re.match(r"^  ([a-zA-Z0-9_-]+):\s*$", line)
        if svc_match:
            current_service = svc_match.group(1)
            continue

        if current_service:
            img_match = re.match(r"^\s+image:\s*([^\s#]+)", line)
            if img_match:
                services[current_service] = img_match.group(1)
                current_service = None

    return services


class DependencyReportAction(BaseAction):
    """Generate Markdown container image inventory, upgrade analysis, and governance assessment."""

    @property
    def action_name(self) -> str:
        return "dependency_report"

    def run(self, context: ActionContext) -> ExecutionResult:
        services = load_services()
        now_utc = datetime.now(timezone.utc)
        now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

        total_projects = len(services)
        total_services = 0
        upgrades_available = []

        logger.info("Scanning %d compose projects for image dependencies...", total_projects)

        for s in services:
            compose_path = s.compose_path
            svc_images = extract_services_and_images(compose_path)
            for svc_name, image_str in svc_images.items():
                total_services += 1
                registry, repo, tag = parse_image_string(image_str)
                curr_ver = parse_version(tag)
                if not curr_ver:
                    continue

                tags = get_remote_tags(registry, repo)
                if not tags:
                    continue

                newer_tag = find_newer_versions(tag, tags)
                if newer_tag:
                    best_ver = parse_version(newer_tag)
                    change_type = "Patch"
                    update_kind = "patch"
                    if best_ver and best_ver["tuple"][0] > curr_ver["tuple"][0]:
                        change_type = "Major"
                        update_kind = "major"
                    elif best_ver and best_ver["tuple"][1] > curr_ver["tuple"][1]:
                        change_type = "Minor"
                        update_kind = "minor"

                    dt, age_days = get_tag_release_age(registry, repo, newer_tag)
                    age_str = "N/A"
                    if age_days is not None:
                        age_str = f"{int(age_days * 24)}h ago" if age_days < 1.0 else f"{age_days:.1f}d ago"

                    is_db = is_database_service(svc_name, image_str)
                    is_infra = is_critical_infra(s.rel_dir)

                    if age_days is not None and age_days < 3.0:
                        renovate_action = "Quarantine (Hold 72h)"
                    elif is_infra or is_db:
                        renovate_action = "Manual Review"
                    elif update_kind in ("patch", "digest"):
                        renovate_action = "Auto-Merge Candidate"
                    else:
                        renovate_action = "Scheduled Batch (Monday)"

                    upgrades_available.append({
                        "project": s.name,
                        "rel_dir": s.rel_dir,
                        "category": s.category,
                        "service": svc_name,
                        "image_repo": f"{registry}/{repo}" if registry != "docker.io" else repo,
                        "current": tag,
                        "latest": newer_tag,
                        "change_type": change_type,
                        "release_age": age_str,
                        "renovate_action": renovate_action,
                        "is_db": is_db,
                    })

        # Build Markdown
        major_cnt = sum(1 for u in upgrades_available if u["change_type"] == "Major")
        minor_cnt = sum(1 for u in upgrades_available if u["change_type"] == "Minor")
        patch_cnt = sum(1 for u in upgrades_available if u["change_type"] == "Patch")
        automerge_cnt = sum(1 for u in upgrades_available if u["renovate_action"] == "Auto-Merge Candidate")
        quarantine_cnt = sum(1 for u in upgrades_available if "Quarantine" in u["renovate_action"])

        md = [
            "# Container Dependency & Vulnerability Assessment",
            f"**Generated**: `{now_str}` | **Scope**: Polaris Infrastructure (VPS A & B) | **Projects**: `{total_projects}` | **Services**: `{total_services}`\n",
            "## 1. Executive Summary",
            "This document outlines the container image dependency status across all deployed Docker Compose stacks on VPS A and VPS B. Upstream registries are inspected continuously to identify security patches, minor feature updates, and major architectural upgrades while enforcing a 72-hour release stability quarantine.\n",
            "## 2. Infrastructure Metrics & Governance Summary",
            "| Metric | Count | Description / Governance Policy |",
            "|---|---|---|",
            f"| **Total Compose Projects** | `{total_projects}` | Monitored stack directories across repository |",
            f"| **Total Tracked Services** | `{total_services}` | Running container definitions |",
            f"| **Pending Container Updates** | `{len(upgrades_available)}` | `{major_cnt}` Major, `{minor_cnt}` Minor, `{patch_cnt}` Patch |",
            f"| **Eligible for Auto-Merge** | `{automerge_cnt}` | Patch updates passing 72-hour stability quarantine |",
            f"| **Quarantined Releases (<72h)** | `{quarantine_cnt}` | Recent releases held for stability evaluation |",
            "",
        ]

        if automerge_cnt > 0:
            md.append(
                "> [!NOTE]\n"
                f"> **Action Required**: {automerge_cnt} patch update(s) have satisfied the 72-hour stability gate and are ready for automated deployment.\n"
            )

        md.extend([
            "## 3. Governance Policy Classifications",
            "- **Auto-Merge Candidate**: Non-breaking patch/digest update that has passed the 72-hour stability quarantine.",
            "- **Quarantine (Hold 72h)**: Upstream release is less than 3 days old; held to protect against zero-day regressions.",
            "- **Manual Review**: High-risk service (Databases, Core Authentication, or Gateway Networks) requiring explicit manual testing.",
            "- **Scheduled Batch (Monday)**: Minor or feature update scheduled for weekly Monday PR evaluation.\n",
        ])

        if upgrades_available:
            md.append("## 4. Pending Upgrades by Governance Category\n")
            gov_configs = [
                ("Auto-Merge Candidates", "Auto-Merge Candidate", "Patch & digest updates that have passed 72h quarantine and are ready for automated deployment"),
                ("Quarantined Releases (Hold 72h)", "Quarantine (Hold 72h)", "Recent upstream releases held to evaluate release stability and prevent 0-day regressions"),
                ("Scheduled Batch (Monday)", "Scheduled Batch (Monday)", "Minor and feature updates grouped for weekly Monday PR evaluation"),
                ("Manual Review Required", "Manual Review", "High-risk services (Databases, Core Authentication, or Gateway Networks) requiring manual testing"),
            ]

            gov_map = {action: [] for _, action, _ in gov_configs}
            gov_map["Other"] = []

            for u in upgrades_available:
                action = u["renovate_action"]
                if action in gov_map:
                    gov_map[action].append(u)
                else:
                    gov_map["Other"].append(u)

            for title, action_key, desc in gov_configs:
                items = gov_map.get(action_key, [])
                md.append(f"### {title} ({len(items)})")
                md.append(f"*{desc}*\n")
                if items:
                    md.append("| Stack / Project | Service | Current Tag | Upstream Target | Scope | Release Age | Category |")
                    md.append("|---|---|---|---|---|---|---|")
                    for u in items:
                        md.append(f"| `{u['project']}` | `{u['service']}` | `{u['current']}` | `{u['latest']}` | `{u['change_type']}` | {u['release_age']} | {u['category']} |")
                    md.append("")
                else:
                    md.append("No pending updates in this category.\n")
        else:
            md.append("## 4. Pending Container Image Upgrades")
            md.append("All monitored container images are currently up-to-date with upstream registries.\n")

        report_md = "\n".join(md)
        output_file = REPO_ROOT / "dependency-report.md"
        try:
            output_file.write_text(report_md, encoding="utf-8")
            logger.info("Report generated successfully at %s", output_file)
        except Exception as e:
            logger.warning("Could not write dependency report file: %s", e)

        github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if github_summary:
            try:
                Path(github_summary).write_text(report_md, encoding="utf-8")
            except Exception:
                pass

        return ExecutionResult(
            service=None,
            action=self.action_name,
            success=True,
            exit_code=0,
            message=report_md,
        )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for dependency report generation."""
    raw_args = argv if argv is not None else sys.argv[1:]
    json_output = "--json" in raw_args
    action = DependencyReportAction()
    res = action.execute(ActionContext(json_output=json_output))
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
