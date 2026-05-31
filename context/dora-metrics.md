# DORA Metrics — Project Context

This file captures the full design, decisions, fixes, and current state of the
`dora-metrics` repo. Use it to resume work in a new session without re-deriving
context from the codebase.

---

## What this repo does

Tracks the four DORA metrics (Deployment Frequency, Change Failure Rate, Lead
Time, MTTR) using ArgoCD sync events as the data source. No additional agents
or instrumentation required — ArgoCD's built-in Prometheus metrics are enough.

**Production path** (Kubernetes):
- `servicemonitors.yaml` — tells Prometheus Operator to scrape ArgoCD's three
  metric endpoints every 30s
- `prometheusrule.yaml` — pre-computes DORA recording rules from raw ArgoCD
  metrics
- `grafana-dashboard-configmap.yaml` — Grafana dashboard loaded by the sidecar

**Local testing path** (Docker Compose):
- `docker-compose/` — self-contained stack (mock exporter + Prometheus + Grafana)
  that works without any Kubernetes or real ArgoCD

---

## Repo file map

```
dora-metrics/
├── servicemonitors.yaml            # K8s: scrape ArgoCD metrics endpoints
├── prometheusrule.yaml             # K8s: DORA recording rules (production)
├── grafana-dashboard-configmap.yaml# K8s: Grafana dashboard as ConfigMap
├── argocd-application.yaml         # K8s: GitOps self-management (optional)
├── README.md                       # User-facing docs
├── context/
│   └── dora-metrics.md             # ← this file (session context, decisions, known issues)
└── docker-compose/
    ├── docker-compose.yml          # Wires up mock-exporter, Prometheus, Grafana
    ├── mock-exporter/
    │   ├── Dockerfile
    │   └── exporter.py             # Python mock — 31 services, versioned metrics
    ├── prometheus/
    │   ├── prometheus.yml          # Scrape config (targets mock-exporter:8000)
    │   └── rules.yml               # DORA recording rules (local, 1h windows)
    └── grafana/
        └── provisioning/
            ├── datasources/
            │   └── prometheus.yaml # Datasource with explicit uid: prometheus
            └── dashboards/
                ├── provider.yaml
                └── dora-metrics.json # Dashboard JSON (single source for local)
```

---

## Running locally

```bash
cd docker-compose

# First run or after exporter.py changes — force image rebuild
sudo docker-compose build --no-cache mock-exporter
sudo docker-compose up -d

# Subsequent runs (no code changes)
sudo docker-compose up -d

# Tear down
sudo docker-compose down
```

| Service        | URL                            | Credentials   |
|----------------|-------------------------------|---------------|
| Grafana        | http://localhost:3000          | admin / admin |
| Prometheus     | http://localhost:9090          | —             |
| Mock exporter  | http://localhost:8000/metrics  | —             |

Verify the mock is serving correctly:
```bash
curl http://localhost:8000/metrics | grep argocd_app_sync_total
```

### Docker permission issue

The user (`saratrajan`) is not in the `docker` group, so `docker-compose`
requires `sudo`. Permanent fix:
```bash
sudo usermod -aG docker saratrajan
# then log out and back in, or: newgrp docker
```

---

## Prometheus recording rules

Two identical rule sets — one for local, one for production. The local version
uses 1h windows so trends appear within minutes.

| Rule | Local window | Production window |
|------|-------------|-------------------|
| `dora:deployment_frequency:daily` | 1h × 24 | 24h |
| `dora:change_failure_rate:7d` | 1h | 7d |
| `dora:lead_time_p95:1h` | 1h | 1h |
| `dora:mttr_proxy:1h` | — (prod only) | 1h |

### Lead time rule — important design note

`argocd_app_reconcile_bucket` only carries `name` and `namespace` (the ArgoCD
namespace), **not** `dest_namespace`. To make the lead time metric filterable
by environment/namespace in the dashboard, both rule files join the histogram
with `argocd_app_info` using a `group_left`:

```promql
histogram_quantile(
  0.95,
  sum by (name, project, dest_namespace, le) (
    rate(argocd_app_reconcile_bucket[1h])
    * on(name, namespace) group_left(dest_namespace, project)
      max by (name, namespace, dest_namespace, project) (argocd_app_info)
  )
)
```

This must be kept in sync between `rules.yml` and `prometheusrule.yaml`.
The production rule also carries `project` in the join for the `$project`
variable filter.

---

## Grafana dashboard

### Template variables (in evaluation order)

