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
dora-metrics/                              branch: main
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
│   ├── grafana-dashboards-deploy-freq.yaml    # ConfigMap with all 4 DF dashboards (overview, rankings, trends, leaderboard)
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
                ├── dora-metrics.json       # local docker-compose dashboard (DORA overview)
                ├── df-overview.json        # Deployment Frequency screen 1 — namespace stats + tier donut
                ├── df-rankings.json        # Deployment Frequency screen 2 — top/bottom 10 bar gauges
                └── df-trends.json          # Deployment Frequency screen 3 — trends + inventory + drill-down
```

---

## Kubernetes clusters

| Cluster | kind name | Purpose |
|---------|-----------|---------|
| `kind-travel-lab` | `travel-lab` | Lab / development environment |
| `kind-travel-prod` | `travel-prod` | Production environment |

ArgoCD runs in both clusters. Each microservice and the monitoring stack are
deployed via ArgoCD GitOps from this repo (branch: `main`).

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

All four ArgoCD apps are in `argocd/` and committed on `main`.
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

---

## Deployment Frequency — TV slideshow dashboards

Four focused dashboards designed for big-screen / slideshow display. All use `uid: prometheus`
datasource and 30s refresh. Variables: `$environment` (lab/prod) and `$namespace` (multi-select).
Screen 3 also has `$app` for service drill-down. Screen 4 also has `$period` (7d / 30d).

All four are embedded in `monitoring/grafana-dashboards-deploy-freq.yaml` (ConfigMap name:
`deploy-frequency-dashboards`, label `grafana_dashboard: "1"`) for in-cluster Grafana via
ArgoCD `dora-monitoring` app. Added via branch `feature/configmap_leaderboard`.

| File | UID | Panels | Purpose |
|------|-----|--------|---------|
| `df-overview.json` | `dora-df-overview` | 10 | 6 namespace stat tiles + stacked area by service + DORA tier donut |
| `df-rankings.json` | `dora-df-rankings` | 3 | Top 10 / Bottom 10 deployers as horizontal bar gauges |
| `df-trends.json` | `dora-df-trends` | 12 | Namespace aggregate + DORA bands, 15m burst rate, cumulative count, full service inventory table, per-service drill-down |
| `df-leaderboard.json` | `dora-df-leaderboard` | 15 | Gamified weekly/monthly race: 🚀 Pole Position / ⚡ Fast Lane / 🔥 Hot Pursuit podium, Biggest Climbers/Fallers bargauges, ranked table (this period vs last period + Change column), New Entries / Improved / Declined stats, deploy velocity race timeseries |

All 25 panels from the original monolithic `deployment-frequency.json` are
preserved across the three files (that file has been deleted).

### Design decisions
- **Top/Bottom 10** (not 15) on the rankings screen — keeps bar gauges readable on TV
- **No `$app` variable on screens 1 & 2** — fewer dropdowns in slideshow mode
- **Stat text sizes explicit** (`titleSize: 14, valueSize: 40–52`) for TV legibility
- **DORA thresholds:** Red < 0.14/hr · Yellow 0.14–1/hr · Green ≥ 1/hr (1h windows, local testing)
- **Bottom 10 title** is neutral ("Services with Lowest Deploy Activity") — not shaming
- `or vector(0)` guards on all tier-count queries to prevent empty donut slices

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
- Branch: `main` (all current work is here)
- Remote: `https://github.com/saratrajan/dora-metrics.git`
- Git author email: `5793844+saratrajan@users.noreply.github.com`
- Commit style: natural, concise messages

---

## Project timeline & thought process

Reconstructed from `git log --all`. Captures not just what changed but why, so
a new session can understand the reasoning chain without re-reading the code.

---

### Phase 1 — Foundation (2026-05-29)

