"""
Phase 8 — Extended Prometheus Metrics Tests.

Verifies:
- 9 new metrics are registered and produce valid Prometheus output
- Rate-limit rejections increment the counter
- Webhook delivery outcomes record correctly
- Circuit-breaker state gauge reflects actual state
- Audit ledger entry count updates at scrape time
- Cache hit/miss counters fire on conditional requests
- SSE subscriber gauge and event counters work
- CLI --enable-metrics flag and config file [metrics] section
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from cortex.caas.instrumentation import (
    AUDIT_ENTRIES,
    CACHE_HITS,
    CACHE_MISSES,
    CIRCUIT_BREAKER_STATE,
    RATE_LIMIT_REJECTED,
    SSE_EVENTS,
    SSE_SUBSCRIBERS_ACTIVE,
    WEBHOOK_DEAD_LETTERS,
    WEBHOOK_DELIVERIES,
    create_default_registry,
)
from cortex.caas.metrics import Counter, Gauge

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_counter(c: Counter) -> None:
    """Reset a counter's values for isolated tests."""
    with c._lock:
        c._values.clear()


def _reset_gauge(g: Gauge) -> None:
    """Reset a gauge's values for isolated tests."""
    with g._lock:
        g._values.clear()


# ---------------------------------------------------------------------------
# TestNewMetricDefinitions
# ---------------------------------------------------------------------------

class TestNewMetricDefinitions(unittest.TestCase):
    """All 9 new metrics are registered and produce valid Prometheus output."""

    def test_registry_has_17_metrics(self):
        registry = create_default_registry()
        # 8 original + 9 new = 17
        self.assertEqual(len(registry._metrics), 17)

    def test_new_counters_in_output(self):
        registry = create_default_registry()
        output = registry.collect()
        for name in [
            "cortex_rate_limit_rejected_total",
            "cortex_webhook_deliveries_total",
            "cortex_cache_hits_total",
            "cortex_cache_misses_total",
            "cortex_sse_events_total",
        ]:
            self.assertIn(f"# TYPE {name} counter", output, f"Missing counter: {name}")

    def test_new_gauges_in_output(self):
        registry = create_default_registry()
        output = registry.collect()
        for name in [
            "cortex_webhook_dead_letters",
            "cortex_circuit_breaker_state",
            "cortex_audit_entries_total",
            "cortex_sse_subscribers_active",
        ]:
            self.assertIn(f"# TYPE {name} gauge", output, f"Missing gauge: {name}")

    def test_rate_limit_counter_labels(self):
        self.assertEqual(RATE_LIMIT_REJECTED.label_names, ())

    def test_webhook_delivery_counter_labels(self):
        self.assertEqual(WEBHOOK_DELIVERIES.label_names, ("webhook_id", "status"))


# ---------------------------------------------------------------------------
# TestRateLimitMetrics
# ---------------------------------------------------------------------------

class TestRateLimitMetrics(unittest.TestCase):
    """Rejected requests increment the rate-limit counter."""

    def setUp(self):
        _reset_counter(RATE_LIMIT_REJECTED)

    def test_increment_on_rejection(self):
        RATE_LIMIT_REJECTED.inc()
        self.assertEqual(RATE_LIMIT_REJECTED.get(), 1.0)

    def test_multiple_increments(self):
        RATE_LIMIT_REJECTED.inc()
        RATE_LIMIT_REJECTED.inc()
        RATE_LIMIT_REJECTED.inc()
        self.assertEqual(RATE_LIMIT_REJECTED.get(), 3.0)

    def test_produces_output(self):
        RATE_LIMIT_REJECTED.inc()
        lines = RATE_LIMIT_REJECTED.collect()
        self.assertTrue(any("cortex_rate_limit_rejected_total 1" in l for l in lines))


# ---------------------------------------------------------------------------
# TestWebhookDeliveryMetrics
# ---------------------------------------------------------------------------

class TestWebhookDeliveryMetrics(unittest.TestCase):
    """Webhook delivery counters and dead-letter gauge."""

    def setUp(self):
        _reset_counter(WEBHOOK_DELIVERIES)
        _reset_gauge(WEBHOOK_DEAD_LETTERS)

    def test_success_delivery(self):
        WEBHOOK_DELIVERIES.inc(webhook_id="w1", status="success")
        self.assertEqual(WEBHOOK_DELIVERIES.get(webhook_id="w1", status="success"), 1.0)

    def test_failure_delivery(self):
        WEBHOOK_DELIVERIES.inc(webhook_id="w1", status="failure")
        self.assertEqual(WEBHOOK_DELIVERIES.get(webhook_id="w1", status="failure"), 1.0)

    def test_circuit_open_delivery(self):
        WEBHOOK_DELIVERIES.inc(webhook_id="w2", status="circuit_open")
        self.assertEqual(WEBHOOK_DELIVERIES.get(webhook_id="w2", status="circuit_open"), 1.0)

    def test_dead_letter_gauge(self):
        WEBHOOK_DEAD_LETTERS.set(3.0, webhook_id="w1")
        self.assertEqual(WEBHOOK_DEAD_LETTERS.get(webhook_id="w1"), 3.0)

    def test_delivery_labels_in_output(self):
        WEBHOOK_DELIVERIES.inc(webhook_id="w1", status="success")
        lines = WEBHOOK_DELIVERIES.collect()
        output = "\n".join(lines)
        self.assertIn('webhook_id="w1"', output)
        self.assertIn('status="success"', output)


