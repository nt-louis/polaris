#!/usr/bin/env bash
# ==============================================================================
# Net-Stream Automated Post-Backup Hook
# ==============================================================================
# Executes immediately after Restic completes snapshots and containers are
# confirmed running.
#
# Key Features:
#   1. Cleans dangling Docker image layers left behind by updates.
#   2. Optional Healthcheck Ping (Healthchecks.io / Uptime Kuma push monitor).
# ==============================================================================
set -euo pipefail

log() {
  echo "[$(date -Is)] [post-backup] $1"
}

log "Executing post-backup host hygiene and reporting..."

# ------------------------------------------------------------------------------
# 1. Clean Dangling Docker Images (Untagged Layers)
# ------------------------------------------------------------------------------
if command -v docker &>/dev/null && docker ps &>/dev/null; then
  log "Pruning dangling Docker images to reclaim host disk space..."
  docker image prune -f --filter "until=24h" 2>/dev/null || true
fi

# ------------------------------------------------------------------------------
# 2. Optional Healthcheck Notification Ping
# ------------------------------------------------------------------------------
# If BACKUP_HEALTHCHECK_URL is defined in environment or Doppler, ping it now
if [[ -n "${BACKUP_HEALTHCHECK_URL:-}" ]]; then
  log "Pinging backup healthcheck monitor..."
  if command -v curl &>/dev/null; then
    curl -fsS -m 10 --retry 3 "${BACKUP_HEALTHCHECK_URL}" >/dev/null 2>&1 || log "WARNING: Healthcheck ping failed."
  fi
fi

log "Post-backup tasks complete."
