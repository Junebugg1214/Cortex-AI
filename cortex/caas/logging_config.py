"""
CaaS Structured Logging — JSON and text formatters with request correlation.

Configures the stdlib ``logging`` module with either JSON-lines output
(for cloud-native log aggregation) or human-readable text output.
Thread-local storage propagates the request_id from the correlation module.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Thread-local request context
# ---------------------------------------------------------------------------

_request_context = threading.local()


def set_request_id(request_id: str) -> None:
    """Set the request ID for the current thread."""
    _request_context.request_id = request_id


def get_request_id() -> str:
    """Get the request ID for the current thread (empty if unset)."""
    return getattr(_request_context, "request_id", "")


def clear_request_context() -> None:
    """Clear request context for the current thread."""
    _request_context.request_id = ""


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Outputs log records as JSON lines for structured log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = get_request_id()
        if request_id:
            entry["request_id"] = request_id
        # Include extra fields
        for key in ("method", "path", "status", "duration_ms", "client_ip"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable log format with timestamp, level, logger, and message."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        request_id = get_request_id()
        rid_part = f" [{request_id}]" if request_id else ""
        msg = record.getMessage()

        # Append structured fields if present
        extras = []
        for key in ("method", "path", "status", "duration_ms"):
            val = getattr(record, key, None)
            if val is not None:
                extras.append(f"{key}={val}")
        extra_part = " " + " ".join(extras) if extras else ""

        base = f"{ts} [{record.levelname}] {record.name}:{rid_part} {msg}{extra_part}"
        if record.exc_info and record.exc_info[1]:
            base += "\n" + self.formatException(record.exc_info)
        return base


# ---------------------------------------------------------------------------
# Filter for request_id injection
# ---------------------------------------------------------------------------

class RequestLogFilter(logging.Filter):
    """Injects request_id into log records from thread-local storage."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()  # type: ignore[attr-defined]
        return True


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Configure the root logging with the given level and format.

    Args:
        level: Logging level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        fmt: Format type — "text" or "json".
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove existing handlers to avoid duplication
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setLevel(numeric_level)

    if fmt.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter())

    handler.addFilter(RequestLogFilter())
    root.addHandler(handler)
