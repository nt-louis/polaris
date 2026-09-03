#!/usr/bin/env bash
# ==============================================================================
# Polaris Universal Backup Script (Restic-based)
# ==============================================================================
# Backs up the entire polaris self-hosted stack using Restic:
#   Phase 1: System configurations (--tag configs)
#   Phase 2: Application data & databases (--tag appdata)
#   Phase 3: Local Docker images (--tag docker-images)
#   Phase 4: Retention enforcement (restic forget --prune)
#   Phase 5: Secondary remote replication (restic copy)
#   Phase 6: Integrity verification (restic check)
#
# Each VPS auto-detects its identity via .active_vps and backs up to
# its own namespaced Restic repository (e.g. rclone:gdrive:.../vps-a).
# ==============================================================================
set -euo pipefail

# Ensure a robust PATH is available when run from cron
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

# Check for root/sudo privilege (Required for accessing root-owned container directories)
if [[ $EUID -ne 0 ]]; then
   echo "ERROR: This script must be run as root (use sudo)." >&2
   exit 1
fi

# Check for required tools
for tool in restic rclone; do
  if ! command -v "$tool" &>/dev/null; then
    echo "ERROR: $tool is not installed. Install with: sudo apt install $tool" >&2
    exit 1
  fi
done

# Define directories - Anchored dynamically two levels up from Scripts/backup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

# Detect the repository owner and group to prevent root-ownership pollution when restoring configs
REPO_USER=$(stat -c '%U' "$PROJECT_DIR" 2>/dev/null || echo "ubuntu")
REPO_GROUP=$(stat -c '%G' "$PROJECT_DIR" 2>/dev/null || echo "ubuntu")

# Backup credentials are injected by manage.py from the active VPS Doppler
# backup config before this script is elevated to root.

# --- Default Configurations & Variable Documentation ---
# Configuration variables below can be pre-defined in your shell environment
# or declared inside the decrypted root .env file.
#
# BACKUP_DIR          - Folder where execution logs and transaction outputs are stored.
#                       Default: /docker/backups/polaris
# BASE_PATH           - Host path holding compose container persistent volume folders.
#                       Default: /docker/appdata
# BACKUP_PASSWORD     - Encryption password used by Restic to open/lock the repository.
#                       Injected from the active VPS Doppler backup config.
# STOP_DURING_BACKUP  - Set 'true' to stop containers prior to backup & resume after.
#                       Default: false
# KEEP_DAILY          - Number of daily snapshots to preserve before pruning. (Default: 7)
# KEEP_WEEKLY         - Number of weekly snapshots to preserve before pruning. (Default: 4)
# KEEP_MONTHLY        - Number of monthly snapshots to preserve before pruning. (Default: 6)
# RUN_DRY             - Pass '--dry-run' as command arg to simulate commands without executing writes.

BACKUP_DIR="${BACKUP_DIR:-/docker/backups/polaris}"
BASE_PATH="${BASE_PATH:-/docker/appdata}"
BACKUP_PASSWORD="${BACKUP_PASSWORD:-}"
STOP_DURING_BACKUP="${STOP_DURING_BACKUP:-false}"
KEEP_DAILY="${KEEP_DAILY:-7}"
KEEP_WEEKLY="${KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${KEEP_MONTHLY:-6}"
RUN_DRY=""
VPS_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      RUN_DRY="--dry-run"
      shift
      ;;
    --vps)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --vps requires a node identifier (e.g. A, B, C)." >&2
        exit 1
      fi
      VPS_OVERRIDE="${2^^}"
      if [[ ! "$VPS_OVERRIDE" =~ ^[A-Za-z0-9_-]+$ ]]; then
        echo "ERROR: --vps must be a valid alphanumeric node identifier (e.g. A, B, C)." >&2
        exit 1
      fi
      shift 2
      ;;
    --vps=*)
      VPS_OVERRIDE="${1#*=}"
      VPS_OVERRIDE="${VPS_OVERRIDE^^}"
      if [[ ! "$VPS_OVERRIDE" =~ ^[A-Za-z0-9_-]+$ ]]; then
        echo "ERROR: --vps must be a valid alphanumeric node identifier (e.g. A, B, C)." >&2
        exit 1
      fi
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--dry-run] [--vps <id>]" >&2
      exit 1
      ;;
  esac
