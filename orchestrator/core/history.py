"""Persistent action audit logging, history management, and automated retention pruning."""

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from orchestrator.core.constants import REPO_ROOT

logger = logging.getLogger(__name__)

STATE_DIR = REPO_ROOT / "state"
HISTORY_FILE = STATE_DIR / "action_history.jsonl"

DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_MAX_RECORDS = 1000


def _ensure_history_permissions(target_file: Path, mode: int = 0o664) -> None:
    """Ensure history file and parent state directory have proper permissions and repo ownership if executed as root."""
    try:
        if target_file.is_file():
            target_file.chmod(mode)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            repo_stat = REPO_ROOT.stat()
            if target_file.is_file():
                os.chown(target_file, repo_stat.st_uid, repo_stat.st_gid)
            if target_file.parent.is_dir():
                os.chown(target_file.parent, repo_stat.st_uid, repo_stat.st_gid)
    except Exception:
        pass


def prune_action_history(
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    max_records: int = DEFAULT_MAX_RECORDS,
    history_file: Optional[Path] = None,
) -> int:
    """Prune history records older than max_age_days or exceeding max_records limit.

    Args:
        max_age_days: Maximum age in days to retain records (<= 0 disables time-based pruning).
        max_records: Maximum number of recent records to keep (<= 0 disables count-based pruning).
        history_file: Optional custom history file path.

    Returns:
        int: Number of records pruned.
    """
    target_file = history_file or HISTORY_FILE
    if not target_file.is_file():
        return 0

    now = datetime.now(timezone.utc)
    cutoff_time = (now - timedelta(days=max_age_days)) if max_age_days > 0 else None

    valid_records: list[dict] = []
    pruned_count = 0

    try:
        with target_file.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                    # Check age if timestamp present
                    if cutoff_time:
                        ts_str = record.get("timestamp")
                        if ts_str:
                            record_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if record_time < cutoff_time:
                                pruned_count += 1
                                continue
                    valid_records.append(record)
                except Exception:
                    # Corrupt line or unparseable date - discard
                    pruned_count += 1

        # Check max records limit (retain the most recent entries)
        if max_records > 0 and len(valid_records) > max_records:
            excess = len(valid_records) - max_records
            pruned_count += excess
            valid_records = valid_records[-max_records:]

        if pruned_count > 0:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_mode = 0o664
            if target_file.is_file():
                try:
                    target_mode = target_file.stat().st_mode & 0o777
                except Exception:
                    pass
            with tempfile.NamedTemporaryFile("w", dir=str(target_file.parent), delete=False, encoding="utf-8") as tmp:
                for r in valid_records:
                    tmp.write(json.dumps(r) + "\n")
                tmp_path = Path(tmp.name)
            try:
                tmp_path.chmod(target_mode)
            except Exception:
                pass
            tmp_path.replace(target_file)
            _ensure_history_permissions(target_file, target_mode)

    except Exception as e:
        logger.warning("Failed during action history pruning on %s: %s", target_file, e)

    return pruned_count


def log_action_event(
    action: str,
    vps: str = "A",
    exit_code: int = 0,
    duration_sec: float = 0.0,
    command: Optional[str] = None,
    details: Optional[str] = None,
    history_file: Optional[Path] = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> None:
    """Append a structured action execution event to the persistent history log and enforce retention."""
    target_file = history_file or HISTORY_FILE
    try:
        target_file.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action.upper(),
            "vps": vps or "A",
            "exit_code": exit_code,
            "status": "SUCCESS" if exit_code == 0 else "FAILED",
            "duration_sec": round(duration_sec, 2),
            "command": command or "",
            "details": details or "",
        }
        with target_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

        _ensure_history_permissions(target_file, 0o664)

        # Automatically enforce retention window & cap file size
        prune_action_history(
            max_age_days=max_age_days,
            max_records=max_records,
            history_file=target_file,
        )
    except Exception as e:
        logger.warning("Failed to write action history log to %s: %s", target_file, e)


def load_action_history(
    limit: int = 100,
    history_file: Optional[Path] = None,
) -> list[dict]:
    """Load persistent action history records from disk."""
    target_file = history_file or HISTORY_FILE
    if not target_file.is_file():
        return []

    records: list[dict] = []
    try:
        with target_file.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    records.append(json.loads(stripped))
                except Exception:
                    pass
    except Exception as e:
        logger.warning("Failed to read action history from %s: %s", target_file, e)

    return records[-limit:]


def format_action_history_text(records: list[dict]) -> str:
    """Format action history records as plain text table."""
    if not records:
        return "[INFO] No persistent action history records found."

    lines = [
        "=" * 80,
        "Net-Stream Persistent Action Audit History",
        "=" * 80,
    ]
    for r in reversed(records):
        ts = r.get("timestamp", "")[:19].replace("T", " ")
        vps = r.get("vps", "A")
        action = r.get("action", "")
        status = r.get("status", "UNKNOWN")
        duration = f"{r.get('duration_sec', 0.0):.1f}s"
        cmd = r.get("command") or r.get("details") or "-"
        lines.append(f"{ts} | VPS {vps} | {action:<15} | {status:<7} | {duration:>6} | {cmd}")
    return "\n".join(lines)