**`73f04f7` Initial commit**
First real skeleton: `README.md`, `argocd-application.yaml`,
`grafana-dashboard-configmap.yaml`, `prometheusrule.yaml`,
`servicemonitors.yaml`. Established the core insight: ArgoCD's built-in
Prometheus metrics (`argocd_app_sync_total`, `argocd_app_reconcile_bucket`)
are sufficient for all four DORA metrics — no extra instrumentation needed.

**`c14b28b` Add SLO stat panels and 30-day trend lines**
First iteration of the dashboard went beyond raw panels and added SLO stat
tiles and 30-day trend overlays. Aim: make the dashboard actionable, not just
decorative.

**`2c4685d` Add docker-compose local testing stack**
Critical decision: Kubernetes is too slow a feedback loop for dashboard
development. Introduced a `local-test/` (later renamed `docker-compose/`)
directory with three containers — mock exporter, Prometheus, Grafana — that
simulate ArgoCD without any cluster. Started with 5 services. This became
the primary dev environment for all subsequent dashboard work.

**`74a47b7` Fix Grafana datasource UID**
First bug: the dashboard JSON referenced the datasource by UID but the
provisioned datasource had no explicit UID, so all panels were empty.
Fix: add `uid: prometheus` to `prometheus.yaml`. Lesson: always hard-code the
datasource UID in both the provisioning YAML and the dashboard JSON.

**`903bccb` Fixes to exporter and dashboard**
Large expansion — dashboard got more panels, exporter gained richer metric
simulation. Rules file tuned.

**`399b704` Major exporter rewrite**
Grew the mock from 5 to 31 microservices across 8 teams (flight, hotel,
cruise, payments, etc.), added Poisson-sampled deploy events, version
auto-bumping (80% patch / 15% minor / 5% major), and pre-seeded history
(cruise 20-45 days, core platform 365 days). The goal was enough variety in
deploy rates to exercise all four DORA tiers on the dashboard at the same time.

**`487a06d` First context file**
Committed `context/dora-metrics.md` to allow future Claude sessions to
resume without re-deriving everything from the code. This pattern
(context-as-code) became a recurring practice.

---

### Phase 2 — Deployment Frequency metric fix (2026-05-29)

**`be6d025` Remove ×24 extrapolation from deploy frequency**
The original recording rule multiplied the 1h rate by 24 to get
"deploys/day". This was wrong for local testing: with a 1h window, you get
at most a handful of events, and ×24 produced misleadingly large numbers.
Decision: drop the extrapolation entirely and display raw deploys/hr. The
DORA tier thresholds were scaled accordingly (Elite ≥ 1/hr instead of 1/day).
This is a local-only convention — the in-cluster rule still uses 24h windows.

**`640e7d5` Fix Deployment Frequency panel bug**
Panel-level fix following the recording rule change.

---

### Phase 3 — Grafana upgrade + microservices (2026-05-31)

**`e818e0a` Grafana 10.x → 11.x**
Upgraded the docker-compose Grafana image. Grafana 11 removed `byNamePattern`
for field overrides — all subsequent dashboards use `byRegexp` instead. This
broke any session that tried to copy overrides from older dashboard JSON.

**`6dbded3` App Health piechart color fix**
`Degraded` was red by default but the Grafana red was too harsh. Changed to
`rgb(255, 166, 176)` (light pink/red) to keep it readable without alarming.

**`b553c9a` → `eb1be48` → `58799f0` Introduce travel-flights and travel-hotels**
Added two real Go microservices to the repo — not just for show, but to
produce real ArgoCD sync events for DORA data generation. Each service is a
simple HTTP server with version injected at build time via `go build -ldflags`.
Version bumps later drove `argocd_app_sync_total` counters in the live cluster.

**`bd02a1b` ArgoCD apps for flights and hotels**
Wired the Helm charts into ArgoCD (`argocd/travel-flights-app.yaml`,
`argocd/travel-hotels-app.yaml`). Both use manual sync intentionally — you
trigger syncs yourself to control DORA data generation, rather than having
ArgoCD auto-deploy and making the metrics non-deterministic.