| Variable | Type | Purpose |
|----------|------|---------|
| `environment` | custom (`lab,prod`) | Scopes the namespace dropdown |
| `project` | query — `label_values(argocd_app_info{dest_namespace=~".*$environment.*"}, project)` | Filters by ArgoCD project (production) |
| `namespace` | query — `label_values(argocd_app_info{dest_namespace=~".*$environment.*"}, dest_namespace)` | Per-service namespace filter |

**Critical:** `namespace` must have **no** `allValue` field. If `allValue: ".*"`
is set, selecting "All" sends `.*` to panel queries — bypassing the environment
filter entirely. Without `allValue`, Grafana joins the actual option values into
a proper regex that respects the environment selection.

### Panel query pattern

All panels filter by `dest_namespace=~"$namespace"`. The `$namespace` variable
is chained to `$environment`, so switching environment automatically restricts
the namespace options and re-scopes all panels.

### Datasource UID

The datasource provisioning YAML (`datasources/prometheus.yaml`) **must**
include `uid: prometheus` explicitly:

```yaml
datasources:
  - name: Prometheus
    type: prometheus
    uid: prometheus          # ← required
    url: http://prometheus:9090
```

Without it, Grafana auto-generates a UID (e.g. `PBFA97CFB590B2093`) that
doesn't match the `uid: "prometheus"` hardcoded in the dashboard JSON and
variable queries — causing all panels to show no data.

### Panel titles

Panel titles do **not** use `$environment` or any template variable. Grafana
only re-interpolates panel titles when the panel re-renders (time range change,
full refresh), not immediately when a dropdown changes. This caused titles to
appear "stuck". Titles are now static descriptive strings.

### Two dashboard files — known divergence

| File | Used by | Differences |
|------|---------|-------------|
| `docker-compose/grafana/provisioning/dashboards/dora-metrics.json` | Docker Compose | `uid: prometheus` datasource, 1h time windows, `byRegexp` overrides, "All Services" table panel |
| `grafana-dashboard-configmap.yaml` (embedded JSON) | Kubernetes | `"Prometheus"` datasource name, 30d time windows, `byNamePattern` overrides, "Unhealthy Applications" table panel, `project` filter in queries |

**App Health piechart color overrides** (both files):
- `Healthy` → `green`
- `Progressing` → `yellow`
- `Degraded` → `rgb(255, 166, 176)` (light red)

**Recommended future fix:** Extract the ConfigMap's embedded JSON to a
standalone `dashboards/dora-metrics.json` and use Kustomize `configMapGenerator`
to wrap it. This eliminates the JSON-in-YAML problem and makes the production
dashboard editable as a real file.

---

## Mock exporter (`docker-compose/mock-exporter/exporter.py`)

### Services

31 unique microservices × 2 environments (lab + prod) = 62 ArgoCD app entries.

| Team / Domain | Services |
|---------------|----------|
| Flight | `flight-search`, `flight-booking`, `seat-selector`, `check-in-service`, `baggage-tracker` |
| Hotel | `hotel-search`, `hotel-booking`, `hotel-reviews` |
| Cruise (newest) | `cruise-planner`, `cruise-booking`, `cruise-excursions` |
| Car rental | `car-rental` |
| Payments | `payment-gateway`, `payment-processor`, `fraud-detection`, `refund-processor`, `currency-converter`, `wallet-service` |
| Travel extras | `travel-insurance`, `itinerary-builder`, `visa-advisor` |
| Customer | `loyalty-rewards`, `review-aggregator`, `recommendation-engine` |
| Core platform | `search-service`, `booking-manager`, `inventory-service`, `notification-service`, `price-engine` |
| Partner / API | `partner-api`, `supplier-connector` |

### Namespace naming

Each service gets its own namespace per environment:
`<service-name>-lab` and `<service-name>-prod`

e.g. `flight-search-lab`, `flight-search-prod`

This matches the dashboard `$namespace` variable pattern and allows per-service
filtering.

### Service tuple fields

```python
(name, dest_namespace, succ_hr, fail_hr, health, seed_days)
```

- `succ_hr` / `fail_hr` — average syncs per hour (Poisson-sampled per tick)
- `health` — `"Healthy"` | `"Degraded"` | `"Progressing"`
- `seed_days` — how many days of history to pre-seed into counters at startup.
  Cruise services start at 20–45 days (new); core platform and payment services
  start at 365 days (mature).

### Deployment frequency design

