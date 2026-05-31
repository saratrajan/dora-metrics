"""
Mock ArgoCD Prometheus exporter for local DORA metrics testing.
Simulates 31 travel-platform microservices across lab and prod environments.
Counters are pre-seeded with months of history so increase() works from first scrape.
Increments are Poisson-sampled so deployment trends show natural variation.
Each service carries a semantic app_version label on reconcile metrics; versions
bump automatically as successful syncs accumulate.
"""

import math
import random
import threading
import time
from prometheus_client import REGISTRY, start_http_server
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, HistogramMetricFamily

# ---------------------------------------------------------------------------
# Service definitions
# (name, dest_namespace, succ/hr, fail/hr, health, seed_days)
# ---------------------------------------------------------------------------
SERVICES = [
    # Flight team — fully automated CD, deploys many times/day
    ("flight-search",          "flight-search-lab",              6.0,  0.30,  "Healthy",      180),
    ("flight-search",          "flight-search-prod",             2.5,  0.05,  "Healthy",      180),
    ("flight-booking",         "flight-booking-lab",             5.0,  0.50,  "Healthy",      180),
    ("flight-booking",         "flight-booking-prod",            1.5,  0.08,  "Healthy",      180),
    ("seat-selector",          "seat-selector-lab",              4.0,  0.20,  "Healthy",      180),
    ("seat-selector",          "seat-selector-prod",             1.0,  0.04,  "Healthy",      180),
    ("check-in-service",       "check-in-service-lab",           3.0,  0.15,  "Healthy",      365),
    ("check-in-service",       "check-in-service-prod",          0.8,  0.02,  "Healthy",      365),
    ("baggage-tracker",        "baggage-tracker-lab",            2.5,  0.60,  "Degraded",     120),
    ("baggage-tracker",        "baggage-tracker-prod",           0.5,  0.04,  "Healthy",      120),

    # Hotel & accommodation
    ("hotel-search",           "hotel-search-lab",               4.0,  0.20,  "Healthy",      240),
    ("hotel-search",           "hotel-search-prod",              1.2,  0.04,  "Healthy",      240),
    ("hotel-booking",          "hotel-booking-lab",              3.0,  0.30,  "Healthy",      240),
    ("hotel-booking",          "hotel-booking-prod",             1.0,  0.06,  "Healthy",      240),
    ("hotel-reviews",          "hotel-reviews-lab",              1.5,  0.10,  "Healthy",       90),
    ("hotel-reviews",          "hotel-reviews-prod",             0.5,  0.02,  "Healthy",       90),

    # Cruise — newest vertical, fast iteration, higher failure rate in lab
    ("cruise-planner",         "cruise-planner-lab",             8.0,  0.90,  "Healthy",       45),
    ("cruise-planner",         "cruise-planner-prod",            3.0,  0.20,  "Healthy",       45),
    ("cruise-booking",         "cruise-booking-lab",             7.0,  0.70,  "Progressing",   30),
    ("cruise-booking",         "cruise-booking-prod",            2.0,  0.15,  "Healthy",       30),
    ("cruise-excursions",      "cruise-excursions-lab",          5.0,  0.50,  "Healthy",       20),
    ("cruise-excursions",      "cruise-excursions-prod",         1.5,  0.10,  "Healthy",       20),

    # Car rental
    ("car-rental",             "car-rental-lab",                 2.0,  0.25,  "Healthy",      300),
    ("car-rental",             "car-rental-prod",                0.6,  0.05,  "Healthy",      300),

    # Payment services — careful change management, low prod rate
    ("payment-gateway",        "payment-gateway-lab",            2.0,  0.50,  "Degraded",     365),
    ("payment-gateway",        "payment-gateway-prod",           0.4,  0.02,  "Healthy",      365),
    ("payment-processor",      "payment-processor-lab",          1.5,  0.30,  "Healthy",      365),
    ("payment-processor",      "payment-processor-prod",         0.3,  0.01,  "Healthy",      365),
    ("fraud-detection",        "fraud-detection-lab",            1.0,  0.40,  "Healthy",      180),
    ("fraud-detection",        "fraud-detection-prod",           0.2,  0.02,  "Healthy",      180),
    ("refund-processor",       "refund-processor-lab",           1.2,  0.20,  "Healthy",      180),
    ("refund-processor",       "refund-processor-prod",          0.3,  0.03,  "Healthy",      180),
    ("currency-converter",     "currency-converter-lab",         0.5,  0.05,  "Healthy",      365),
    ("currency-converter",     "currency-converter-prod",        0.1,  0.005, "Healthy",      365),
    ("wallet-service",         "wallet-service-lab",             2.0,  0.30,  "Healthy",       90),
    ("wallet-service",         "wallet-service-prod",            0.5,  0.02,  "Healthy",       90),

    # Travel extras
    ("travel-insurance",       "travel-insurance-lab",           1.5,  0.15,  "Healthy",      270),
    ("travel-insurance",       "travel-insurance-prod",          0.4,  0.02,  "Healthy",      270),
    ("itinerary-builder",      "itinerary-builder-lab",          3.5,  0.35,  "Healthy",      150),
    ("itinerary-builder",      "itinerary-builder-prod",         1.0,  0.08,  "Healthy",      150),
    ("visa-advisor",           "visa-advisor-lab",               1.0,  0.10,  "Healthy",       60),
    ("visa-advisor",           "visa-advisor-prod",              0.3,  0.02,  "Healthy",       60),

    # Customer experience
    ("loyalty-rewards",        "loyalty-rewards-lab",            2.5,  0.20,  "Healthy",      365),
    ("loyalty-rewards",        "loyalty-rewards-prod",           0.8,  0.04,  "Healthy",      365),
    ("review-aggregator",      "review-aggregator-lab",          1.0,  0.10,  "Healthy",      200),
    ("review-aggregator",      "review-aggregator-prod",         0.3,  0.01,  "Healthy",      200),
    ("recommendation-engine",  "recommendation-engine-lab",      5.0,  0.50,  "Healthy",      120),
    ("recommendation-engine",  "recommendation-engine-prod",     1.5,  0.10,  "Healthy",      120),

    # Core booking platform
    ("search-service",         "search-service-lab",             4.0,  0.20,  "Healthy",      365),
    ("search-service",         "search-service-prod",            1.0,  0.02,  "Healthy",      365),
    ("booking-manager",        "booking-manager-lab",            3.0,  0.30,  "Healthy",      365),
    ("booking-manager",        "booking-manager-prod",           1.2,  0.06,  "Healthy",      365),
    ("inventory-service",      "inventory-service-lab",          2.5,  0.15,  "Healthy",      365),
    ("inventory-service",      "inventory-service-prod",         0.8,  0.04,  "Healthy",      365),
    ("notification-service",   "notification-service-lab",       1.5,  0.35,  "Progressing",  365),
    ("notification-service",   "notification-service-prod",      0.3,  0.00,  "Healthy",      365),
    ("price-engine",           "price-engine-lab",               4.0,  0.30,  "Healthy",      180),
    ("price-engine",           "price-engine-prod",              1.0,  0.05,  "Healthy",      180),

    # Partner & API gateway
    ("partner-api",            "partner-api-lab",                1.0,  0.10,  "Healthy",      300),
    ("partner-api",            "partner-api-prod",               0.3,  0.02,  "Healthy",      300),
    ("supplier-connector",     "supplier-connector-lab",         0.8,  0.08,  "Healthy",      300),
    ("supplier-connector",     "supplier-connector-prod",        0.2,  0.01,  "Healthy",      300),
]

