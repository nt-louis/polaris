"""Core system constants and filesystem layout definitions."""

import os
from pathlib import Path


def _resolve_repo_root() -> Path:
    """Resolve the active Polaris repository root.

    Resolution order:
    1. NET_STREAM_ROOT environment variable (if pointing to a valid polaris root).
    2. Parent directory traversal from current working directory (looking for manage.py + orchestrator/).
    3. Source-relative location of this file (orchestrator/core/constants.py -> repo root).
    """
    env_root = os.environ.get("POLARIS_ROOT") or os.environ.get("NET_STREAM_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        if p.is_dir() and (p / "orchestrator").is_dir() and (p / "manage.py").is_file():
            return p

    try:
        cur = Path.cwd().resolve()
        for parent in (cur, *cur.parents):
            if (parent / "manage.py").is_file() and (parent / "orchestrator").is_dir():
                return parent
    except Exception:
        pass

    return Path(__file__).resolve().parents[2]


REPO_ROOT: Path = _resolve_repo_root()

# Directories excluded from filesystem scans and compose discovery
EXCLUDE_DIRS: tuple[str, ...] = (
    "Archived",
    ".git",
    "node_modules",
    ".snapshots",
    "venv",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
)
