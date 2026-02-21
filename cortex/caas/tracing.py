"""
OpenTelemetry-compatible Distributed Tracing — stdlib-only implementation.

Provides W3C Trace Context compatible spans with two exporters:
- **console**: JSON-formatted spans to the structured logger
- **otlp_http**: OTLP HTTP exporter via ``urllib.request``

Uses thread-local storage for span propagation (same pattern as
``logging_config.py``).

Usage::

    from cortex.caas.tracing import TracingManager, Span

    tracer = TracingManager(exporter="console")
    with tracer.span("handle_request", attributes={"method": "GET"}) as s:
        s.set_attribute("status", 200)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger("cortex.tracing")

# ---------------------------------------------------------------------------
# Thread-local span context
# ---------------------------------------------------------------------------

_span_context = threading.local()


def current_span() -> Span | None:
    """Return the active span for the current thread, or None."""
    return getattr(_span_context, "span", None)


def _set_current_span(span: Span | None) -> None:
    _span_context.span = span


# ---------------------------------------------------------------------------
# Span
# ---------------------------------------------------------------------------

class Span:
    """A single trace span compatible with W3C Trace Context.

    Attributes are key-value pairs attached to the span for filtering
    and querying.
    """

    __slots__ = (
        "trace_id", "span_id", "parent_span_id", "name",
        "start_time", "end_time", "attributes", "status", "events",
    )

    def __init__(
        self,
        name: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> None:
        self.trace_id = trace_id or uuid.uuid4().hex
        self.span_id = uuid.uuid4().hex[:16]
        self.parent_span_id = parent_span_id
        self.name = name
        self.start_time = time.time()
        self.end_time: float | None = None
        self.attributes: dict[str, Any] = {}
        self.status = "OK"
        self.events: list[dict[str, Any]] = []

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a key-value attribute on this span."""
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Add a timestamped event to this span."""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def set_status(self, status: str) -> None:
        """Set span status: OK or ERROR."""
        self.status = status

    def end(self) -> None:
        """End the span, recording the end time."""
        if self.end_time is None:
            self.end_time = time.time()

    @property
    def duration_ms(self) -> float:
        """Duration in milliseconds."""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        """Serialize the span to a dict."""
        d: dict[str, Any] = {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "attributes": self.attributes,
            "status": self.status,
        }
        if self.parent_span_id:
            d["parent_span_id"] = self.parent_span_id
        if self.events:
            d["events"] = self.events
        return d

    def traceparent(self) -> str:
        """Return W3C traceparent header value."""
        # Version 00, trace_id (32 hex), span_id (16 hex), flags 01 (sampled)
        tid = self.trace_id.ljust(32, "0")[:32]
        sid = self.span_id.ljust(16, "0")[:16]
        return f"00-{tid}-{sid}-01"

    @staticmethod
    def parse_traceparent(header: str) -> tuple[str, str] | None:
        """Parse a W3C traceparent header. Returns (trace_id, parent_span_id) or None."""
        parts = header.strip().split("-")
        if len(parts) < 4:
            return None
        return (parts[1], parts[2])


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------

class SpanExporter:
    """Base exporter interface."""

    def export(self, span: Span) -> None:
        raise NotImplementedError


class ConsoleExporter(SpanExporter):
    """Export spans as JSON log lines to the structured logger."""

    def export(self, span: Span) -> None:
        logger.info("span: %s", json.dumps(span.to_dict(), default=str))


class OTLPHttpExporter(SpanExporter):
    """Export spans via OTLP HTTP (urllib.request).

    Endpoint defaults to ``OTEL_EXPORTER_OTLP_ENDPOINT`` env var
    or ``http://localhost:4318/v1/traces``.
    """

    def __init__(self, endpoint: str | None = None) -> None:
        self.endpoint = endpoint or os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "http://localhost:4318/v1/traces",
        )

    def export(self, span: Span) -> None:
        import urllib.request

        payload = json.dumps({
            "resourceSpans": [{
                "resource": {"attributes": [
                    {"key": "service.name", "value": {"stringValue": "cortex-caas"}},
                ]},
                "scopeSpans": [{
                    "scope": {"name": "cortex.tracing"},
                    "spans": [self._to_otlp_span(span)],
                }],
            }],
        }).encode("utf-8")

        req = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            logger.debug("Failed to export span to %s", self.endpoint, exc_info=True)

    @staticmethod
    def _to_otlp_span(span: Span) -> dict:
        return {
            "traceId": span.trace_id,
            "spanId": span.span_id,
            "parentSpanId": span.parent_span_id or "",
            "name": span.name,
            "startTimeUnixNano": int(span.start_time * 1e9),
            "endTimeUnixNano": int((span.end_time or span.start_time) * 1e9),
            "attributes": [
                {"key": k, "value": {"stringValue": str(v)}}
                for k, v in span.attributes.items()
            ],
            "status": {"code": 1 if span.status == "OK" else 2},
        }


class NoopExporter(SpanExporter):
    """No-op exporter — discards all spans."""

    def export(self, span: Span) -> None:
        pass


# ---------------------------------------------------------------------------
# TracingManager
# ---------------------------------------------------------------------------

_EXPORTERS = {
    "console": ConsoleExporter,
    "otlp_http": OTLPHttpExporter,
    "noop": NoopExporter,
}


class TracingManager:
    """Manages span creation and export.

    Parameters
    ----------
    exporter : str
        Name of the exporter: "console", "otlp_http", or "noop".
    endpoint : str or None
        OTLP endpoint URL (only for otlp_http exporter).
    """

    def __init__(self, exporter: str = "console", endpoint: str | None = None) -> None:
        factory = _EXPORTERS.get(exporter, NoopExporter)
        if exporter == "otlp_http" and endpoint:
            self._exporter: SpanExporter = factory(endpoint=endpoint)
        else:
            self._exporter = factory()
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @contextmanager
    def span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        traceparent: str | None = None,
    ) -> Generator[Span, None, None]:
        """Context manager that creates, activates, and exports a span.

        Propagates trace context from parent span or traceparent header.
        """
        parent = current_span()
        trace_id = None
        parent_span_id = None

        if traceparent:
            parsed = Span.parse_traceparent(traceparent)
            if parsed:
                trace_id, parent_span_id = parsed
        elif parent:
            trace_id = parent.trace_id
            parent_span_id = parent.span_id

        s = Span(name, trace_id=trace_id, parent_span_id=parent_span_id)
        if attributes:
            for k, v in attributes.items():
                s.set_attribute(k, v)

        _set_current_span(s)
        try:
            yield s
        except Exception as e:
            s.set_status("ERROR")
            s.set_attribute("error.message", str(e))
            raise
        finally:
            s.end()
            _set_current_span(parent)
            if self._enabled:
                try:
                    self._exporter.export(s)
                except Exception:
                    logger.debug("Failed to export span", exc_info=True)

    @property
    def exporter(self) -> SpanExporter:
        return self._exporter