done

TIMESTAMP="$(date +%F_%H-%M-%S)"

# --- Detect VPS Identity ---
# Read from .active_vps, falling back to the hostname when no context is set.
VPS_ID=""
if [[ -n "$VPS_OVERRIDE" ]]; then
  VPS_ID="${VPS_OVERRIDE,,}"
elif [[ -f "$PROJECT_DIR/.active_vps" ]]; then
  VPS_ID=$(tr '[:upper:]' '[:lower:]' < "$PROJECT_DIR/.active_vps" | xargs)
fi
if [[ -z "$VPS_ID" ]]; then
  VPS_ID=$(hostname | tr '[:upper:]' '[:lower:]')
fi
VPS_ID="${VPS_ID#vps-}"
VPS_ID="vps-${VPS_ID}"

# --- Validate Required Configuration ---
if [[ -z "$BACKUP_PASSWORD" ]]; then
  echo "ERROR: BACKUP_PASSWORD is not set. Cannot access Restic repository." >&2
  exit 1
fi

if [[ -z "${RCLONE_REMOTE:-}" ]]; then
  echo "ERROR: RCLONE_REMOTE is not set. Cannot determine backup destination." >&2
  exit 1
fi

# --- Configure Restic ---
export RESTIC_PASSWORD="$BACKUP_PASSWORD"
export RESTIC_REPOSITORY="rclone:${RCLONE_REMOTE}/${VPS_ID}"
export RESTIC_CACHE_DIR="${RESTIC_CACHE_DIR:-/root/.cache/restic}"

# Detect rclone config path and export so Restic's rclone backend inherits it
if [[ -z "${RCLONE_CONFIG:-}" ]]; then
  if [[ -f "$PROJECT_DIR/rclone.conf" ]]; then
    export RCLONE_CONFIG="$PROJECT_DIR/rclone.conf"
  elif [[ -f "/root/.config/rclone/rclone.conf" ]]; then
    export RCLONE_CONFIG="/root/.config/rclone/rclone.conf"
  elif [[ -f "/home/${REPO_USER}/.config/rclone/rclone.conf" ]]; then
    export RCLONE_CONFIG="/home/${REPO_USER}/.config/rclone/rclone.conf"
  fi
fi


# Ensure backup log directory exists
mkdir -p "$BACKUP_DIR"
LOG_FILE="$BACKUP_DIR/backup_$TIMESTAMP.log"

# Logging helper
log() {
  local msg="[$(date -Is)] $1"
  if [[ "$RUN_DRY" == "--dry-run" ]]; then
    echo "DRY-RUN: $msg" | tee -a "$LOG_FILE"
  else
    echo "$msg" | tee -a "$LOG_FILE"
  fi
}

log "Starting Polaris Restic Backup..."
log "VPS Identity: $VPS_ID"
log "Restic Repository: $RESTIC_REPOSITORY"
log "External AppData Path: $BASE_PATH"
log "Repository Path: $PROJECT_DIR"

if [[ "$RUN_DRY" == "--dry-run" ]]; then
  log "--- RUNNING IN DRY-RUN MODE ---"
fi

# Container state tracking for cleanup trap
CONTAINERS_STOPPED="false"
ACTIVE_PROJECTS_FILE=""

# Helper to execute manage.py with repository owner privileges if running as root
REPO_USER=""
if [[ "$EUID" -eq 0 ]]; then
  REPO_USER="$(stat -c '%U' "$PROJECT_DIR" 2>/dev/null || echo "")"
fi

run_manage_cmd() {
  if [[ "$EUID" -eq 0 && -n "$REPO_USER" && "$REPO_USER" != "root" ]]; then
    sudo -u "$REPO_USER" -H python3 "$PROJECT_DIR/manage.py" "$@"
  else
    python3 "$PROJECT_DIR/manage.py" "$@"
  fi
}

