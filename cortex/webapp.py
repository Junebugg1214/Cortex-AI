"""
Small local web UI for Git-for-AI-Memory workflows.

Zero-dependency HTTP server with a single-page interface for review, blame,
history, governance, remote sync, indexing, and maintenance operations.
"""

from __future__ import annotations

import json
import secrets
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from cortex.auth import authorize_api_key
from cortex.config import APIKeyConfig, is_loopback_host, validate_runtime_security
from cortex.http_hardening import (
    HTTPRequestPolicy,
    HTTPRequestValidationError,
    InMemoryRateLimiter,
    apply_read_timeout,
    enforce_rate_limit,
    read_json_request,
    request_policy_for_mode,
)
from cortex.webapp_backend import MemoryUIBackend
from cortex.webapp_shell import UI_HTML, UI_SESSION_HEADER, UI_SESSION_PLACEHOLDER


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def _error_payload(message: str, *, code: str, suggestion: str) -> dict[str, str]:
    return {"status": "error", "error": message, "code": code, "suggestion": suggestion}


def make_handler(
    backend: MemoryUIBackend,
    *,
    api_keys: tuple[APIKeyConfig, ...] = (),
    allow_local_session: bool = True,
    session_token: str | None = None,
    request_policy: HTTPRequestPolicy | None = None,
):
    def query_value(parsed, key: str, default: str = "") -> str:
        return parse_qs(parsed.query).get(key, [default])[0]

    def query_int(parsed, key: str, default: int) -> int:
        raw = query_value(parsed, key, "")
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"Invalid integer for {key}: {raw}") from exc

    def query_bool(parsed, key: str, default: bool = False) -> bool:
        raw = query_value(parsed, key, "")
        if not raw:
            return default
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean for {key}: {raw}")

    session_secret = session_token or secrets.token_urlsafe(24)
    rendered_html = UI_HTML.replace(UI_SESSION_PLACEHOLDER, json.dumps(session_secret))
    policy = request_policy or HTTPRequestPolicy()
    rate_limiter = InMemoryRateLimiter(policy.rate_limit_per_minute) if policy.rate_limit_per_minute else None

    class MemoryUIHandler(BaseHTTPRequestHandler):
        server_version = "CortexUI/1.0"
        _cortex_ui_session_token = session_secret
        _cortex_ui_local_session_enabled = allow_local_session
        _cortex_ui_api_key_count = len(api_keys)
        _cortex_ui_request_policy = policy
        _cortex_ui_rate_limiter = rate_limiter

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send_json(self, payload: dict[str, Any], status: int = 200, *, request_id: str = "") -> None:
            data = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            if request_id:
                self.send_header("X-Request-ID", request_id)
            self.end_headers()
            self.wfile.write(data)

        def _send_html(self, text: str, status: int = 200, *, request_id: str = "") -> None:
            data = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            )
            if request_id:
                self.send_header("X-Request-ID", request_id)
            self.end_headers()
            self.wfile.write(data)

        def _normalized_headers(self) -> dict[str, str]:
            return {str(key).lower(): str(value).strip() for key, value in self.headers.items()}

        def _origin_matches_host(self, headers: dict[str, str]) -> bool:
            origin = headers.get("origin", "").strip()
            if not origin:
                return False
            host = headers.get("x-forwarded-host", "").strip() or headers.get("host", "").strip()
            if not host:
                return False
            proto = headers.get("x-forwarded-proto", "").strip() or "http"
            parsed_origin = urlparse(origin)
            return f"{parsed_origin.scheme}://{parsed_origin.netloc}" == f"{proto}://{host}"

        def _authorize_api_request(self, *, method: str) -> tuple[int, str] | None:
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                return None

            headers = self._normalized_headers()
            required_scope = "read" if method == "GET" else "write"
            decision = None
            if api_keys:
                decision = authorize_api_key(
                    keys=api_keys,
                    headers=headers,
                    required_scope=required_scope,
                    namespace=None,
                    namespace_required=False,
                )
                if decision.allowed:
                    return None

            session_header = headers.get(UI_SESSION_HEADER.lower(), "")
            if allow_local_session and session_header and secrets.compare_digest(session_header, session_secret):
                if method == "POST" and not self._origin_matches_host(headers):
                    return (
                        403,
                        "Forbidden: browser session POST requests must include an Origin matching the current host.",
                    )
                return None

            if decision is not None and decision.error and "missing API key" not in decision.error:
                return decision.status_code, decision.error
            if allow_local_session:
                return (
                    401,
                    "Unauthorized: missing API key or local UI session token. Browser requests should send X-Cortex-UI-Session.",
                )
            return 401, "Unauthorized: missing API key."

        def _log_request(
            self,
            *,
            request_id: str,
            method: str,
            path: str,
            started_at: float,
            status: int,
            error: str = "",
        ) -> None:
            backend.service.observability.record_request(
                request_id=request_id,
                method=method,
                path=path,
                status=status,
                duration_ms=(perf_counter() - started_at) * 1000,
                namespace=backend.backend.versions.current_branch(),
                backend=backend._backend_name(),
                index_lag_commits=backend._safe_index_status(ref="HEAD").get("lag_commits"),
                error=error,
            )

        def _write_request_error(self, status: int, message: str, *, request_id: str) -> None:
            self._send_json(
                _error_payload(
                    message,
                    code="rate_limited" if status == 429 else "request_error",
                    suggestion="Try again after adjusting the request.",
                ),
                status=status,
                request_id=request_id,
            )

        def _log_unhandled_exception(self, *, request_id: str, exc: Exception) -> None:
            print(f"[cortex-ui] request_id={request_id} unhandled error: {exc}", file=sys.stderr)
            traceback.print_exc()

        def _check_rate_limit(self) -> str | None:
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                return None
            return enforce_rate_limit(
                self,
                limiter=self._cortex_ui_rate_limiter,
                policy=self._cortex_ui_request_policy,
            )

        def do_GET(self) -> None:  # noqa: N802
            request_id = uuid4().hex[:16]
            started_at = perf_counter()
            status = 200
            error = ""
            try:
                apply_read_timeout(self, policy=self._cortex_ui_request_policy)
                if rate_error := self._check_rate_limit():
                    status = 429
                    error = rate_error
                    self._write_request_error(status, error, request_id=request_id)
                    return
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send_html(rendered_html, request_id=request_id)
                    return
                auth_error = self._authorize_api_request(method="GET")
                if auth_error is not None:
                    status, error = auth_error
                    self._send_json(
                        _error_payload(
                            error,
                            code="unauthorized" if status == 401 else "forbidden",
                            suggestion="Provide a valid API key or local session token, then retry.",
                        ),
                        status=status,
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/meta":
                    self._send_json(backend.meta(), request_id=request_id)
                    return
                if parsed.path == "/api/health":
                    self._send_json(backend.health(), request_id=request_id)
                    return
                if parsed.path == "/api/onboarding/state":
                    self._send_json(backend.onboarding_state(), request_id=request_id)
                    return
                if parsed.path == "/api/metrics":
                    self._send_json(backend.metrics(), request_id=request_id)
                    return
                if parsed.path == "/api/portability/scan":
                    self._send_json(
                        backend.portability_scan(
                            project_dir=query_value(parsed, "project_dir", ""),
                            metadata_only=query_bool(parsed, "metadata_only", False),
                        ),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/portability/status":
                    self._send_json(
                        backend.portability_status(project_dir=query_value(parsed, "project_dir", "")),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/portability/audit":
                    self._send_json(
                        backend.portability_audit(project_dir=query_value(parsed, "project_dir", "")),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/portability/context":
                    target = query_value(parsed, "target", "").strip()
                    if not target:
                        raise ValueError("target is required")
                    self._send_json(
                        backend.portability_context(
                            target=target,
                            project_dir=query_value(parsed, "project_dir", ""),
                            smart=query_bool(parsed, "smart", True),
                            max_chars=query_int(parsed, "max_chars", 900),
                        ),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/minds":
                    self._send_json(backend.mind_list(), request_id=request_id)
                    return
                if parsed.path == "/api/minds/status":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.mind_status(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/minds/mounts":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.mind_mounts(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/packs":
                    self._send_json(backend.pack_list(), request_id=request_id)
                    return
                if parsed.path == "/api/packs/status":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.pack_status(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/packs/sources":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.pack_sources(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/packs/concepts":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.pack_concepts(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/packs/claims":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.pack_claims(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/packs/unknowns":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.pack_unknowns(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/packs/artifacts":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.pack_artifacts(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/governance/rules":
                    self._send_json(backend.list_governance_rules(), request_id=request_id)
                    return
                if parsed.path == "/api/remotes":
                    self._send_json(backend.list_remotes(), request_id=request_id)
                    return
                if parsed.path == "/api/index/status":
                    self._send_json(
                        backend.index_status(ref=query_value(parsed, "ref", "HEAD")),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/prune/status":
                    self._send_json(
                        backend.prune_status(retention_days=query_int(parsed, "retention_days", 7)),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/prune/audit":
                    self._send_json(
                        backend.prune_audit(limit=query_int(parsed, "limit", 20)),
                        request_id=request_id,
                    )
                    return
                status = 404
                error = "Not found"
                self._send_json(
                    _error_payload(error, code="not_found", suggestion="Check the path and try again."),
                    status=status,
                    request_id=request_id,
                )
            except ValueError as exc:
                status = 400
                error = str(exc)
                self._send_json(
                    _error_payload(error, code="bad_request", suggestion="Review the request fields and try again."),
                    status=status,
                    request_id=request_id,
                )
            except FileNotFoundError as exc:
                status = 404
                error = str(exc)
                self._send_json(
                    _error_payload(error, code="not_found", suggestion="Check the file path and try again."),
                    status=status,
                    request_id=request_id,
                )
            except Exception as exc:  # pragma: no cover - defensive
                status = 500
                self._log_unhandled_exception(request_id=request_id, exc=exc)
                error = "Internal server error."
                self._send_json(
                    _error_payload(error, code="internal_error", suggestion="Retry the request or check the server logs."),
                    status=status,
                    request_id=request_id,
                )
            finally:
                self._log_request(
                    request_id=request_id,
                    method="GET",
                    path=self.path,
                    started_at=started_at,
                    status=status,
                    error=error,
                )

        def do_POST(self) -> None:  # noqa: N802
            request_id = uuid4().hex[:16]
            started_at = perf_counter()
            status = 200
            error = ""
            try:
                apply_read_timeout(self, policy=self._cortex_ui_request_policy)
                if rate_error := self._check_rate_limit():
                    status = 429
                    error = rate_error
                    self._write_request_error(status, error, request_id=request_id)
                    return
                auth_error = self._authorize_api_request(method="POST")
                if auth_error is not None:
                    status, error = auth_error
                    self._send_json(
                        _error_payload(
                            error,
                            code="unauthorized" if status == 401 else "forbidden",
                            suggestion="Provide a valid API key or local session token, then retry.",
                        ),
                        status=status,
                        request_id=request_id,
                    )
                    return
                payload = read_json_request(self, policy=self._cortex_ui_request_policy, require_object=True)
                path = self.path
                if path == "/api/review":
                    self._send_json(backend.review(**payload), request_id=request_id)
                    return
                if path == "/api/portability/sync":
                    self._send_json(backend.portability_sync(**payload), request_id=request_id)
                    return
                if path == "/api/portability/remember":
                    self._send_json(backend.portability_remember(**payload), request_id=request_id)
                    return
                if path == "/api/minds/compose":
                    self._send_json(backend.mind_compose(**payload), request_id=request_id)
                    return
                if path == "/api/blame":
                    self._send_json(backend.blame(**payload), request_id=request_id)
                    return
                if path == "/api/history":
                    self._send_json(backend.history(**payload), request_id=request_id)
                    return
                if path == "/api/governance/allow":
                    self._send_json(
                        backend.save_governance_rule(effect="allow", payload=payload), request_id=request_id
                    )
                    return
                if path == "/api/governance/deny":
                    self._send_json(backend.save_governance_rule(effect="deny", payload=payload), request_id=request_id)
                    return
                if path == "/api/governance/delete":
                    self._send_json(backend.delete_governance_rule(payload["name"]), request_id=request_id)
                    return
                if path == "/api/governance/check":
                    self._send_json(backend.check_governance(**payload), request_id=request_id)
                    return
                if path == "/api/onboarding/start":
                    self._send_json(backend.onboarding_start(**payload), request_id=request_id)
                    return
                if path == "/api/onboarding/create":
                    self._send_json(backend.onboarding_create_mind(**payload), request_id=request_id)
                    return
                if path == "/api/onboarding/ingest":
                    self._send_json(backend.onboarding_ingest_source(**payload), request_id=request_id)
                    return
                if path == "/api/onboarding/compile":
                    self._send_json(backend.onboarding_compile_output(**payload), request_id=request_id)
                    return
                if path == "/api/onboarding/skip":
                    self._send_json(backend.onboarding_skip(), request_id=request_id)
                    return
                if path == "/api/onboarding/reset":
                    self._send_json(backend.onboarding_reset(), request_id=request_id)
                    return
                if path == "/api/remote/add":
                    self._send_json(backend.add_remote(**payload), request_id=request_id)
                    return
                if path == "/api/remote/remove":
                    self._send_json(backend.remove_remote(payload["name"]), request_id=request_id)
                    return
                if path == "/api/remote/push":
                    self._send_json(backend.remote_push(**payload), request_id=request_id)
                    return
                if path == "/api/remote/pull":
                    self._send_json(backend.remote_pull(**payload), request_id=request_id)
                    return
                if path == "/api/remote/fork":
                    self._send_json(backend.remote_fork(**payload), request_id=request_id)
                    return
                if path == "/api/index/rebuild":
                    self._send_json(backend.index_rebuild(**payload), request_id=request_id)
                    return
                if path == "/api/prune":
                    self._send_json(backend.prune(**payload), request_id=request_id)
                    return
            except HTTPRequestValidationError as exc:
                status = exc.status
                error = exc.message
                self._send_json(
                    _error_payload(error, code="invalid_request", suggestion="Fix the request shape and try again."),
                    status=status,
                    request_id=request_id,
                )
            except ValueError as exc:
                status = 400
                error = str(exc)
                self._send_json(
                    _error_payload(error, code="bad_request", suggestion="Review the request fields and try again."),
                    status=status,
                    request_id=request_id,
                )
            except FileNotFoundError as exc:
                status = 404
                error = str(exc)
                self._send_json(
                    _error_payload(error, code="not_found", suggestion="Check the file path and try again."),
                    status=status,
                    request_id=request_id,
                )
            except Exception as exc:  # pragma: no cover - defensive
                status = 500
                self._log_unhandled_exception(request_id=request_id, exc=exc)
                error = "Internal server error."
                self._send_json(
                    _error_payload(error, code="internal_error", suggestion="Retry the request or check the server logs."),
                    status=status,
                    request_id=request_id,
                )
            else:
                status = 404
                error = "Not found"
                self._send_json(
                    _error_payload(error, code="not_found", suggestion="Check the path and try again."),
                    status=status,
                    request_id=request_id,
                )
            finally:
                self._log_request(
                    request_id=request_id,
                    method="POST",
                    path=self.path,
                    started_at=started_at,
                    status=status,
                    error=error,
                )

    return MemoryUIHandler


def start_ui_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    store_dir: str | Path = ".cortex",
    context_file: str | Path | None = None,
    open_browser: bool = False,
    runtime_mode: str = "local-single-user",
    allow_unsafe_bind: bool = False,
    api_keys: tuple[APIKeyConfig, ...] = (),
    request_policy: HTTPRequestPolicy | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    validate_runtime_security(
        surface="ui",
        host=host,
        runtime_mode=runtime_mode,
        api_keys=api_keys,
        allow_unsafe_bind=allow_unsafe_bind,
    )
    backend = MemoryUIBackend(store_dir=store_dir, context_file=context_file)
    policy = request_policy or request_policy_for_mode(runtime_mode)
    server = ThreadingHTTPServer(
        (host, port),
        make_handler(
            backend,
            api_keys=api_keys,
            allow_local_session=is_loopback_host(host),
            request_policy=policy,
        ),
    )
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}/"
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    return server, url