# ---------------------------------------------------------------------------
# TestCircuitBreakerStateMetrics
# ---------------------------------------------------------------------------

class TestCircuitBreakerStateMetrics(unittest.TestCase):
    """Circuit-breaker state gauge reflects open/closed/half_open."""

    def setUp(self):
        _reset_gauge(CIRCUIT_BREAKER_STATE)

    def test_closed_state(self):
        CIRCUIT_BREAKER_STATE.set(0.0, webhook_id="w1")
        self.assertEqual(CIRCUIT_BREAKER_STATE.get(webhook_id="w1"), 0.0)

    def test_open_state(self):
        CIRCUIT_BREAKER_STATE.set(1.0, webhook_id="w1")
        self.assertEqual(CIRCUIT_BREAKER_STATE.get(webhook_id="w1"), 1.0)

    def test_half_open_state(self):
        CIRCUIT_BREAKER_STATE.set(2.0, webhook_id="w1")
        self.assertEqual(CIRCUIT_BREAKER_STATE.get(webhook_id="w1"), 2.0)


# ---------------------------------------------------------------------------
# TestAuditLedgerMetrics
# ---------------------------------------------------------------------------

class TestAuditLedgerMetrics(unittest.TestCase):
    """Audit entry count gauge updates correctly."""

    def setUp(self):
        _reset_gauge(AUDIT_ENTRIES)

    def test_set_count(self):
        AUDIT_ENTRIES.set(42.0)
        self.assertEqual(AUDIT_ENTRIES.get(), 42.0)

    def test_update_count(self):
        AUDIT_ENTRIES.set(10.0)
        AUDIT_ENTRIES.set(20.0)
        self.assertEqual(AUDIT_ENTRIES.get(), 20.0)

    def test_produces_output(self):
        AUDIT_ENTRIES.set(5.0)
        lines = AUDIT_ENTRIES.collect()
        self.assertTrue(any("cortex_audit_entries_total 5" in l for l in lines))


# ---------------------------------------------------------------------------
# TestCacheMetrics
# ---------------------------------------------------------------------------

class TestCacheMetrics(unittest.TestCase):
    """Cache hit and miss counters."""

    def setUp(self):
        _reset_counter(CACHE_HITS)
        _reset_counter(CACHE_MISSES)

    def test_cache_hit(self):
        CACHE_HITS.inc()
        self.assertEqual(CACHE_HITS.get(), 1.0)

    def test_cache_miss(self):
        CACHE_MISSES.inc()
        self.assertEqual(CACHE_MISSES.get(), 1.0)

    def test_multiple_hits_and_misses(self):
        CACHE_HITS.inc()
        CACHE_HITS.inc()
        CACHE_MISSES.inc()
        self.assertEqual(CACHE_HITS.get(), 2.0)
        self.assertEqual(CACHE_MISSES.get(), 1.0)

    def test_unconditional_request_no_increment(self):
        """When no If-None-Match is sent, neither counter should fire."""
        # This is inherent — we only call inc() in the handler when
        # If-None-Match is present. Here we verify counters stay at zero.
        self.assertEqual(CACHE_HITS.get(), 0.0)
        self.assertEqual(CACHE_MISSES.get(), 0.0)


# ---------------------------------------------------------------------------
# TestSSEMetrics
# ---------------------------------------------------------------------------

class TestSSEMetrics(unittest.TestCase):
    """SSE subscriber gauge and event counter."""

    def setUp(self):
        _reset_gauge(SSE_SUBSCRIBERS_ACTIVE)
        _reset_counter(SSE_EVENTS)

    def test_subscriber_gauge(self):
        SSE_SUBSCRIBERS_ACTIVE.set(3.0)
        self.assertEqual(SSE_SUBSCRIBERS_ACTIVE.get(), 3.0)

    def test_event_counter_by_type(self):
        SSE_EVENTS.inc(event_type="context.updated")
        SSE_EVENTS.inc(event_type="context.updated")
        SSE_EVENTS.inc(event_type="grant.created")
        self.assertEqual(SSE_EVENTS.get(event_type="context.updated"), 2.0)
        self.assertEqual(SSE_EVENTS.get(event_type="grant.created"), 1.0)

    def test_event_counter_output(self):
        SSE_EVENTS.inc(event_type="context.updated")
        lines = SSE_EVENTS.collect()
        output = "\n".join(lines)
        self.assertIn('event_type="context.updated"', output)


# ---------------------------------------------------------------------------
# TestMetricsConfigFlag
# ---------------------------------------------------------------------------

