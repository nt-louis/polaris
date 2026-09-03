"""Secret management engine for Doppler SaaS process injection, transient .env files, and SOPS."""

from orchestrator.secrets.doppler import (
    DopplerClient,
    audit_repository_secrets,
    check_missing_secrets,
    clean_slug,
    default_doppler_client,
    get_doppler_config,
    get_doppler_project,
    get_short_category_slug,
    prune_redundant_secrets,
    sync_repository_configs,
)
from orchestrator.secrets.snapshots import (
    SnapshotManager,
    parse_dotenv_content,
    sync_snapshots_to_branch,
)
from orchestrator.secrets.sops import (
    find_sops_binary,
    is_sops_available,
    setup_age_key_env,
)
from orchestrator.secrets.transient import (
    compose_declares_env_file,
    materialize_transient_env,
)

__all__ = [
    "DopplerClient",
    "default_doppler_client",
    "clean_slug",
    "get_short_category_slug",
    "get_doppler_project",
    "get_doppler_config",
    "audit_repository_secrets",
    "check_missing_secrets",
    "prune_redundant_secrets",
    "sync_repository_configs",
    "compose_declares_env_file",
    "materialize_transient_env",
    "find_sops_binary",
    "is_sops_available",
    "setup_age_key_env",
    "sync_snapshots_to_branch",
    "SnapshotManager",
    "parse_dotenv_content",
]
