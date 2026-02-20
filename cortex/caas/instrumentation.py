"""
Pre-defined Prometheus metrics for CaaS server instrumentation.
"""

from cortex.caas.metrics import Counter, Gauge, Histogram, MetricsRegistry

HTTP_REQUESTS_TOTAL = Counter(
    "cortex_http_requests_total",
    "Total HTTP requests",
    label_names=("method", "path", "status"),
)

HTTP_REQUEST_DURATION = Histogram(
    "cortex_http_request_duration_seconds",
    "HTTP request latency in seconds",
    label_names=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

HTTP_IN_FLIGHT = Gauge(
    "cortex_http_requests_in_flight",
    "Current in-flight HTTP requests",
)

GRANTS_ACTIVE = Gauge(
    "cortex_grants_active",
    "Number of active (non-revoked) grants",
)

GRAPH_NODES = Gauge(
    "cortex_graph_nodes",
    "Number of nodes in the context graph",
)

GRAPH_EDGES = Gauge(
    "cortex_graph_edges",
    "Number of edges in the context graph",
)

ERRORS_TOTAL = Counter(
    "cortex_errors_total",
    "Total errors by type",
    label_names=("error_type",),
)

BUILD_INFO = Gauge(
    "cortex_build_info",
    "Build information",
    label_names=("version",),
)

# ---------------------------------------------------------------------------
# Phase 8 — Extended observability metrics
# ---------------------------------------------------------------------------

RATE_LIMIT_REJECTED = Counter(
    "cortex_rate_limit_rejected_total",
    "Requests rejected by rate limiter",
)

WEBHOOK_DELIVERIES = Counter(
    "cortex_webhook_deliveries_total",
    "Webhook delivery attempts by outcome",
    label_names=("webhook_id", "status"),
)

WEBHOOK_DEAD_LETTERS = Gauge(
    "cortex_webhook_dead_letters",
    "Dead-letter queue depth per webhook",
    label_names=("webhook_id",),
)

CIRCUIT_BREAKER_STATE = Gauge(
    "cortex_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half_open)",
    label_names=("webhook_id",),
)

AUDIT_ENTRIES = Gauge(
    "cortex_audit_entries_total",
    "Total audit ledger entries",
)

CACHE_HITS = Counter(
    "cortex_cache_hits_total",
    "HTTP 304 responses (ETag matched)",
)

CACHE_MISSES = Counter(
    "cortex_cache_misses_total",
    "Conditional requests where ETag did not match",
)

SSE_SUBSCRIBERS_ACTIVE = Gauge(
    "cortex_sse_subscribers_active",
    "Currently connected SSE clients",
)

SSE_EVENTS = Counter(
    "cortex_sse_events_total",
    "SSE events broadcast by type",
    label_names=("event_type",),
)


def create_default_registry() -> MetricsRegistry:
    """Create a MetricsRegistry with all pre-defined metrics registered."""
    registry = MetricsRegistry()
    # Core metrics (Phase 3)
    registry.register(HTTP_REQUESTS_TOTAL)
    registry.register(HTTP_REQUEST_DURATION)
    registry.register(HTTP_IN_FLIGHT)
    registry.register(GRANTS_ACTIVE)
    registry.register(GRAPH_NODES)
    registry.register(GRAPH_EDGES)
    registry.register(ERRORS_TOTAL)
    registry.register(BUILD_INFO)
    # Extended observability (Phase 8)
    registry.register(RATE_LIMIT_REJECTED)
    registry.register(WEBHOOK_DELIVERIES)
    registry.register(WEBHOOK_DEAD_LETTERS)
    registry.register(CIRCUIT_BREAKER_STATE)
    registry.register(AUDIT_ENTRIES)
    registry.register(CACHE_HITS)
    registry.register(CACHE_MISSES)
    registry.register(SSE_SUBSCRIBERS_ACTIVE)
    registry.register(SSE_EVENTS)
    BUILD_INFO.set(1.0, version="1.0.0")
    return registry
