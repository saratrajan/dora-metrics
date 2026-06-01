# DORA Metrics — Project Context

This file captures the full design, decisions, fixes, and current state of the
`dora-metrics` repo. Use it to resume work in a new session without re-deriving
context from the codebase.

---

## What this repo does

Tracks the four DORA metrics (Deployment Frequency, Change Failure Rate, Lead
Time, MTTR) using ArgoCD sync events as the data source. No additional agents
or instrumentation required — ArgoCD's built-in Prometheus metrics are enough.

**Production path** (Kubernetes, kube-prometheus-stack):
- `monitoring/servicemonitors.yaml` — Prometheus Operator scrapes ArgoCD's three metric endpoints every 30s
- `monitoring/prometheusrule.yaml` — DORA recording rules via PrometheusRule CRD
- `monitoring/grafana-dashboard-configmap-live.yaml` — Grafana dashboard for in-cluster kube-prometheus-stack

**GitOps path** (ArgoCD manages everything):
- `argocd/kube-prometheus-stack-app.yaml` — ArgoCD app that installs kube-prometheus-stack v69.3.2
- `argocd/monitoring-app.yaml` — ArgoCD app (`dora-monitoring`) that syncs `monitoring/` from this repo
- `argocd/travel-flights-app.yaml` — ArgoCD app for travel-flights microservice
- `argocd/travel-hotels-app.yaml` — ArgoCD app for travel-hotels microservice

**Local testing path** (Docker Compose):
- `docker-compose/` — self-contained stack (mock exporter + Prometheus + Grafana)
  that works without any Kubernetes or real ArgoCD

---

## Repo file map

```
dora-metrics/                              branch: feature/microservices
├── README.md
├── grafana-dashboard-configmap.yaml        # legacy root file — NOT actively used
├── context/
│   └── dora-metrics.md                     # ← this file
├── docs/
│   └── images/
│       ├── dashboard-view-lab.jpg
│       └── dashboard-view-prd.jpg
├── apps/
│   ├── travel-flights/
│   │   ├── Dockerfile                      # multi-stage, ARG VERSION=dev, port 9080
│   │   ├── app/main.go                     # Go HTTP server, version injected via ldflags
│   │   └── chart/
│   │       ├── Chart.yaml                  # appVersion: v1.0.2, version: 0.1.0
│   │       ├── values.yaml                 # image.tag: v1.0.2, namespace: travel-flights-lab
│   │       └── templates/
│   │           ├── deployment.yaml
│   │           └── service.yaml
│   └── travel-hotels/
│       ├── Dockerfile                      # port 9081
│       ├── app/main.go
│       └── chart/
│           ├── Chart.yaml                  # appVersion: v1.0.2, version: 0.1.0
│           ├── values.yaml                 # image.tag: v1.0.2, namespace: travel-hotels-lab
│           └── templates/
│               ├── deployment.yaml
│               └── service.yaml
├── argocd/
│   ├── kube-prometheus-stack-app.yaml      # installs kube-prometheus-stack v69.3.2
│   ├── monitoring-app.yaml                 # syncs monitoring/ from this repo
│   ├── travel-flights-app.yaml             # deploys flights chart → travel-flights-lab
│   └── travel-hotels-app.yaml             # deploys hotels chart → travel-hotels-lab
├── monitoring/
│   ├── grafana-dashboard-configmap-live.yaml  # in-cluster Grafana dashboard (15 fixes applied)
│   ├── prometheusrule.yaml
│   └── servicemonitors.yaml
└── docker-compose/
    ├── docker-compose.yml
    ├── mock-exporter/
    │   ├── Dockerfile
    │   └── exporter.py                     # 31 services × 2 envs, versioned metrics
    ├── prometheus/
    │   ├── prometheus.yml
    │   └── rules.yml                       # DORA rules (1h windows for local testing)
    └── grafana/
        └── provisioning/
            ├── datasources/
            │   └── prometheus.yaml         # uid: prometheus (must match dashboard JSON)
            └── dashboards/
                ├── provider.yaml
                └── dora-metrics.json       # local docker-compose dashboard
```

---

## Kubernetes clusters

| Cluster | kind name | Purpose |
|---------|-----------|---------|
| `kind-travel-lab` | `travel-lab` | Lab / development environment |
| `kind-travel-prod` | `travel-prod` | Production environment |

ArgoCD runs in both clusters. Each microservice and the monitoring stack are
deployed via ArgoCD GitOps from this repo (branch: `feature/microservices`).

---

## Microservices

### travel-flights
- **Port:** 9080 (8080 is taken by ArgoCD)
- **Namespace:** `travel-flights-lab`
- **Image:** `travel-flights:v1.0.2` (built locally, `kind load docker-image`)
- **imagePullPolicy:** `Never` (kind cluster)
- **Version injection:** `go build -ldflags "-X main.version=${VERSION}"` with `ARG VERSION=dev` in Dockerfile
- **Endpoints:** `/` (service info JSON), `/flights` (mock data), `/healthz`

### travel-hotels
- **Port:** 9081
- **Namespace:** `travel-hotels-lab`
- **Image:** `travel-hotels:v1.0.2`
- Same pattern as travel-flights

### Helm chart conventions (both services)
- All values via `{{ .Values.* }}` — nothing hardcoded in templates
- Resource limits: `cpu: 200m / memory: 128Mi`, requests: `cpu: 50m / memory: 64Mi`
- Readiness + liveness probes on `/healthz`
- Service: ClusterIP, port 80 → targetPort from values

---

## ArgoCD Application manifests

All four ArgoCD apps are in `argocd/` and committed on `feature/microservices`.
**All use manual sync only** — no `automated: {}` block. This is intentional to
control when deployments happen (for DORA data generation purposes).

| App name | File | Source | Destination namespace |
|----------|------|--------|-----------------------|
| `kube-prometheus-stack` | `kube-prometheus-stack-app.yaml` | Helm chart (prometheus-community), v69.3.2 | `monitoring` |
| `dora-monitoring` | `monitoring-app.yaml` | `monitoring/` path in this repo | `monitoring` |
| `travel-flights` | `travel-flights-app.yaml` | `apps/travel-flights/chart` in this repo | `travel-flights-lab` |
| `travel-hotels` | `travel-hotels-app.yaml` | `apps/travel-hotels/chart` in this repo | `travel-hotels-lab` |

All use `syncOptions: [CreateNamespace=true]`.

### kube-prometheus-stack Helm values
```yaml
grafana:
  adminPassword: admin
prometheus:
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false
    ruleSelectorNilUsesHelmValues: false
```

The two `NilUsesHelmValues: false` flags are critical — they tell the Prometheus
Operator to pick up ALL ServiceMonitors and PrometheusRules in the cluster, not
just ones labeled for the kube-prometheus-stack release.

---

## monitoring/ files

### grafana-dashboard-configmap-live.yaml
In-cluster Grafana dashboard. Key differences from the docker-compose version:

| Setting | Value |
|---------|-------|
| ConfigMap name | `dora-metrics-dashboard-live` |
| Dashboard uid | `dora-argocd-live` |
| Dashboard title | `DORA Metrics (ArgoCD Live)` |
| Default time range | `now-3h` to `now` |
| Refresh | `15s` |
| Datasource references | `${datasource}` variable (not hardcoded UID) |

**15 fixes applied (last session):**
- `now-3h` default time range
- `15s` auto-refresh
- `Deploys / hr` display name with `decimals: 1` on SLO stat
- `avg(... > 0)` filter on lead time stat (hides NaN series)
- `byRegexp` with `/30d avg/` for trend line overrides (Grafana 11.6.1 compatible)
- Per-service expressions in timeseries panels (not summed)
- `datasource` variable as first in templating list
- `All Services` table panel replacing old `Unhealthy Applications` panel
- App Health piechart: `Healthy`→green, `Progressing`→yellow, `Degraded`→`rgb(255, 166, 176)`

### prometheusrule.yaml
PrometheusRule CRD with DORA recording rules for in-cluster Prometheus.

### servicemonitors.yaml
ServiceMonitor CRDs for scraping ArgoCD's three metric endpoints
(`application-controller`, `argocd-server`, `repo-server`).

---

## Prometheus recording rules

Two rule sets: local (`docker-compose/prometheus/rules.yml`) and in-cluster
(`monitoring/prometheusrule.yaml`). Local uses 1h windows for fast feedback.

| Rule | Local | Production |
|------|-------|------------|
| `dora:deployment_frequency:daily` | 1h × 24 | 24h |
| `dora:change_failure_rate:7d` | 1h | 7d |
| `dora:lead_time_p95:1h` | 1h | 1h |

### Lead time rule

`argocd_app_reconcile_bucket` does not carry `dest_namespace`. Two approaches
have been tried:

1. **Join approach** (used in `prometheusrule.yaml`): join histogram with
   `argocd_app_info` via `group_left(dest_namespace)` on `(name, namespace)`.
   Risk: many-to-many if the same app name exists in lab AND prod — only an
   issue when both clusters are scraped by the same Prometheus.

2. **Exporter approach** (used in `docker-compose/prometheus/rules.yml`): the
   mock exporter emits `dest_namespace` on reconcile histograms directly,
   eliminating the join. The rule then uses simple `sum by (name, project, dest_namespace, le)`.

For the in-cluster case (separate clusters), the join is safe.

---

## Grafana dashboard — two versions

| File | Used by | Datasource ref |
|------|---------|----------------|
| `docker-compose/grafana/provisioning/dashboards/dora-metrics.json` | Docker Compose | `uid: prometheus` (hardcoded, matches datasource provisioning) |
| `monitoring/grafana-dashboard-configmap-live.yaml` | Kubernetes / kube-prometheus-stack | `${datasource}` variable |

**Do not** use `grafana-dashboard-configmap.yaml` (root-level legacy file) — it
is outdated and not referenced by anything active.

### Template variables (both dashboards, in order)
1. `datasource` — datasource picker (live dashboard only)
2. `environment` — custom: `lab,prod`, default `lab`
3. `project` — query: `label_values(argocd_app_info{dest_namespace=~".*$environment.*"}, project)`
4. `namespace` — query: `label_values(argocd_app_info{dest_namespace=~".*$environment.*"}, dest_namespace)`

**Critical:** `namespace` must have **no** `allValue` field. If `allValue: ".*"`
is set, "All" bypasses the environment filter entirely.

### App Health piechart color overrides
- `Healthy` → `green`
- `Progressing` → `yellow`
- `Degraded` → `rgb(255, 166, 176)` (light red/pink)

---

## Mock exporter (`docker-compose/mock-exporter/exporter.py`)

31 microservices × 2 environments (lab + prod) = 62 ArgoCD app simulations.

| Team | Services |
|------|---------|
| Flight | `flight-search`, `flight-booking`, `seat-selector`, `check-in-service`, `baggage-tracker` |
| Hotel | `hotel-search`, `hotel-booking`, `hotel-reviews` |
| Cruise (newest) | `cruise-planner`, `cruise-booking`, `cruise-excursions` |
| Car rental | `car-rental` |
| Payments | `payment-gateway`, `payment-processor`, `fraud-detection`, `refund-processor`, `currency-converter`, `wallet-service` |
| Travel extras | `travel-insurance`, `itinerary-builder`, `visa-advisor` |
| Customer | `loyalty-rewards`, `review-aggregator`, `recommendation-engine` |
| Core platform | `search-service`, `booking-manager`, `inventory-service`, `notification-service`, `price-engine` |
| Partner/API | `partner-api`, `supplier-connector` |

Namespace naming: `<service>-lab` / `<service>-prod` (e.g. `flight-search-lab`).

### Key implementation details
- Tick: every 15s, Poisson-sampled deploy events
- Histogram: raw (non-cumulative) bucket counts stored; cumulative computed at collection time
- `dest_namespace` is emitted on reconcile histograms (eliminates join requirement)
- Versions auto-bump after N syncs: 80% patch, 15% minor, 5% major
- Counters pre-seeded with history: cruise = 20–45 days, core platform = 365 days

---

## Running locally

```bash
cd docker-compose
sudo docker-compose up --build        # first run / after code changes
sudo docker-compose up -d             # subsequent runs
sudo docker-compose down              # tear down
```

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin / admin |
| Prometheus | http://localhost:9090 | — |
| Mock exporter | http://localhost:8000/metrics | — |

Note: user `saratrajan` needs `sudo` (not in docker group). Fix: `sudo usermod -aG docker saratrajan` + re-login.

---

## Versions pinned

| Component | Version |
|-----------|---------|
| Grafana (docker-compose) | `grafana/grafana:11.6.1` |
| Prometheus (docker-compose) | `prom/prometheus:v2.51.2` |
| Mock exporter base | `python:3.12-slim` |
| prometheus-client | `0.20.0` |
| kube-prometheus-stack (Helm) | `69.3.2` |
| Go microservices | `golang:1.22-alpine` (builder), `alpine:3.19` (runtime) |
| Microservice version | `v1.0.2` |

---

## Git / workflow rules

- **Always ask before `git push`** — never push without explicit user approval
- Branch: `feature/microservices` (all current work is here)
- Remote: `https://github.com/saratrajan/dora-metrics.git`
- Git author email: `5793844+saratrajan@users.noreply.github.com`
- Commit style: natural, concise messages

---

## Known issues / pending work

### dora-monitoring ArgoCD app OutOfSync/Missing
The `dora-monitoring` ArgoCD application (which syncs `monitoring/` from this
repo) was showing OutOfSync or Missing status at the end of the last session.
Root cause not fully diagnosed. kube-prometheus-stack pods in `monitoring`
namespace were healthy. Next step: `kubectl describe app dora-monitoring -n argocd`
on `kind-travel-lab`.

### Prod deploys showing 0.0
`travel-prod` cluster services have low deploy rates. `increase([1h])` needs
actual events since Prometheus restart. Not broken — needs real events or wider
window (e.g. `[6h]`).

### grafana-dashboard-configmap.yaml at root
There is still a `grafana-dashboard-configmap.yaml` at the repo root (legacy).
It is not referenced by any active ArgoCD app. Can be deleted when convenient.

### No MTTR panel
`dora:mttr_proxy:1h` recording rule exists in `prometheusrule.yaml` but no
dashboard panel has been built for it yet.

### Future: Kustomize migration
Extract the ConfigMap's embedded JSON to a standalone file; use
`configMapGenerator` in `kustomization.yaml` to eliminate JSON-in-YAML
maintenance burden.

### byRegexp note (Grafana 11.6.1)
`byNamePattern` was removed in Grafana 11.x. All trend line overrides use
`byRegexp` with `options: "/30d avg/"`. Do not revert to `byNamePattern`.
