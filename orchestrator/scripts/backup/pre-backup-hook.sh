#!/usr/bin/env bash
# ==============================================================================
# Net-Stream Automated Pre-Backup Hook
# ==============================================================================
# Executes immediately before Restic snapshots to optimize storage and ensure
# database transaction consistency.
#
# Key Features:
#   1. Runs LIVE while containers are running (zero downtime).
#   2. SQLite WAL Checkpointing: Flushes uncommitted WAL pages into main .db files
#      and truncates *.db-wal buffers to 0 bytes, stopping volatile buffer bloat.
#   3. PostgreSQL Hot Dumps: Automatically detects active Postgres containers and
#      generates compressed logical SQL dumps for maximum Restic deduplication.
#   4. Ephemeral Temp Cleaning: Cleans stale temporary artifacts before scanning.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
BASE_PATH="${BASE_PATH:-/docker/appdata}"

log() {
  echo "[$(date -Is)] [pre-backup] $1"
}

log "Starting pre-backup storage and database optimizations..."

# ------------------------------------------------------------------------------
# 1. SQLite WAL Checkpointing (Online, Hot Flush Scoped to Active VPS)
# ------------------------------------------------------------------------------
if command -v sqlite3 &>/dev/null; then
  # Detect active VPS
  VPS_ID="A"
  if [[ -f "$PROJECT_DIR/.active_vps" ]]; then
    VPS_ID=$(tr '[:upper:]' '[:lower:]' < "$PROJECT_DIR/.active_vps" | xargs)
    VPS_ID="${VPS_ID#vps-}"
    VPS_ID="${VPS_ID^^}"
  fi
  [[ "$VPS_ID" != "A" && "$VPS_ID" != "B" ]] && VPS_ID="A"
  
  log "Scanning for SQLite databases to checkpoint WAL buffers (VPS $VPS_ID)..."
  
  while read -r db_file; do
    if [[ -f "$db_file" && -w "$db_file" ]]; then
      # Checkpoint WAL to flush pages and truncate WAL file to 0 bytes
      sqlite3 "$db_file" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null 2>&1 || true
    fi
  done < <(python3 -c "
import sys, os
sys.path.insert(0, '$PROJECT_DIR')
SKIP_DIRS = {'.git', 'node_modules', '.venv', 'Archived', 'cache-rd', 'cache-tb', 'vfsMeta', 'vfs', 'media', 'cloud-data', 'bookdrop', 'consume', 'export', 'trainingData', 'metadata', 'logs', 'cache'}
try:
    from orchestrator.registry.discovery import discover_appdata_paths
    paths = discover_appdata_paths('$VPS_ID', '$BASE_PATH')
    for root_dir in paths:
        if os.path.basename(root_dir.rstrip('/')) in SKIP_DIRS:
            continue
        for root, dirs, files in os.walk(root_dir):
            rel = os.path.relpath(root, root_dir)
            if (0 if rel == '.' else len(rel.split(os.sep))) >= 2:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if f.endswith(('.db', '.sqlite', '.sqlite3')) and not any(f.endswith(s) for s in ('-wal', '-shm', '-journal')):
                    print(os.path.join(root, f))
except Exception:
    pass
" 2>/dev/null)
  log "SQLite WAL checkpointing complete."
else
  log "sqlite3 CLI not found on host. Skipping host-level SQLite WAL truncation."
fi

# ------------------------------------------------------------------------------
# 2. PostgreSQL Live Container Logical Dumps (Hot, Non-blocking)
# ------------------------------------------------------------------------------
if command -v docker &>/dev/null; then
  # Find running containers running PostgreSQL
  POSTGRES_CONTAINERS=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E 'postgres|supabase-db|linkwarden-db|penpot.*postgres|coolify.*db' || true)
  
  if [[ -n "$POSTGRES_CONTAINERS" ]]; then
    log "Discovered active PostgreSQL container(s). Performing live logical dumps..."
    while read -r container; do
      [[ -z "$container" ]] && continue
      
      # Determine dump directory (in-app directory or central /docker/appdata)
      target_dir="/tmp"
      if [[ -d "$BASE_PATH/$container" ]]; then
        target_dir="$BASE_PATH/$container"
      fi
      
      dump_file="$target_dir/${container}_backup.sql.gz"
      if docker exec -t "$container" pg_dumpall -U postgres 2>/dev/null | gzip > "$dump_file.tmp"; then
        mv "$dump_file.tmp" "$dump_file"
        chmod 640 "$dump_file" 2>/dev/null || true
        log "  Successfully dumped $container -> $dump_file"
      else
        rm -f "$dump_file.tmp"
      fi
    done <<< "$POSTGRES_CONTAINERS"
  fi
fi

# ------------------------------------------------------------------------------
# 3. Clean Stale Ephemeral Temp Files
# ------------------------------------------------------------------------------
log "Cleaning stale temporary files older than 3 days..."
find /tmp -maxdepth 1 -name "net-stream-*" -mtime +3 -exec rm -rf {} + 2>/dev/null || true

log "Pre-backup optimizations finished successfully."