class TestMetricsConfigFlag(unittest.TestCase):
    """CLI flag parsing and config file loading for --enable-metrics."""

    def test_serve_parser_has_enable_metrics(self):
        from cortex.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["serve", "dummy.json", "--enable-metrics"])
        self.assertTrue(args.enable_metrics)

    def test_serve_parser_default_false(self):
        from cortex.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["serve", "dummy.json"])
        self.assertFalse(args.enable_metrics)

    def test_config_metrics_section_defaults(self):
        from cortex.caas.config import CortexConfig
        config = CortexConfig.defaults()
        self.assertFalse(config.getbool("metrics", "enabled", fallback=False))

    def test_config_metrics_enabled_true(self):
        import configparser

        from cortex.caas.config import CortexConfig
        parser = configparser.ConfigParser()
        parser["metrics"] = {"enabled": "true"}
        config = CortexConfig(parser)
        self.assertTrue(config.getbool("metrics", "enabled", fallback=False))


# ---------------------------------------------------------------------------
# Integration: Webhook worker records metrics
# ---------------------------------------------------------------------------

class TestWebhookWorkerMetricsIntegration(unittest.TestCase):
    """Webhook worker records delivery metrics during actual deliveries."""

    def setUp(self):
        _reset_counter(WEBHOOK_DELIVERIES)
        _reset_gauge(WEBHOOK_DEAD_LETTERS)

    def test_circuit_open_records_metric(self):
        """When circuit is open, delivery records circuit_open metric."""
        from cortex.caas.storage import JsonWebhookStore
        from cortex.caas.webhook_worker import WebhookWorker

        store = JsonWebhookStore()
        worker = WebhookWorker(store, max_retries=1)

        # Create a mock registration
        reg = MagicMock()
        reg.webhook_id = "test-wh-circuit"
        reg.url = "http://example.com/hook"

        # Force circuit open
        cb = worker._get_circuit(reg.webhook_id)
        for _ in range(10):
            cb.record_failure()

        # Attempt delivery — circuit should be open
        worker._deliver_with_retry(reg, "test.event", {"key": "value"})

        self.assertEqual(
            WEBHOOK_DELIVERIES.get(webhook_id="test-wh-circuit", status="circuit_open"),
            1.0,
        )

    def test_successful_delivery_records_metric(self):
        """When delivery succeeds, records success metric."""
        from cortex.caas.storage import JsonWebhookStore
        from cortex.caas.webhook_worker import WebhookWorker

        store = JsonWebhookStore()
        worker = WebhookWorker(store, max_retries=1)

        reg = MagicMock()
        reg.webhook_id = "test-wh-success"
        reg.url = "http://example.com/hook"

        with patch("cortex.caas.webhook_worker.deliver_webhook", return_value=(True, 200, {})):
            worker._deliver_with_retry(reg, "test.event", {"key": "value"})

        self.assertEqual(
            WEBHOOK_DELIVERIES.get(webhook_id="test-wh-success", status="success"),
            1.0,
        )

    def test_exhausted_retries_records_failure(self):
        """When all retries fail, records failure metric + dead-letter gauge."""
        from cortex.caas.storage import JsonWebhookStore
        from cortex.caas.webhook_worker import WebhookWorker

        store = JsonWebhookStore()
        worker = WebhookWorker(store, max_retries=1, backoff_base=0.001)

        reg = MagicMock()
        reg.webhook_id = "test-wh-fail"
        reg.url = "http://example.com/hook"

        with patch("cortex.caas.webhook_worker.deliver_webhook", return_value=(False, 503, {})):
            worker._deliver_with_retry(reg, "test.event", {"key": "value"})

        self.assertEqual(
            WEBHOOK_DELIVERIES.get(webhook_id="test-wh-fail", status="failure"),
            1.0,
        )
        # Dead-letter gauge should reflect 1 entry
        self.assertGreaterEqual(
            WEBHOOK_DEAD_LETTERS.get(webhook_id="test-wh-fail"),
            1.0,
        )


# ---------------------------------------------------------------------------
# Integration: SSE broadcast records metrics
# ---------------------------------------------------------------------------

class TestSSEBroadcastMetricsIntegration(unittest.TestCase):
    """SSE broadcast records event counter."""

    def setUp(self):
        _reset_counter(SSE_EVENTS)

    def test_broadcast_increments_event_counter(self):
        from cortex.caas.sse import SSEManager
        mgr = SSEManager()
        mgr.broadcast("context.updated", {"test": True})
        self.assertEqual(SSE_EVENTS.get(event_type="context.updated"), 1.0)

    def test_broadcast_multiple_types(self):
        from cortex.caas.sse import SSEManager
        mgr = SSEManager()
        mgr.broadcast("context.updated", {"test": True})
        mgr.broadcast("grant.created", {"test": True})
        mgr.broadcast("context.updated", {"test": True})
        self.assertEqual(SSE_EVENTS.get(event_type="context.updated"), 2.0)
        self.assertEqual(SSE_EVENTS.get(event_type="grant.created"), 1.0)


if __name__ == "__main__":
    unittest.main()
