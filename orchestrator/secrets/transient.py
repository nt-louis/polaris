"""Transient 0600 .env file materialization and cleanup engine.

Materializes temporary .env files with strict 0600 permissions only for services
that declare 'env_file:' in their Compose configuration, guaranteeing immediate
removal upon command completion or failure.
"""

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from orchestrator.core.models import ServiceMetadata
from orchestrator.secrets.doppler import (
    DopplerClient,
    default_doppler_client,
    get_doppler_config,
    get_doppler_project,
)

logger = logging.getLogger(__name__)


def compose_declares_env_file(service: ServiceMetadata) -> bool:
    """Check if the service's compose file contains an 'env_file:' directive."""
    if service.env_file_required:
        return True

    path = service.compose_path
    if not path.is_file():
        return False

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        return "env_file:" in content
    except Exception:
        return False


@contextmanager
def materialize_transient_env(
    service: ServiceMetadata,
    vps: Optional[str] = None,
    doppler_client: Optional[DopplerClient] = None,
) -> Generator[Optional[Path], None, None]:
    """Context manager for temporary 0600 .env materialization.

    Yields:
        Optional[Path]: Absolute path to the transient .env file if materialized,
                        or None if the service does not require an env_file.
    """
    if not compose_declares_env_file(service):
        yield None
        return

    client = doppler_client or default_doppler_client
    vps_ctx = vps or service.vps
    project = get_doppler_project(vps_ctx)
    config = get_doppler_config(service.rel_dir, service.name, service.category)
    env_file_path = service.abs_dir / ".env"

    if env_file_path.is_file():
        raise RuntimeError(
            f"Refusing to overwrite existing plaintext environment file: {env_file_path}"
        )

    # Download secrets from Doppler as ENV formatted string
    secrets_content = client.fetch_secrets(project, config, format_type="env")
    if not secrets_content.strip():
        raise RuntimeError(f"Doppler returned empty secrets for {project}/{config}")

    # Create file with exclusive creation and 0600 mode
    fd = os.open(str(env_file_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    created = True
    try:
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(secrets_content)
            os.chmod(str(env_file_path), 0o600)
        except Exception as exc:
            # If writing, flushing, or chmod fails, ensure immediate cleanup
            if env_file_path.is_file():
                try:
                    env_file_path.unlink()
                except Exception as unlink_err:
                    logger.critical(
                        "SECURITY ALERT: Failed to remove transient plaintext environment file after write error at %s: %s",
                        env_file_path,
                        unlink_err,
                    )
                    raise RuntimeError(
                        f"CRITICAL: Failed to remove transient environment file at {env_file_path} after write failure ({exc}): {unlink_err}"
                    ) from unlink_err
                finally:
                    created = False
            raise

        yield env_file_path
    finally:
        if created and env_file_path.is_file():
            try:
                env_file_path.unlink()
            except Exception as e:
                logger.critical(
                    "SECURITY ALERT: Failed to remove transient plaintext environment file at %s: %s",
                    env_file_path,
                    e,
                )
                raise RuntimeError(
                    f"CRITICAL: Failed to remove transient environment file at {env_file_path}: {e}"
                ) from e
