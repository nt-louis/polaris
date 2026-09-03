#!/usr/bin/env bash
# ==============================================================================
# Net-Stream NetBird Server Update and Configuration Script
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
NETBIRD_DIR="$REPO_ROOT/Utilities/netbird-server"

# Load environment variables. First look for local .env, then root .env
if [[ -f "$NETBIRD_DIR/.env" ]]; then
    source "$NETBIRD_DIR/.env"
elif [[ -f "$REPO_ROOT/.env" ]]; then
    source "$REPO_ROOT/.env"
else
    if [[ -z "${NETBIRD_DOMAIN:-}" ]]; then
        echo "[ERROR] NETBIRD_DOMAIN is not set. Run this utility through Doppler or provide a configured environment." >&2
        exit 1
    fi
fi

echo "[INFO] Configuring NetBird Control Plane files..."

# Ensure data directories exist
mkdir -p "$NETBIRD_DIR/data/management" "$NETBIRD_DIR/data/signal"

# Manage persistent datastore encryption key
KEY_FILE="$NETBIRD_DIR/data/management/datastore_key"
if [[ -f "$KEY_FILE" ]]; then
    NETBIRD_DATASTORE_ENCRYPTION_KEY=$(cat "$KEY_FILE")
else
    echo "[INFO] Generating new persistent datastore encryption key..."
    NETBIRD_DATASTORE_ENCRYPTION_KEY=$(openssl rand -base64 32)
    echo -n "$NETBIRD_DATASTORE_ENCRYPTION_KEY" > "$KEY_FILE"
fi

# Generate management.json dynamically using variables loaded from the env
cat <<EOF > "$NETBIRD_DIR/management.json"
{
  "Stuns": [
    {
      "Proto": "udp",
      "URI": "stun:stun.l.google.com:19302",
      "Username": "",
      "Password": null
    },
    {
      "Proto": "udp",
      "URI": "stun:stun1.l.google.com:19302",
      "Username": "",
      "Password": null
    }
  ],
  "TURNConfig": {
    "Turns": [
      {
        "Proto": "udp",
        "URI": "turn:${NETBIRD_DOMAIN}:3478",
        "Username": "netbird",
        "Password": "${NETBIRD_RELAY_SECRET}"
      }
    ],
    "CredentialsTTL": "24h",
    "Secret": "${NETBIRD_RELAY_SECRET}",
    "TimeBasedCredentials": true
  },
  "Signal": {
    "Proto": "https",
    "URI": "${NETBIRD_DOMAIN}:443",
    "Username": "",
    "Password": null
  },
  "Relay": {
    "Addresses": [
      "rels://relay.${NETBIRD_DOMAIN}:443"
    ],
    "CredentialsTTL": "24h",
    "Secret": "${NETBIRD_RELAY_SECRET}"
  },
  "HttpConfig": {
    "Address": "0.0.0.0:33073",
    "AuthIssuer": "${OIDC_ISSUER}",
    "AuthAudience": "${OIDC_CLIENT_ID}",
    "OIDCConfigEndpoint": "${OIDC_ISSUER}/.well-known/openid-configuration"
  },
  "DeviceAuthorizationFlow": {
    "Provider": "hosted",
    "ProviderConfig": {
      "Audience": "${OIDC_CLIENT_ID}",
      "ClientID": "${OIDC_CLIENT_ID}",
      "Domain": "${OIDC_ISSUER}",
      "Scope": "openid profile email offline_access",
      "TokenEndpoint": "${OIDC_ISSUER}/api/oidc/token",
      "DeviceAuthEndpoint": "${OIDC_ISSUER}/api/oidc/device/authorize",
      "AuthorizationEndpoint": "${OIDC_ISSUER}/authorize"
    }
  },
  "IdpManagerConfig": {
    "ManagerType": ""
  },
  "DataDir": "/var/lib/netbird",
  "HttpAPIAddr": ":33073",
  "GrpcPort": "33073",
  "Store": "sqlite",
  "DataStoreEncryptionKey": "${NETBIRD_DATASTORE_ENCRYPTION_KEY}"
}
EOF

# Generate turnserver.conf for Coturn dynamically
cat <<EOF > "$NETBIRD_DIR/turnserver.conf"
listening-port=3478
lt-cred-mech
use-auth-secret
static-auth-secret=${NETBIRD_RELAY_SECRET}
realm=${NETBIRD_DOMAIN}
EOF

echo "[INFO] Booting NetBird server docker stack..."

# Run standard docker compose commands
docker compose -p utilities-netbird-server -f "$NETBIRD_DIR/docker-compose.yml" pull --ignore-pull-failures || true
docker compose -p utilities-netbird-server -f "$NETBIRD_DIR/docker-compose.yml" up -d --force-recreate

echo "[INFO] NetBird Control Plane stack started successfully!"
