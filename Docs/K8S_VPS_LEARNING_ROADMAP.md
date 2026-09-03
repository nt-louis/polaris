# Kubernetes (k3s) 2-Node Learning Roadmap

A practical, project-based guide to building, managing, and automating a 2-node Kubernetes cluster across **VPS A** and **VPS B** over **Tailscale**.

> [!WARNING]
> This is experimental learning material, not a production deployment
> template. Never commit real credentials to Kubernetes manifests. Use a
> Kubernetes Secret, an external secret manager, or a development-only value
> supplied outside version control.

---

## 🏗️ Architecture Overview

```
                          ┌─────────────────────────────────────┐
                          │   Local Laptop / Admin Workstation │
                          │             kubectl / Helm          │
                          └──────────────────┬──────────────────┘
                                             │ (Tailscale / SSH)
                                             ▼
       ┌─────────────────────────────────────┴─────────────────────────────────────┐
       │                                                                           │
       ▼                                                                           ▼
┌──────────────────────────────────────────┐               ┌──────────────────────────────────────────┐
│              VPS A (Control Plane)       │               │              VPS B (Worker Node)         │
│  - k3s Server (API Server, Scheduler)   │ ◄──Tailscale─►│  - k3s Agent (Kubelet, Containerd)     │
│  - Traefik Ingress / cert-manager        │    Flannel    │  - Stateful / Stateless Worker Pods      │
│  - ArgoCD Controller                     │     Mesh      │  - Longhorn Replicated Storage           │
└──────────────────────────────────────────┘               └──────────────────────────────────────────┘
```

---

## 🚀 Stage 1: Cluster Bootstrap & Core Mechanics

### 1.1 Install k3s Control Plane (VPS A)
Run on **VPS A**:
```bash
# Install k3s server binding to Tailscale interface
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--node-ip=$(tailscale ip -4) --flannel-iface=tailscale0" sh -

# Extract node join token
sudo cat /var/lib/rancher/k3s/server/node-token
```

### 1.2 Join Worker Node (VPS B)
Run on **VPS B**:
```bash
K3S_URL="https://<VPS-A-TAILSCALE-IP>:6443"
K3S_TOKEN="<NODE-TOKEN-FROM-VPS-A>"

curl -sfL https://get.k3s.io | K3S_URL=$K3S_URL K3S_TOKEN=$K3S_TOKEN INSTALL_K3S_EXEC="--node-ip=$(tailscale ip -4) --flannel-iface=tailscale0" sh -
```

### 1.3 Configure Non-Root `kubectl` Access
By default, `k3s` stores the kubeconfig at `/etc/rancher/k3s/k3s.yaml` owned by `root`. To run `kubectl` commands **without `sudo`** on VPS A:

```bash
# Create local kube directory for your user account
mkdir -p ~/.kube

# Copy k3s config and set ownership
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
chmod 600 ~/.kube/config

# Add KUBECONFIG variable to your shell
echo "export KUBECONFIG=~/.kube/config" >> ~/.bashrc
source ~/.bashrc
```

### 1.4 Configure Remote `kubectl` on Laptop
Copy `/etc/rancher/k3s/k3s.yaml` from VPS A to `~/.kube/config` on your laptop, and change `server: https://127.0.0.1:6443` to `server: https://<VPS-A-TAILSCALE-IP>:6443`.

Verify cluster status (without `sudo`!):
```bash
kubectl get nodes -o wide
```

### 1.4 Deploy First App (`homarr-deployment.yaml`)
Create `homarr.yaml`:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: homarr
  labels:
    app: homarr
spec:
  replicas: 1
  selector:
    matchLabels:
      app: homarr
  template:
    metadata:
      labels:
        app: homarr
    spec:
      containers:
      - name: homarr
        image: ghcr.io/ajnart/homarr:latest
        ports:
        - containerPort: 7575
---
apiVersion: v1
kind: Service
metadata:
  name: homarr-service
spec:
  selector:
    app: homarr
  ports:
  - port: 80
    targetPort: 7575
  type: ClusterIP
