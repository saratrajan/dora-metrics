# DORA Metrics — ArgoCD + Prometheus + Grafana

Track Deployment Frequency, Change Failure Rate, Lead Time, and MTTR using your existing ArgoCD, Prometheus, and Grafana stack. No additional tools required.

---

## Architecture

```mermaid
flowchart LR
    classDef argo    fill:#E8461E,stroke:#bf3615,color:#fff
    classDef prom    fill:#E6522C,stroke:#c93f1a,color:#fff
    classDef storage fill:#C94C1E,stroke:#a33d17,color:#fff
    classDef grafana fill:#F5A623,stroke:#c8841a,color:#1a1a1a

    subgraph AC["ArgoCD"]
        E1([application-controller\n/metrics])
        E2([argocd-server\n/metrics])
        E3([repo-server\n/metrics])
    end

    subgraph PR["Prometheus"]
        S[(Time Series\nStore)]
        R[/DORA\nRecording Rules/]
    end

    subgraph GR["Grafana"]
        D[DORA Dashboard\nLab · Prod]
    end

    E1 & E2 & E3 -->|scrape every 30s| S
    S -->|evaluate every 1m| R
    R -->|PromQL| D

    class E1,E2,E3 argo
    class R prom
    class S storage
    class D grafana
```

---

## Local testing with Docker Compose

The `docker-compose/` directory spins up a self-contained stack — no Kubernetes or real ArgoCD required. It is useful for developing and testing the dashboard locally before applying anything to a cluster.

### What runs

| Service | Port | Endpoint | Description |
|---------|------|----------|-------------|
| `mock-exporter` | 8000 | `http://localhost:8000/metrics` | Python service that emits realistic ArgoCD-compatible Prometheus metrics for five travel-platform microservices |
| `prometheus` | 9090 | `http://localhost:9090` | Scrapes the mock exporter and evaluates the DORA recording rules every 15s |
| `grafana` | 3000 | `http://localhost:3000` | Loads the DORA dashboard automatically via provisioning |

The mock exporter simulates five services each in their own lab and prod namespaces (e.g. `search-service-lab`, `search-service-prod`) and seeds 24 hours of history so `increase()` queries return meaningful values from the very first scrape.

### Running the stack

```bash
cd docker-compose
sudo docker-compose up --build
```

Grafana is available at `http://localhost:3000` (credentials: `admin` / `admin`).

Once running, you can verify the mock exporter is serving metrics:

```bash
curl http://localhost:8000/metrics | grep argocd_app_sync_total
```

Expected output — one line per service/namespace/phase combination:

```
argocd_app_sync_total{dest_namespace="search-service-lab",...,phase="Succeeded"} 96.0
argocd_app_sync_total{dest_namespace="search-service-lab",...,phase="Failed"} 4.0
...
```

To stop and clean up:

```bash
sudo docker-compose down
```

### docker-compose files

| File | What it does |
|------|-------------|
| `docker-compose.yml` | Defines the three-service stack |
| `mock-exporter/exporter.py` | Mock ArgoCD Prometheus exporter — edit `SERVICES` here to change simulated services, rates, or health states |
| `prometheus/prometheus.yml` | Scrape config pointing at the mock exporter |
| `prometheus/rules.yml` | Same DORA recording rules used in production (`prometheusrule.yaml`), adapted for the local stack |
| `grafana/provisioning/` | Auto-provisions the Prometheus datasource and the DORA dashboard on startup |

---

## Files

| File | What it does |
|------|-------------|
| `servicemonitors.yaml` | Tells Prometheus to scrape ArgoCD's three metric endpoints every 30s |
| `prometheusrule.yaml` | Pre-computes DORA recording rules every 1 min from raw ArgoCD metrics |
| `grafana-dashboard-configmap.yaml` | Grafana dashboard with an `Environment` dropdown (lab / prod) — auto-loaded by the Grafana sidecar |
| `argocd-application.yaml` | ArgoCD Application that manages all the above via GitOps (optional — see below) |

---

## Before you apply

### 1. Match your Prometheus label selectors

