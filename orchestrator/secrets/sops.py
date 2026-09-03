"""SOPS Age key resolution and environment setup.

Locates SOPS age private keys across standard directories, repository root,
and user configuration paths, configuring SOPS_AGE_KEY_FILE without downloading binaries.
"""

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from orchestrator.core.constants import REPO_ROOT

logger = logging.getLogger(__name__)


def find_sops_binary(repo_root: Optional[Path] = None) -> Optional[str]:
    """Check system PATH and repo bin/ directory for sops binary."""
    system_path = shutil.which("sops")
    if system_path:
        return system_path

    root = repo_root or REPO_ROOT
    local_name = "sops.exe" if sys.platform.startswith("win") else "sops"
    local_path = root / "bin" / local_name
    if local_path.is_file():
        if sys.platform.startswith("win") or os.access(str(local_path), os.X_OK):
            return str(local_path)

    return None


def is_sops_available(repo_root: Optional[Path] = None) -> bool:
    """Return True if sops binary is installed and executable."""
    return find_sops_binary(repo_root) is not None


def setup_age_key_env(repo_root: Optional[Path] = None) -> bool:
    """Ensure SOPS_AGE_KEY_FILE is set and points to an existing key file.

    Search order:
    1. Existing $SOPS_AGE_KEY_FILE if valid.
    2. keys.txt in repository root.
    3. ~/.config/sops/age/keys.txt.
    4. Repo owner's ~/.config/sops/age/keys.txt when running as root.

    Returns:
        bool: True if key file found and environment variable configured.
    """
    root = repo_root or REPO_ROOT

    # 1. Existing environment variable
    existing = os.environ.get("SOPS_AGE_KEY_FILE")
    if existing and os.path.isfile(existing):
        return True

    # 2. keys.txt in repo root
    repo_keys = root / "keys.txt"
    if repo_keys.is_file():
        os.environ["SOPS_AGE_KEY_FILE"] = str(repo_keys)
        return True

    # 3. User config directory
    home_keys = Path.home() / ".config" / "sops" / "age" / "keys.txt"
    if home_keys.is_file():
        os.environ["SOPS_AGE_KEY_FILE"] = str(home_keys)
        return True

    # 4. Fallback for root execution -> repo owner's home
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        try:
            import pwd

            repo_uid = os.stat(str(root)).st_uid
            owner_home = Path(pwd.getpwuid(repo_uid).pw_dir)
            owner_keys = owner_home / ".config" / "sops" / "age" / "keys.txt"
            if owner_keys.is_file():
                os.environ["SOPS_AGE_KEY_FILE"] = str(owner_keys)
                return True
        except Exception:
            pass

    return False
