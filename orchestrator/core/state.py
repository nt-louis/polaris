"""Active VPS node context and deploy selection state persistence."""

import logging
import os
from pathlib import Path
from typing import Optional

from orchestrator.core.constants import REPO_ROOT
from orchestrator.core.models import ServiceMetadata
from orchestrator.registry.manifest import (
    get_default_node_id,
    get_node,
    get_valid_node_ids,
)

logger = logging.getLogger(__name__)

ACTIVE_VPS_FILE = REPO_ROOT / ".active_vps"
LAST_DEPLOY_FILE = REPO_ROOT / ".last_deploy"
LOG_STREAM_MODE_FILE = REPO_ROOT / ".log_stream_mode"


def get_log_stream_path(vps: Optional[str] = None) -> Path:
    """Return the path of the log stream mode state file for the given VPS."""
    if vps:
        node = get_node(vps)
        node_id = node.id.lower() if node else vps.strip().lower()
        return REPO_ROOT / f".log_stream_mode_{node_id}"
    return LOG_STREAM_MODE_FILE


def get_log_stream_mode(
    vps: Optional[str] = None,
    default: str = "native",
    prompt_if_missing: bool = False,
) -> str:
    """Retrieve log stream mode ('native' or 'piped') from env, persistent node file, or default.

    If the preference file does not exist and prompt_if_missing is True in an interactive TTY,
    prompts the user once to select their preference and persists it for that node.
    """
    import sys

    env_mode = os.environ.get("POLARIS_LOG_MODE") or os.environ.get("NET_STREAM_LOG_MODE", "").strip().lower()
    if env_mode in ("native", "piped"):
        return env_mode

    path = get_log_stream_path(vps)
    if path.is_file():
        try:
            content = path.read_text(encoding="utf-8").strip().lower()
            if content in ("native", "piped"):
                return content
            logger.warning("Invalid log stream mode '%s' in %s; ignoring.", content, path)
        except OSError as e:
            logger.warning("Could not read log stream mode file %s: %s", path, e)

    # Check global file as secondary fallback
    if vps and LOG_STREAM_MODE_FILE.is_file():
        try:
            content = LOG_STREAM_MODE_FILE.read_text(encoding="utf-8").strip().lower()
            if content in ("native", "piped"):
                return content
        except OSError:
            pass

    if prompt_if_missing and sys.stdin.isatty():
        from orchestrator.core.guards import is_test_environment

        if is_test_environment():
            return default

        try:
            node_label = f" for Node {vps}" if vps else ""
            print(f"\n\033[1;36m[LOG STREAM MODE] Select Docker Compose log streaming preference{node_label}:\033[0m")
            print("  1) Native TTY (Default - Real-time progress bars, colors, interactive updates)")
            print("  2) Piped Line Capture (Buffered stdout streaming)")
            choice = input("\033[1;33mChoose log streaming mode [1/2] (Default: 1): \033[0m").strip()
            mode = "piped" if choice == "2" else "native"
            set_log_stream_mode(mode, vps=vps)
            print(f"\033[1;32m✓ Saved log stream preference: '{mode}'\033[0m\n")
            return mode
        except (KeyboardInterrupt, EOFError):
            pass

    return default


def set_log_stream_mode(mode: str, vps: Optional[str] = None) -> None:
    """Persist the log stream mode preference ('native' or 'piped') scoped to a node."""
    clean_mode = mode.strip().lower()
    if clean_mode not in ("native", "piped"):
        raise ValueError(f"Invalid log stream mode '{mode}'. Must be 'native' or 'piped'.")

    path = get_log_stream_path(vps)
    try:
        path.write_text(f"{clean_mode}\n", encoding="utf-8")
    except OSError as e:
        logger.error("Could not write log stream mode file %s: %s", path, e)
        raise


def get_active_vps(default: Optional[str] = None) -> str:
    """Retrieve active VPS node context from env, persistent state file, or declarative defaults.

    Validates all candidate node IDs against the declarative registry.
    """
    env_vps = os.environ.get("POLARIS_VPS") or os.environ.get("NET_STREAM_VPS", "").strip().upper()
    if env_vps:
        node = get_node(env_vps)
        if node:
            return node.id
        logger.warning("Invalid NET_STREAM_VPS environment value '%s' (not registered in services.yaml); ignoring.", env_vps)

    if ACTIVE_VPS_FILE.is_file():
        try:
            content = ACTIVE_VPS_FILE.read_text(encoding="utf-8").strip().upper()
            if content:
                node = get_node(content)
                if node:
                    return node.id
                logger.warning("Invalid active VPS file content '%s' in %s; ignoring.", content, ACTIVE_VPS_FILE)
        except OSError as e:
            logger.warning("Could not read active VPS state file %s: %s", ACTIVE_VPS_FILE, e)

    if default:
        node = get_node(default)
        if node:
            return node.id
        logger.warning("Invalid default VPS node ID '%s'; ignoring.", default)

    dyn_default = get_default_node_id()
    if dyn_default:
        node = get_node(dyn_default)
        if node:
            return node.id

    valid = get_valid_node_ids()
    if valid:
        return sorted(valid)[0]

    raise ValueError("No valid VPS node registered in services.yaml.")


def set_active_vps(vps: str) -> None:
    """Persist the active VPS node context after validating against the registry."""
    clean_vps = vps.strip().upper()
    node = get_node(clean_vps)
    if not node:
        valid_nodes = get_valid_node_ids()
        raise ValueError(
            f"Invalid VPS node ID '{vps}'. Must be one of: {', '.join(sorted(valid_nodes))}."
        )

    try:
        ACTIVE_VPS_FILE.write_text(f"{node.id}\n", encoding="utf-8")
    except OSError as e:
        logger.error("Could not write active VPS state file %s: %s", ACTIVE_VPS_FILE, e)
        raise


def get_last_deploy_path(vps: Optional[str] = None) -> Path:
    """Return the path of the last-deploy state file for the given VPS."""
    if vps:
        node = get_node(vps)
        node_id = node.id.lower() if node else vps.strip().lower()
        return REPO_ROOT / f".last_deploy_{node_id}"
    return LAST_DEPLOY_FILE


def load_last_deploy_services(
    services: list[ServiceMetadata],
    vps: Optional[str] = None,
) -> list[ServiceMetadata]:
    """Load previously saved services from the state file matching the given pool."""
    path = get_last_deploy_path(vps)
    if not path.is_file():
        return []

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        saved_keys = {line.strip() for line in lines if line.strip()}
        # Match against either relative directory path or short service name
        return [
            s for s in services
            if s.rel_dir in saved_keys or s.name in saved_keys
        ]
    except OSError as e:
        logger.warning("Could not load last deploy state from %s: %s", path, e)
        return []


def save_last_deploy_services(
    selected_services: list[ServiceMetadata],
    vps: Optional[str] = None,
) -> None:
    """Persist the selected services to the state file."""
    path = get_last_deploy_path(vps)
    try:
        content = "\n".join(s.rel_dir for s in selected_services) + ("\n" if selected_services else "")
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        logger.warning("Could not save last deploy state to %s: %s", path, e)