**`82dfa7e` → `4d716b0` Monitoring folder refactor**
Moved `grafana-dashboard-configmap.yaml` and Prometheus files under
`monitoring/`. Deleted the old root-level `argocd-application.yaml` (replaced
by the per-resource files in `argocd/`). The root-level
`grafana-dashboard-configmap.yaml` was NOT deleted and remains as legacy.

**`d2645f8` In-cluster dashboard**
Created `monitoring/grafana-dashboard-configmap-live.yaml` — a Grafana
dashboard ConfigMap deployed by ArgoCD into kube-prometheus-stack. Key
difference from the docker-compose version: uses a `${datasource}` Grafana
variable instead of a hardcoded UID, since the in-cluster datasource name
varies.

**`d5951b0` kube-prometheus-stack + monitoring ArgoCD apps**
Added `argocd/kube-prometheus-stack-app.yaml` (installs kube-prometheus-stack
v69.3.2 via Helm) and `argocd/monitoring-app.yaml` (syncs `monitoring/` from
this repo). The two critical Helm values:
`serviceMonitorSelectorNilUsesHelmValues: false` and
`ruleSelectorNilUsesHelmValues: false` — without these, the Prometheus
Operator ignores ServiceMonitors and PrometheusRules created outside the
kube-prometheus-stack release.

---

### Phase 4 — In-cluster datasource debugging (2026-05-31)

Four rapid-fire commits to fix the in-cluster dashboard's datasource variable:

| Commit | What broke | Fix |
|--------|-----------|-----|
| `9ab41e4` | Initial in-cluster fixes | General panel/query corrections |
| `23fcde3` | `${datasource}` not resolving | Added datasource variable definition |
| `48ae15c` | Variable default using UID | Changed default to use name, not UID |
| `bba2335` | Variable not refreshing on load | Added `refresh: 1` |
| `03fda49` | Still resolving wrong datasource | Hard-coded the prometheus datasource UUID in all panel targets |
| `b0eef2a` | Redundant namespace filter | Removed it |

Root cause: Grafana variable chaining for datasource selectors is finicky. The
`${datasource}` interpolation only works correctly when the variable has
`current.value` set to the actual datasource UID, not the display name.
`refresh: 1` (on load) is required for the variable to pick up the live
datasource list before panels render.

---

### Phase 5 — Generating real DORA data (2026-05-31)

Series of version bumps on the travel-flights and travel-hotels charts to
produce real ArgoCD sync events:

```
v1.0.2 → v1.0.3 → v1.0.4 → v1.0.5 → rollback to v1.0.3 → redeploy v1.0.4
```

Each `helm upgrade` triggered by an ArgoCD manual sync increments
`argocd_app_sync_total{phase="Succeeded"}`, which feeds the DORA recording
rules. The rollback (`d3dcd50`) was intentional — to test Change Failure Rate
and MTTR panels with a real failure event.

**`a38185c` Fix recording rules — join for dest_namespace**
`argocd_app_sync_total` carries `dest_namespace` but
`argocd_app_reconcile_bucket` does not. Added a `group_left(dest_namespace)`
join with `argocd_app_info` on `(name, namespace)` to propagate the label to
lead time rules. Safe when lab and prod are on separate clusters (no
many-to-many collision). The docker-compose mock exporter avoids this entirely
by emitting `dest_namespace` directly on reconcile metrics.

---

### Phase 6 — Stabilization & rule fixes (2026-05-31)

**`3270b7d` Bootstrap context**
Added `context/plan-bootstrap.md` as a planning scratchpad for cluster
bootstrapping steps.

**`7dfb9ad` Fix lead time rule — drop broken join**
A previous version of the lead time rule used `name` as a join key between
`argocd_app_reconcile_bucket` and `argocd_app_info`. Problem: the reconcile
bucket has no `name` label (it uses `app`). Fixed by dropping the join
attempt and simplifying the rule to use what the exporter actually emits.

**`1f50fe5` → `99c397f` → `4035c5d` ArgoCD pointing + CFR fix**
- `monitoring-app.yaml` and `travel-flights-app.yaml` had `targetRevision` set
  to a feature branch; corrected to `main`.
- A chart `values.yaml` referenced a container tag that didn't exist in the
  local kind registry.
- CFR (`dora:change_failure_rate:7d`) prometheusrule was incorrect —
  the failure detection expression was over-broad, counting non-failure syncs.
  Fixed the PromQL to properly identify `phase="Failed"` vs total syncs.

---

### Phase 7 — TV Deployment Frequency dashboards (2026-06-04)

**`df-leaderboard.json` — Gamified leaderboard dashboard (screen 4 of 4)**

15 panels across 4 rows. Uses `$period` variable (7d / 30d) to compare this period vs last. Key panels:
- **Top 3** (🚀 Pole Position `#E53935` / ⚡ Fast Lane `#1E88E5` / 🔥 Hot Pursuit `#FB8C00`): `topk(1/2/3)` with `unless` chaining to isolate each rank. Gold/Silver/Bronze deliberately avoided — those terms conflict with the DevOps maturity model used in this project.
- **Climbers / Fallers bargauges**: positive/negative delta filtered with `> 0` / `< 0`, fallers negated for clean bar display
- **Leaderboard table**: two instant queries (A = this period, B = last period offset $period), merged and `calculateField` binary subtraction for Change column, color-coded red/gray/green
- **New Entries stat**: `unless` vector matching to find services with zero last period
- **Race timeseries**: `topk(10, dora:deployment_frequency:daily)` over the time window

`$period` variable interpolated as PromQL offset: `offset $period` → `offset 7d`.

---

**`b791c6e` Three TV-optimised Deployment Frequency dashboards** (branch: `feature/deployment-frequency`)

The original `dora-metrics.json` dashboard covers all four DORA metrics in one
view. The ask was a dedicated, deeper Deployment Frequency experience split into
TV slideshow screens — informational, not shaming, readable from across a room.

**Design sequence:**

1. **Prototype as one file first** — built `deployment-frequency.json` (25
   panels, 6 rows) to validate all the queries and layouts before splitting.
   This was never committed to main; it was a working draft.

2. **Decided on 3 screens, not 4** — the original split idea had
   Trend & Cadence as its own screen, but Trends + Inventory + Drill-down
   fit cleanly on one screen since the TV audience doesn't need to see all
   three simultaneously.

3. **Screen 1 — Overview** (`df-overview.json`, uid: `dora-df-overview`):
   6 stat tiles (DORA Tier, Deploys/hr, Active Services, Elite Services,
   Success Rate, Top Deployer) + stacked area by service + DORA tier donut.
   Stat text sizes explicit (`titleSize: 14`, `valueSize: 40-52`) for TV.
   No `$app` drill-down variable — keeps the header bar minimal in slideshow mode.

4. **Screen 2 — Rankings** (`df-rankings.json`, uid: `dora-df-rankings`):
   Started as Top/Bottom 15, changed to **Top/Bottom 10** before commit.
   Reason: 15 bars on a TV are too small to read service names without walking
   up to the screen. 10 bars give each service enough vertical height.
   Bottom panel title deliberately neutral — "Services with Lowest Deploy
   Activity" rather than "Slowest" — per the ask to avoid shaming.

5. **Screen 3 — Trends & Services** (`df-trends.json`, uid: `dora-df-trends`):
   All three trend charts (namespace aggregate with DORA bands, 15m burst rate,
   cumulative count), full service inventory table (colour-coded by DORA tier,
   sortable, footer with namespace total), and per-service drill-down section
   with `$app` variable. This is the interactive screen — not for passive
   slideshow but for when someone walks up to investigate a specific service.

6. **Panel accounting** — verified 25 panels in = 25 panels out (10 + 3 + 12)
   before committing. The original `deployment-frequency.json` was deleted
   since it was never committed.

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
