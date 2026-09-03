# 4b: Self-Hosted Runner Federation

> **Sub-Phase:** 4b  
> **Target:** Host Runner Labels & GitHub Environment Configuration  

---

## 1. Objective

Standardize the provisioning, labeling, and GitHub environment variables for all self-hosted runners across the cluster.

---

## 2. Runner Labeling Standard

Every runner registered on GitHub must have two essential labels:
1. `self-hosted` (standard GitHub identifier)
2. `<node-id>` (matching the key in `topology.yaml`, e.g. `vps-a`, `vps-b`, `nas-storage`)

Runners use a dedicated unprivileged OS account and runner group. Self-hosted deployment
runners accept only protected-branch `push` and manually approved environment jobs;
untrusted `pull_request` and `pull_request_target` workflows never execute on them.
Environment protection rules restrict approvers and deployment branches.

### Runner Registration Command Template:
```bash
./config.sh --url https://github.com/nt-louis/net-stream \
            --token <REGISTRATION_TOKEN> \
            --name "<node-id>-runner" \
            --labels "self-hosted,<node-id>" \
            --work "_work" \
            --unattended
```

---

## 3. GitHub Environment Secrets & Variables

For each node defined in `topology.yaml`, create a corresponding **GitHub Environment** (e.g. Environment `vps-a`, `vps-b`):

| Environment Name | Environment Variables | Secrets |
| :--- | :--- | :--- |
| `vps-a` | Node-specific `PROD_DIR` | `DOPPLER_TOKEN` (scoped to `net-stream-vps-a`) |
| `vps-b` | Node-specific `PROD_DIR` | `DOPPLER_TOKEN` (scoped to `net-stream-vps-b`) |
| `[future-node]` | Node-specific `PROD_DIR` | `DOPPLER_TOKEN` (scoped to `net-stream-<node>`) |

---

## 4. Verification Criteria
* GitHub Actions Settings ➔ Runners displays:
  * `vps-a-runner` with labels `[self-hosted, vps-a]`
  * `vps-b-runner` with labels `[self-hosted, vps-b]`
* Runner connection test succeeds and receives matrix jobs properly.
