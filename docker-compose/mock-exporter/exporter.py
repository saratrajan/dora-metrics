"""
Mock ArgoCD Prometheus exporter for local DORA metrics testing.
Simulates 5 travel-platform microservices across lab and prod environments.
Counters are pre-seeded with 24h of history so increase() works from first scrape.
"""

import time
import random
import threading
from prometheus_client import start_http_server, Counter, Gauge, Histogram, REGISTRY
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, HistogramMetricFamily

# ---------------------------------------------------------------------------
# Service definitions
# Each entry: (name, dest_namespace, syncs_succeeded_per_hr, syncs_failed_per_hr, health)
# ---------------------------------------------------------------------------
SERVICES = [
    # name                   dest_namespace              succ/hr  fail/hr  health
    ("search-service",       "search-service-lab",       4.0,     0.2,     "Healthy"),
    ("search-service",       "search-service-prod",      1.0,     0.02,    "Healthy"),
    ("booking-manager",      "booking-manager-lab",      3.0,     0.3,     "Healthy"),
    ("booking-manager",      "booking-manager-prod",     1.2,     0.06,    "Healthy"),
    ("payment-gateway",      "payment-gateway-lab",      2.0,     0.5,     "Degraded"),   # flaky in lab
    ("payment-gateway",      "payment-gateway-prod",     0.5,     0.02,    "Healthy"),
    ("inventory-service",    "inventory-service-lab",    2.5,     0.15,    "Healthy"),
    ("inventory-service",    "inventory-service-prod",   0.8,     0.04,    "Healthy"),
    ("notification-service", "notification-service-lab", 1.5,     0.35,    "Progressing"),
    ("notification-service", "notification-service-prod",0.3,     0.0,     "Healthy"),
]

PROJECT      = "travel-platform"
ARGOCD_NS    = "argocd"
DEST_SERVER  = "https://kubernetes.default.svc"

# Reconcile histogram buckets matching ArgoCD defaults (seconds)
BUCKETS = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]

# Realistic reconcile durations per service (mean seconds)
RECONCILE_MEAN = {
    "search-service":       0.4,
    "booking-manager":      0.8,
    "payment-gateway":      1.5,
    "inventory-service":    0.6,
    "notification-service": 0.5,
}

# ---------------------------------------------------------------------------
# Internal counter state — pre-seeded with 24h of simulated history
# ---------------------------------------------------------------------------
state = {}
reconcile_state = {}  # {name: {"sum": float, "count": int, "buckets": {le: int}}}

def _bucket_counts(mean_s):
    """Return histogram bucket counts for a single reconcile observation."""
    counts = {le: 0 for le in BUCKETS}
    for le in BUCKETS:
        if mean_s <= le:
            counts[le] = 1
            break
    return counts

def _init_state():
    for (name, dest_ns, succ_hr, fail_hr, health) in SERVICES:
        key = (name, dest_ns)
        # Seed 24 h of history
        seed_succ = int(succ_hr * 24)
        seed_fail = int(fail_hr * 24)
        state[key] = {"succeeded": float(seed_succ), "failed": float(seed_fail)}

        # Reconcile histogram — seed with total_syncs observations
        total = seed_succ + seed_fail
        mean_s = RECONCILE_MEAN.get(name, 1.0)
        buckets = {le: 0 for le in BUCKETS}
        for _ in range(total):
            obs = random.gauss(mean_s, mean_s * 0.3)
            obs = max(0.05, obs)
            for le in BUCKETS:
                if obs <= le:
                    buckets[le] += 1
                    break
        # cumulative
        cum = 0
        cum_buckets = {}
        for le in BUCKETS:
            cum += buckets[le]
            cum_buckets[le] = cum
        cum_buckets[float("+Inf")] = total

        if name not in reconcile_state:
            reconcile_state[name] = {
                "sum": mean_s * total,
                "count": total,
                "buckets": cum_buckets,
            }

_init_state()

# ---------------------------------------------------------------------------
# Increment counters in the background to simulate ongoing deployments
# ---------------------------------------------------------------------------
TICK_SECONDS = 15  # increment every 15s

