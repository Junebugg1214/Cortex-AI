from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from cortex.config import APIKeyConfig, validate_runtime_security
from cortex.release import API_VERSION, OPENAPI_VERSION, PROJECT_VERSION
from cortex.runtime_control import ShutdownController, install_shutdown_handlers
from cortex.runtime_logging import get_logger, log_operation
from cortex.service import MemoryService
from cortex.service.http_hardening import (
    HTTPRequestPolicy,
    HTTPRequestValidationError,
    InMemoryRateLimiter,
    enforce_rate_limit,
    request_policy_for_mode,
)
from cortex.service.server import _error_envelope as _server_error_envelope
from cortex.service.server import _json_bytes, dispatch_api_request

LOGGER = get_logger("cortex.server.asgi")


@dataclass(frozen=True)
class _ASGIClientView:
    client_address: tuple[str, int]
    headers: dict[str, str]


class XRequestIDMiddleware(BaseHTTPMiddleware):
    """Ensure every ASGI request has a stable request id header."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id", "").strip() or uuid4().hex[:16]
        raw_headers = list(request.scope.get("headers", []))
        if not any(key.lower() == b"x-request-id" for key, _value in raw_headers):
            raw_headers.append((b"x-request-id", request_id.encode("ascii")))
            request.scope["headers"] = raw_headers
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def _header_value(headers: dict[str, str], name: str, default: str = "") -> str:
    return str(headers.get(name.lower()) or headers.get(name) or default)


def _content_length(headers: dict[str, str], *, max_body_bytes: int) -> int:
    raw_length = _header_value(headers, "content-length", "0").strip() or "0"
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise HTTPRequestValidationError(400, "Invalid Content-Length header.") from exc
    if length < 0:
        raise HTTPRequestValidationError(400, "Invalid Content-Length header.")
    if length > max_body_bytes:
        raise HTTPRequestValidationError(413, f"Request body exceeds {max_body_bytes} bytes.")
    return length


def _require_json_content_type(headers: dict[str, str], *, length: int) -> None:
    if length <= 0:
        return
    raw = _header_value(headers, "content-type").strip()
    media_type = raw.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPRequestValidationError(415, "Expected Content-Type: application/json.")


async def _read_json_request(request: Request, *, policy: HTTPRequestPolicy, require_object: bool = True) -> Any:
    headers = {str(key).lower(): value for key, value in request.headers.items()}
    length = _content_length(headers, max_body_bytes=policy.max_body_bytes)
    _require_json_content_type(headers, length=length)
    raw = await request.body()
    if len(raw) > policy.max_body_bytes:
        raise HTTPRequestValidationError(413, f"Request body exceeds {policy.max_body_bytes} bytes.")
    if not raw and require_object:
        raw = b"{}"
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except UnicodeDecodeError as exc:
        raise HTTPRequestValidationError(400, "Request body must be valid UTF-8 JSON.") from exc
    except json.JSONDecodeError as exc:
        raise HTTPRequestValidationError(400, f"Invalid JSON body: {exc.msg}") from exc
    if require_object and not isinstance(payload, dict):
        raise HTTPRequestValidationError(400, "JSON body must decode to an object.")
    return payload


def _request_error_payload(status: int, message: str) -> dict[str, Any]:
    code = "invalid_request"
    suggestion = "Fix the request and try again."
    if status == 401:
        code = "unauthorized"
        suggestion = "Send a valid API key, then retry."
    elif status == 403:
        code = "forbidden"
        suggestion = "Use a key or namespace with access to this operation."
    elif status == 404:
        code = "not_found"
        suggestion = "Check the requested endpoint path and method."
    elif status == 413:
        code = "request_too_large"
        suggestion = "Reduce the request size and send it again."
    elif status == 415:
        code = "unsupported_media_type"
        suggestion = "Send JSON with Content-Type: application/json."
    elif status == 429:
        code = "rate_limited"
        suggestion = "Wait for the rate-limit window to reset, then retry."
    return _server_error_envelope(message, code=code, suggestion=suggestion)


def _json_response(payload: dict[str, Any], *, status: int = 200) -> Response:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Cortex-Release": PROJECT_VERSION,
        "X-Cortex-API-Version": API_VERSION,
        "X-Cortex-OpenAPI-Version": OPENAPI_VERSION,
    }
    if payload.get("request_id"):
        headers["X-Request-ID"] = str(payload["request_id"])
    release = payload.get("release")
    if isinstance(release, dict):
        contract = release.get("contract")
        if isinstance(contract, dict) and contract.get("hash"):
            headers["X-Cortex-Contract-Hash"] = str(contract["hash"])
    return Response(_json_bytes(payload), status_code=status, headers=headers)


def _request_path(request: Request) -> str:
    query = request.url.query
    return f"{request.url.path}?{query}" if query else request.url.path


def build_asgi_app(
    service: MemoryService,
    *,
    api_key: str | None = None,
    auth_keys: tuple[APIKeyConfig, ...] = (),
    request_policy: HTTPRequestPolicy | None = None,
    external_base_url: str | None = None,
    cors_origins: Iterable[str] = (),
) -> Starlette:
    """Build a Starlette app that mirrors the stdlib Cortex REST API."""

    policy = request_policy or HTTPRequestPolicy()
    rate_limiter = InMemoryRateLimiter(policy.rate_limit_per_minute) if policy.rate_limit_per_minute else None

    async def api_endpoint(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204)

        headers = {str(key): value for key, value in request.headers.items()}
        client_host = request.client.host if request.client else "unknown"
        client_port = request.client.port if request.client else 0
        rate_error = enforce_rate_limit(
            _ASGIClientView(client_address=(client_host, client_port), headers=headers),
            limiter=rate_limiter,
            policy=policy,
        )
        if rate_error:
            return _json_response(_request_error_payload(429, rate_error), status=429)

        payload: dict[str, Any] | None = None
        if request.method == "POST":
            try:
                payload = await _read_json_request(request, policy=policy, require_object=True)
            except HTTPRequestValidationError as exc:
                return _json_response(_request_error_payload(exc.status, exc.message), status=exc.status)

        status, response = dispatch_api_request(
            service,
            method=request.method,
            path=_request_path(request),
            payload=payload,
            headers=headers,
            api_key=api_key,
            auth_keys=auth_keys,
            external_base_url=external_base_url,
        )
        return _json_response(response, status=status)

    app = Starlette(routes=[Route("/{path:path}", api_endpoint, methods=["GET", "POST", "OPTIONS"])])
    origins = tuple(str(origin).strip() for origin in cors_origins if str(origin).strip())
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(origins),
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=[
                "X-Request-ID",
                "X-Cortex-Release",
                "X-Cortex-API-Version",
                "X-Cortex-OpenAPI-Version",
                "X-Cortex-Contract-Hash",
            ],
        )
    app.add_middleware(XRequestIDMiddleware)
    app.state.cortex_service = service
    return app


def run_asgi_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8766,
    store_dir: str | Path = ".cortex",
    context_file: str | Path | None = None,
    runtime_mode: str = "local-single-user",
    api_key: str | None = None,
    auth_keys: tuple[APIKeyConfig, ...] = (),
    allow_unsafe_bind: bool = False,
    request_policy: HTTPRequestPolicy | None = None,
    external_base_url: str | None = None,
    cors_origins: Iterable[str] = (),
) -> int:
    """Run the Cortex REST API through Uvicorn with Cortex shutdown hooks."""

    import uvicorn

    validate_runtime_security(
        surface="api",
        host=host,
        runtime_mode=runtime_mode,
        api_keys=auth_keys,
        allow_unsafe_bind=allow_unsafe_bind,
    )
    service = MemoryService(store_dir=store_dir, context_file=context_file)
    policy = request_policy or request_policy_for_mode(runtime_mode)
    app = build_asgi_app(
        service,
        api_key=api_key,
        auth_keys=auth_keys,
        request_policy=policy,
        external_base_url=external_base_url,
        cors_origins=cors_origins,
    )
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    server.install_signal_handlers = lambda: None

    controller = ShutdownController()

    def _stop_uvicorn_on_signal() -> None:
        controller.wait()
        server.should_exit = True

    log_operation(LOGGER, logging.INFO, "startup", f"Cortex ASGI API running at http://{host}:{port}")
    monitor = threading.Thread(target=_stop_uvicorn_on_signal, daemon=True)
    monitor.start()
    with install_shutdown_handlers(controller):
        try:
            server.run()
        finally:
            controller.request_shutdown("ASGI server stopped")
    log_operation(
        LOGGER,
        logging.INFO,
        "shutdown",
        "Cortex ASGI API stopped.",
        reason=controller.reason or "Process exit",
    )
    return 0


__all__ = ["XRequestIDMiddleware", "build_asgi_app", "run_asgi_server"]
