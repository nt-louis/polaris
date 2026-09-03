#!/usr/bin/env bash
#
# Idempotently installs git hooks for net-stream. Currently installs:
#   - pre-commit  (orchestrator/scripts/hooks/pre-commit) — blocks decrypted secrets
#     and live state from being committed. See the hook header for the full
#     rule set.
#
# Run via: ./manage.py hooks install
# Or directly: bash orchestrator/scripts/hooks/install-hooks.sh
#
# Pure stdlib bash, no external dependencies.

set -euo pipefail

# Resolve repo root from script location (works regardless of cwd).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

if [ ! -d "$REPO_ROOT/.git" ]; then
	echo "[hooks] Not a git repository (no .git at $REPO_ROOT). Skipping install." >&2
	exit 0
fi

mkdir -p "$HOOKS_DIR"

install_hook() {
	local name="$1"            # pre-commit
	local src="$REPO_ROOT/orchestrator/scripts/hooks/$name"
	local dst="$HOOKS_DIR/$name"

	if [ ! -f "$src" ]; then
		echo "[hooks] Source $src missing — aborting." >&2
		return 1
	fi

	# If a non-symlink hook already exists and differs, back it up rather than
	# silently overwriting a user's hand-written hook.
	if [ -e "$dst" ] && [ ! -L "$dst" ]; then
		if cmp -s "$src" "$dst"; then
			chmod +x "$dst"
			echo "[hooks] $name already installed (file copy, identical)."
			return 0
		fi
		local backup="$dst.bak.$(date +%s)"
		mv "$dst" "$backup"
		echo "[hooks] Backed up existing $name -> $(basename "$backup")"
	fi

	# Always (re)point the symlink at the repo copy so edits to the tracked
	# script take effect without re-running the installer.
	ln -sfn "$src" "$dst"
	chmod +x "$src"
	echo "[hooks] Installed $name -> $src"
}

install_hook pre-commit

echo
echo "[hooks] Done. Verify with: ./manage.py hooks verify"