# Clean up on exit and ensure containers are restarted if suspended
cleanup() {
  if [[ "${STOP_DURING_BACKUP:-false}" == "true" && "${CONTAINERS_STOPPED:-false}" == "true" ]]; then
    log "WARNING: Script exiting unexpectedly. Restarting all containers using manage.py..."
    if [[ -f "$PROJECT_DIR/manage.py" ]]; then
      if [[ -f "${ACTIVE_PROJECTS_FILE:-}" && -s "$ACTIVE_PROJECTS_FILE" ]]; then
        run_manage_cmd redeploy --yes --resume-from "$ACTIVE_PROJECTS_FILE"
      else
        run_manage_cmd redeploy --yes
      fi
      log "All containers restarted."
    else
      log "ERROR: manage.py not found. Please restart containers manually."
    fi
  fi
  if [[ -f "${ACTIVE_PROJECTS_FILE:-}" ]]; then
    rm -f "$ACTIVE_PROJECTS_FILE"
  fi
}
trap cleanup EXIT

# Restic dry-run flag (shared across phases)
DRY_RUN_FLAG=""
if [[ "$RUN_DRY" == "--dry-run" ]]; then
  DRY_RUN_FLAG="--dry-run"
fi

# ==============================================================================
# REPOSITORY INITIALIZATION
# ==============================================================================
if ! restic cat config >/dev/null 2>&1; then
  log "Restic repository not found at $RESTIC_REPOSITORY. Initializing..."
  if [[ "$RUN_DRY" != "--dry-run" ]]; then
    restic init 2>&1 | tee -a "$LOG_FILE"
    log "Repository initialized successfully."
  else
    log "[DRY-RUN] Would initialize Restic repository at $RESTIC_REPOSITORY"
  fi
fi

# ==============================================================================
# PHASE 1: CONFIGURATION BACKUP
# ==============================================================================
log "PHASE 1: Snapshotting System Configurations (--tag configs)..."

set +eo pipefail
restic backup $DRY_RUN_FLAG \
  --tag configs \
  --exclude-caches \
  --exclude ".git" \
  --exclude "node_modules" \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  --exclude ".venv" \
  --exclude "venv" \
  --exclude "data" \
  --exclude "state" \
  --exclude "config" \
  --exclude "backups" \
  --exclude "logs" \
  --exclude "dist" \
  --exclude "build" \
  --exclude "Archived" \
  --exclude "**/db" \
  --exclude "**/postgres*" \
  --exclude "**/mariadb*" \
  --exclude "**/redis*" \
  --exclude "**/cloud-data" \
  --exclude "**/storage-data" \
  --exclude "**/agent_data" \
  --exclude "**/cache*" \
  --exclude "**/.cache" \
  --exclude "**/tmp" \
  --exclude "**/temp" \
  --exclude "**/letsencrypt" \
  --exclude "Media/zurg/cache*" \
  --exclude "Media/stremio/addons/aiomanager/aio-*" \
  --exclude "Utilities/netbird-server/data" \
  "$PROJECT_DIR" 2>&1 | tee -a "$LOG_FILE"
restic_status="${PIPESTATUS[0]}"
set -eo pipefail

if [[ $restic_status -eq 0 || $restic_status -eq 3 ]]; then
  [[ $restic_status -eq 3 ]] && log "WARNING: Config snapshot completed with warnings (some files may have been skipped)."
  log "Phase 1 complete."
else
  log "ERROR: Config snapshot failed with exit code $restic_status."
  exit 1
fi

# ==============================================================================
# PHASE 2: APPLICATION DATA & DATABASE BACKUP
# ==============================================================================
TARGET_VPS_CHAR="${VPS_ID#vps-}"
TARGET_VPS_CHAR="${TARGET_VPS_CHAR^^}"
log "PHASE 2: Snapshotting Application Databases & Active Volumes for VPS $TARGET_VPS_CHAR (--tag appdata)..."

# Stage appdata paths strictly scoped to the active VPS assignment
APPDATA_PATHS=()

log "Discovering application data paths scoped to VPS $TARGET_VPS_CHAR..."
while read -r discovered_path; do
  if [[ -n "$discovered_path" && -d "$discovered_path" ]]; then
    APPDATA_PATHS+=("$discovered_path")
  fi