```
Deploy and inspect:
```bash
kubectl apply -f homarr.yaml
kubectl get pods -o wide
kubectl logs -f deployment/homarr
```

---

## 🌐 Stage 2: Ingress Routing & Auto-SSL

### 2.1 Expose Apps via Ingress (`homarr-ingress.yaml`)
Create `ingress.yaml`:
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: homarr-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  rules:
  - host: homarr.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: homarr-service
            port:
              number: 80
```

### 2.2 Install `cert-manager` for Automatic TLS
```bash
# Install cert-manager via Helm
helm repo add jetstack https://charts.jetstack.io
helm repo update
helm install cert-manager jetstack/cert-manager --namespace cert-manager --create-namespace --set installCRDs=true

# Create ClusterIssuer
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: your-email@example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: traefik
EOF
```

---

## 💾 Stage 3: Stateful Workloads & Volume Management

### 3.1 Create PersistentVolumeClaim (PVC)
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
```

### 3.2 Deploy Stateful Database (`postgres-statefulset.yaml`)
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: "postgres"
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:16-alpine
        env:
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-credentials
              key: password
        volumeMounts:
        - name: postgres-db
          mountPath: /var/lib/postgresql/data
      volumes:
       - name: postgres-db
         persistentVolumeClaim:
           claimName: postgres-pvc
```

Create the development secret out of band before applying the StatefulSet:

```bash
kubectl create secret generic postgres-credentials \
  --from-literal=password='<development-only-value>'
```

### 3.3 Storage Resiliency Test
```bash
# Delete the database pod intentionally
kubectl delete pod postgres-0

# Watch k8s automatically recreate the pod and re-attach the volume with 0 data loss
kubectl get pods -w
```

---

## 🔄 Stage 4: Helm Packages & GitOps Automation (ArgoCD)

### 4.1 Install ArgoCD
```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

### 4.2 Connect GitOps Repository
Create an ArgoCD Application pointing to your Git repository:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: polaris-k8s
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://github.com/your-username/k8s-manifests.git'
    targetRevision: HEAD
    path: apps
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```
> **Result**: Any `git push` to your manifest repo automatically updates your live cluster!

---

## 🛡️ Stage 5: Pod Sidecars & Network Policies

### 5.1 Recreate Gateway Sidecar Pattern in Kubernetes
In Kubernetes, all containers inside the **same Pod** share the exact same network namespace (`127.0.0.1`):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: protected-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: protected-app
  template:
    metadata:
      labels:
        app: protected-app
    spec:
      containers:
      # Sidecar 1: Gluetun VPN Gateway
      - name: gluetun
        image: qmcgaw/gluetun:v3
        securityContext:
          capabilities:
            add: ["NET_ADMIN"]
      # Container 2: App routing traffic through Gluetun (127.0.0.1)
      - name: app
        image: nginx:alpine
```

### 5.2 Restrict Database Traffic with NetworkPolicies
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: db-allow-app-only
spec:
  podSelector:
    matchLabels:
      app: postgres
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: homarr
    ports:
    - protocol: TCP
      port: 5432
```

---

## 🛠️ Essential `kubectl` Troubleshooting Cheat Sheet

| Command | Purpose |
| :--- | :--- |
| `kubectl get pods -A` | List all pods across all namespaces |
| `kubectl get nodes -o wide` | Check node status & internal IP addresses |
| `kubectl logs -f <pod-name> -c <container-name>` | Stream container logs |
| `kubectl describe pod <pod-name>` | Inspect events, failures & mount errors |
| `kubectl exec -it <pod-name> -- sh` | Open interactive shell inside a running pod |
| `kubectl get events --sort-by='.metadata.creationTimestamp'` | View recent cluster system events |
| `kubectl top nodes / top pods` | Monitor CPU & RAM usage per node/pod |

---

## 🎓 Next Steps
1. Experiment with **Longhorn** for distributed storage replication between VPS A and VPS B.
2. Explore **Talos Linux** for immutable OS-level Kubernetes.
