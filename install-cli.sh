#!/usr/bin/env bash
# ==============================================================================
# install-cli.sh — Install net-stream CLI wrapper to user or system bin
# ==============================================================================
set -e

# Resolve repository root
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER_SRC="$REPO_ROOT/orchestrator/scripts/cli/net-stream"

# Default install target directory
PREFIX="${1:-$HOME/.local/bin}"
TARGET="$PREFIX/polaris"
TARGET_COMPAT="$PREFIX/net-stream"

echo "[cli] Installing net-stream CLI wrapper..."
echo "[cli] Source: $WRAPPER_SRC"
echo "[cli] Target: $TARGET"

mkdir -p "$PREFIX"
chmod +x "$WRAPPER_SRC"

# Create symlink
ln -sf "$WRAPPER_SRC" "$TARGET"
ln -sf "$WRAPPER_SRC" "$TARGET_COMPAT"

echo "[cli] Successfully installed: $TARGET -> $WRAPPER_SRC"

# Check if PREFIX is in PATH
case ":$PATH:" in
    *":$PREFIX:"*)
        echo "[cli] '$PREFIX' is in your PATH. You can now run 'polaris' or 'net-stream' from anywhere."
        ;;
    *)
        echo "[cli] NOTE: '$PREFIX' is NOT currently in your PATH."
        echo "[cli] Add it to your shell config (~/.bashrc or ~/.zshrc):"
        echo "        export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac
