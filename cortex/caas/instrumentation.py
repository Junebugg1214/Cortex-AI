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


def create_default_registry() -> MetricsRegistry:
    """Create a MetricsRegistry with all pre-defined metrics registered."""
    registry = MetricsRegistry()
    registry.register(HTTP_REQUESTS_TOTAL)
    registry.register(HTTP_REQUEST_DURATION)
    registry.register(HTTP_IN_FLIGHT)
    registry.register(GRANTS_ACTIVE)
    registry.register(GRAPH_NODES)
    registry.register(GRAPH_EDGES)
    registry.register(ERRORS_TOTAL)
    registry.register(BUILD_INFO)
    BUILD_INFO.set(1.0, version="1.0.0")
    return registry