Prometheus Operator only picks up ServiceMonitors and PrometheusRules that match its configured selectors. Check yours:

```bash
kubectl get prometheus -n monitoring -o jsonpath='{.items[0].spec.serviceMonitorSelector}' | jq .
kubectl get prometheus -n monitoring -o jsonpath='{.items[0].spec.ruleSelector}' | jq .
```

Replace the `release: prometheus` label in `servicemonitors.yaml` and `prometheusrule.yaml` with whatever the above returns.

### 2. Set your namespaces

| File | Field | Default | Change to |
|------|-------|---------|-----------|
| `servicemonitors.yaml` | `metadata.namespace` | `argocd` | Your ArgoCD namespace |
| `prometheusrule.yaml` | `metadata.namespace` | `argocd` | Your ArgoCD namespace |
| `grafana-dashboard-configmap.yaml` | `metadata.namespace` | `monitoring` | Your Grafana namespace |

### 3. Set your Grafana sidecar label

The ConfigMap uses `grafana_dashboard: "1"`. Confirm your sidecar watches this label — it is the default for `kube-prometheus-stack`. If yours differs, update `metadata.labels` in `grafana-dashboard-configmap.yaml`.

### 4. Verify the Prometheus data source exists in Grafana

```bash
kubectl port-forward svc/grafana 3000:80 -n monitoring
# Grafana UI → Connections → Data Sources — confirm "Prometheus" is listed
```

---

## Deployment plan — Lab first, then Prod

The Grafana dashboard has a built-in **Environment** dropdown (`lab` / `prod`). It filters all panels by `dest_namespace` on ArgoCD app metrics, so a single dashboard covers both environments.

### Phase 1 — Lab

```bash
# Apply manifests to your lab cluster (or lab-scoped namespaces)
kubectl apply -f servicemonitors.yaml
kubectl apply -f prometheusrule.yaml
kubectl apply -f grafana-dashboard-configmap.yaml
```

Wait ~2 minutes, then verify:

```bash
# Confirm ArgoCD targets are being scraped
kubectl port-forward svc/prometheus-operated 9090:9090 -n monitoring
# Prometheus UI → Status → Targets — look for argocd entries

# Confirm recording rules are computing
# Prometheus UI → Status → Rules — look for "dora.rules"

# Confirm dashboard loaded
kubectl port-forward svc/grafana 3000:80 -n monitoring
# Grafana → Dashboards → search "DORA Metrics"
# Set the Environment dropdown to "lab" and confirm data appears
```

Validate the dashboard shows expected deployment counts for lab before proceeding.

### Phase 2 — Prod

Once lab looks correct, apply the same files to your prod cluster or prod namespaces:

```bash
kubectl apply -f servicemonitors.yaml
kubectl apply -f prometheusrule.yaml
kubectl apply -f grafana-dashboard-configmap.yaml
```

Switch the dashboard **Environment** dropdown to `prod` to see prod metrics. Both environments share the same dashboard — toggle between them to compare failure rates before and after a rollout.

### Optional — GitOps management via ArgoCD

If you want ArgoCD to manage these manifests going forward instead of manual `kubectl apply`:

1. Update `argocd-application.yaml` — replace `repoURL` and `path` with your repo details
2. Apply once:
   ```bash
   kubectl apply -f argocd-application.yaml
   ```

ArgoCD will keep all manifests in sync with this repo automatically.

---

## Dashboard — Environment variable

The dashboard `$environment` variable defaults to `lab`. All six panels filter ArgoCD metrics by `dest_namespace=~".*$environment.*"` — meaning your ArgoCD app destination namespaces should contain the string `lab` or `prod` (e.g. `app-lab`, `payments-prod`). Adjust the regex in the dashboard JSON if your naming convention differs.

---

## Reference

- [ArgoCD Operator Manual — Metrics](https://argo-cd.readthedocs.io/en/latest/operator-manual/metrics/) — full list of available ArgoCD Prometheus metrics. Use this to extend the recording rules in `prometheusrule.yaml` or add panels to the Grafana dashboard as needed.
