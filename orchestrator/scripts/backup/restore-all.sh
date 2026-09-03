#!/usr/bin/env bash
# ==============================================================================
# Polaris Universal Recovery & Restore Script (Restic-based)
# ==============================================================================
# Recovers configurations, databases, and Docker images from Restic snapshots.
#
# Usage:
#   ./restore-all.sh                         Full disaster recovery (latest snapshots)
#   ./restore-all.sh --list                  Browse all available snapshots
#   ./restore-all.sh --vps a                 Restore VPS A's backups (for bare-metal recovery)
#   ./restore-all.sh --snapshot <id>         Restore a specific snapshot only
#   ./restore-all.sh --include <path>        Granular single-file/directory restore
#   ./restore-all.sh --yes                   Skip restore confirmation prompts
# ==============================================================================
set -euo pipefail

# Define directories - Anchored dynamically two levels up from Scripts/backup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

# Detect host repository owner and group to prevent root-owned file leak
REPO_USER=$(stat -c '%U' "$PROJECT_DIR" 2>/dev/null || echo "ubuntu")
REPO_GROUP=$(stat -c '%G' "$PROJECT_DIR" 2>/dev/null || echo "ubuntu")

# Backup credentials are injected by manage.py from the active VPS Doppler
# backup config before this script is elevated to root.

# --- Default Configurations ---
BACKUP_PASSWORD="${BACKUP_PASSWORD:-}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"

# --- Parse Arguments ---
VPS_OVERRIDE=""
SNAPSHOT_ID=""
INCLUDE_PATH=""
LIST_MODE=false
AUTO_YES=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --vps)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --vps requires a or b." >&2
        exit 1
      fi
      VPS_OVERRIDE="${2^^}"
      if [[ "$VPS_OVERRIDE" != "A" && "$VPS_OVERRIDE" != "B" ]]; then
        echo "ERROR: --vps must be A or B." >&2
        exit 1
      fi
      shift 2 ;;
    --vps=*)
      VPS_OVERRIDE="${1#*=}"
      VPS_OVERRIDE="${VPS_OVERRIDE^^}"
      if [[ "$VPS_OVERRIDE" != "A" && "$VPS_OVERRIDE" != "B" ]]; then
        echo "ERROR: --vps must be a or b." >&2
        exit 1
      fi
      shift ;;
    --snapshot)
      SNAPSHOT_ID="$2"; shift 2 ;;
    --include)
      INCLUDE_PATH="$2"; shift 2 ;;
    --list)
      LIST_MODE=true; shift ;;
    --yes|-y)
      AUTO_YES=true; shift ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--list] [--vps a|b] [--snapshot <id>] [--include <path>] [--yes]" >&2
      exit 1 ;;
  esac
done

# Check for root/sudo privilege (Required for writing to root system directories)
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

# --- Detect VPS Identity ---
if [[ -n "$VPS_OVERRIDE" ]]; then
      VPS_ID="${VPS_OVERRIDE,,}"
elif [[ -f "$PROJECT_DIR/.active_vps" ]]; then
  VPS_ID="$(tr '[:upper:]' '[:lower:]' < "$PROJECT_DIR/.active_vps" | xargs)"
else
  VPS_ID="$(hostname | tr '[:upper:]' '[:lower:]')"
fi
VPS_ID="${VPS_ID#vps-}"
VPS_ID="vps-${VPS_ID}"

# --- Configure Restic ---
# Securely prompt for password if not found in environment/.env
if [[ -z "$BACKUP_PASSWORD" ]]; then
  echo "[SECURITY] Restic repository password is required for decryption."
  read -sp "Enter the backup password: " BACKUP_PASSWORD
  echo ""
  if [[ -z "$BACKUP_PASSWORD" ]]; then
    echo "ERROR: Password cannot be empty." >&2
    exit 1
  fi
fi

if [[ -z "$RCLONE_REMOTE" ]]; then
  echo "ERROR: RCLONE_REMOTE is not set. Cannot locate backup repository." >&2
  exit 1
fi

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

