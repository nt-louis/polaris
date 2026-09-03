# 1a: Central Topology Manifest Specification (`topology.yaml`)

> **Sub-Phase:** 1a  
> **Target:** `topology.yaml` & `Scripts/deploy/core/topology.py`  

---

## 1. Specification: Nested `topology.yaml`

The manifest defines four distinct contracts. These contracts are authoritative for
discovery, validation, deployment, diagnostics, and migration; no consumer may infer
placement from a directory named after a node.

1. **Repository roots:** The retained functional layout to scan (`Network/`, `Media/`,
   and `Utilities/`).
2. **Nodes:** Physical hosts, aliases, mesh endpoints, and Doppler projects.
3. **Network namespaces:** Every real shared namespace, including the exact Compose
   owner service and runtime container name used by `service:` and `container:` modes.
4. **Placements:** Ordered, non-overlapping path rules that map every active Compose
   project to one node and, where applicable, one namespace.

```yaml
version: "1.0"
cluster_name: "net-stream"
default_node: "vps-a"

repository:
  compose_roots: ["Network", "Media", "Utilities"]
  excluded_roots: ["Archived", "data", "state"]

nodes:
  vps-a:
    name: "Primary Ingress & Core Media Node"
    description: "Core media server, ingress gateway, authentication, and personal cloud"
    doppler_project: "net-stream-vps-a"
    aliases: ["vps-a"]
    tailscale_fqdn: "vps-a.<tailnet-suffix>"
    tags: [core, ingress, media, storage, auth]
    backup:
      repository: "rclone:gdrive:backups/net-stream/vps-a"

  vps-b:
    name: "Stremio Addons & Secondary Utilities Node"
    description: "Stremio scrapers, debrid caching, download helpers, and secondary developer tools"
    doppler_project: "net-stream-vps-b"
    aliases: ["vps-b"]
    tailscale_fqdn: "vps-b.<tailnet-suffix>"
    tags: [stremio, scrapers, compute, ai]
    backup:
      repository: "rclone:gdrive:backups/net-stream/vps-b"

# Each entry is one real shared network namespace. `owner` resolves an
# intra-project `service:` reference; `container_name` resolves cross-project
# `container:` references. The implementation manifest must enumerate all current
# namespaces, including network, exit-node, core-media, comics, Stremio addons,
# Proton addons, Stremio utilities, general utilities, and Nextcloud cloud.
gateways:
  network-gateway:
    node: "vps-a"
    type: "gluetun"
    owner:
      path: "Network"
      service: "gluetun"
      container_name: "network-gateway-gluetun"

  media-core:
    node: "vps-a"
    type: "gluetun"
    owner:
      path: "Media/local-media/gateway"
      service: "gluetun"
      container_name: "media-gateway-core-gluetun"
    tailscale_fqdn: "core.<tailnet-suffix>"

  media-comics:
    node: "vps-a"
    type: "gluetun"
    owner:
      path: "Media/comics/gateway"
      service: "gluetun"
      container_name: "media-gateway-comics-gluetun"
    tailscale_fqdn: "comics.<tailnet-suffix>"

  stremio-addons-gateway:
    node: "vps-b"
    type: "gluetun"
    owner:
      path: "Media/stremio/addons/gateway"
      service: "gluetun"
      container_name: "media-gateway-stremio-addons-gluetun"
    tailscale_fqdn: "addons.<tailnet-suffix>"

  stremio-proton-gateway:
    node: "vps-b"
    type: "gluetun"
    owner:
      path: "Media/stremio/addons/gateway-proton"
      service: "gluetun"
      container_name: "media-gateway-proton-gluetun"

  stremio-utilities-gateway:
    node: "vps-b"
    type: "gluetun"
    owner:
      path: "Media/stremio/utilities/gateway"
      service: "gluetun"
      container_name: "media-gateway-stremio-utilities-gluetun"

  utilities-gateway:
    node: "vps-a"
    type: "gluetun"
    owner:
      path: "Utilities/gateway"
      service: "gluetun"
      container_name: "utilities-gateway-gluetun"

  utilities-cloud-gateway:
    node: "vps-a"
    type: "gluetun"
    owner:
      path: "Utilities/cloud-docs/nextcloud/gateway"
      service: "gluetun"
      container_name: "utilities-gateway-cloud-gluetun"

  utilities-exit-node:
    node: "vps-a"
    type: "gluetun"
    owner:
      path: "Utilities/exit-node"
      service: "gluetun"
      container_name: "utilities-exit-node-gluetun"

# Rules are evaluated by exact path first, then by longest directory prefix.
# Equal-specificity matches are invalid. This sample is abbreviated; the committed
# manifest must classify every discovered active Compose project explicitly. `gateway`
# means shared Linux namespace, not merely common ingress; bridge/host projects use null.
placements:
  - path: "Media/stremio/addons/gateway-proton"
    node: "vps-b"
    gateway: "stremio-proton-gateway"
  - path: "Media/stremio/addons"
    node: "vps-b"
    gateway: "stremio-addons-gateway"
  - path: "Media/stremio/utilities"
    node: "vps-b"
    gateway: "stremio-utilities-gateway"
  - path: "Media/comics"
    node: "vps-a"
    gateway: "media-comics"
  - path: "Media/local-media"
    node: "vps-a"
    gateway: "media-core"
  - path: "Utilities/admin/coolify"
    node: "vps-b"
    gateway: null
  - path: "Utilities/cloud-docs/nextcloud"
    node: "vps-a"
    gateway: "utilities-cloud-gateway"
  - path: "Utilities/exit-node"
    node: "vps-a"
    gateway: "utilities-exit-node"
  - path: "Utilities"
    node: "vps-a"
    gateway: null
  - path: "Network"
    node: "vps-a"
    gateway: "network-gateway"
```

