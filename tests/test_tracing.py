"""Tests for cortex.caas.tracing — OpenTelemetry-compatible distributed tracing."""

from __future__ import annotations

import json
import time

import pytest

from cortex.caas.tracing import (
    ConsoleExporter,
    NoopExporter,
    OTLPHttpExporter,
    Span,
    SpanExporter,
    TracingManager,
    _set_current_span,
    current_span,
)


# ---------------------------------------------------------------------------
# Span tests
# ---------------------------------------------------------------------------

class TestSpan:
    def test_create_span(self):
        s = Span("test-op")
        assert s.name == "test-op"
        assert len(s.trace_id) == 32
        assert len(s.span_id) == 16
        assert s.parent_span_id is None
        assert s.status == "OK"

    def test_set_attribute(self):
        s = Span("op")
        s.set_attribute("method", "GET")
        s.set_attribute("status", 200)
        assert s.attributes["method"] == "GET"
        assert s.attributes["status"] == 200

    def test_add_event(self):
        s = Span("op")
        s.add_event("cache_miss", {"key": "abc"})
        assert len(s.events) == 1
        assert s.events[0]["name"] == "cache_miss"
        assert s.events[0]["attributes"]["key"] == "abc"

    def test_end_records_time(self):
        s = Span("op")
        time.sleep(0.01)
        s.end()
        assert s.end_time is not None
        assert s.end_time >= s.start_time

    def test_duration_ms(self):
        s = Span("op")
        time.sleep(0.01)
        s.end()
        assert s.duration_ms >= 10

    def test_to_dict(self):
        s = Span("test-op")
        s.set_attribute("key", "value")
        s.end()
        d = s.to_dict()
        assert d["name"] == "test-op"
        assert d["trace_id"] == s.trace_id
        assert d["span_id"] == s.span_id
        assert d["attributes"]["key"] == "value"
        assert d["status"] == "OK"
        assert "duration_ms" in d

    def test_to_dict_with_parent(self):
        s = Span("child", parent_span_id="abc123")
        d = s.to_dict()
        assert d["parent_span_id"] == "abc123"

    def test_to_dict_without_parent(self):
        s = Span("root")
        d = s.to_dict()
        assert "parent_span_id" not in d

    def test_set_status(self):
        s = Span("op")
        s.set_status("ERROR")
        assert s.status == "ERROR"

    def test_traceparent_header(self):
        s = Span("op")
        tp = s.traceparent()
        assert tp.startswith("00-")
        parts = tp.split("-")
        assert len(parts) == 4
        assert parts[0] == "00"
        assert len(parts[1]) == 32
        assert len(parts[2]) == 16
        assert parts[3] == "01"

    def test_parse_traceparent(self):
        result = Span.parse_traceparent("00-abcdef12345678901234567890abcdef-1234567890abcdef-01")
        assert result is not None
        trace_id, parent_id = result
        assert trace_id == "abcdef12345678901234567890abcdef"
        assert parent_id == "1234567890abcdef"

    def test_parse_traceparent_invalid(self):
        assert Span.parse_traceparent("invalid") is None
        assert Span.parse_traceparent("00-abc") is None


# ---------------------------------------------------------------------------
# Thread-local context tests
# ---------------------------------------------------------------------------

class TestSpanContext:
    def test_current_span_none_by_default(self):
        _set_current_span(None)
        assert current_span() is None

    def test_set_and_get_current_span(self):
        s = Span("test")
        _set_current_span(s)
        assert current_span() is s
        _set_current_span(None)


# ---------------------------------------------------------------------------
# Exporter tests
# ---------------------------------------------------------------------------

class TestConsoleExporter:
    def test_export_does_not_raise(self):
        exporter = ConsoleExporter()
        s = Span("test")
        s.end()
        exporter.export(s)  # Should log, not raise


class TestNoopExporter:
    def test_export_does_nothing(self):
        exporter = NoopExporter()
        s = Span("test")
        exporter.export(s)


class TestOTLPHttpExporter:
    def test_default_endpoint(self):
        exporter = OTLPHttpExporter()
        assert "4318" in exporter.endpoint

    def test_custom_endpoint(self):
        exporter = OTLPHttpExporter(endpoint="http://collector:4318/v1/traces")
        assert exporter.endpoint == "http://collector:4318/v1/traces"

    def test_to_otlp_span(self):
        s = Span("test")
        s.set_attribute("method", "GET")
        s.end()
        otlp = OTLPHttpExporter._to_otlp_span(s)
        assert otlp["name"] == "test"
        assert otlp["traceId"] == s.trace_id
        assert otlp["spanId"] == s.span_id
        assert otlp["status"]["code"] == 1  # OK


# ---------------------------------------------------------------------------
# TracingManager tests
# ---------------------------------------------------------------------------

class TestTracingManager:
    def test_create_with_console(self):
        mgr = TracingManager(exporter="console")
        assert isinstance(mgr.exporter, ConsoleExporter)

    def test_create_with_noop(self):
        mgr = TracingManager(exporter="noop")
        assert isinstance(mgr.exporter, NoopExporter)

    def test_create_with_otlp(self):
        mgr = TracingManager(exporter="otlp_http", endpoint="http://localhost:4318/v1/traces")
        assert isinstance(mgr.exporter, OTLPHttpExporter)

    def test_unknown_exporter_falls_back_to_noop(self):
        mgr = TracingManager(exporter="unknown")
        assert isinstance(mgr.exporter, NoopExporter)

    def test_span_context_manager(self):
        mgr = TracingManager(exporter="noop")
        with mgr.span("test-op", attributes={"key": "val"}) as s:
            assert current_span() is s
            assert s.name == "test-op"
            assert s.attributes["key"] == "val"
        # After context exit, span should be ended
        assert s.end_time is not None

    def test_nested_spans_propagate_trace_id(self):
        mgr = TracingManager(exporter="noop")
        with mgr.span("parent") as parent:
            with mgr.span("child") as child:
                assert child.trace_id == parent.trace_id
                assert child.parent_span_id == parent.span_id
        # After both exit, current span should be None
        assert current_span() is None

    def test_span_error_handling(self):
        mgr = TracingManager(exporter="noop")
        with pytest.raises(RuntimeError):
            with mgr.span("failing") as s:
                raise RuntimeError("boom")
        assert s.status == "ERROR"
        assert s.attributes.get("error.message") == "boom"

    def test_traceparent_propagation(self):
        mgr = TracingManager(exporter="noop")
        tp = "00-abcdef12345678901234567890abcdef-1234567890abcdef-01"
        with mgr.span("child", traceparent=tp) as s:
            assert s.trace_id == "abcdef12345678901234567890abcdef"
            assert s.parent_span_id == "1234567890abcdef"

    def test_enabled_toggle(self):
        mgr = TracingManager(exporter="noop")
        assert mgr.enabled is True
        mgr.enabled = False
        assert mgr.enabled is False

    def test_span_restores_parent(self):
        mgr = TracingManager(exporter="noop")
        _set_current_span(None)
        with mgr.span("outer") as outer:
            with mgr.span("inner") as inner:
                assert current_span() is inner
            assert current_span() is outer
        assert current_span() is None