# Verify the repository is accessible
if ! restic cat config >/dev/null 2>&1; then
  echo "ERROR: Cannot access Restic repository at $RESTIC_REPOSITORY" >&2
  echo "Verify that RCLONE_REMOTE, BACKUP_PASSWORD, and --vps flag are correct." >&2
  exit 1
fi

# ==============================================================================
# LIST MODE — Browse available snapshots and exit
# ==============================================================================
if [[ "$LIST_MODE" == "true" ]]; then
  echo "=============================================================================="
  echo "[INFO] Available Restic Snapshots ($VPS_ID)"
  echo "   Repository: $RESTIC_REPOSITORY"
  echo "=============================================================================="
  restic snapshots --group-by tags
  exit 0
fi

# ==============================================================================
# SINGLE SNAPSHOT MODE — Restore one specific snapshot and exit
# ==============================================================================
if [[ -n "$SNAPSHOT_ID" ]]; then
  echo "=============================================================================="
  echo "[INFO] Restoring Specific Snapshot: $SNAPSHOT_ID"
  echo "   Repository: $RESTIC_REPOSITORY"
  if [[ -n "$INCLUDE_PATH" ]]; then
    echo "   Filter: $INCLUDE_PATH"
  fi
  echo "=============================================================================="
  if [[ "$AUTO_YES" != "true" ]]; then
    read -p "[CONFIRM] This will overwrite files at their original paths. Continue? (y/N) " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
      echo "Restore cancelled."
      exit 0
    fi
  fi

  INCLUDE_FLAGS=()
  if [[ -n "$INCLUDE_PATH" ]]; then
    INCLUDE_FLAGS+=(--include "$INCLUDE_PATH")
  fi

  restic restore "$SNAPSHOT_ID" --target / "${INCLUDE_FLAGS[@]}"
  echo "[OK] Snapshot $SNAPSHOT_ID restored successfully."
  exit 0
fi

# ==============================================================================
# FULL DISASTER RECOVERY — Restore latest of all tags
# ==============================================================================

# Helper to resolve the latest snapshot ID for a given tag
resolve_latest_snapshot() {
  local tag="$1"
  restic snapshots --tag "$tag" --json --latest 1 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['short_id'] if isinstance(d, list) and len(d) > 0 and 'short_id' in d[0] else '')" 2>/dev/null || true
}

# Discover available snapshots
CONFIG_SNAPSHOT=$(resolve_latest_snapshot "configs")
APPDATA_SNAPSHOT=$(resolve_latest_snapshot "appdata")
IMAGE_SNAPSHOT=$(resolve_latest_snapshot "docker-images")

echo "=============================================================================="
echo "[WARNING] DISASTER RECOVERY & RESTORE OPERATION (Restic)"
echo "=============================================================================="
echo "VPS Identity    : $VPS_ID"
echo "Repository      : $RESTIC_REPOSITORY"
echo "Config Snapshot : ${CONFIG_SNAPSHOT:-NOT FOUND}"
echo "AppData Snapshot: ${APPDATA_SNAPSHOT:-NOT FOUND}"
echo "Image Snapshot  : ${IMAGE_SNAPSHOT:-NOT FOUND}"
echo "Repository Path : $PROJECT_DIR"
echo "=============================================================================="
echo "[WARNING] Restoring directly over an existing installation merges the backup"
echo "   files with existing host files. Leftovers will not be deleted."
echo "   For a completely clean restore (recommended when fixing corruption/compromise),"
echo "   please delete or rename existing directories (e.g. /docker/appdata) first."
echo "=============================================================================="
if [[ "$AUTO_YES" != "true" ]]; then
  read -p "[CONFIRM] This will overwrite current configs and databases. Continue? (y/N) " confirm
  if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Restore cancelled."
    exit 0
  fi
fi

INCLUDE_FLAGS=()
if [[ -n "$INCLUDE_PATH" ]]; then
  INCLUDE_FLAGS+=(--include "$INCLUDE_PATH")
fi

# ------------------------------------------------------------------------------
# STEP 1: STOP RUNNING SERVICES
# ------------------------------------------------------------------------------
echo "[$(date -Is)] Stopping all active container stacks to prevent file locks..."
if [[ -f "$PROJECT_DIR/manage.py" ]]; then
  # --yes: automated pre-restore stop, no interactive prompt (see manage.py confirm gates)
  python3 "$PROJECT_DIR/manage.py" stop --yes || true
