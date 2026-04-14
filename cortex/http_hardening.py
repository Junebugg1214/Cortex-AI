from __future__ import annotations

import json
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from time import monotonic
from typing import Any, Mapping

DEFAULT_MAX_BODY_BYTES = 1_048_576
DEFAULT_READ_TIMEOUT_SECONDS = 15.0
DEFAULT_HOSTED_RATE_LIMIT_PER_MINUTE = 60


@dataclass(frozen=True, slots=True)
class HTTPRequestPolicy:
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS
    rate_limit_per_minute: int = 0
    trust_forwarded_headers: bool = False
    trusted_proxies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_body_bytes": self.max_body_bytes,
            "read_timeout_seconds": self.read_timeout_seconds,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "trust_forwarded_headers": self.trust_forwarded_headers,
            "trusted_proxies": list(self.trusted_proxies),
        }


class HTTPRequestValidationError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = int(status)
        self.message = message


class InMemoryRateLimiter:
    def __init__(self, limit_per_minute: int) -> None:
        self.limit_per_minute = max(0, int(limit_per_minute))
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.limit_per_minute <= 0:
            return True
        now = monotonic()
        window_start = now - 60.0
        with self._lock:
            events = self._events[key]
            while events and events[0] <= window_start:
                events.popleft()
            if len(events) >= self.limit_per_minute:
                return False
            events.append(now)
            return True


def request_policy_for_mode(runtime_mode: str) -> HTTPRequestPolicy:
    if str(runtime_mode or "").strip().lower() == "hosted-service":
        return HTTPRequestPolicy(rate_limit_per_minute=DEFAULT_HOSTED_RATE_LIMIT_PER_MINUTE)
    return HTTPRequestPolicy()


def apply_read_timeout(handler: Any, *, policy: HTTPRequestPolicy) -> None:
    connection = getattr(handler, "connection", None)
    if connection is None:
        return
    try:
        connection.settimeout(float(policy.read_timeout_seconds))
    except Exception:
        return


def _trusted_proxy_set(policy: HTTPRequestPolicy | None) -> set[str]:
    return {str(item).strip() for item in tuple(getattr(policy, "trusted_proxies", ()) or ()) if str(item).strip()}


def client_identifier(handler: Any, *, policy: HTTPRequestPolicy | None = None) -> str:
    client_address = getattr(handler, "client_address", None)
    client_ip = str(client_address[0]).strip() if client_address and client_address[0] else "unknown"
    if not client_ip:
        client_ip = "unknown"
    headers = getattr(handler, "headers", {}) or {}
    normalized_headers = {str(key).lower(): value for key, value in dict(headers).items()}
    if policy and policy.trust_forwarded_headers and client_ip in _trusted_proxy_set(policy):
        forwarded = str(normalized_headers.get("x-forwarded-for", "")).strip()
        if forwarded:
            forwarded_client = forwarded.split(",", 1)[0].strip()
            if forwarded_client:
                return forwarded_client
    return client_ip


def enforce_rate_limit(
    handler: Any,
    *,
    limiter: InMemoryRateLimiter | None,
    policy: HTTPRequestPolicy | None = None,
) -> str | None:
    if limiter is None or limiter.limit_per_minute <= 0:
        return None
    if limiter.allow(client_identifier(handler, policy=policy)):
        return None
    return f"Too many requests: limit is {limiter.limit_per_minute} requests per minute."


def _content_length(headers: Mapping[str, Any], *, max_body_bytes: int) -> int:
    raw_length = str(headers.get("Content-Length", "0") or "0").strip()
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise HTTPRequestValidationError(400, "Invalid Content-Length header.") from exc
    if length < 0:
        raise HTTPRequestValidationError(400, "Invalid Content-Length header.")
    if length > max_body_bytes:
        raise HTTPRequestValidationError(413, f"Request body exceeds {max_body_bytes} bytes.")
    return length


def _require_json_content_type(headers: Mapping[str, Any], *, length: int) -> None:
    if length <= 0:
        return
    raw = str(headers.get("Content-Type", "") or "").strip()
    media_type = raw.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPRequestValidationError(415, "Expected Content-Type: application/json.")


def read_json_request(
    handler: Any,
    *,
    policy: HTTPRequestPolicy,
    require_object: bool = True,
) -> Any:
    length = _content_length(handler.headers, max_body_bytes=policy.max_body_bytes)
    _require_json_content_type(handler.headers, length=length)
    raw = handler.rfile.read(length) if length else (b"{}" if require_object else b"")
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except UnicodeDecodeError as exc:
        raise HTTPRequestValidationError(400, "Request body must be valid UTF-8 JSON.") from exc
    except json.JSONDecodeError as exc:
        raise HTTPRequestValidationError(400, f"Invalid JSON body: {exc.msg}") from exc
    if require_object and not isinstance(payload, dict):
        raise HTTPRequestValidationError(400, "JSON body must decode to an object.")
    return payload


__all__ = [
    "DEFAULT_HOSTED_RATE_LIMIT_PER_MINUTE",
    "DEFAULT_MAX_BODY_BYTES",
    "DEFAULT_READ_TIMEOUT_SECONDS",
    "HTTPRequestPolicy",
    "HTTPRequestValidationError",
    "InMemoryRateLimiter",
    "apply_read_timeout",
    "client_identifier",
    "enforce_rate_limit",
    "read_json_request",
    "request_policy_for_mode",
]
