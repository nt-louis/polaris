# 3a: Cluster & Individual Service Placements

> **Sub-Phase:** 3a  
> **Target:** Dual-Level Placement Modeling & Network Rebinding  

---

## 1. Dual-Level Placement Models

Polaris supports two placement models to balance zero-friction moves with surgical rebalancing:

### Model 1: Cluster / Pod Level Placement (No Member Reconfiguration)
* **How it works:** An entire explicit namespace (for example `media-core`, including
  its owner Compose project and all member placements) changes node together.
* **Network Impact:** Member Compose files do not change. Internal services still use
  `127.0.0.1:<port>` through the shared namespace. The operator must nevertheless
  validate target VPN/Tailscale device access, ingress/DNS cutover, bind-mount state,
  and target port availability before changing the namespace's node.
* **Best for:** Core media stacks, Stremio addon clusters, or grouped utility stacks.

### Model 2: Individual Service Placement (With Network Rebinding)
* **How it works:** A single service is separated from its former cluster and moved to another node.
* **Network Requirement:** If the service previously used either `service:` or
  `container:` namespace sharing, the move must include a reviewed Compose change to:
  * A topology-registered local gateway on the new host, OR
  * Standalone Tailscale container sidecar, OR
  * Host networking / bridge network.

---

## 2. Declarative Syntax in `topology.yaml`

```yaml
gateways:
  media-core:
    node: "vps-a"
    type: "gluetun"
    owner:
      path: "Media/local-media/gateway"
      service: "gluetun"
      container_name: "media-gateway-core-gluetun"

# Exact paths override broader prefixes by longest-match resolution.
placements:
  - service_id: "open-webui"
    path: "Utilities/tools/open-webui"
    node: "gpu-node"
    gateway: null
    network:
      mode: "host"
      listen_ports: [{port: 8080, protocol: tcp}]
```

---

## 3. Verification Criteria
* Moving a gateway requires one atomic topology change that also moves every member
  placement; validation rejects a split namespace.
* Individual service overrides take precedence over cluster wildcards.
* A service move is blocked until its network rebinding, state mappings, secret-key
  parity, and target port ownership all validate.