done < <(python3 -c "
import sys, os
sys.path.insert(0, '$PROJECT_DIR')
try:
    from orchestrator.registry.discovery import discover_appdata_paths
    for p in discover_appdata_paths('$TARGET_VPS_CHAR', '$BASE_PATH'):
        print(p)
except Exception:
    sys.exit(1)
" 2>/dev/null || true)

# Fallback: if Python discovery produced no paths (e.g. minimal runtime), scan compose mounts directly
if [[ ${#APPDATA_PATHS[@]} -eq 0 ]]; then
  log "Using fallback directory discovery for VPS $TARGET_VPS_CHAR..."
  while read -r dir_path; do
    if [[ -n "$dir_path" && -d "$dir_path" ]]; then
      APPDATA_PATHS+=("$dir_path")
    fi
  done < <(find "$PROJECT_DIR" -type d \( -name "data" -o -name "state" -o -name "config" \) \
    -not -path "*/.git/*" \
    -not -path "*/node_modules/*" \
    -not -path "*/.venv/*" \
    -not -path "*/Archived/*" \
    -not -path "*/backups/*" \
    -not -path "*/logs/*" 2>/dev/null)
fi

# Deduplicate paths
readarray -t APPDATA_PATHS < <(printf '%s\n' "${APPDATA_PATHS[@]}" | sort -u)

if [[ ${#APPDATA_PATHS[@]} -eq 0 ]]; then
  log "ERROR: No application data directories found to archive."
  exit 1
fi

log "Discovered ${#APPDATA_PATHS[@]} application data folders to snapshot:"
for target in "${APPDATA_PATHS[@]}"; do
  log "  -> $target"
done

# Helper to restart suspended containers
restart_suspended_containers() {
  if [[ "$STOP_DURING_BACKUP" == "true" && "$CONTAINERS_STOPPED" == "true" ]]; then
    log "Restarting all suspended containers using manage.py..."
    if [[ -f "$PROJECT_DIR/manage.py" ]]; then
      set +eo pipefail
      if [[ -f "${ACTIVE_PROJECTS_FILE:-}" && -s "$ACTIVE_PROJECTS_FILE" ]]; then
        run_manage_cmd redeploy --yes --resume-from "$ACTIVE_PROJECTS_FILE" 2>&1 | tee -a "$LOG_FILE"
      else
        run_manage_cmd redeploy --yes 2>&1 | tee -a "$LOG_FILE"
      fi
      redeploy_status="${PIPESTATUS[0]}"
      set -eo pipefail
      if [[ $redeploy_status -eq 0 ]]; then
        log "All containers restarted successfully."
      else
        log "WARNING: redeploy returned exit code $redeploy_status. Containers may still be starting."
      fi
      CONTAINERS_STOPPED="false"
      if [[ -f "${ACTIVE_PROJECTS_FILE:-}" ]]; then
        rm -f "$ACTIVE_PROJECTS_FILE"
      fi
    else
      log "ERROR: manage.py not found. Please restart containers manually."
    fi
  fi
}

# Run pre-backup hook if present
PRE_HOOK="$SCRIPT_DIR/pre-backup-hook.sh"
if [[ -f "$PRE_HOOK" ]]; then
  log "Found pre-backup hook script: $PRE_HOOK. Executing..."
  bash "$PRE_HOOK" || log "WARNING: Pre-backup hook exited with non-zero status"
fi

# Optional cold backup — temporarily suspend active containers for database consistency
if [[ "$STOP_DURING_BACKUP" == "true" && "$RUN_DRY" != "--dry-run" ]]; then
  ACTIVE_PROJECTS_FILE="$(mktemp /tmp/polaris-active-projects-XXXXXX.txt)"
  chmod 644 "$ACTIVE_PROJECTS_FILE"

  log "Saving list of currently active compose projects..."
  if command -v docker &>/dev/null; then
    docker ps --filter "label=com.docker.compose.project" --format "{{.Label \"com.docker.compose.project.working_dir\"}}" | sort -u | while read -r working_dir; do
      if [[ -n "$working_dir" && "$working_dir" == "$PROJECT_DIR"* ]]; then
        rel_dir="${working_dir#$PROJECT_DIR}"
        rel_dir="${rel_dir#/}"
        echo "$rel_dir" >> "$ACTIVE_PROJECTS_FILE"
        log "  Saved active project: $rel_dir"
      fi
    done
  fi

  log "STOP_DURING_BACKUP is enabled. Stopping all running containers using manage.py..."
  if [[ -f "$PROJECT_DIR/manage.py" ]]; then
    # --yes: automated stop during backup, no interactive prompt (see manage.py confirm gates)
    run_manage_cmd stop --yes
    CONTAINERS_STOPPED="true"
    log "All running containers have been temporarily suspended."
  else
    log "ERROR: manage.py not found. Proceeding in hot-backup mode."
  fi
fi

# Run the appdata snapshot with comprehensive cache, temp, and churn filtering
set +eo pipefail
restic backup $DRY_RUN_FLAG \
  --tag appdata \
  --exclude-caches \
  --exclude "**/.cache" \
  --exclude "**/cache" \
  --exclude "**/Cache" \
  --exclude "**/cache-*" \
  --exclude "**/vfs" \
  --exclude "**/vfsMeta" \
  --exclude "**/transcodes" \
  --exclude "**/Transcodes" \
  --exclude "**/transcode" \
  --exclude "**/preview" \
  --exclude "**/thumbnails" \
  --exclude "**/Thumbnails" \
  --exclude "**/tmp" \
  --exclude "**/temp" \
  --exclude "**/Temp" \
  --exclude "**/*.tmp" \
  --exclude "**/*.sock" \
  --exclude "**/*.socket" \
  --exclude "**/*.log" \
  --exclude "**/*.log.*" \
  --exclude "**/*.log.gz" \
  --exclude "**/flaresolverr/data" \
  --exclude "**/browser-data" \
  --exclude "**/profiles" \
  --exclude "**/consume" \
  --exclude "**/export" \
  --exclude "**/node_modules" \
  --exclude "**/__pycache__" \
  --exclude "**/*.pyc" \
  "${APPDATA_PATHS[@]}" 2>&1 | tee -a "$LOG_FILE"
restic_status="${PIPESTATUS[0]}"
set -eo pipefail

# Always restart containers before checking status
restart_suspended_containers

# Run post-backup hook if present
POST_HOOK="$SCRIPT_DIR/post-backup-hook.sh"
if [[ -f "$POST_HOOK" ]]; then
  log "Found post-backup hook script: $POST_HOOK. Executing..."
  bash "$POST_HOOK" || log "WARNING: Post-backup hook exited with non-zero status"
fi

if [[ $restic_status -eq 0 || $restic_status -eq 3 ]]; then
  [[ $restic_status -eq 3 ]] && log "WARNING: Appdata snapshot completed with warnings (some files may have been skipped)."
  log "Phase 2 complete."
else
  log "ERROR: Appdata snapshot failed with exit code $restic_status."
  exit 1
fi

# ==============================================================================
# PHASE 3: DOCKER IMAGES BACKUP
# ==============================================================================
log "PHASE 3: Snapshotting Local Docker Images (--tag docker-images)..."

for img in "fmhy" "monochrome"; do
  if docker image inspect "local/${img}:latest" &>/dev/null; then
    log "Discovered local image local/${img}:latest. Snapshotting via stdin..."
    if [[ "$RUN_DRY" != "--dry-run" ]]; then
      set +eo pipefail
      docker save "local/${img}:latest" | restic backup --stdin --stdin-filename "docker-images/${img}-latest.tar" --tag docker-images 2>&1 | tee -a "$LOG_FILE"
      restic_status="${PIPESTATUS[1]}"
      set -eo pipefail

      if [[ $restic_status -eq 0 ]]; then
        log "Successfully snapshotted local/${img}:latest."
      else
        log "WARNING: Docker image snapshot for ${img} failed with exit code $restic_status. Continuing."
      fi
    else
      log "[DRY-RUN] Would snapshot local/${img}:latest via restic --stdin"
    fi
  else
    log "No local/${img}:latest image found in Docker cache. Skipping."
  fi
done

log "Phase 3 complete."

# Determine if we run an unconditional full prune and check (Sundays)
RUN_PRUNE="false"
if [[ "$(date +%u)" -eq 7 ]]; then
  RUN_PRUNE="true"
fi

# ==============================================================================
# PHASE 4: RETENTION ENFORCEMENT & SELF-REGULATING PRUNING
# ==============================================================================
log "PHASE 4: Enforcing Retention Policy (daily=$KEEP_DAILY, weekly=$KEEP_WEEKLY, monthly=$KEEP_MONTHLY)..."

FORGET_FLAGS=(
  --keep-daily "$KEEP_DAILY"
  --keep-weekly "$KEEP_WEEKLY"
  --keep-monthly "$KEEP_MONTHLY"
  --group-by "tags"
  --prune
)

if [[ "$RUN_PRUNE" == "true" ]]; then
  log "Sunday detected: Enforcing retention with unconditional full prune..."
else
  log "Continuous maintenance: Enforcing retention with --max-unused 10% self-regulating prune..."
  FORGET_FLAGS+=(--max-unused "10%")
fi

set +eo pipefail
restic forget $DRY_RUN_FLAG "${FORGET_FLAGS[@]}" 2>&1 | tee -a "$LOG_FILE"
restic_status="${PIPESTATUS[0]}"
set -eo pipefail

if [[ $restic_status -ne 0 ]]; then
  log "WARNING: Retention enforcement exited with code $restic_status."
fi

log "Phase 4 complete."

# ==============================================================================
# PHASE 5: SECONDARY REMOTE REPLICATION
# ==============================================================================
if [[ -n "${RCLONE_REMOTE_SECONDARY:-}" ]]; then
  SECONDARY_REPO="rclone:${RCLONE_REMOTE_SECONDARY}/${VPS_ID}"
  log "PHASE 5: Replicating snapshots to secondary remote ($SECONDARY_REPO)..."

  if [[ "$RUN_DRY" != "--dry-run" ]]; then
    # Initialize secondary repo if needed
    if ! restic -r "$SECONDARY_REPO" cat config >/dev/null 2>&1; then
      log "Secondary repository not found. Initializing at $SECONDARY_REPO..."
      restic -r "$SECONDARY_REPO" init 2>&1 | tee -a "$LOG_FILE"
      log "Secondary repository initialized successfully."
    fi

    # Copy snapshots from primary to secondary
    export RESTIC_FROM_REPOSITORY="$RESTIC_REPOSITORY"
    export RESTIC_FROM_PASSWORD="$BACKUP_PASSWORD"

    set +eo pipefail
    restic -r "$SECONDARY_REPO" copy 2>&1 | tee -a "$LOG_FILE"
    restic_status="${PIPESTATUS[0]}"
    set -eo pipefail

    if [[ $restic_status -ne 0 ]]; then
      log "WARNING: Secondary replication exited with code $restic_status."
    fi

    # Apply retention on secondary too
    SECONDARY_FORGET_FLAGS=(
      --keep-daily "$KEEP_DAILY"
      --keep-weekly "$KEEP_WEEKLY"
      --keep-monthly "$KEEP_MONTHLY"
      --group-by "tags"
      --prune
    )
    if [[ "$RUN_PRUNE" == "true" ]]; then
      log "Sunday detected: Enforcing secondary retention with unconditional full prune..."
    else
      log "Continuous maintenance: Enforcing secondary retention with --max-unused 10% self-regulating prune..."
      SECONDARY_FORGET_FLAGS+=(--max-unused "10%")
    fi

    set +eo pipefail
    restic -r "$SECONDARY_REPO" forget "${SECONDARY_FORGET_FLAGS[@]}" 2>&1 | tee -a "$LOG_FILE"
    set -eo pipefail

    unset RESTIC_FROM_REPOSITORY
    unset RESTIC_FROM_PASSWORD

    log "Phase 5 complete."
  else
    log "[DRY-RUN] Would replicate snapshots and enforce retention on secondary remote: $SECONDARY_REPO"
  fi
else
  log "PHASE 5: Secondary remote replication skipped (RCLONE_REMOTE_SECONDARY is not set)."
fi

# ==============================================================================
# PHASE 6: INTEGRITY VERIFICATION
# ==============================================================================
if [[ "$RUN_PRUNE" == "true" ]]; then
  log "PHASE 6: Verifying repository integrity (Sunday full check)..."
  if [[ "$RUN_DRY" != "--dry-run" ]]; then
    set +eo pipefail
    restic check 2>&1 | tee -a "$LOG_FILE"
    restic_status="${PIPESTATUS[0]}"
    set -eo pipefail

    if [[ $restic_status -eq 0 ]]; then
      log "Repository integrity verified successfully."
    else
      log "WARNING: Repository integrity check reported issues (exit code $restic_status). Review output above."
    fi
  else
    log "[DRY-RUN] Would verify repository integrity with 'restic check'"
  fi
else
  log "PHASE 6: Integrity check skipped (Runs on Sundays only)."
fi

log "[SUCCESS] Polaris Restic Backup completed successfully!"
