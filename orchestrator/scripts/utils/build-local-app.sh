#!/usr/bin/env bash
# ==============================================================================
# Net-Stream Local App Builder Script (build-local-app.sh)
# ==============================================================================
# Unified builder for local source-built applications (fmhy, monochrome).
# Clones or updates the upstream repository, builds the Docker image outside
# the VPN namespace using host network mode, and redeploys the container.
# ==============================================================================
set -euo pipefail

# Anchor project directory to the repository root (three directories up from orchestrator/scripts/utils)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

log() {
  echo "[$(date -Is)] $1"
}

APP="${1:-}"

if [[ -z "$APP" ]]; then
  echo "[ERROR] Usage: $0 <fmhy|monochrome>" >&2
  exit 1
fi

case "$APP" in
  fmhy)
    APP_LABEL="FMHY Wiki"
    REL_DIR="Utilities/information/fmhy"
    REPO_URL="https://github.com/fmhy/edit.git"
    IMAGE_NAME="local/fmhy:latest"
    DOCKERFILE="Dockerfile"
    BUILD_ARGS=()
    ;;

  monochrome)
    APP_LABEL="Monochrome Music App"
    REL_DIR="Media/local-media/players/monochrome"
    REPO_URL="https://github.com/monochrome-music/monochrome.git"
    IMAGE_NAME="local/monochrome:latest"
    DOCKERFILE="docker/Dockerfile"

    # Load root .env and service .env for build arguments
    if [[ -f "$PROJECT_ROOT/.env" ]]; then
      set -a; source "$PROJECT_ROOT/.env"; set +a
    fi
    if [[ -f "$PROJECT_ROOT/$REL_DIR/.env" ]]; then
      set -a; source "$PROJECT_ROOT/$REL_DIR/.env"; set +a
    fi

    AUTH_ENABLED="${AUTH_ENABLED:-false}"
    AUTH_SECRET="${AUTH_SECRET:-changeme}"
    APPWRITE_ENDPOINT="${APPWRITE_ENDPOINT:-}"
    APPWRITE_PROJECT_ID="${APPWRITE_PROJECT_ID:-}"
    POCKETBASE_URL="${POCKETBASE_URL:-}"
    SESSION_MAX_AGE="${SESSION_MAX_AGE:-2592000}"

    BUILD_ARGS=(
      --build-arg AUTH_ENABLED="$AUTH_ENABLED"
      --build-arg AUTH_SECRET="$AUTH_SECRET"
      --build-arg APPWRITE_ENDPOINT="$APPWRITE_ENDPOINT"
      --build-arg APPWRITE_PROJECT_ID="$APPWRITE_PROJECT_ID"
      --build-arg POCKETBASE_URL="$POCKETBASE_URL"
      --build-arg SESSION_MAX_AGE="$SESSION_MAX_AGE"
    )
    ;;

  *)
    echo "[ERROR] Unknown application '$APP'. Expected: fmhy or monochrome" >&2
    exit 1
    ;;
esac

APP_DIR="$PROJECT_ROOT/$REL_DIR"
SRC_DIR="$APP_DIR/src"

log "[INFO] Updating source code for $APP_LABEL..."

if [[ -d "$SRC_DIR" ]]; then
  log "Pulling updates in $REL_DIR/src..."
  (cd "$SRC_DIR" && git pull --rebase --autostash) || log "[WARNING] git pull failed in $REL_DIR/src. Continuing with existing code."
else
  log "Cloning $APP_LABEL repository from $REPO_URL..."
  git clone "$REPO_URL" "$SRC_DIR" || log "[WARNING] git clone failed."
fi

if [[ -f "$APP_DIR/.dockerignore.template" ]]; then
  cp "$APP_DIR/.dockerignore.template" "$SRC_DIR/.dockerignore" || true
fi

if [[ -d "$SRC_DIR" ]]; then
  cd "$SRC_DIR"

  log "[INFO] Building the $APP_LABEL image ($IMAGE_NAME)..."
  if docker build --network host -t "$IMAGE_NAME" "${BUILD_ARGS[@]}" -f "$DOCKERFILE" .; then
    log "[OK] $APP_LABEL Docker image built successfully."
  else
    if docker image inspect "$IMAGE_NAME" &>/dev/null; then
      log "[WARNING] Docker build failed, but existing $IMAGE_NAME image was found. Proceeding with existing image."
    else
      log "[ERROR] Docker build failed and no $IMAGE_NAME image exists."
      exit 1
    fi
  fi
elif ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
  log "[ERROR] Source directory missing and no $IMAGE_NAME image found."
  exit 1
fi

log "[INFO] Restarting $APP_LABEL container..."
cd "$APP_DIR"
docker compose up -d --force-recreate

log "[OK] $APP_LABEL has been updated and redeployed successfully!"
