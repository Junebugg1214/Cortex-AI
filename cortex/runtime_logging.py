"""Structured logging helpers for long-running Cortex runtime processes."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from typing import Any, TextIO

_SENSITIVE_MARKERS = ("secret", "token", "password", "authorization", "api_key", "key")


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(item) for item in value]
    return value


def sanitize_log_fields(fields: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Redact sensitive-looking log fields before they reach the formatter."""
    sanitized: dict[str, Any] = {}
    for key, value in dict(fields or {}).items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in _SENSITIVE_MARKERS):
            sanitized[str(key)] = "[redacted]"
            continue
        sanitized[str(key)] = _sanitize_value(value)
    return sanitized


class CortexStructuredFormatter(logging.Formatter):
    """Render Cortex runtime logs as single-line JSON payloads."""

    default_time_format = "%Y-%m-%dT%H:%M:%S"
    default_msec_format = "%s.%03dZ"

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "module": record.name,
            "operation": getattr(record, "operation", ""),
            "summary": getattr(record, "summary", record.getMessage()),
        }
        fields = sanitize_log_fields(getattr(record, "fields", {}) or {})
        if fields:
            payload["fields"] = fields
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class CortexStructuredStreamHandler(logging.Handler):
    """A stream handler that follows the current stderr unless overridden."""

    terminator = "\n"

    def __init__(self, stream: TextIO | None = None) -> None:
        super().__init__()
        self._stream_override = stream

    @property
    def stream(self) -> TextIO:
        return self._stream_override or sys.stderr

    def setStream(self, stream: TextIO | None) -> TextIO | None:  # noqa: N802 - match logging API
        previous = self._stream_override
        self._stream_override = stream
        return previous

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            stream = self.stream
            stream.write(message + self.terminator)
            stream.flush()
        except Exception:
            self.handleError(record)


def configure_structured_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the shared Cortex logger tree for structured runtime logs."""
    logger = logging.getLogger("cortex")
    if not getattr(logger, "_cortex_structured_logging", False):
        handler = CortexStructuredStreamHandler()
        handler.setFormatter(CortexStructuredFormatter())
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.propagate = True
        setattr(logger, "_cortex_structured_logging", True)
    logger.setLevel(level)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a module logger from the Cortex logging tree."""
    return logging.getLogger(name)


def log_operation(
    logger: logging.Logger,
    level: int,
    operation: str,
    summary: str,
    *,
    exc_info: Any | None = None,
    **fields: Any,
) -> None:
    """Write one structured runtime log entry."""
    logger.log(
        level,
        summary,
        extra={"operation": operation, "summary": summary, "fields": sanitize_log_fields(fields)},
        exc_info=exc_info,
    )


__all__ = [
    "CortexStructuredFormatter",
    "CortexStructuredStreamHandler",
    "configure_structured_logging",
    "get_logger",
    "log_operation",
    "sanitize_log_fields",
]
