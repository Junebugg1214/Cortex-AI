"""Shared user-facing error payload helpers for REST and MCP surfaces."""

from __future__ import annotations

from typing import Any


_JSONRPC_DEFAULTS: dict[int, tuple[str, str]] = {
    -32700: ("parse_error", "Send valid JSON-RPC 2.0 JSON and try again."),
    -32603: ("internal_error", "Retry once. If the error persists, inspect the Cortex logs."),
    -32602: ("invalid_params", "Review the method arguments and try again."),
    -32601: ("method_not_found", "Check the method or tool name and try again."),
    -32600: ("invalid_request", "Send a valid JSON-RPC 2.0 request object and try again."),
    -32029: ("rate_limited", "Wait for the rate-limit window to reset, then retry."),
    -32002: ("not_initialized", "Initialize the MCP session before calling tools."),
    -32001: ("unauthorized", "Provide a valid key, scope, or namespace, then retry."),
}


def error_envelope(
    message: str,
    *,
    code: str,
    suggestion: str,
    request_id: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a consistent user-facing error envelope."""
    payload: dict[str, Any] = {
        "status": "error",
        "error": str(message),
        "code": str(code),
        "suggestion": str(suggestion),
    }
    if request_id:
        payload["request_id"] = request_id
    if details:
        payload["details"] = dict(details)
    return payload


def jsonrpc_error_data(
    jsonrpc_code: int,
    message: str,
    *,
    code: str | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return structured JSON-RPC error data aligned with REST envelopes."""
    default_code, default_suggestion = _JSONRPC_DEFAULTS.get(
        int(jsonrpc_code),
        ("jsonrpc_error", "Review the request and try again."),
    )
    return error_envelope(
        message,
        code=code or default_code,
        suggestion=suggestion or default_suggestion,
        details=details,
    )


__all__ = ["error_envelope", "jsonrpc_error_data"]