Increments run every 15 seconds (`TICK_SECONDS = 15`) using Poisson sampling
(`_poisson(λ)` — Knuth's algorithm). This means deploys arrive in random bursts
rather than at a fixed rate, producing natural variation in Grafana time series
charts.

High-frequency teams (cruise, flight) deploy 5–8 times/hr in lab. Careful
teams (payment, currency-converter) deploy 0.1–0.5 times/hr in lab and much
less in prod.

### Semantic versioning on reconcile metrics

`argocd_app_reconcile` is emitted with an `app_version` label (e.g.
`app_version="v2.9.3"`). `argocd_app_info` also carries `app_version`.

`RECONCILE_MEAN` is keyed by `(service_name, version_string)` — different
versions of the same service can have different reconcile characteristics.
Newer versions trend faster; payment/fraud services stay slow regardless of
version.

Versions **bump automatically** in the background thread. After `_bump_interval`
successful syncs accumulate per service, the version advances:
- 80% patch bump (v1.2.3 → v1.2.4)
- 15% minor bump (v1.2.3 → v1.3.0)
- 5% major bump (v1.2.3 → v2.0.0)

Each new version creates a new time series in Prometheus; old versions stop
accumulating and go stale — exactly how real ArgoCD version rollouts look.

Fast-moving services (`cruise-planner`: every 5 syncs) bump versions much more
often than stable ones (`currency-converter`: every 80 syncs).

### Histogram implementation note

`reconcile_state` stores **raw** (non-cumulative) bucket counts per
`(name, version)` key. Cumulative values are computed at collection time in
`ArgoMockCollector.collect()`. This avoids the bug in the original code where
cumulative-on-cumulative recalculation corrupted bucket counts.

---

## Known issues / decisions made

### `namespace` label collision in Prometheus scrape config

`prometheus.yml` adds a static label `namespace: argocd` to all scraped
metrics. The mock exporter also emits `namespace="argocd"` on its metrics. When
Prometheus sees a collision it renames the metric's label to `exported_namespace`
and applies the target label. This means both `argocd_app_reconcile_bucket` and
`argocd_app_info` end up with `namespace="argocd"` (from scrape config) and
`exported_namespace="argocd"` (original). The recording rule join
`on(name, namespace)` works correctly because both sides carry the scrape-config
`namespace` label.

### Production `prometheusrule.yaml` was missing `dest_namespace`

The original `dora:deployment_frequency:daily` and `dora:change_failure_rate:7d`
rules used `sum by (name, project)` — dropping `dest_namespace`. This meant the
dashboard's `{dest_namespace=~"$namespace"}` filter would return no data. Fixed
by adding `dest_namespace` to all `sum by` clauses.

### SLO Lead Time stat panel showed green / no value

The original recording rule for `dora:lead_time_p95:1h` had no `dest_namespace`
label in its output. The panel query filtering by `{dest_namespace=~"$namespace"}`
matched nothing → no value displayed, panel showed the default green threshold
colour. Fixed by the `group_left` join described above.

---

## Git commit style

- Natural, concise commit messages
- **Always ask before `git push`** — never push without explicit user approval

---

## Versions pinned

| Component | Version |
|-----------|---------|
| Grafana | `grafana/grafana:11.6.1` |
| Prometheus | `prom/prometheus:v2.51.2` |
| Mock exporter base | `python:3.12-slim` |
| prometheus-client | `0.20.0` |

---

## What's parked / future work

- **Kustomize migration** — extract the ConfigMap's embedded JSON to a
  standalone file; use `configMapGenerator` in a `kustomization.yaml` so the
  ConfigMap is generated, not hand-maintained.
- **Historical time series in Grafana** — Prometheus only stores data from when
  the stack started. For long-range trend charts (weeks/months), options are:
  pre-populating TSDB blocks, using a remote write with Thanos/Mimir, or
  accepting that trends accumulate from stack start.
- **MTTR panel** — `dora:mttr_proxy:1h` exists in `prometheusrule.yaml` but
  has no corresponding panel in the local dashboard yet.
- **Lead time many-to-many (prod)** — `argocd_app_reconcile_bucket` has no
  `dest_namespace`. Join on `(name, namespace)` can produce many-to-many if
  the same app name exists in both lab and prod rows in `argocd_app_info`.
  Discussed but not yet resolved — user reverted fix. Options: drop the join
  (lose namespace filterability) or accept the error only happens in prod
  where a real ArgoCD has separate namespaces per cluster.
- **Low-frequency services showing 0.0** (e.g. `car-rental`) — Poisson(λ=0.008)
  per 15s tick means ~30 min before first event. Could add a `SIM_SPEED`
  multiplier but user reverted that approach. Currently: wait or widen time range.
- **dest_server split** — lab and prod are separate K8s clusters
  (`travel-lab`, `travel-prod`). Mock exporter currently uses a single
  `DEST_SERVER` value. Splitting to two distinct URLs would differentiate
  clusters more accurately but was reverted due to stale series.