PROJECT     = "travel-platform"
ARGOCD_NS   = "argocd"
DEST_SERVER = "https://kubernetes.default.svc"

# Reconcile histogram buckets (seconds) — matches ArgoCD defaults
BUCKETS = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]

# ---------------------------------------------------------------------------
# Mean reconcile duration per service version (seconds).
# Keyed by (service_name, semver) — newer versions are generally faster
# due to optimisation work; payment services stay slow regardless.
# ---------------------------------------------------------------------------
RECONCILE_MEAN = {
    # ── Flight ──────────────────────────────────────────────────────────────
    ("flight-search",          "v3.2.7"):   0.28,
    ("flight-search",          "v3.2.6"):   0.32,
    ("flight-booking",         "v2.8.12"):  0.58,
    ("flight-booking",         "v2.8.11"):  0.63,
    ("seat-selector",          "v2.1.4"):   0.30,
    ("check-in-service",       "v4.0.3"):   0.61,
    ("baggage-tracker",        "v1.5.9"):   0.92,

    # ── Hotel ────────────────────────────────────────────────────────────────
    ("hotel-search",           "v3.4.1"):   0.34,
    ("hotel-booking",          "v2.6.8"):   0.69,
    ("hotel-reviews",          "v1.2.0"):   0.48,

    # ── Cruise (new — versions still low, reconcile slower) ──────────────────
    ("cruise-planner",         "v0.8.14"):  1.25,
    ("cruise-planner",         "v0.8.13"):  1.30,
    ("cruise-booking",         "v0.6.22"):  1.42,
    ("cruise-booking",         "v0.6.21"):  1.50,
    ("cruise-excursions",      "v0.4.7"):   1.10,

    # ── Car rental ───────────────────────────────────────────────────────────
    ("car-rental",             "v3.1.5"):   0.68,

    # ── Payments (high major versions — mature but reconcile is slow
    #              due to DB migration steps on each deploy) ──────────────────
    ("payment-gateway",        "v5.2.1"):   2.55,
    ("payment-gateway",        "v5.2.0"):   2.70,
    ("payment-processor",      "v4.7.3"):   2.02,
    ("fraud-detection",        "v2.3.11"):  3.48,
    ("fraud-detection",        "v2.3.10"):  3.60,
    ("refund-processor",       "v3.0.8"):   1.28,
    ("currency-converter",     "v6.1.2"):   0.41,
    ("wallet-service",         "v1.3.4"):   0.82,

    # ── Travel extras ────────────────────────────────────────────────────────
    ("travel-insurance",       "v2.5.6"):   0.79,
    ("itinerary-builder",      "v2.2.15"):  0.88,
    ("itinerary-builder",      "v2.2.14"):  0.94,
    ("visa-advisor",           "v1.0.7"):   0.61,

    # ── Customer experience ───────────────────────────────────────────────────
    ("loyalty-rewards",        "v4.3.0"):   0.71,
    ("review-aggregator",      "v2.8.4"):   0.52,
    ("recommendation-engine",  "v1.7.22"):  1.82,
    ("recommendation-engine",  "v1.7.21"):  1.90,

    # ── Core platform ────────────────────────────────────────────────────────
    ("search-service",         "v5.1.8"):   0.39,
    ("search-service",         "v5.1.7"):   0.43,
    ("booking-manager",        "v4.4.6"):   0.81,
    ("inventory-service",      "v3.6.2"):   0.59,
    ("notification-service",   "v3.2.14"):  0.51,
    ("price-engine",           "v2.9.3"):   0.38,
    ("price-engine",           "v2.9.2"):   0.42,

    # ── Partner / API ─────────────────────────────────────────────────────────
    ("partner-api",            "v3.5.7"):   0.63,
    ("supplier-connector",     "v2.1.19"):  0.72,
}

