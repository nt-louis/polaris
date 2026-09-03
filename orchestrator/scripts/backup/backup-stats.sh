#!/usr/bin/env bash
# ==============================================================================
# Net-Stream Backup Repository Statistics (Restic)
# ==============================================================================
# Displays storage statistics, compression ratios, and snapshot sizes for the
# active or targeted VPS Restic backup repository.
#
# Usage:
#   ./backup-stats.sh [--vps A|B] [--mode raw-data|restore-size] [--tag <tag>] [snapshot_id]
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
VPS_OVERRIDE=""
STATS_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
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
      STATS_ARGS+=("$1")
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
echo "[INFO] Restic Repository Storage Statistics"
echo "   VPS: $VPS_ID"
echo "   Repository: $RESTIC_REPOSITORY"
echo "=============================================================================="

restic stats "${STATS_ARGS[@]}"