else
  # Fallback to repository-only docker stop if manage.py is missing
  echo "manage.py not found. Stopping repository containers manually..."
  if command -v docker &>/dev/null; then
    containers=""
    while read -r cid working_dir; do
      if [[ -n "$working_dir" && "$working_dir" == "$PROJECT_DIR"* ]]; then
        containers="$containers $cid"
      fi
    done < <(docker ps --filter "label=com.docker.compose.project" --format "{{.ID}} {{.Label \"com.docker.compose.project.working_dir\"}}" 2>/dev/null || true)
    containers=$(echo "$containers" | xargs)
    if [[ -n "$containers" ]]; then
      docker stop $containers || true
    fi
  fi
fi

# ------------------------------------------------------------------------------
# STEP 2: RESTORE CONFIGURATIONS
# ------------------------------------------------------------------------------
if [[ -n "$CONFIG_SNAPSHOT" ]]; then
  echo "[$(date -Is)] Restoring system configurations (snapshot: $CONFIG_SNAPSHOT)..."
  mkdir -p "$PROJECT_DIR"
  restic restore "$CONFIG_SNAPSHOT" --target / "${INCLUDE_FLAGS[@]}"
  echo "[$(date -Is)] Configurations recovered successfully."
else
  echo "[$(date -Is)] WARNING: No config snapshot found. Skipping configuration restore."
fi

# Ensure all restored configurations are owned by the repository owner (prevent root-owned file leak)
echo "[$(date -Is)] Restoring repository file ownership to $REPO_USER:$REPO_GROUP..."
find "$PROJECT_DIR" \
  -not -path "*/data/*" \
  -not -path "*/state/*" \
  -not -path "*/config/*" \
  -not -path "*/mariadb/*" \
  -not -path "*/jackett_config/*" \
  -not -path "*/redis/*" \
  -not -path "*/postgres-data/*" \
  -not -path "*/db/*" \
  -not -path "*/store/*" \
  -not -path "*/metadata/*" \
  -not -path "*/downloads/*" \
  -exec chown "$REPO_USER:$REPO_GROUP" {} + 2>/dev/null || true

# ------------------------------------------------------------------------------
# STEP 3: RESTORE APPLICATION DATA
# ------------------------------------------------------------------------------
if [[ -n "$APPDATA_SNAPSHOT" ]]; then
  echo "[$(date -Is)] Restoring application databases and volumes (snapshot: $APPDATA_SNAPSHOT)..."
  restic restore "$APPDATA_SNAPSHOT" --target / "${INCLUDE_FLAGS[@]}"
  echo "[$(date -Is)] Application databases and volumes recovered successfully."
else
  echo "[$(date -Is)] WARNING: No appdata snapshot found. Skipping application data restore."
fi

# ------------------------------------------------------------------------------
# STEP 4: RESTORE DOCKER IMAGES
# ------------------------------------------------------------------------------
if [[ -n "$IMAGE_SNAPSHOT" ]]; then
  echo "[$(date -Is)] Discovered Docker image snapshot: $IMAGE_SNAPSHOT. Loading into Docker..."
  for img in "fmhy" "monochrome"; do
    if restic dump "$IMAGE_SNAPSHOT" "docker-images/${img}-latest.tar" 2>/dev/null | docker load; then
      echo "[$(date -Is)] Successfully loaded local/${img}:latest into Docker image cache."
    else
      echo "[$(date -Is)] Note: ${img}-latest.tar not found in snapshot or failed to load."
    fi
  done
else
  echo "[$(date -Is)] No Docker image snapshot found. Skipping."
fi

echo "=============================================================================="
echo "[SUCCESS] SYSTEM RESTORE COMPLETED SUCCESSFULLY!"
echo "=============================================================================="
echo "Your configurations and service databases have been fully recovered."
echo "You can redeploy the stack using:"
echo "   ./manage.py deploy  (or ./manage.py redeploy)"
echo "=============================================================================="
