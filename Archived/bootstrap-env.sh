#!/usr/bin/env bash
# ==============================================================================
# Net-Stream Environment Bootstrapping Script (bootstrap-env.sh)
# ==============================================================================
# Finds all .env.example files in the repository and copies them to .env.
# ==============================================================================
set -euo pipefail

# Anchor working directory to the repository root (two directories up from Scripts/utils)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

log() {
  echo "[$(date -Is)] $1"
}

log "Bootstrapping all .env files..."

# Find all .env.example templates recursively, ignoring .git and node_modules
find . -type f -name ".env.example" -not -path "*/.git/*" -not -path "*/node_modules/*" | while read -r env_ex; do
    dir=$(dirname "$env_ex")
    if [[ ! -f "$dir/.env" ]]; then
        cp "$env_ex" "$dir/.env"
        log "[OK] Created $dir/.env"
    else
        log "[SKIP] $dir/.env already exists, skipping."
    fi
done

log "Done."