---

## 2. Implementation: `Scripts/deploy/core/topology.py`

```python
import os
import yaml

TOPOLOGY_FILE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "topology.yaml")
)

_CACHED_TOPOLOGY = None

def load_topology(force_reload=False):
    """Load and validate topology.yaml, returning the parsed dict."""
    global _CACHED_TOPOLOGY
    if _CACHED_TOPOLOGY is not None and not force_reload:
        return _CACHED_TOPOLOGY

    if not os.path.exists(TOPOLOGY_FILE):
        raise FileNotFoundError(f"Topology manifest not found at: {TOPOLOGY_FILE}")

    with open(TOPOLOGY_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Validate essential schema fields
    if "nodes" not in data or not isinstance(data["nodes"], dict):
        raise ValueError("Invalid topology.yaml: missing 'nodes' dictionary")
    if "gateways" not in data or not isinstance(data["gateways"], dict):
        raise ValueError("Invalid topology.yaml: missing 'gateways' dictionary")

    _CACHED_TOPOLOGY = data
    return data

def resolve_placement(service_rel_path):
    """Return the single explicit placement for a repository-relative path."""
    topo = load_topology()
    matches = [
        rule for rule in topo["placements"]
        if service_rel_path == rule["path"]
        or service_rel_path.startswith(rule["path"] + os.sep)
    ]
    if not matches:
        raise ValueError(f"No topology placement for {service_rel_path}")
    longest = max(len(rule["path"].split("/")) for rule in matches)
    winners = [rule for rule in matches if len(rule["path"].split("/")) == longest]
    if len(winners) != 1:
        raise ValueError(f"Ambiguous topology placement for {service_rel_path}")
    return winners[0]
```

---

## 3. Verification Criteria
* Schema validation rejects unknown node/gateway references, duplicate namespace
  owners/container names, overlapping equal-specificity placements, and unclassified
  active Compose projects.
* `resolve_placement("Media/local-media/players/jellyfin")` returns `vps-a` and
  `media-core`.
* `resolve_placement("Media/stremio/addons/jackett")` returns `vps-b` and
  `stremio-addons-gateway`.