def _increment():
    while True:
        time.sleep(TICK_SECONDS)
        for (name, dest_ns, succ_hr, fail_hr, health) in SERVICES:
            key = (name, dest_ns)
            tick_succ = (succ_hr / 3600) * TICK_SECONDS
            tick_fail = (fail_hr / 3600) * TICK_SECONDS

            # probabilistic: add 1 when accumulated fraction >= 1
            state[key]["succeeded"] += tick_succ
            state[key]["failed"]    += tick_fail

            # add reconcile observations proportional to tick rate
            obs_count = (succ_hr + fail_hr) / 3600 * TICK_SECONDS
            if random.random() < obs_count:
                mean_s = RECONCILE_MEAN.get(name, 1.0)
                obs = max(0.05, random.gauss(mean_s, mean_s * 0.3))
                rs = reconcile_state[name]
                rs["sum"]   += obs
                rs["count"] += 1
                for le in BUCKETS:
                    if obs <= le:
                        rs["buckets"][le] += 1
                        break
                # keep cumulative
                cum = 0
                for le in BUCKETS:
                    cum += rs["buckets"][le]  # already incremented above
                # recalculate cumulative properly
                raw = {}
                prev = 0
                for le in BUCKETS:
                    raw[le] = rs["buckets"][le]
                cum2 = 0
                for le in BUCKETS:
                    cum2 += raw[le]
                    rs["buckets"][le] = cum2
                rs["buckets"][float("+Inf")] = rs["count"]

threading.Thread(target=_increment, daemon=True).start()

# ---------------------------------------------------------------------------
# Custom collector — renders current state as Prometheus metrics
# ---------------------------------------------------------------------------
class ArgoMockCollector:
    def collect(self):

        # argocd_app_sync_total
        sync = CounterMetricFamily(
            "argocd_app_sync_total",
            "ArgoCD app sync count (mock)",
            labels=["name", "namespace", "project", "dest_namespace", "dest_server", "phase"],
        )
        for (name, dest_ns, _, _, _) in SERVICES:
            key = (name, dest_ns)
            sync.add_metric(
                [name, ARGOCD_NS, PROJECT, dest_ns, DEST_SERVER, "Succeeded"],
                state[key]["succeeded"],
            )
            sync.add_metric(
                [name, ARGOCD_NS, PROJECT, dest_ns, DEST_SERVER, "Failed"],
                state[key]["failed"],
            )
        yield sync

        # argocd_app_info
        info = GaugeMetricFamily(
            "argocd_app_info",
            "ArgoCD app info (mock)",
            labels=["name", "namespace", "project", "dest_namespace", "dest_server",
                    "sync_status", "health_status"],
        )
        for (name, dest_ns, _, _, health) in SERVICES:
            sync_status = "Synced" if health == "Healthy" else "OutOfSync"
            info.add_metric(
                [name, ARGOCD_NS, PROJECT, dest_ns, DEST_SERVER, sync_status, health],
                1.0,
            )
        yield info

        # argocd_app_reconcile (histogram) — keyed by name only (matches ArgoCD)
        for name in RECONCILE_MEAN:
            rs = reconcile_state[name]
            h = HistogramMetricFamily(
                "argocd_app_reconcile",
                "ArgoCD app reconcile duration (mock)",
                labels=["name", "namespace"],
            )
            bucket_list = [(str(le), rs["buckets"].get(le, 0)) for le in BUCKETS]
            bucket_list.append(("+Inf", rs["count"]))
            h.add_metric(
                [name, ARGOCD_NS],
                buckets=bucket_list,
                sum_value=rs["sum"],
            )
            yield h


REGISTRY.register(ArgoMockCollector())

# ---------------------------------------------------------------------------
if __name__ == "__main__":
    start_http_server(8000)
    print("Mock ArgoCD exporter running on :8000/metrics")
    print("Services:", [s[0] for s in SERVICES])
    while True:
        time.sleep(60)
