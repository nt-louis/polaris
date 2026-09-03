#!/usr/bin/env bash
# ==============================================================================
# Net-Stream Backup Pruning & Retention Script (Restic)
# ==============================================================================
# Executes on-demand or automated repository pruning and snapshot retention
# enforcement for the active or targeted VPS repository.
#
# Usage:
#   ./backup-prune.sh [--vps A|B] [--dry-run] [--max-unused <pct>]
# ==============================================================================
set -euo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

# Check for root/sudo privilege
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

# Define directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

REPO_USER=$(stat -c '%U' "$PROJECT_DIR" 2>/dev/null || echo "ubuntu")

# Configuration defaults
BACKUP_PASSWORD="${BACKUP_PASSWORD:-}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"
KEEP_DAILY="${KEEP_DAILY:-7}"
KEEP_WEEKLY="${KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${KEEP_MONTHLY:-6}"
MAX_UNUSED=""
RUN_DRY=""
VPS_OVERRIDE=""
EXTRA_ARGS=()

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
    --max-unused)
      MAX_UNUSED="$2"
      shift 2
      ;;
    --max-unused=*)
      MAX_UNUSED="${1#*=}"
      shift
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

# Detect VPS identity
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

# Validate
if [[ -z "$BACKUP_PASSWORD" ]]; then
  echo "ERROR: BACKUP_PASSWORD is not set." >&2
  exit 1
fi
if [[ -z "$RCLONE_REMOTE" ]]; then
  echo "ERROR: RCLONE_REMOTE is not set." >&2
  exit 1
fi

# Configure Restic
export RESTIC_PASSWORD="$BACKUP_PASSWORD"
export RESTIC_REPOSITORY="rclone:${RCLONE_REMOTE}/${VPS_ID}"
export RESTIC_CACHE_DIR="${RESTIC_CACHE_DIR:-/root/.cache/restic}"

# Detect rclone config
if [[ -z "${RCLONE_CONFIG:-}" ]]; then
  if [[ -f "$PROJECT_DIR/rclone.conf" ]]; then
    export RCLONE_CONFIG="$PROJECT_DIR/rclone.conf"
  elif [[ -f "/root/.config/rclone/rclone.conf" ]]; then
    export RCLONE_CONFIG="/root/.config/rclone/rclone.conf"
  elif [[ -f "/home/${REPO_USER}/.config/rclone/rclone.conf" ]]; then
    export RCLONE_CONFIG="/home/${REPO_USER}/.config/rclone/rclone.conf"
  fi
fi

echo "=============================================================================="
echo "[INFO] Restic Repository Retention Enforcement & Prune"
echo "   VPS: $VPS_ID"
echo "   Repository: $RESTIC_REPOSITORY"
echo "   Retention: keep-daily=$KEEP_DAILY, keep-weekly=$KEEP_WEEKLY, keep-monthly=$KEEP_MONTHLY"
[[ -n "$MAX_UNUSED" ]] && echo "   Max Unused Threshold: $MAX_UNUSED"
[[ -n "$RUN_DRY" ]] && echo "   Mode: DRY-RUN"
echo "=============================================================================="

FORGET_FLAGS=(
  --keep-daily "$KEEP_DAILY"
  --keep-weekly "$KEEP_WEEKLY"
  --keep-monthly "$KEEP_MONTHLY"
  --group-by "tags"
  --prune
)

if [[ -n "$RUN_DRY" ]]; then
  FORGET_FLAGS+=(--dry-run)
fi

if [[ -n "$MAX_UNUSED" ]]; then
  FORGET_FLAGS+=(--max-unused "$MAX_UNUSED")
fi

if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  FORGET_FLAGS+=("${EXTRA_ARGS[@]}")
fi

restic forget "${FORGET_FLAGS[@]}"

# Prune secondary remote if configured
if [[ -n "${RCLONE_REMOTE_SECONDARY:-}" ]]; then
  SECONDARY_REPO="rclone:${RCLONE_REMOTE_SECONDARY}/${VPS_ID}"
  echo ""
  echo "=============================================================================="
  echo "[INFO] Secondary Remote Retention & Prune ($SECONDARY_REPO)"
  echo "=============================================================================="
  
  if [[ -z "$RUN_DRY" ]]; then
    restic -r "$SECONDARY_REPO" forget "${FORGET_FLAGS[@]}" || true
  else
    echo "[DRY-RUN] Would prune secondary repository at $SECONDARY_REPO"
  fi
fi

echo ""
echo "[OK] Prune and retention enforcement complete."