# Current live version per service — the value at container start; patch
# version bumps automatically as successful syncs accumulate.
# Format: [major, minor, patch]
_live_version: dict[str, list[int]] = {
    "flight-search":          [3, 2, 7],
    "flight-booking":         [2, 8, 12],
    "seat-selector":          [2, 1, 4],
    "check-in-service":       [4, 0, 3],
    "baggage-tracker":        [1, 5, 9],
    "hotel-search":           [3, 4, 1],
    "hotel-booking":          [2, 6, 8],
    "hotel-reviews":          [1, 2, 0],
    "cruise-planner":         [0, 8, 14],
    "cruise-booking":         [0, 6, 22],
    "cruise-excursions":      [0, 4, 7],
    "car-rental":             [3, 1, 5],
    "payment-gateway":        [5, 2, 1],
    "payment-processor":      [4, 7, 3],
    "fraud-detection":        [2, 3, 11],
    "refund-processor":       [3, 0, 8],
    "currency-converter":     [6, 1, 2],
    "wallet-service":         [1, 3, 4],
    "travel-insurance":       [2, 5, 6],
    "itinerary-builder":      [2, 2, 15],
    "visa-advisor":           [1, 0, 7],
    "loyalty-rewards":        [4, 3, 0],
    "review-aggregator":      [2, 8, 4],
    "recommendation-engine":  [1, 7, 22],
    "search-service":         [5, 1, 8],
    "booking-manager":        [4, 4, 6],
    "inventory-service":      [3, 6, 2],
    "notification-service":   [3, 2, 14],
    "price-engine":           [2, 9, 3],
    "partner-api":            [3, 5, 7],
    "supplier-connector":     [2, 1, 19],
}

