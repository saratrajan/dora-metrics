# Bootstrap Plan: Portable DORA Metrics Stack

## Context

The `dora-metrics` repo (branch: `main`) has all the Kubernetes manifests, Helm charts, ArgoCD Application CRDs, and a Docker Compose local stack — but zero automation. Going from a fresh machine to a working DORA metrics dashboard today requires ~15 manual steps, knowledge of cluster names, label selectors, port-forwards, and tool prerequisites.

The goal: **clone the repo, run one script, get everything working.** No desktop-specific config. No manual kubectl patchwork.

---

## What Gets Built

### 1. `scripts/bootstrap.sh` — the single entry point

A bash script that runs the full stack on any machine with Docker + WSL/Linux. Does:

1. **Prerequisite check** — verifies `docker`, `kind`, `kubectl`, `helm`, `argocd` CLI are present; prints install hints if missing
2. **Create kind clusters** — `travel-lab` and `travel-prod` using embedded kind config (1 control-plane node each, with `extraPortMappings` for Grafana/ArgoCD/Prometheus)
3. **Install ArgoCD** in both clusters via kubectl (official install manifest, pinned version)
4. **Wait for ArgoCD to be ready** — polls until all pods are Running
5. **Apply the 4 ArgoCD Application manifests** from `argocd/` — this hands off all further installs to ArgoCD GitOps:
   - `kube-prometheus-stack-app.yaml` → ArgoCD installs Prometheus + Grafana
   - `monitoring-app.yaml` → ArgoCD syncs `monitoring/` (ServiceMonitors, PrometheusRule, dashboard ConfigMap)
   - `travel-flights-app.yaml` and `travel-hotels-app.yaml` → ArgoCD deploys microservices
6. **Build and kind-load microservice images** — `travel-flights:v1.0.5` and `travel-hotels:v1.0.5` for both clusters
7. **Trigger ArgoCD syncs** for all 4 apps (using `argocd` CLI)
8. **Wait for health** — polls `argocd app get` until all apps are `Healthy + Synced`
9. **Print access URLs** — Grafana, Prometheus, ArgoCD UI with port-forward commands

### 2. `scripts/kind-config.yaml` — reusable kind cluster config

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
```

Shared config for both clusters (no special port mappings needed — everything accessed via `kubectl port-forward`).

### 3. `scripts/teardown.sh` — clean reset

Deletes both kind clusters. One command to start fresh.

### 4. `scripts/deploy-version.sh VERSION` — version bump helper

Replaces the full manual flow the user just did for v1.0.3/v1.0.4/v1.0.5:
1. Bumps `apps/travel-flights/chart/values.yaml` and `apps/travel-hotels/chart/values.yaml` to `VERSION`
2. Builds both Docker images with that version
3. Loads images into `kind travel-lab`
4. Commits values.yaml changes and pushes
5. Syncs both ArgoCD apps

### 5. Updated `README.md`

Replace current manual steps with:
```
## Quickstart
git clone https://github.com/saratrajan/dora-metrics
cd dora-metrics
bash scripts/bootstrap.sh
```
Plus prerequisites section and troubleshooting tips.

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `scripts/bootstrap.sh` | **Create** |
| `scripts/teardown.sh` | **Create** |
| `scripts/deploy-version.sh` | **Create** |
| `scripts/kind-config.yaml` | **Create** |
| `README.md` | **Update** quickstart section |
| `context/dora-metrics.md` | **Update** to reflect scripts |

No changes to any manifests, Helm charts, or Go code.

---

## Key Design Decisions

- **ArgoCD does the heavy lifting** — bootstrap only installs ArgoCD; everything else (Prometheus, Grafana, microservices, monitoring) is applied via the existing `argocd/` manifests. No duplicate install logic in the script.
- **Pinned ArgoCD version** — `v2.13.x` (whatever is current stable) to avoid install drift
- **`imagePullPolicy: Never` stays** — images are loaded via `kind load docker-image` for both clusters; no registry needed
- **Both clusters bootstrapped by default** — `travel-lab` fully automated; `travel-prod` cluster created and ArgoCD installed, but apps pointed at prod are separate (user can add prod ArgoCD apps later)
- **No secrets in repo** — Grafana admin password stays `admin` (acceptable for local kind clusters); documented clearly
- **Idempotent** — script checks if clusters already exist before creating, skips steps that are already done
- **WSL-compatible** — uses `wsl -d Ubuntu -e bash -lc` pattern for kind/kubectl calls when running from Windows

---

## Prerequisites (documented in README)

- Docker Desktop (Windows/Mac) or Docker Engine (Linux)
- WSL2 with Ubuntu (Windows only)
- Tools installed in WSL: `kind`, `kubectl`, `helm`, `argocd` CLI
- `git` (any platform)
- ~4GB RAM free for kind clusters

---

## Verification Steps

After `bootstrap.sh` completes:

1. `kubectl get apps -n argocd --context kind-travel-lab` → all 4 apps Healthy/Synced
2. `kubectl port-forward svc/kube-prometheus-stack-grafana 3000:80 -n monitoring --context kind-travel-lab`
   → http://localhost:3000 → DORA dashboard → App Health shows 100%, All Services table shows travel-flights + travel-hotels
3. `kubectl port-forward svc/kube-prometheus-stack-prometheus 9090:9090 -n monitoring --context kind-travel-lab`
   → `dora:deployment_frequency:daily{dest_namespace=~".*lab.*"}` returns data
4. `bash scripts/deploy-version.sh v1.0.6` → new sync event recorded in Prometheus within 2 min

---

## Out of Scope

- `travel-prod` app deployment automation (cluster created, ArgoCD installed, but apps not applied — prod requires real images in a registry)
- Multi-node kind clusters
- TLS / ingress (everything via port-forward for local dev)
- CI/CD pipeline integration (GitHub Actions, etc.)