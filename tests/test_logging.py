"""Tests for cortex.caas.logging_config — Structured logging."""

from __future__ import annotations

import json
import logging
from io import StringIO

from cortex.caas.logging_config import (
    JsonFormatter,
    RequestLogFilter,
    TextFormatter,
    clear_request_context,
    get_request_id,
    set_request_id,
    setup_logging,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler(formatter: logging.Formatter) -> tuple[logging.Handler, StringIO]:
    """Create a StreamHandler writing to a StringIO buffer."""
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(formatter)
    handler.addFilter(RequestLogFilter())
    return handler, buf


def _make_record(
    name: str = "test.logger",
    level: int = logging.INFO,
    msg: str = "test message",
    **extra,
) -> logging.LogRecord:
    """Create a LogRecord with optional extra attrs."""
    record = logging.LogRecord(
        name=name, level=level, pathname="", lineno=0,
        msg=msg, args=(), exc_info=None,
    )
    for k, v in extra.items():
        setattr(record, k, v)
    return record


# ---------------------------------------------------------------------------
# TestJsonFormatter
# ---------------------------------------------------------------------------

class TestJsonFormatter:
    def setup_method(self):
        clear_request_context()

    def test_basic_json_output(self):
        fmt = JsonFormatter()
        record = _make_record(msg="hello world")
        output = fmt.format(record)
        data = json.loads(output)
        assert data["message"] == "hello world"
        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert "timestamp" in data

    def test_includes_request_id(self):
        set_request_id("req-123")
        fmt = JsonFormatter()
        record = _make_record()
        output = fmt.format(record)
        data = json.loads(output)
        assert data["request_id"] == "req-123"

    def test_no_request_id_when_unset(self):
        fmt = JsonFormatter()
        record = _make_record()
        output = fmt.format(record)
        data = json.loads(output)
        assert "request_id" not in data

    def test_includes_extra_fields(self):
        fmt = JsonFormatter()
        record = _make_record(method="GET", path="/context", status=200, duration_ms=12.3)
        output = fmt.format(record)
        data = json.loads(output)
        assert data["method"] == "GET"
        assert data["path"] == "/context"
        assert data["status"] == 200
        assert data["duration_ms"] == 12.3

    def test_exception_included(self):
        fmt = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="", lineno=0,
                msg="error", args=(), exc_info=sys.exc_info(),
            )
        output = fmt.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError: boom" in data["exception"]

    def test_output_is_valid_json(self):
        fmt = JsonFormatter()
        for msg in ["simple", "with 'quotes'", 'with "double"', "with\nnewline"]:
            record = _make_record(msg=msg)
            output = fmt.format(record)
            json.loads(output)  # Should not raise

    def test_level_matches_record(self):
        fmt = JsonFormatter()
        for level in (logging.DEBUG, logging.WARNING, logging.ERROR, logging.CRITICAL):
            record = _make_record(level=level)
            data = json.loads(fmt.format(record))
            assert data["level"] == logging.getLevelName(level)


# ---------------------------------------------------------------------------
# TestTextFormatter
# ---------------------------------------------------------------------------

class TestTextFormatter:
    def setup_method(self):
        clear_request_context()

    def test_basic_text_output(self):
        fmt = TextFormatter()
        record = _make_record(msg="hello")
        output = fmt.format(record)
        assert "[INFO]" in output
        assert "test.logger" in output
        assert "hello" in output

    def test_includes_request_id(self):
        set_request_id("req-abc")
        fmt = TextFormatter()
        record = _make_record(msg="test")
        output = fmt.format(record)
        assert "[req-abc]" in output

    def test_no_request_id_when_unset(self):
        fmt = TextFormatter()
        record = _make_record(msg="test")
        output = fmt.format(record)
        assert "[]" not in output

    def test_includes_extra_fields(self):
        fmt = TextFormatter()
        record = _make_record(method="POST", path="/grants", status=201, duration_ms=5.5)
        output = fmt.format(record)
        assert "method=POST" in output
        assert "path=/grants" in output
        assert "status=201" in output

    def test_timestamp_format(self):
        fmt = TextFormatter()
        record = _make_record()
        output = fmt.format(record)
        # Should start with ISO-like timestamp
        assert output[4] == "-"  # YYYY-MM-...
        assert "Z" in output[:25]

    def test_exception_appended(self):
        fmt = TextFormatter()
        try:
            raise RuntimeError("crash")
        except RuntimeError:
            import sys
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="", lineno=0,
                msg="fail", args=(), exc_info=sys.exc_info(),
            )
        output = fmt.format(record)
        assert "RuntimeError: crash" in output


# ---------------------------------------------------------------------------
# TestRequestLogFilter
# ---------------------------------------------------------------------------

class TestRequestLogFilter:
    def setup_method(self):
        clear_request_context()

    def test_injects_request_id(self):
        set_request_id("filter-123")
        f = RequestLogFilter()
        record = _make_record()
        f.filter(record)
        assert record.request_id == "filter-123"  # type: ignore

    def test_empty_when_no_context(self):
        f = RequestLogFilter()
        record = _make_record()
        f.filter(record)
        assert record.request_id == ""  # type: ignore

    def test_always_returns_true(self):
        f = RequestLogFilter()
        record = _make_record()
        assert f.filter(record) is True


# ---------------------------------------------------------------------------
# TestSetupLogging
# ---------------------------------------------------------------------------

class TestSetupLogging:
    def teardown_method(self):
        # Reset root logger
        root = logging.getLogger()
        for h in root.handlers[:]:
            root.removeHandler(h)
        root.setLevel(logging.WARNING)
        clear_request_context()

    def test_setup_text_format(self):
        setup_logging(level="DEBUG", fmt="text")
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, TextFormatter)

    def test_setup_json_format(self):
        setup_logging(level="INFO", fmt="json")
        root = logging.getLogger()
        assert isinstance(root.handlers[0].formatter, JsonFormatter)

    def test_removes_duplicate_handlers(self):
        setup_logging(level="INFO", fmt="text")
        setup_logging(level="INFO", fmt="text")
        root = logging.getLogger()
        assert len(root.handlers) == 1

    def test_level_filtering(self):
        setup_logging(level="ERROR", fmt="text")
        logger = logging.getLogger("test.filter")
        # Replace handler's stream to capture output
        buf = StringIO()
        root = logging.getLogger()
        root.handlers[0].stream = buf
        logger.info("should be filtered")
        logger.error("should appear")
        output = buf.getvalue()
        assert "should be filtered" not in output
        assert "should appear" in output

    def test_logger_hierarchy(self):
        setup_logging(level="DEBUG", fmt="text")
        child = logging.getLogger("caas.server.sub")
        buf = StringIO()
        root = logging.getLogger()
        root.handlers[0].stream = buf
        child.info("child message")
        output = buf.getvalue()
        assert "caas.server.sub" in output
        assert "child message" in output


# ---------------------------------------------------------------------------
# TestRequestContext
# ---------------------------------------------------------------------------

class TestRequestContext:
    def setup_method(self):
        clear_request_context()

    def test_set_and_get(self):
        set_request_id("ctx-001")
        assert get_request_id() == "ctx-001"

    def test_clear(self):
        set_request_id("ctx-002")
        clear_request_context()
        assert get_request_id() == ""

    def test_default_is_empty(self):
        assert get_request_id() == ""