# Syncs between version bumps — fast-moving services bump more often
_bump_interval: dict[str, int] = {
    "cruise-planner":         5,
    "cruise-booking":         5,
    "cruise-excursions":      6,
    "flight-search":          8,
    "flight-booking":         8,
    "seat-selector":          10,
    "recommendation-engine":  10,
    "price-engine":           10,
    "hotel-search":           12,
    "search-service":         12,
    "itinerary-builder":      12,
    "booking-manager":        15,
    "hotel-booking":          15,
    "inventory-service":      18,
    "check-in-service":       20,
    "notification-service":   20,
    "baggage-tracker":        20,
    "loyalty-rewards":        20,
    "car-rental":             25,
    "review-aggregator":      25,
    "travel-insurance":       25,
    "wallet-service":         25,
    "hotel-reviews":          30,
    "visa-advisor":           30,
    "partner-api":            35,
    "supplier-connector":     35,
    "refund-processor":       40,
    "fraud-detection":        50,
    "payment-processor":      50,
    "payment-gateway":        60,
    "currency-converter":     80,
}

_syncs_since_bump: dict[str, int] = {name: 0 for name in _live_version}

# ---------------------------------------------------------------------------
# Internal state
#   sync_state:      {(name, dest_ns): {"succeeded": float, "failed": float}}
#   reconcile_state: {(name, dest_ns, version_str): {"sum", "count", "raw"}}
# ---------------------------------------------------------------------------
sync_state:      dict = {}
reconcile_state: dict = {}


def _ver(name: str) -> str:
    v = _live_version[name]
    return f"v{v[0]}.{v[1]}.{v[2]}"


def _mean_s(name: str, version: str) -> float:
    """Reconcile mean for (name, version); fall back to nearest known version."""
    if (name, version) in RECONCILE_MEAN:
        return RECONCILE_MEAN[(name, version)]
    # Fall back: find any entry for this service
    for (n, _v), m in RECONCILE_MEAN.items():
        if n == name:
            return m
    return 1.0


def _poisson(lam: float) -> int:
    """Sample from Poisson(lam) — Knuth's algorithm."""
    if lam <= 0:
        return 0
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        k += 1
        p *= random.random()
        if p <= L:
            return k - 1


def _record_reconcile(name: str, dest_ns: str, version: str, n: int) -> None:
    """Add n reconcile observations to the (name, dest_ns, version) bucket."""
    if n <= 0:
        return
    key = (name, dest_ns, version)
    if key not in reconcile_state:
        reconcile_state[key] = {"sum": 0.0, "count": 0, "raw": {le: 0 for le in BUCKETS}}
    mean_s = _mean_s(name, version)
    rs = reconcile_state[key]
    for _ in range(n):
        obs = max(0.05, random.gauss(mean_s, mean_s * 0.25))
        rs["sum"]   += obs
        rs["count"] += 1
        for le in BUCKETS:
            if obs <= le:
                rs["raw"][le] += 1
                break


def _bump_version(name: str) -> None:
    """Advance the live version: 80% patch, 15% minor, 5% major."""
    v = _live_version[name]
    r = random.random()
    if r < 0.05:
        v[0] += 1; v[1] = 0; v[2] = 0
    elif r < 0.20:
        v[1] += 1; v[2] = 0
    else:
        v[2] += 1


