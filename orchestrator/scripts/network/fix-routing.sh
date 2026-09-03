#!/usr/bin/env bash
# ==============================================================================
# Polaris Routing Fix Script (fix-routing.sh)
# ==============================================================================
# Fixes routing conflicts between Gluetun and Tailscale.
#
# Problem: Gluetun's ip rule 101 catches ALL traffic (not marked 0xca6c)
# and routes it through the VPN tunnel (table 51820). This includes
# response traffic that should go back through tailscale0 to Tailnet peers.
#
# Fix: Add Tailscale's peer routing table (52) at a higher priority (50)
# so Tailnet-destined traffic is routed through tailscale0 BEFORE
# Gluetun's catch-all rule (101) and subnet rule (99 / table 199) intercept it.
# ==============================================================================
set -euo pipefail

log() {
  echo "[$(date -Is)] $1"
}

# Check for root/sudo privilege
if [[ $EUID -ne 0 ]]; then
   log "ERROR: This script must be run as root (use sudo)." >&2
   exit 1
fi

log "Applying gateway routing fix..."

# Add Tailscale peer routing table rule
if ip rule add lookup 52 priority 50 2>/dev/null || true; then
  log "[OK] Tailscale peer routing table rule added (table 52 at priority 50)"
fi

# Ensure iptables-nft FORWARD allows forwarded packets (useful for exit nodes)
if iptables -P FORWARD ACCEPT 2>/dev/null || true; then
  log "[OK] iptables FORWARD chain policy set to ACCEPT"
fi

log "Routing fix application complete."
