# Phase 4: GitOps Matrix & Mesh Diagnostics

> **Phase:** 4 of 5  
> **Target:** Dynamic Multi-Runner Deployments & Cross-Node Mesh Healthchecks  
> **Status:** Draft / Actionable  

---

## 1. Overview & Objective

Phase 4 evolves the deployment and observability pipelines to be dynamically multi-node:
1. Replaces hardcoded `deploy-vps-a` and `deploy-vps-b` jobs in [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) with a **Dynamic GitHub Actions Deployment Matrix** that deploys only to nodes whose stacks were modified.
2. Standardizes self-hosted runner labeling (`[self-hosted, <node-id>]`) across all host machines.
3. Deploys a versioned, authenticated, read-only diagnostic agent on every node and
   uses it for cross-node mesh health checks without exposing Docker mutation access.

---

## 2. Granular Task Breakdown

| Document | Focus Area | Deliverable |
| :--- | :--- | :--- |
| [`4a-github-actions-matrix-deployment.md`](./4a-github-actions-matrix-deployment.md) | GitOps CD Pipeline | Dynamic matrix detection & deployment job in `deploy.yml`. |
| [`4b-self-hosted-runner-federation.md`](./4b-self-hosted-runner-federation.md) | Runner Provisioning | Self-hosted runner labeling, environment secrets, and provisioning guide. |
| [`4c-mesh-diagnostics-and-healthchecks.md`](./4c-mesh-diagnostics-and-healthchecks.md) | Mesh Observability | Cross-node status probing over Tailscale/NetBird for `--cluster` mode. |

---

## 3. Definition of Done (DoD) Checklist

- [ ] `deploy.yml` generates dynamic matrix: e.g. `["vps-a"]` if only VPS A files changed, `["vps-a", "vps-b"]` if both changed.
- [ ] Deployments run in parallel on target self-hosted runners.
- [ ] `./manage.py status --cluster` queries and reports remote node statuses over the Tailnet.