def _init() -> None:
    for (name, dest_ns, succ_hr, fail_hr, _, seed_days) in SERVICES:
        key = (name, dest_ns)
        seed_succ = int(succ_hr * 24 * seed_days)
        seed_fail = int(fail_hr * 24 * seed_days)
        sync_state[key] = {"succeeded": float(seed_succ), "failed": float(seed_fail)}
        _record_reconcile(name, dest_ns, _ver(name), seed_succ + seed_fail)


_init()

# ---------------------------------------------------------------------------
# Background thread — Poisson-sampled increments + version bumps
# ---------------------------------------------------------------------------
TICK_SECONDS = 15


def _increment() -> None:
    while True:
        time.sleep(TICK_SECONDS)
        for (name, dest_ns, succ_hr, fail_hr, _, _sd) in SERVICES:
            key     = (name, dest_ns)
            n_succ  = _poisson(succ_hr / 3600 * TICK_SECONDS)
            n_fail  = _poisson(fail_hr / 3600 * TICK_SECONDS)

            sync_state[key]["succeeded"] += n_succ
            sync_state[key]["failed"]    += n_fail

            if n_succ + n_fail == 0:
                continue

            version = _ver(name)
            _record_reconcile(name, dest_ns, version, n_succ + n_fail)

            # Bump version when enough syncs have accumulated
            _syncs_since_bump[name] += n_succ
            threshold = _bump_interval.get(name, 20)
            if _syncs_since_bump[name] >= threshold:
                _syncs_since_bump[name] = 0
                _bump_version(name)


threading.Thread(target=_increment, daemon=True).start()


# ---------------------------------------------------------------------------
# Custom collector
# ---------------------------------------------------------------------------
class ArgoMockCollector:
    def collect(self):
        # argocd_app_sync_total
        sync = CounterMetricFamily(
            "argocd_app_sync_total",
            "ArgoCD app sync count (mock)",
            labels=["name", "namespace", "project", "dest_namespace", "dest_server", "phase"],
        )
        for (name, dest_ns, *_) in SERVICES:
            s = sync_state[(name, dest_ns)]
            sync.add_metric([name, ARGOCD_NS, PROJECT, dest_ns, DEST_SERVER, "Succeeded"], s["succeeded"])
            sync.add_metric([name, ARGOCD_NS, PROJECT, dest_ns, DEST_SERVER, "Failed"],    s["failed"])
        yield sync

        # argocd_app_info
        info = GaugeMetricFamily(
            "argocd_app_info",
            "ArgoCD app info (mock)",
            labels=["name", "namespace", "project", "dest_namespace", "dest_server",
                    "sync_status", "health_status", "app_version"],
        )
        for (name, dest_ns, _, _, health, *_) in SERVICES:
            sync_status = "Synced" if health == "Healthy" else "OutOfSync"
            info.add_metric(
                [name, ARGOCD_NS, PROJECT, dest_ns, DEST_SERVER, sync_status, health, _ver(name)],
                1.0,
            )
        yield info

        # argocd_app_reconcile — one histogram per (service, dest_namespace, version)
        for (name, dest_ns, version), rs in list(reconcile_state.items()):
            h = HistogramMetricFamily(
                "argocd_app_reconcile",
                "ArgoCD app reconcile duration (mock)",
                labels=["name", "namespace", "dest_namespace", "app_version"],
            )
            cum, bucket_list = 0, []
            for le in BUCKETS:
                cum += rs["raw"][le]
                bucket_list.append((str(le), cum))
            bucket_list.append(("+Inf", rs["count"]))
            h.add_metric([name, ARGOCD_NS, dest_ns, version], buckets=bucket_list, sum_value=rs["sum"])
            yield h


REGISTRY.register(ArgoMockCollector())

# ---------------------------------------------------------------------------
if __name__ == "__main__":
    unique = sorted({s[0] for s in SERVICES})
    start_http_server(8000)
    print(f"Mock ArgoCD exporter running on :8000/metrics")
    print(f"{len(unique)} services × 2 envs = {len(SERVICES)} ArgoCD apps")
    print("Initial versions:")
    for n in unique:
        print(f"  {n:<30} {_ver(n)}")
    while True:
        time.sleep(60)
