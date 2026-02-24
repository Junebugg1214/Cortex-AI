"""
CaaS HTTP API Server — Context-as-a-Service for AI platforms.

Mirrors cortex/dashboard/server.py patterns:
- BaseHTTPRequestHandler subclass
- Class-level attributes set before server start
- _json_response() / _respond() helpers
- Security headers, CORS

Endpoints:
    GET  /                              → server info
    GET  /.well-known/upai-configuration → discovery
    GET  /identity                       → W3C DID Document

    POST   /grants                       → create grant token
    GET    /grants                       → list grants
    DELETE /grants/<grant_id>            → revoke grant

    GET  /context                        → full signed graph
    GET  /context/compact                → markdown summary
    GET  /context/nodes                  → paginated nodes
    GET  /context/nodes/<node_id>        → single node
    GET  /context/edges                  → paginated edges
    GET  /context/stats                  → graph statistics

    GET  /versions                       → paginated history
    GET  /versions/<version_id>          → single snapshot
    GET  /versions/diff                  → diff two versions

    POST   /webhooks                     → register webhook
    GET    /webhooks                     → list webhooks
    DELETE /webhooks/<webhook_id>        → unregister

    GET  /health                         → health check (no auth)

    Dashboard:
    GET  /dashboard                      → SPA shell
    GET  /dashboard/*                    → static files
    POST /dashboard/auth                 → session login
    GET  /dashboard/api/*                → owner-only JSON endpoints
    POST /dashboard/api/*                → owner-only mutations
    DELETE /dashboard/api/*              → owner-only deletions
"""

from __future__ import annotations

import json
import threading
import time as _time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import TYPE_CHECKING, Any

from cortex.caas.caching import check_if_none_match, generate_etag, get_cache_profile
from cortex.caas.correlation import parse_request_id
from cortex.caas.dashboard.auth import DashboardSessionManager
from cortex.caas.dashboard.static import guess_content_type, resolve_dashboard_path
from cortex.caas.storage import AbstractAuditLog, AbstractGrantStore, AbstractWebhookStore, JsonWebhookStore
from cortex.caas.webapp.static import guess_webapp_content_type, resolve_webapp_path
from cortex.upai.disclosure import BUILTIN_POLICIES, DisclosurePolicy, PolicyRegistry, apply_disclosure
from cortex.upai.errors import (
    ERR_INSUFFICIENT_SCOPE,
    ERR_INTERNAL,
    ERR_INVALID_POLICY,
    ERR_INVALID_REQUEST,
    ERR_INVALID_TOKEN,
    ERR_NOT_CONFIGURED,
    ERR_NOT_FOUND,
    ERR_PAYLOAD_TOO_LARGE,
    ERR_POLICY_IMMUTABLE,
    UPAIError,
)
from cortex.upai.pagination import paginate

if TYPE_CHECKING:
    from cortex.graph import CortexGraph
    from cortex.upai.identity import UPAIIdentity


# ---------------------------------------------------------------------------
# Grant store (in-memory + optional persistence)
# ---------------------------------------------------------------------------

class JsonGrantStore(AbstractGrantStore):
    """Thread-safe grant token store with optional JSON file persistence."""

    def __init__(self, persist_path: str | None = None) -> None:
        self._grants: dict[str, dict] = {}  # grant_id → {token_str, token_data, created_at, revoked}
        self._lock = threading.Lock()
        self._persist_path = persist_path
        if persist_path:
            self._load()

    def _load(self) -> None:
        if self._persist_path:
            from pathlib import Path
            p = Path(self._persist_path)
            if p.exists():
                data = json.loads(p.read_text())
                self._grants = data.get("grants", {})

    def _save(self) -> None:
        if self._persist_path:
            from pathlib import Path
            p = Path(self._persist_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"grants": self._grants}, indent=2))

    def add(self, grant_id: str, token_str: str, token_data: dict) -> None:
        with self._lock:
            self._grants[grant_id] = {
                "token_str": token_str,
                "token_data": token_data,
                "created_at": token_data.get("issued_at", ""),
                "revoked": False,
            }
            self._save()

    def get(self, grant_id: str) -> dict | None:
        with self._lock:
            return self._grants.get(grant_id)

    def list_all(self) -> list[dict]:
        with self._lock:
            result = []
            for gid, g in self._grants.items():
                result.append({
                    "grant_id": gid,
                    "audience": g["token_data"].get("audience", ""),
                    "policy": g["token_data"].get("policy", ""),
                    "created_at": g.get("created_at", ""),
                    "revoked": g.get("revoked", False),
                })
            return result

    def revoke(self, grant_id: str) -> bool:
        with self._lock:
            if grant_id in self._grants:
                self._grants[grant_id]["revoked"] = True
                self._save()
                return True
            return False


# Backward-compatible alias
GrantStore = JsonGrantStore


# ---------------------------------------------------------------------------
# Nonce cache (replay protection)
# ---------------------------------------------------------------------------

class NonceCache:
    """Thread-safe LRU nonce cache with TTL for replay protection."""

    def __init__(self, max_size: int = 10000, ttl_seconds: float = 300) -> None:
        self._cache: dict[str, float] = {}  # nonce → timestamp
        self._lock = threading.Lock()
        self._max_size = max_size
        self._ttl = ttl_seconds

    def check_and_add(self, nonce: str) -> bool:
        """Return True if nonce is fresh (not seen before). Adds it to cache."""
        with self._lock:
            self._evict_expired()
            if nonce in self._cache:
                return False
            self._cache[nonce] = _time.monotonic()
            return True

    def _evict_expired(self) -> None:
        now = _time.monotonic()
        expired = [k for k, v in self._cache.items() if now - v > self._ttl]
        for k in expired:
            del self._cache[k]
        # LRU eviction if still over max
        while len(self._cache) > self._max_size:
            oldest_key = min(self._cache, key=self._cache.get)  # type: ignore
            del self._cache[oldest_key]


# ---------------------------------------------------------------------------
# Threading HTTP Server
# ---------------------------------------------------------------------------

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_BODY_SIZE = 1_048_576  # 1 MB

VALID_SCOPES = {
    "context:read", "context:write", "context:subscribe", "versions:read", "identity:read",
    "credentials:read", "credentials:write",
    "webhooks:manage", "policies:manage", "grants:manage", "devices:manage",
}


# ---------------------------------------------------------------------------
# CaaS Request Handler
# ---------------------------------------------------------------------------

class CaaSHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the CaaS API."""

    # Class-level attributes (set before server starts)
    graph: CortexGraph | None = None
    identity: UPAIIdentity | None = None
    grant_store: AbstractGrantStore = JsonGrantStore()
    nonce_cache: NonceCache = NonceCache()
    version_store: Any = None
    webhook_store: AbstractWebhookStore = JsonWebhookStore()
    audit_log: AbstractAuditLog | None = None
    policy_registry: PolicyRegistry = PolicyRegistry()
    metrics_registry: Any = None  # Optional MetricsRegistry (None = metrics disabled)
    rate_limiter: Any = None  # Optional RateLimiter
    webhook_worker: Any = None  # Optional WebhookWorker
    _allowed_origins: set[str] = set()
    session_manager: DashboardSessionManager | None = None
    oauth_manager: Any = None  # Optional OAuthManager
    credential_store: Any = None  # Optional CredentialStore
    sse_manager: Any = None  # Optional SSEManager
    keychain: Any = None  # Optional Keychain
    csrf_enabled: bool = False  # Set True to require CSRF tokens on dashboard mutations
    plugin_manager: Any = None  # Optional PluginManager
    tracing_manager: Any = None  # Optional TracingManager
    federation_manager: Any = None  # Optional FederationManager
    enable_webapp: bool = False  # Enable /app web UI
    api_key_store: Any = None  # Optional ApiKeyStore for shareable memory
    profile_store: Any = None  # Optional ProfileStore for public profiles

    _request_id: str = ""
    _logger = None  # lazily set

    @classmethod
    def _get_logger(cls):
        if cls._logger is None:
            import logging
            cls._logger = logging.getLogger("caas.server")
        return cls._logger

    def _init_request_id(self) -> None:
        """Extract or generate a request correlation ID."""
        self._request_id = parse_request_id(self.headers.get("X-Request-ID"))
        # Propagate to thread-local for logging
        try:
            from cortex.caas.logging_config import set_request_id
            set_request_id(self._request_id)
        except ImportError:
            pass

    def _log_request(self, status_code: int) -> None:
        """Log the completed request with method, path, status, and duration."""
        logger = self._get_logger()
        duration_ms = round((_time.monotonic() - self._request_start_time) * 1000, 1)
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        method = self.command or "GET"
        logger.info(
            "%s %s %d %.1fms",
            method, path, status_code, duration_ms,
            extra={"method": method, "path": path, "status": status_code, "duration_ms": duration_ms},
        )

    def do_GET(self) -> None:
        self._request_start_time = _time.monotonic()
        self._init_request_id()
        self._metrics_inc_in_flight(1)
        if self._check_rate_limit():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        if path == "" or path == "/":
            self._serve_info()
        elif path == "/.well-known/upai-configuration":
            self._serve_discovery()
        elif path == "/identity":
            self._serve_identity()
        elif path == "/grants":
            self._serve_list_grants()
        elif path == "/health":
            self._serve_health()
        elif path == "/metrics":
            self._serve_metrics()
        elif path == "/context":
            self._serve_context(query)
        elif path == "/context/compact":
            self._serve_context_compact(query)
        elif path == "/context/nodes":
            self._serve_context_nodes(query)
        elif path == "/context/edges":
            self._serve_context_edges(query)
        elif path == "/context/stats":
            self._serve_context_stats(query)
        elif path.startswith("/context/path/"):
            rest = path[len("/context/path/"):]
            self._serve_shortest_path(rest)
        elif path.startswith("/context/nodes/") and path.endswith("/neighbors"):
            node_id = path[len("/context/nodes/"):-len("/neighbors")]
            self._serve_node_neighbors(node_id, query)
        elif path.startswith("/context/nodes/"):
            node_id = path[len("/context/nodes/"):]
            self._serve_context_node(node_id, query)
        elif path == "/versions":
            self._serve_versions(query)
        elif path == "/versions/diff":
            self._serve_version_diff(query)
        elif path.startswith("/versions/"):
            version_id = path[len("/versions/"):]
            self._serve_version(version_id, query)
        elif path == "/webhooks":
            self._serve_list_webhooks()
        elif path == "/credentials":
            self._serve_credentials(query)
        elif path.startswith("/credentials/"):
            cred_id = path[len("/credentials/"):]
            self._serve_credential_detail(cred_id)
        elif path == "/policies":
            self._serve_list_policies()
        elif path.startswith("/policies/"):
            policy_name = path[len("/policies/"):]
            self._serve_get_policy(policy_name)
        elif path.startswith("/resolve/"):
            did_encoded = path[len("/resolve/"):]
            self._serve_resolve_did(did_encoded)
        elif path == "/audit":
            self._serve_audit(query)
        elif path == "/audit/verify":
            self._serve_audit_verify()
        elif path == "/events":
            self._handle_sse(query)
        elif path == "/docs":
            self._serve_swagger_ui()
        elif path == "/openapi.json":
            self._serve_openapi_spec()
        # ── OAuth routes ──────────────────────────────────────────
        elif path == "/dashboard/oauth/providers":
            self._serve_oauth_providers()
        elif path == "/dashboard/oauth/authorize":
            self._handle_oauth_authorize(query)
        elif path == "/dashboard/oauth/callback":
            self._handle_oauth_callback(query)
        # ── Federation routes ─────────────────────────────────────
        elif path == "/federation/peers":
            self._serve_federation_peers()
        # ── Profile routes ─────────────────────────────────────
        elif path == "/api/profile":
            self._handle_get_profile()
        elif path == "/api/profile/preview":
            self._handle_profile_preview()
        elif path.startswith("/p/"):
            handle = path[len("/p/"):]
            self._serve_profile_page(handle)
        # ── Attestation routes ─────────────────────────────────
        elif path == "/api/attestations":
            self._handle_list_attestations()
        elif path.startswith("/api/attestations/"):
            node_id = path[len("/api/attestations/"):]
            self._handle_get_attestations_for_node(node_id)
        # ── Timeline routes ────────────────────────────────────
        elif path == "/api/timeline":
            self._handle_get_timeline()
        elif path.startswith("/api/timeline/"):
            self._handle_get_timeline_node(path[len("/api/timeline/"):])
        # ── API key routes ──────────────────────────────────────
        elif path == "/api/keys":
            self._handle_list_api_keys()
        elif path.startswith("/api/memory/"):
            self._handle_public_memory(path, query)
        elif path.startswith("/api/resume/"):
            self._handle_public_resume(path)
        # ── Webapp routes ────────────────────────────────────────
        elif path.startswith("/app"):
            self._serve_webapp_file(path)
        # ── Dashboard routes ──────────────────────────────────────
        elif path.startswith("/dashboard/api/"):
            self._route_dashboard_api_get(path, query)
        elif path.startswith("/dashboard"):
            self._serve_dashboard_file(path)
        else:
            self._error_response(ERR_NOT_FOUND("endpoint"))

    def do_POST(self) -> None:
        self._request_start_time = _time.monotonic()
        self._init_request_id()
        self._metrics_inc_in_flight(1)
        if self._check_rate_limit():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/grants":
            self._handle_create_grant()
        elif path == "/context/nodes":
            self._handle_create_node()
        elif path == "/context/edges":
            self._handle_create_edge()
        elif path == "/context/search":
            self._handle_search_nodes()
        elif path == "/context/batch":
            self._handle_batch_mutations()
        elif path == "/webhooks":
            self._handle_create_webhook()
        elif path == "/credentials":
            self._handle_create_credential()
        elif path.startswith("/credentials/") and path.endswith("/verify"):
            cred_id = path[len("/credentials/"):-len("/verify")]
            self._handle_verify_credential(cred_id)
        elif path == "/policies":
            self._handle_create_policy()
        elif path == "/api/token-exchange":
            self._handle_token_exchange()
        elif path == "/api/upload":
            self._handle_webapp_upload()
        elif path == "/api/import/github":
            self._handle_github_import()
        elif path == "/api/import/linkedin":
            self._handle_linkedin_import()
        elif path == "/api/profile":
            self._handle_save_profile()
        elif path == "/api/attestations/request":
            self._handle_create_attestation_request()
        elif path == "/api/attestations/sign":
            self._handle_sign_attestation()
        elif path == "/api/timeline":
            self._handle_create_timeline_entry()
        elif path == "/api/keys":
            self._handle_create_api_key()
        # ── Webapp auth routes ────────────────────────────────────
        elif path == "/app/auth":
            self._handle_webapp_login()
        elif path == "/app/logout":
            self._handle_webapp_logout()
        # ── Federation routes ─────────────────────────────────────
        elif path == "/federation/export":
            self._handle_federation_export()
        elif path == "/federation/import":
            self._handle_federation_import()
        # ── Dashboard routes ──────────────────────────────────────
        elif path == "/dashboard/auth":
            self._handle_dashboard_login()
        elif path.startswith("/dashboard/api/"):
            self._route_dashboard_api_post(path)
        else:
            self._error_response(ERR_NOT_FOUND("endpoint"))

    def do_DELETE(self) -> None:
        self._request_start_time = _time.monotonic()
        self._init_request_id()
        self._metrics_inc_in_flight(1)
        if self._check_rate_limit():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith("/grants/"):
            grant_id = path[len("/grants/"):]
            self._handle_revoke_grant(grant_id)
        elif path.startswith("/context/nodes/"):
            node_id = path[len("/context/nodes/"):]
            self._handle_delete_node(node_id)
        elif path.startswith("/context/edges/"):
            edge_id = path[len("/context/edges/"):]
            self._handle_delete_edge(edge_id)
        elif path.startswith("/webhooks/"):
            webhook_id = path[len("/webhooks/"):]
            self._handle_delete_webhook(webhook_id)
        elif path.startswith("/credentials/"):
            cred_id = path[len("/credentials/"):]
            self._handle_delete_credential(cred_id)
        elif path.startswith("/policies/"):
            policy_name = path[len("/policies/"):]
            self._handle_delete_policy(policy_name)
        elif path.startswith("/api/attestations/"):
            cred_id = path[len("/api/attestations/"):]
            self._handle_delete_attestation(cred_id)
        elif path.startswith("/api/timeline/"):
            node_id = path[len("/api/timeline/"):]
            self._handle_delete_timeline_entry(node_id)
        elif path.startswith("/api/keys/"):
            key_id = path[len("/api/keys/"):]
            self._handle_revoke_api_key(key_id)
        # ── Dashboard routes ──────────────────────────────────────
        elif path.startswith("/dashboard/api/"):
            self._route_dashboard_api_delete(path)
        else:
            self._error_response(ERR_NOT_FOUND("endpoint"))

    def do_PUT(self) -> None:
        self._request_start_time = _time.monotonic()
        self._init_request_id()
        self._metrics_inc_in_flight(1)
        if self._check_rate_limit():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith("/api/timeline/"):
            node_id = path[len("/api/timeline/"):]
            self._handle_update_timeline_entry(node_id)
        elif path.startswith("/context/nodes/"):
            node_id = path[len("/context/nodes/"):]
            self._handle_update_node(node_id)
        elif path.startswith("/policies/"):
            policy_name = path[len("/policies/"):]
            self._handle_update_policy(policy_name)
        else:
            self._error_response(ERR_NOT_FOUND("endpoint"))

    def do_OPTIONS(self) -> None:
        self._respond(204, "text/plain", b"", extra_headers={
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
        })

    # ── Rate limiting ─────────────────────────────────────────────────

    def _check_rate_limit(self) -> bool:
        """Check rate limit. Returns True if request was rejected (response already sent)."""
        limiter = self.__class__.rate_limiter
        if limiter is None:
            return False
        client_ip = self.client_address[0]
        if not limiter.allow(client_ip):
            from cortex.upai.errors import ERR_RATE_LIMITED
            # Record metric
            if self.__class__.metrics_registry is not None:
                try:
                    from cortex.caas.instrumentation import RATE_LIMIT_REJECTED
                    RATE_LIMIT_REJECTED.inc()
                except Exception:
                    pass
            error = ERR_RATE_LIMITED()
            body = json.dumps(error.to_dict(), default=str).encode("utf-8")
            self._respond(error.http_status, "application/json", body, extra_headers={
                "Retry-After": str(limiter.window),
            })
            return True
        return False

    # ── Metrics helpers ────────────────────────────────────────────────

    _request_start_time: float = 0.0

    @staticmethod
    def _metrics_path(path: str) -> str:
        """Normalize request path for metric labels (replace IDs with :id)."""
        parts = path.strip("/").split("/")
        normalized = []
        for i, part in enumerate(parts):
            # Heuristic: if a part looks like a UUID or long hex string, replace with :id
            if len(part) > 8 and ("-" in part or all(c in "0123456789abcdef" for c in part.lower())):
                normalized.append(":id")
            else:
                normalized.append(part)
        return "/" + "/".join(normalized) if normalized else "/"

    def _metrics_inc_in_flight(self, delta: int) -> None:
        registry = self.__class__.metrics_registry
        if registry is None:
            return
        from cortex.caas.instrumentation import HTTP_IN_FLIGHT
        if delta > 0:
            HTTP_IN_FLIGHT.inc()
        else:
            HTTP_IN_FLIGHT.dec()

    def _record_metrics(self, status_code: int) -> None:
        registry = self.__class__.metrics_registry
        if registry is None:
            return
        from cortex.caas.instrumentation import HTTP_REQUEST_DURATION, HTTP_REQUESTS_TOTAL
        parsed = urllib.parse.urlparse(self.path)
        path = self._metrics_path(parsed.path.rstrip("/") or "/")
        method = self.command or "GET"
        HTTP_REQUESTS_TOTAL.inc(method=method, path=path, status=str(status_code))
        start = getattr(self, "_request_start_time", 0.0)
        if start:
            duration = _time.monotonic() - start
            HTTP_REQUEST_DURATION.observe(duration, method=method, path=path)
        self._metrics_inc_in_flight(-1)

    def _serve_metrics(self) -> None:
        registry = self.__class__.metrics_registry
        if registry is None:
            self._respond(404, "text/plain", b"Metrics not enabled\n")
            return
        # Update domain gauges before collecting
        from cortex.caas.instrumentation import (
            AUDIT_ENTRIES,
            CIRCUIT_BREAKER_STATE,
            GRANTS_ACTIVE,
            GRAPH_EDGES,
            GRAPH_NODES,
            SSE_SUBSCRIBERS_ACTIVE,
            WEBHOOK_DEAD_LETTERS,
        )
        graph = self.__class__.graph
        if graph:
            GRAPH_NODES.set(float(len(graph.nodes)))
            GRAPH_EDGES.set(float(len(graph.edges)))
        grants = self.__class__.grant_store.list_all()
        active = sum(1 for g in grants if not g.get("revoked"))
        GRANTS_ACTIVE.set(float(active))

        # Phase 8: scrape-time gauge updates
        try:
            worker = self.__class__.webhook_worker
            if worker is not None:
                from cortex.caas.circuit_breaker import CircuitState
                state_map = {CircuitState.CLOSED: 0, CircuitState.OPEN: 1, CircuitState.HALF_OPEN: 2}
                with worker._cb_lock:
                    for wh_id, cb in worker._circuit_breakers.items():
                        CIRCUIT_BREAKER_STATE.set(float(state_map.get(cb.state, 0)), webhook_id=wh_id)
                        WEBHOOK_DEAD_LETTERS.set(float(worker._dead_letter.count(wh_id)), webhook_id=wh_id)
        except Exception:
            pass

        try:
            audit = self.__class__.audit_log
            if audit is not None and hasattr(audit, "count"):
                AUDIT_ENTRIES.set(float(audit.count()))
        except Exception:
            pass

        try:
            sse = self.__class__.sse_manager
            if sse is not None:
                SSE_SUBSCRIBERS_ACTIVE.set(float(sse.subscriber_count))
        except Exception:
            pass

        body = registry.collect().encode("utf-8")
        self._respond(200, "text/plain; version=0.0.4; charset=utf-8", body)

    # ── Auth helpers ─────────────────────────────────────────────────

    def _authenticate(self, required_scope: str = "") -> dict | None:
        """Authenticate request via Bearer token. Returns token_data or None (sends error)."""
        from cortex.upai.tokens import GrantToken

        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._audit("auth.failed", {"reason": "missing_or_malformed_header"})
            err = ERR_INVALID_TOKEN("Missing or malformed Authorization header")
            from cortex.upai.error_hints import hint_for_invalid_token
            err.hint = hint_for_invalid_token()
            self._error_response(err)
            return None

        token_str = auth_header[len("Bearer "):]
        identity = self.__class__.identity
        if identity is None:
            self._error_response(ERR_NOT_CONFIGURED("No identity configured"))
            return None

        token, err = GrantToken.verify_and_decode(
            token_str, identity.public_key_b64
        )
        if token is None:
            self._audit("auth.failed", {"reason": err})
            self._error_response(ERR_INVALID_TOKEN(err))
            return None

        # Check grant not revoked
        grant_info = self.__class__.grant_store.get(token.grant_id)
        if grant_info and grant_info.get("revoked"):
            self._audit("auth.failed", {"reason": "grant_revoked", "grant_id": token.grant_id})
            self._error_response(ERR_INVALID_TOKEN("Grant has been revoked"))
            return None

        # Check scope
        if required_scope and not token.has_scope(required_scope):
            err = ERR_INSUFFICIENT_SCOPE(required_scope)
            from cortex.upai.error_hints import hint_for_insufficient_scope
            err.hint = hint_for_insufficient_scope(required_scope)
            self._error_response(err)
            return None

        return token.to_dict()

    def _authenticate_or_dashboard(self, required_scope: str = "") -> dict | None:
        """Authenticate via Bearer token, webapp session cookie, or dashboard session.

        For routes that accept either. Returns token_data dict (or synthetic
        owner dict for dashboard/webapp sessions), or None (error already sent).
        """
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return self._authenticate(required_scope)

        sm = self.__class__.session_manager
        cookie_header = self.headers.get("Cookie", "")

        # Check webapp session cookie (cortex_app_session)
        if getattr(self.__class__, "enable_webapp", False) and sm is not None:
            for part in cookie_header.split(";"):
                part = part.strip()
                if part.startswith("cortex_app_session="):
                    token = part[len("cortex_app_session="):]
                    if token and sm.validate(token):
                        return {"_webapp": True, "scopes": list(VALID_SCOPES)}
                    break

        # Check dashboard session cookie (cortex_session)
        if sm is not None:
            for part in cookie_header.split(";"):
                part = part.strip()
                if part.startswith("cortex_session="):
                    token = part[len("cortex_session="):]
                    if token and sm.validate(token):
                        return {"_dashboard": True, "scopes": list(VALID_SCOPES)}
                    break

        # No valid auth found — send proper UPAI error
        from cortex.upai.error_hints import hint_for_invalid_token
        err = ERR_INVALID_TOKEN("Missing or malformed Authorization header")
        err.hint = hint_for_invalid_token()
        self._error_response(err)
        return None

    # ── Audit helper ─────────────────────────────────────────────────

    def _audit(self, event_type: str, details: dict | None = None, actor: str = "") -> None:
        """Log an audit event if audit_log is configured."""
        log = self.__class__.audit_log
        if log is not None:
            d = dict(details) if details else {}
            request_id = self._request_id or ""
            # Use new ledger API if available, else fall back to old
            if hasattr(log, 'append'):
                log.append(event_type, actor=actor or "system",
                           request_id=request_id, details=d)
            else:
                if request_id:
                    d["request_id"] = request_id
                log.log(event_type, d)

    # ── Webhook fire helper ──────────────────────────────────────────

    def _fire_webhook(self, event: str, data: dict) -> None:
        """Enqueue a webhook event for delivery if worker is configured. Also broadcast via SSE."""
        worker = self.__class__.webhook_worker
        if worker is not None:
            worker.enqueue(event, data)
        sse = self.__class__.sse_manager
        if sse is not None:
            sse.broadcast(event, data)

    def _fire_plugin(self, hook: str, context: dict) -> None:
        """Fire a plugin hook if plugin_manager is configured."""
        pm = self.__class__.plugin_manager
        if pm is not None:
            context.setdefault("hook", hook)
            pm.fire(hook, context)

    # ── Health check ─────────────────────────────────────────────────

    def _serve_health(self) -> None:
        identity = self.__class__.identity
        graph = self.__class__.graph
        grant_count = len(self.__class__.grant_store.list_all())
        self._json_response({
            "status": "ok",
            "version": "1.0.0",
            "has_identity": identity is not None,
            "has_graph": graph is not None,
            "grant_count": grant_count,
        })

    # ── Swagger UI / OpenAPI ────────────────────────────────────────

    def _serve_swagger_ui(self) -> None:
        """GET /docs — serve Swagger UI HTML page."""
        from cortex.caas.swagger import swagger_html
        html = swagger_html("/openapi.json")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        encoded = html.encode("utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
        self._metrics_observe_request("GET", "/docs", 200)

    def _serve_openapi_spec(self) -> None:
        """GET /openapi.json — serve the bundled OpenAPI spec."""
        from cortex.caas.swagger import load_openapi_spec
        spec = load_openapi_spec()
        if spec is None:
            self._error_response(ERR_NOT_FOUND("openapi.json"))
            return
        self._json_response(spec)

    # ── Info / Discovery ─────────────────────────────────────────────

    def _serve_info(self) -> None:
        identity = self.__class__.identity
        self._json_response({
            "service": "UPAI Context-as-a-Service",
            "version": "1.0.0",
            "upai_version": "1.0",
            "did": identity.did if identity else None,
            "discovery": "/.well-known/upai-configuration",
        })

    def _serve_discovery(self) -> None:
        identity = self.__class__.identity
        self._json_response({
            "upai_version": "1.0",
            "did": identity.did if identity else None,
            "endpoints": {
                "context": "/context",
                "identity": "/identity",
                "grants": "/grants",
                "versions": "/versions",
                "webhooks": "/webhooks",
                "credentials": "/credentials",
                "events": "/events",
            },
            "supported_policies": [p.name for p in self.__class__.policy_registry.list_all()],
            "supported_scopes": sorted(VALID_SCOPES),
            "server_version": "1.0.0",
        })

    def _serve_identity(self) -> None:
        identity = self.__class__.identity
        if identity is None:
            self._error_response(ERR_NOT_CONFIGURED("No identity configured"))
            return

        port = getattr(self.server, "server_port", 8421)
        service_endpoints = [
            {
                "id": f"{identity.did}#caas",
                "type": "ContextService",
                "serviceEndpoint": f"http://localhost:{port}",
            }
        ]
        doc = identity.to_did_document(service_endpoints=service_endpoints)
        self._json_response(doc)

    # ── Grants ───────────────────────────────────────────────────────

    def _handle_create_grant(self) -> None:
        from cortex.upai.rbac import VALID_ROLES, scopes_for_role
        from cortex.upai.tokens import GrantToken

        # Auth: grants:manage or dashboard
        token_data = self._authenticate_or_dashboard("grants:manage")
        if token_data is None:
            return

        identity = self.__class__.identity
        if identity is None:
            self._error_response(ERR_NOT_CONFIGURED("No identity configured"))
            return

        body = self._read_body()
        if body is None:
            return

        audience = body.get("audience", "")
        policy = body.get("policy", "professional")
        scopes = body.get("scopes")
        role = body.get("role", "")
        ttl_hours = body.get("ttl_hours", 24)

        # If role provided, resolve scopes from role
        if role:
            if role not in VALID_ROLES:
                self._error_response(ERR_INVALID_REQUEST(f"Unknown role: {role}"))
                return
            scopes = list(scopes_for_role(role))

        if not audience:
            self._error_response(ERR_INVALID_REQUEST("'audience' is required"))
            return

        # Validate audience length
        if len(audience) > 256:
            self._error_response(ERR_INVALID_REQUEST("'audience' must be at most 256 characters"))
            return

        if self.__class__.policy_registry.get(policy) is None:
            err = ERR_INVALID_POLICY(policy)
            from cortex.upai.error_hints import hint_for_policy
            known = [p.name for p in self.__class__.policy_registry.list_all()]
            err.hint = hint_for_policy(policy, known)
            self._error_response(err)
            return

        # Validate ttl_hours range
        if not isinstance(ttl_hours, (int, float)) or ttl_hours < 1 or ttl_hours > 8760:
            self._error_response(ERR_INVALID_REQUEST("'ttl_hours' must be between 1 and 8760"))
            return

        # Validate scopes
        if scopes is not None:
            if not isinstance(scopes, list):
                self._error_response(ERR_INVALID_REQUEST("'scopes' must be a list"))
                return
            for s in scopes:
                if s not in VALID_SCOPES:
                    self._error_response(ERR_INVALID_REQUEST(f"Unknown scope: {s}"))
                    return

        token = GrantToken.create(
            identity, audience=audience, policy=policy,
            scopes=scopes, ttl_hours=ttl_hours,
        )
        if role:
            token.role = role
        token_str = token.sign(identity)

        self.__class__.grant_store.add(token.grant_id, token_str, token.to_dict())
        self._audit("grant.created", {"grant_id": token.grant_id, "audience": audience, "policy": policy})
        self._fire_webhook("grant.created", {"grant_id": token.grant_id, "audience": audience, "policy": policy})

        resp = {
            "grant_id": token.grant_id,
            "token": token_str,
            "expires_at": token.expires_at,
            "policy": token.policy,
            "scopes": token.scopes,
        }
        if role:
            resp["role"] = role
        self._json_response(resp, status=201)

    def _serve_list_grants(self) -> None:
        token_data = self._authenticate_or_dashboard("grants:manage")
        if token_data is None:
            return
        grants = self.__class__.grant_store.list_all()
        self._json_response({"grants": grants})

    def _handle_revoke_grant(self, grant_id: str) -> None:
        token_data = self._authenticate_or_dashboard("grants:manage")
        if token_data is None:
            return
        if self.__class__.grant_store.revoke(grant_id):
            self._audit("grant.revoked", {"grant_id": grant_id})
            self._fire_webhook("grant.revoked", {"grant_id": grant_id})
            self._json_response({"revoked": True, "grant_id": grant_id})
        else:
            self._error_response(ERR_NOT_FOUND("grant"))

    # ── Context ──────────────────────────────────────────────────────

    def _get_policy_for_token(self, token_data: dict) -> str:
        return token_data.get("policy", "professional")

    def _serve_context(self, query: dict) -> None:
        token_data = self._authenticate_or_dashboard("context:read")
        if token_data is None:
            return

        graph = self.__class__.graph
        identity = self.__class__.identity
        if graph is None or identity is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        # Owner sessions (webapp/dashboard) honor the ?policy= query param
        if token_data.get("_webapp") or token_data.get("_dashboard"):
            policy_name = query.get("policy", ["full"])[0]
        else:
            policy_name = self._get_policy_for_token(token_data)
        policy = self.__class__.policy_registry.get(policy_name) or BUILTIN_POLICIES["professional"]
        filtered = apply_disclosure(graph, policy)
        data = filtered.export_v5()

        self._json_response(data)

    def _serve_context_compact(self, query: dict) -> None:
        token_data = self._authenticate_or_dashboard("context:read")
        if token_data is None:
            return

        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        if token_data.get("_webapp") or token_data.get("_dashboard"):
            policy_name = query.get("policy", ["full"])[0]
        else:
            policy_name = self._get_policy_for_token(token_data)
        policy = self.__class__.policy_registry.get(policy_name) or BUILTIN_POLICIES["professional"]
        filtered = apply_disclosure(graph, policy)

        lines = []
        for node in filtered.nodes.values():
            tags = ", ".join(node.tags) if node.tags else "untagged"
            lines.append(f"- **{node.label}** ({tags}, {node.confidence:.0%}): {node.brief}")

        self._respond(200, "text/markdown; charset=utf-8", "\n".join(lines).encode("utf-8"))

    def _serve_context_nodes(self, query: dict) -> None:
        token_data = self._authenticate_or_dashboard("context:read")
        if token_data is None:
            return

        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        policy_name = self._get_policy_for_token(token_data)
        policy = self.__class__.policy_registry.get(policy_name) or BUILTIN_POLICIES["professional"]
        filtered = apply_disclosure(graph, policy)

        items = [n.to_dict() for n in filtered.nodes.values()]
        items.sort(key=lambda x: x.get("id", ""))

        limit = int(query.get("limit", ["20"])[0])
        cursor = query.get("cursor", [None])[0]
        page = paginate(items, limit=limit, cursor=cursor)
        self._json_response(page.to_dict())

    def _serve_context_node(self, node_id: str, query: dict) -> None:
        token_data = self._authenticate_or_dashboard("context:read")
        if token_data is None:
            return

        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        policy_name = self._get_policy_for_token(token_data)
        policy = self.__class__.policy_registry.get(policy_name) or BUILTIN_POLICIES["professional"]
        filtered = apply_disclosure(graph, policy)

        node = filtered.nodes.get(node_id)
        if node is None:
            self._error_response(ERR_NOT_FOUND("node"))
            return

        self._json_response(node.to_dict())

    def _serve_context_edges(self, query: dict) -> None:
        token_data = self._authenticate_or_dashboard("context:read")
        if token_data is None:
            return

        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        policy_name = self._get_policy_for_token(token_data)
        policy = self.__class__.policy_registry.get(policy_name) or BUILTIN_POLICIES["professional"]
        filtered = apply_disclosure(graph, policy)

        items = [e.to_dict() for e in filtered.edges.values()]
        items.sort(key=lambda x: x.get("id", ""))

        limit = int(query.get("limit", ["20"])[0])
        cursor = query.get("cursor", [None])[0]
        page = paginate(items, limit=limit, cursor=cursor)
        self._json_response(page.to_dict())

    def _serve_context_stats(self, query: dict) -> None:
        token_data = self._authenticate_or_dashboard("context:read")
        if token_data is None:
            return

        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        self._json_response(graph.stats())

    # ── Graph mutations & intelligence ──────────────────────────────

    def _handle_create_node(self) -> None:
        """POST /context/nodes — create a new node. Requires context:write."""
        from cortex.graph import Node, make_node_id
        token_data = self._authenticate_or_dashboard("context:write")
        if token_data is None:
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return
        body = self._read_body()
        if body is None:
            return
        label = body.get("label", "")
        if not label:
            self._error_response(ERR_INVALID_REQUEST("'label' is required"))
            return
        node_id = body.get("id") or make_node_id(label)
        node = Node(
            id=node_id,
            label=label,
            tags=body.get("tags", []),
            confidence=body.get("confidence", 0.5),
            properties=body.get("properties", {}),
            brief=body.get("brief", ""),
            full_description=body.get("full_description", ""),
        )
        self._fire_plugin("PRE_NODE_CREATE", {"node_id": node_id, "label": label})
        graph.add_node(node)
        self._audit("context.node.created", {"node_id": node_id, "label": label})
        self._fire_webhook("context.node.created", {"node_id": node_id, "label": label})
        self._fire_plugin("POST_NODE_CREATE", {"node_id": node_id, "label": label})
        self._json_response(node.to_dict(), status=201)

    def _handle_update_node(self, node_id: str) -> None:
        """PUT /context/nodes/{id} — partial update. Requires context:write."""
        token_data = self._authenticate_or_dashboard("context:write")
        if token_data is None:
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return
        body = self._read_body()
        if body is None:
            return
        self._fire_plugin("PRE_NODE_UPDATE", {"node_id": node_id})
        node = graph.update_node(node_id, body)
        if node is None:
            self._error_response(ERR_NOT_FOUND("node"))
            return
        self._audit("context.node.updated", {"node_id": node_id})
        self._fire_webhook("context.node.updated", {"node_id": node_id})
        self._fire_plugin("POST_NODE_UPDATE", {"node_id": node_id})
        self._json_response(node.to_dict())

    def _handle_delete_node(self, node_id: str) -> None:
        """DELETE /context/nodes/{id} — remove node + connected edges. Requires context:write."""
        token_data = self._authenticate_or_dashboard("context:write")
        if token_data is None:
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return
        self._fire_plugin("PRE_NODE_DELETE", {"node_id": node_id})
        if graph.remove_node(node_id):
            self._audit("context.node.deleted", {"node_id": node_id})
            self._fire_webhook("context.node.deleted", {"node_id": node_id})
            self._fire_plugin("POST_NODE_DELETE", {"node_id": node_id})
            self._json_response({"deleted": True, "node_id": node_id})
        else:
            self._error_response(ERR_NOT_FOUND("node"))

    def _handle_create_edge(self) -> None:
        """POST /context/edges — create edge. Requires context:write."""
        from cortex.graph import Edge, make_edge_id
        token_data = self._authenticate_or_dashboard("context:write")
        if token_data is None:
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return
        body = self._read_body()
        if body is None:
            return
        source_id = body.get("source_id", "")
        target_id = body.get("target_id", "")
        relation = body.get("relation", "")
        if not source_id or not target_id or not relation:
            self._error_response(ERR_INVALID_REQUEST("'source_id', 'target_id', and 'relation' are required"))
            return
        if source_id not in graph.nodes:
            self._error_response(ERR_NOT_FOUND(f"source node '{source_id}'"))
            return
        if target_id not in graph.nodes:
            self._error_response(ERR_NOT_FOUND(f"target node '{target_id}'"))
            return
        edge_id = body.get("id") or make_edge_id(source_id, target_id, relation)
        edge = Edge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            confidence=body.get("confidence", 0.5),
            properties=body.get("properties", {}),
        )
        self._fire_plugin("PRE_EDGE_CREATE", {"edge_id": edge_id, "relation": relation})
        graph.add_edge(edge)
        self._audit("context.edge.created", {"edge_id": edge_id, "relation": relation})
        self._fire_webhook("context.edge.created", {"edge_id": edge_id})
        self._fire_plugin("POST_EDGE_CREATE", {"edge_id": edge_id, "relation": relation})
        self._json_response(edge.to_dict(), status=201)

    def _handle_delete_edge(self, edge_id: str) -> None:
        """DELETE /context/edges/{id} — remove edge. Requires context:write."""
        token_data = self._authenticate_or_dashboard("context:write")
        if token_data is None:
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return
        self._fire_plugin("PRE_EDGE_DELETE", {"edge_id": edge_id})
        if graph.remove_edge(edge_id):
            self._audit("context.edge.deleted", {"edge_id": edge_id})
            self._fire_webhook("context.edge.deleted", {"edge_id": edge_id})
            self._fire_plugin("POST_EDGE_DELETE", {"edge_id": edge_id})
            self._json_response({"deleted": True, "edge_id": edge_id})
        else:
            self._error_response(ERR_NOT_FOUND("edge"))

    def _handle_search_nodes(self) -> None:
        """POST /context/search — full-text search. Requires context:read."""
        token_data = self._authenticate_or_dashboard("context:read")
        if token_data is None:
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return
        body = self._read_body()
        if body is None:
            return
        query = body.get("query", "")
        if not query:
            self._error_response(ERR_INVALID_REQUEST("'query' is required"))
            return
        mode = body.get("mode", "substring")
        limit = body.get("limit", 50)

        self._fire_plugin("PRE_SEARCH", {"query": query, "mode": mode})
        if mode == "semantic":
            raw = graph.semantic_search(query, limit=limit, min_score=body.get("min_score", 0.0))
            results_list = []
            for r in raw:
                node = r["node"]
                d = node.to_dict() if hasattr(node, "to_dict") else dict(node)
                d["_score"] = r["score"]
                results_list.append(d)
            self._fire_plugin("POST_SEARCH", {"query": query, "count": len(results_list), "mode": "semantic"})
            self._json_response({
                "results": results_list,
                "count": len(results_list),
                "mode": "semantic",
            })
        else:
            fields = body.get("fields")
            min_confidence = body.get("min_confidence", 0.0)
            results = graph.search_nodes(query, fields=fields, min_confidence=min_confidence, limit=limit)
            self._fire_plugin("POST_SEARCH", {"query": query, "count": len(results), "mode": "substring"})
            self._json_response({
                "results": [n.to_dict() for n in results],
                "count": len(results),
                "mode": "substring",
            })

    def _serve_node_neighbors(self, node_id: str, query: dict) -> None:
        """GET /context/nodes/{id}/neighbors — neighbors with optional relation filter."""
        token_data = self._authenticate_or_dashboard("context:read")
        if token_data is None:
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return
        if node_id not in graph.nodes:
            self._error_response(ERR_NOT_FOUND("node"))
            return
        relation = query.get("relation", [None])[0]
        neighbors = graph.get_neighbors(node_id, relation=relation)
        self._json_response({
            "node_id": node_id,
            "neighbors": [
                {"edge": e.to_dict(), "node": n.to_dict()}
                for e, n in neighbors
            ],
            "count": len(neighbors),
        })

    def _serve_shortest_path(self, rest: str) -> None:
        """GET /context/path/{source_id}/{target_id} — shortest path."""
        token_data = self._authenticate_or_dashboard("context:read")
        if token_data is None:
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return
        parts = rest.split("/", 1)
        if len(parts) != 2:
            self._error_response(ERR_INVALID_REQUEST("Path format: /context/path/{source_id}/{target_id}"))
            return
        source_id, target_id = parts
        path = graph.shortest_path(source_id, target_id)
        self._json_response({
            "source_id": source_id,
            "target_id": target_id,
            "path": path,
            "length": len(path) - 1 if path else -1,
        })

    def _handle_batch_mutations(self) -> None:
        """POST /context/batch — batch create/update/delete. Requires context:write."""
        from cortex.graph import Edge, Node, make_edge_id, make_node_id
        token_data = self._authenticate_or_dashboard("context:write")
        if token_data is None:
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return
        body = self._read_body()
        if body is None:
            return
        operations = body.get("operations", [])
        if not isinstance(operations, list):
            self._error_response(ERR_INVALID_REQUEST("'operations' must be a list"))
            return
        results = []
        for op in operations:
            op_type = op.get("op", "")
            try:
                if op_type == "create_node":
                    label = op.get("label", "")
                    nid = op.get("id") or make_node_id(label)
                    node = Node(
                        id=nid, label=label,
                        tags=op.get("tags", []),
                        confidence=op.get("confidence", 0.5),
                        properties=op.get("properties", {}),
                        brief=op.get("brief", ""),
                    )
                    graph.add_node(node)
                    self._fire_webhook("context.node.created", {"node_id": nid})
                    results.append({"op": op_type, "id": nid, "status": "ok"})
                elif op_type == "update_node":
                    nid = op.get("id", "")
                    updates = {k: v for k, v in op.items() if k not in ("op", "id")}
                    n = graph.update_node(nid, updates)
                    if n is None:
                        results.append({"op": op_type, "id": nid, "status": "not_found"})
                    else:
                        self._fire_webhook("context.node.updated", {"node_id": nid})
                        results.append({"op": op_type, "id": nid, "status": "ok"})
                elif op_type == "delete_node":
                    nid = op.get("id", "")
                    if graph.remove_node(nid):
                        self._fire_webhook("context.node.deleted", {"node_id": nid})
                        results.append({"op": op_type, "id": nid, "status": "ok"})
                    else:
                        results.append({"op": op_type, "id": nid, "status": "not_found"})
                elif op_type == "create_edge":
                    src = op.get("source_id", "")
                    tgt = op.get("target_id", "")
                    rel = op.get("relation", "")
                    eid = op.get("id") or make_edge_id(src, tgt, rel)
                    edge = Edge(
                        id=eid, source_id=src, target_id=tgt, relation=rel,
                        confidence=op.get("confidence", 0.5),
                        properties=op.get("properties", {}),
                    )
                    graph.add_edge(edge)
                    self._fire_webhook("context.edge.created", {"edge_id": eid})
                    results.append({"op": op_type, "id": eid, "status": "ok"})
                elif op_type == "delete_edge":
                    eid = op.get("id", "")
                    if graph.remove_edge(eid):
                        self._fire_webhook("context.edge.deleted", {"edge_id": eid})
                        results.append({"op": op_type, "id": eid, "status": "ok"})
                    else:
                        results.append({"op": op_type, "id": eid, "status": "not_found"})
                else:
                    results.append({"op": op_type, "status": "unknown_operation"})
            except Exception as e:
                results.append({"op": op_type, "status": "error", "error": str(e)})
        self._audit("context.batch", {"count": len(operations)})
        self._json_response({"results": results, "count": len(results)})

    # ── Versions ─────────────────────────────────────────────────────

    def _serve_versions(self, query: dict) -> None:
        token_data = self._authenticate("versions:read")
        if token_data is None:
            return

        vs = self.__class__.version_store
        if vs is None:
            self._json_response({"items": [], "has_more": False})
            return

        versions = vs.log(limit=100)
        items = [v.to_dict() for v in versions]

        limit = int(query.get("limit", ["20"])[0])
        cursor = query.get("cursor", [None])[0]
        page = paginate(items, limit=limit, cursor=cursor, sort_key="version_id")
        self._json_response(page.to_dict())

    def _serve_version(self, version_id: str, query: dict) -> None:
        token_data = self._authenticate("versions:read")
        if token_data is None:
            return

        vs = self.__class__.version_store
        if vs is None:
            self._error_response(ERR_NOT_FOUND("version"))
            return

        try:
            graph = vs.checkout(version_id)
            self._json_response(graph.export_v5())
        except FileNotFoundError:
            self._error_response(ERR_NOT_FOUND("version"))

    def _serve_version_diff(self, query: dict) -> None:
        token_data = self._authenticate("versions:read")
        if token_data is None:
            return

        vs = self.__class__.version_store
        if vs is None:
            self._error_response(ERR_NOT_CONFIGURED("No version store"))
            return

        a = query.get("a", [None])[0]
        b = query.get("b", [None])[0]
        if not a or not b:
            self._error_response(ERR_INVALID_REQUEST("Both 'a' and 'b' query params required"))
            return

        try:
            diff = vs.diff(a, b)
            self._json_response(diff)
        except FileNotFoundError as e:
            self._error_response(ERR_NOT_FOUND(str(e)))

    # ── Webhooks ─────────────────────────────────────────────────────

    def _handle_create_webhook(self) -> None:
        token_data = self._authenticate_or_dashboard("webhooks:manage")
        if token_data is None:
            return
        body = self._read_body()
        if body is None:
            return

        url = body.get("url", "")
        events = body.get("events", [])
        if not url:
            self._error_response(ERR_INVALID_REQUEST("'url' is required"))
            return

        # Validate URL format
        if not url.startswith(("http://", "https://")):
            self._error_response(ERR_INVALID_REQUEST("'url' must start with http:// or https://"))
            return

        # Validate URL length
        if len(url) > 2048:
            self._error_response(ERR_INVALID_REQUEST("'url' must be at most 2048 characters"))
            return

        # SSRF check — block private/internal IPs
        try:
            from cortex.caas.security import validate_webhook_url
            url_valid, url_err = validate_webhook_url(url)
            if not url_valid:
                self._error_response(ERR_INVALID_REQUEST(f"Webhook URL rejected: {url_err}"))
                return
        except Exception:
            pass  # If security module unavailable, skip check

        try:
            from cortex.upai.webhooks import VALID_EVENTS, create_webhook
        except ImportError:
            self._error_response(ERR_INTERNAL("Webhook module not available"))
            return

        # Validate events
        for event in events:
            if event not in VALID_EVENTS:
                self._error_response(ERR_INVALID_REQUEST(f"Unknown event: {event}"))
                return

        registration = create_webhook(url, events or list(VALID_EVENTS))
        self.__class__.webhook_store.add(registration)
        self._audit("webhook.created", {"webhook_id": registration.webhook_id, "url": url})

        self._json_response({
            "webhook_id": registration.webhook_id,
            "url": registration.url,
            "events": registration.events,
            "secret": registration.secret,
            "created_at": registration.created_at,
        }, status=201)

    def _serve_list_webhooks(self) -> None:
        token_data = self._authenticate_or_dashboard("webhooks:manage")
        if token_data is None:
            return
        registrations = self.__class__.webhook_store.list_all()
        webhooks = []
        for reg in registrations:
            webhooks.append({
                "webhook_id": reg.webhook_id,
                "url": reg.url,
                "events": reg.events,
                "active": reg.active,
                "created_at": reg.created_at,
            })
        self._json_response({"webhooks": webhooks})

    def _handle_delete_webhook(self, webhook_id: str) -> None:
        token_data = self._authenticate_or_dashboard("webhooks:manage")
        if token_data is None:
            return
        if self.__class__.webhook_store.delete(webhook_id):
            self._audit("webhook.deleted", {"webhook_id": webhook_id})
            self._json_response({"deleted": True, "webhook_id": webhook_id})
        else:
            self._error_response(ERR_NOT_FOUND("webhook"))

    # ── Audit endpoints ───────────────────────────────────────────────

    def _serve_audit(self, query: dict) -> None:
        """GET /audit — paginated, filterable audit entries. Requires grants:manage."""
        token_data = self._authenticate_or_dashboard("grants:manage")
        if token_data is None:
            return

        log = self.__class__.audit_log
        if log is None or not hasattr(log, 'query'):
            self._json_response({"entries": []})
            return

        event_type = query.get("event_type", [None])[0]
        actor = query.get("actor", [None])[0]
        limit = min(int(query.get("limit", ["50"])[0]), 1000)
        offset = int(query.get("offset", ["0"])[0])

        entries = log.query(event_type=event_type, actor=actor, limit=limit, offset=offset)
        self._json_response({
            "entries": [e.to_dict() if hasattr(e, 'to_dict') else e for e in entries],
            "count": len(entries),
            "limit": limit,
            "offset": offset,
        })

    def _serve_audit_verify(self) -> None:
        """GET /audit/verify — verify hash chain integrity. Requires grants:manage."""
        token_data = self._authenticate_or_dashboard("grants:manage")
        if token_data is None:
            return

        log = self.__class__.audit_log
        if log is None or not hasattr(log, 'verify'):
            self._json_response({"valid": True, "entries_checked": 0, "error": ""})
            return

        valid, checked, error = log.verify()
        self._json_response({
            "valid": valid,
            "entries_checked": checked,
            "error": error,
        })

    # ── Policies ─────────────────────────────────────────────────

    def _serve_list_policies(self) -> None:
        token_data = self._authenticate_or_dashboard("")
        if token_data is None:
            return
        policies = self.__class__.policy_registry.list_all()
        result = []
        for p in policies:
            result.append({
                "name": p.name,
                "include_tags": p.include_tags,
                "exclude_tags": p.exclude_tags,
                "min_confidence": p.min_confidence,
                "redact_properties": p.redact_properties,
                "max_nodes": p.max_nodes,
                "builtin": self.__class__.policy_registry.is_builtin(p.name),
            })
        self._json_response({"policies": result})

    def _serve_get_policy(self, name: str) -> None:
        token_data = self._authenticate_or_dashboard("")
        if token_data is None:
            return
        policy = self.__class__.policy_registry.get(name)
        if policy is None:
            self._error_response(ERR_NOT_FOUND("policy"))
            return
        self._json_response({
            "name": policy.name,
            "include_tags": policy.include_tags,
            "exclude_tags": policy.exclude_tags,
            "min_confidence": policy.min_confidence,
            "redact_properties": policy.redact_properties,
            "max_nodes": policy.max_nodes,
            "builtin": self.__class__.policy_registry.is_builtin(policy.name),
        })

    def _handle_create_policy(self) -> None:
        token_data = self._authenticate_or_dashboard("policies:manage")
        if token_data is None:
            return
        body = self._read_body()
        if body is None:
            return

        name = body.get("name", "")
        if not name:
            self._error_response(ERR_INVALID_REQUEST("'name' is required"))
            return

        if self.__class__.policy_registry.get(name) is not None:
            self._error_response(ERR_INVALID_REQUEST(f"Policy '{name}' already exists"))
            return

        try:
            policy = DisclosurePolicy(
                name=name,
                include_tags=body.get("include_tags", []),
                exclude_tags=body.get("exclude_tags", []),
                min_confidence=float(body.get("min_confidence", 0.0)),
                redact_properties=body.get("redact_properties", []),
                max_nodes=int(body.get("max_nodes", 0)),
            )
            self.__class__.policy_registry.register(policy)
        except (ValueError, TypeError) as e:
            self._error_response(ERR_INVALID_REQUEST(str(e)))
            return

        self._json_response({
            "name": policy.name,
            "include_tags": policy.include_tags,
            "exclude_tags": policy.exclude_tags,
            "min_confidence": policy.min_confidence,
            "redact_properties": policy.redact_properties,
            "max_nodes": policy.max_nodes,
        }, status=201)

    def _handle_update_policy(self, name: str) -> None:
        token_data = self._authenticate_or_dashboard("policies:manage")
        if token_data is None:
            return
        if self.__class__.policy_registry.is_builtin(name):
            self._error_response(ERR_POLICY_IMMUTABLE(name))
            return

        body = self._read_body()
        if body is None:
            return

        existing = self.__class__.policy_registry.get(name)
        if existing is None:
            self._error_response(ERR_NOT_FOUND("policy"))
            return

        try:
            policy = DisclosurePolicy(
                name=body.get("name", name),
                include_tags=body.get("include_tags", existing.include_tags),
                exclude_tags=body.get("exclude_tags", existing.exclude_tags),
                min_confidence=float(body.get("min_confidence", existing.min_confidence)),
                redact_properties=body.get("redact_properties", existing.redact_properties),
                max_nodes=int(body.get("max_nodes", existing.max_nodes)),
            )
            self.__class__.policy_registry.update(name, policy)
        except (ValueError, TypeError) as e:
            self._error_response(ERR_INVALID_REQUEST(str(e)))
            return

        self._json_response({
            "name": policy.name,
            "include_tags": policy.include_tags,
            "exclude_tags": policy.exclude_tags,
            "min_confidence": policy.min_confidence,
            "redact_properties": policy.redact_properties,
            "max_nodes": policy.max_nodes,
        })

    def _handle_delete_policy(self, name: str) -> None:
        token_data = self._authenticate_or_dashboard("policies:manage")
        if token_data is None:
            return
        if self.__class__.policy_registry.is_builtin(name):
            self._error_response(ERR_POLICY_IMMUTABLE(name))
            return

        if self.__class__.policy_registry.delete(name):
            self._json_response({"deleted": True, "name": name})
        else:
            self._error_response(ERR_NOT_FOUND("policy"))

    # ── Credentials ─────────────────────────────────────────────────

    def _handle_create_credential(self) -> None:
        """POST /credentials — issue a self-signed credential."""
        token_data = self._authenticate("credentials:write")
        if token_data is None:
            return

        identity = self.__class__.identity
        store = self.__class__.credential_store
        if identity is None:
            self._error_response(ERR_NOT_CONFIGURED("No identity configured"))
            return
        if store is None:
            self._error_response(ERR_NOT_CONFIGURED("Credential store not configured"))
            return

        body = self._read_body()
        if body is None:
            return

        credential_type = body.get("credential_type", ["VerifiableCredential"])
        subject_did = body.get("subject_did", "")
        claims = body.get("claims", {})
        ttl_days = body.get("ttl_days", 0)
        bound_node_id = body.get("bound_node_id", "")

        if not subject_did:
            self._error_response(ERR_INVALID_REQUEST("'subject_did' is required"))
            return

        if not isinstance(claims, dict):
            self._error_response(ERR_INVALID_REQUEST("'claims' must be an object"))
            return

        from cortex.upai.credentials import CredentialIssuer
        issuer = CredentialIssuer()
        try:
            credential = issuer.issue(
                identity=identity,
                subject_did=subject_did,
                credential_type=credential_type,
                claims=claims,
                ttl_days=ttl_days,
                bound_node_id=bound_node_id,
            )
        except ValueError as e:
            self._error_response(ERR_INVALID_REQUEST(str(e)))
            return

        store.add(credential)
        self._audit("credential.created", {"credential_id": credential.credential_id})
        self._fire_webhook("context.updated", {"credential_created": credential.credential_id})
        self._json_response(credential.to_dict(), status=201)

    def _serve_credentials(self, query: dict) -> None:
        """GET /credentials — list credentials, optional ?node_id= filter."""
        token_data = self._authenticate("credentials:read")
        if token_data is None:
            return

        store = self.__class__.credential_store
        if store is None:
            self._json_response({"credentials": []})
            return

        node_id = query.get("node_id", [None])[0]
        if node_id:
            credentials = store.list_by_node(node_id)
        else:
            credentials = store.list_all()

        self._json_response({
            "credentials": [c.to_dict() for c in credentials],
        })

    def _serve_credential_detail(self, cred_id: str) -> None:
        """GET /credentials/{id} — get credential by ID."""
        token_data = self._authenticate("credentials:read")
        if token_data is None:
            return

        store = self.__class__.credential_store
        if store is None:
            self._error_response(ERR_NOT_FOUND("credential"))
            return

        credential = store.get(cred_id)
        if credential is None:
            self._error_response(ERR_NOT_FOUND("credential"))
            return

        self._json_response(credential.to_dict())

    def _handle_delete_credential(self, cred_id: str) -> None:
        """DELETE /credentials/{id} — requires dashboard session auth."""
        if not self._dashboard_auth_check():
            return

        store = self.__class__.credential_store
        if store is None:
            self._error_response(ERR_NOT_FOUND("credential"))
            return

        if store.delete(cred_id):
            self._audit("credential.deleted", {"credential_id": cred_id})
            self._json_response({"deleted": True, "credential_id": cred_id})
        else:
            self._error_response(ERR_NOT_FOUND("credential"))

    def _handle_verify_credential(self, cred_id: str) -> None:
        """POST /credentials/{id}/verify — re-verify credential signature."""
        token_data = self._authenticate("credentials:read")
        if token_data is None:
            return

        identity = self.__class__.identity
        store = self.__class__.credential_store
        if store is None or identity is None:
            self._error_response(ERR_NOT_FOUND("credential"))
            return

        credential = store.get(cred_id)
        if credential is None:
            self._error_response(ERR_NOT_FOUND("credential"))
            return

        from cortex.upai.credentials import CredentialVerifier
        verifier = CredentialVerifier()
        valid, error = verifier.verify(credential.to_dict(), identity.public_key_b64)
        status = verifier.check_status(credential)

        self._json_response({
            "credential_id": cred_id,
            "valid": valid,
            "status": status,
            "error": error,
        })

    # ── Discovery / DID resolution ───────────────────────────────────

    def _serve_resolve_did(self, did_encoded: str) -> None:
        """GET /resolve/{did} — resolve a DID to its DID Document."""
        did = urllib.parse.unquote(did_encoded)

        identity = self.__class__.identity
        from cortex.upai.discovery import DIDResolver
        resolver = DIDResolver()

        port = getattr(self.server, "server_port", 8421)
        service_endpoints = None
        if identity and identity.did == did:
            service_endpoints = [{
                "id": f"{identity.did}#caas",
                "type": "ContextService",
                "serviceEndpoint": f"http://localhost:{port}",
            }]

        doc = resolver.resolve(
            did,
            identity=identity,
            service_endpoints=service_endpoints,
        )
        if doc is None:
            self._error_response(ERR_NOT_FOUND("DID"))
            return

        self._json_response(doc)

    # ── SSE (Server-Sent Events) ─────────────────────────────────────

    def _handle_sse(self, query: dict) -> None:
        """GET /events — SSE endpoint for real-time push with replay support."""
        sse = self.__class__.sse_manager
        if sse is None:
            self._respond(503, "application/json",
                          json.dumps({"error": "SSE not enabled"}).encode("utf-8"))
            return

        token_data = self._authenticate("context:subscribe")
        if token_data is None:
            return

        # Parse event filter
        events_param = query.get("events", [None])[0]
        events: set[str] = set()
        if events_param:
            events = set(events_param.split(","))

        # Parse Last-Event-ID for replay
        last_event_id = 0
        lei_header = self.headers.get("Last-Event-ID", "")
        lei_query = query.get("last_event_id", [None])[0]
        lei_str = lei_header or lei_query or ""
        if lei_str:
            try:
                last_event_id = int(lei_str)
            except (ValueError, TypeError):
                last_event_id = 0

        grant_id = token_data.get("grant_id", "")

        # Send SSE headers
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

        # Replay buffered events if Last-Event-ID was provided
        if last_event_id > 0:
            sse.replay(self.wfile, last_event_id, events=events or None)

        # Register subscriber
        subscriber = sse.subscribe(self.wfile, events=events, grant_id=grant_id)
        self._audit("sse.connected", {"subscriber_id": subscriber.subscriber_id})

        # Block until connection closes
        try:
            while subscriber.alive:
                import time as _t
                _t.sleep(1)
        except (OSError, BrokenPipeError, ConnectionResetError):
            pass
        finally:
            sse.unsubscribe(subscriber.subscriber_id)

    # ── Backup / Device routes (dashboard-only) ──────────────────────

    def _handle_create_backup(self) -> None:
        """POST /dashboard/api/backup — create encrypted backup."""
        identity = self.__class__.identity
        if identity is None:
            self._error_response(ERR_NOT_CONFIGURED("No identity"))
            return

        body = self._read_body()
        if body is None:
            return

        passphrase = body.get("passphrase", "")
        if not passphrase or len(passphrase) < 8:
            self._error_response(ERR_INVALID_REQUEST("Passphrase must be at least 8 characters"))
            return

        from cortex.upai.backup import KeyBackup
        backup = KeyBackup()
        try:
            blob = backup.backup(identity, passphrase)
        except ValueError as e:
            self._error_response(ERR_INVALID_REQUEST(str(e)))
            return

        self._audit("backup.created", {})
        self._json_response(json.loads(blob), status=201)

    def _handle_restore_backup(self) -> None:
        """POST /dashboard/api/backup/restore — restore from encrypted backup."""
        body = self._read_body()
        if body is None:
            return

        backup_data = body.get("backup")
        passphrase = body.get("passphrase", "")

        if not backup_data or not passphrase:
            self._error_response(ERR_INVALID_REQUEST("'backup' and 'passphrase' required"))
            return

        from cortex.upai.backup import KeyBackup
        kb = KeyBackup()
        try:
            backup_bytes = json.dumps(backup_data).encode("utf-8")
            restored = kb.restore(backup_bytes, passphrase)
        except ValueError as e:
            self._error_response(ERR_INVALID_REQUEST(str(e)))
            return

        self._audit("backup.restored", {"did": restored.did})
        self._json_response({
            "did": restored.did,
            "name": restored.name,
            "public_key_b64": restored.public_key_b64,
        })

    def _handle_generate_recovery(self) -> None:
        """POST /dashboard/api/backup/recovery-phrase — generate 12-word phrase."""
        from cortex.upai.backup import RecoveryCodeGenerator
        gen = RecoveryCodeGenerator()
        phrase = gen.generate_recovery_phrase()
        self._json_response({"recovery_phrase": phrase}, status=201)

    def _handle_authorize_device(self) -> None:
        """POST /dashboard/api/devices — authorize a new device."""
        identity = self.__class__.identity
        kc = self.__class__.keychain
        if identity is None or kc is None:
            self._error_response(ERR_NOT_CONFIGURED("Identity or keychain not configured"))
            return

        body = self._read_body()
        if body is None:
            return

        device_name = body.get("device_name", "")
        if not device_name:
            self._error_response(ERR_INVALID_REQUEST("'device_name' is required"))
            return

        try:
            record, device_identity = kc.authorize_device(identity, device_name)
        except ValueError as e:
            self._error_response(ERR_INVALID_REQUEST(str(e)))
            return

        self._audit("device.authorized", {"device_id": record.device_id, "device_name": device_name})
        self._json_response({
            "device_id": record.device_id,
            "device_name": record.device_name,
            "device_did": record.device_did,
            "device_public_key_b64": record.device_public_key_b64,
            "authorized_at": record.authorized_at,
        }, status=201)

    def _serve_devices(self) -> None:
        """GET /dashboard/api/devices — list authorized devices."""
        kc = self.__class__.keychain
        if kc is None:
            self._json_response({"devices": []})
            return
        devices = kc.list_devices()
        self._json_response({
            "devices": [d.to_dict() for d in devices],
        })

    def _handle_revoke_device(self, device_id: str) -> None:
        """DELETE /dashboard/api/devices/{id} — revoke device."""
        kc = self.__class__.keychain
        if kc is None:
            self._error_response(ERR_NOT_FOUND("device"))
            return

        revoked_at = kc.revoke_device(device_id)
        if revoked_at:
            self._audit("device.revoked", {"device_id": device_id})
            self._json_response({"revoked": True, "device_id": device_id, "revoked_at": revoked_at})
        else:
            self._error_response(ERR_NOT_FOUND("device"))

    # ── OAuth routes ──────────────────────────────────────────────────

    def _serve_oauth_providers(self) -> None:
        """GET /dashboard/oauth/providers — list available OAuth providers (no auth)."""
        om = self.__class__.oauth_manager
        if om is None or not om.enabled:
            self._json_response({"providers": []})
            return
        self._json_response({"providers": om.provider_names})

    def _handle_oauth_authorize(self, query: dict) -> None:
        """GET /dashboard/oauth/authorize — 302 redirect to provider."""
        om = self.__class__.oauth_manager
        if om is None or not om.enabled:
            self._oauth_redirect_to_dashboard("oauth_not_configured")
            return

        provider_name = query.get("provider", [None])[0]
        if not provider_name:
            self._oauth_redirect_to_dashboard("missing_provider")
            return

        result = om.get_authorization_url(provider_name)
        if result is None:
            self._oauth_redirect_to_dashboard("unknown_provider")
            return

        url, _nonce = result
        self._respond(302, "text/plain", b"Redirecting...", extra_headers={
            "Location": url,
        })

    def _handle_oauth_callback(self, query: dict) -> None:
        """GET /dashboard/oauth/callback — exchange code, create session, redirect."""
        om = self.__class__.oauth_manager
        if om is None:
            self._oauth_redirect_to_dashboard("oauth_not_configured")
            return

        error = query.get("error", [None])[0]
        if error:
            self._oauth_redirect_to_dashboard(f"provider_error:{error}")
            return

        code = query.get("code", [None])[0]
        state = query.get("state", [None])[0]
        if not code or not state:
            self._oauth_redirect_to_dashboard("missing_code_or_state")
            return

        userinfo, provider_or_error = om.handle_callback(code, state)
        if userinfo is None:
            self._oauth_redirect_to_dashboard(provider_or_error)
            return

        # Create session via DashboardSessionManager
        sm = self.__class__.session_manager
        if sm is None:
            self._oauth_redirect_to_dashboard("dashboard_not_configured")
            return

        email = userinfo.get("email", "")
        name = userinfo.get("name", userinfo.get("login", ""))
        token = sm.create_oauth_session(provider_or_error, email, name)
        self._audit("dashboard.oauth_login", {"provider": provider_or_error, "email": email})

        # SameSite=Lax because this is a cross-site redirect from the OAuth provider
        self._respond(302, "text/plain", b"Redirecting to dashboard...", extra_headers={
            "Location": "/dashboard",
            "Set-Cookie": f"cortex_session={token}; HttpOnly; SameSite=Lax; Path=/dashboard",
        })

    def _oauth_redirect_to_dashboard(self, error: str = "") -> None:
        """Helper: redirect to dashboard with optional error query param."""
        location = "/dashboard"
        if error:
            location += f"?oauth_error={urllib.parse.quote(error)}"
        self._respond(302, "text/plain", b"Redirecting...", extra_headers={
            "Location": location,
        })

    def _handle_token_exchange(self) -> None:
        """POST /api/token-exchange — validate external token, create UPAI grant."""
        from cortex.caas.oauth import validate_github_token, validate_google_id_token
        from cortex.upai.tokens import GrantToken

        om = self.__class__.oauth_manager
        if om is None or not om.enabled:
            self._error_response(ERR_NOT_CONFIGURED("OAuth not configured"))
            return

        identity = self.__class__.identity
        if identity is None:
            self._error_response(ERR_NOT_CONFIGURED("No identity configured"))
            return

        body = self._read_body()
        if body is None:
            return

        provider = body.get("provider", "")
        token = body.get("token", "")
        audience = body.get("audience", "")

        if not provider or not token:
            self._error_response(ERR_INVALID_REQUEST("'provider' and 'token' are required"))
            return

        if not audience:
            self._error_response(ERR_INVALID_REQUEST("'audience' is required"))
            return

        # Validate external token
        email = None
        if provider == "google":
            provider_cfg = om._providers.get("google")
            if provider_cfg is None:
                self._error_response(ERR_INVALID_REQUEST("Google OAuth not configured"))
                return
            claims = validate_google_id_token(token, provider_cfg.client_id)
            if claims is None:
                self._error_response(ERR_INVALID_TOKEN("Invalid Google ID token"))
                return
            email = claims.get("email", "")
        elif provider == "github":
            user_info = validate_github_token(token)
            if user_info is None:
                self._error_response(ERR_INVALID_TOKEN("Invalid GitHub token"))
                return
            email = user_info.get("email", "")
        else:
            self._error_response(ERR_INVALID_REQUEST(f"Unsupported provider: {provider}"))
            return

        # Check email allowlist
        if email and not om.is_email_allowed(email):
            self._respond(403, "application/json",
                          json.dumps({"error": "email_not_allowed"}).encode())
            return

        # Create grant
        policy = body.get("policy", "professional")
        scopes = body.get("scopes")
        ttl_hours = body.get("ttl_hours", 24)

        grant = GrantToken.create(
            identity, audience=audience, policy=policy,
            scopes=scopes, ttl_hours=ttl_hours,
        )
        grant_str = grant.sign(identity)

        self.__class__.grant_store.add(grant.grant_id, grant_str, grant.to_dict())
        self._audit("token_exchange", {"provider": provider, "email": email, "audience": audience})

        self._json_response({
            "grant_id": grant.grant_id,
            "token": grant_str,
            "expires_at": grant.expires_at,
            "policy": grant.policy,
            "scopes": grant.scopes,
        }, status=201)

    # ── Webapp: static files & upload ────────────────────────────────

    def _serve_webapp_file(self, path: str) -> None:
        """Serve a static file from the webapp directory."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        resolved = resolve_webapp_path(path)
        if resolved is None:
            self._error_response(ERR_NOT_FOUND("webapp file"))
            return
        ct = guess_webapp_content_type(resolved)
        body = resolved.read_bytes()
        self._respond(200, ct, body, dashboard=True)

    def _handle_webapp_upload(self) -> None:
        """POST /api/upload — accept a file upload and extract nodes/edges.

        The webapp upload is owner-only: requires a valid dashboard session.
        Accepts multipart/form-data with a single 'file' field.
        Parses JSON chat exports to create nodes + edges in the graph.
        """
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return

        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))

        # Size limit: 100 MB for uploads
        max_upload = 100 * 1024 * 1024
        if content_length > max_upload:
            self._error_response(ERR_PAYLOAD_TOO_LARGE())
            return

        if "multipart/form-data" not in content_type:
            self._respond(415, "application/json",
                          json.dumps({"error": "Expected multipart/form-data"}).encode())
            return

        # Parse multipart boundary
        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[len("boundary="):]
                break

        if not boundary:
            self._error_response(ERR_INVALID_REQUEST("Missing multipart boundary"))
            return

        raw = self.rfile.read(content_length)
        file_data = self._parse_multipart_file(raw, boundary)

        if file_data is None:
            self._error_response(ERR_INVALID_REQUEST("No file found in upload"))
            return

        # Detect file type and route accordingly
        from cortex.caas.importers import (
            detect_file_type,
            extract_text_from_docx,
            extract_text_from_pdf,
            parse_linkedin_export,
            parse_resume_text,
        )

        # Extract filename from multipart headers (best effort)
        filename = self._extract_multipart_filename(raw, boundary) or "upload"
        ftype = detect_file_type(filename, file_data)

        if ftype == "resume_pdf":
            text = extract_text_from_pdf(file_data)
            if not text.strip():
                self._error_response(ERR_INVALID_REQUEST("Could not extract text from PDF"))
                return
            import_result = parse_resume_text(text)
            result = self._import_nodes_edges(import_result)
            self._json_response(result, status=201)
            return

        if ftype == "resume_docx":
            text = extract_text_from_docx(file_data)
            if not text.strip():
                self._error_response(ERR_INVALID_REQUEST("Could not extract text from DOCX"))
                return
            import_result = parse_resume_text(text)
            result = self._import_nodes_edges(import_result)
            self._json_response(result, status=201)
            return

        if ftype == "linkedin_export":
            import_result = parse_linkedin_export(file_data)
            result = self._import_nodes_edges(import_result)
            self._json_response(result, status=201)
            return

        # Existing path: zip or JSON/text chat exports
        import io
        import zipfile

        if zipfile.is_zipfile(io.BytesIO(file_data)):
            parsed = self._parse_zip_upload(file_data)
            if parsed is None:
                self._error_response(ERR_INVALID_REQUEST("No JSON file found in zip archive"))
                return
        else:
            # Try to parse as JSON
            try:
                parsed = json.loads(file_data)
            except (json.JSONDecodeError, ValueError):
                # Treat as plain text — create a single node
                text = file_data.decode("utf-8", errors="replace").strip()
                if not text:
                    self._error_response(ERR_INVALID_REQUEST("Empty file"))
                    return
                parsed = {"text": text}

        # Extract nodes and edges from the parsed content
        result = self._extract_from_upload(parsed)
        self._json_response(result, status=201)

    def _parse_multipart_file(self, raw: bytes, boundary: str) -> bytes | None:
        """Extract the first file's content from multipart form data."""
        delimiter = b"--" + boundary.encode()
        parts = raw.split(delimiter)

        for part in parts:
            if b"Content-Disposition" not in part:
                continue
            # Split headers from body
            header_end = part.find(b"\r\n\r\n")
            if header_end < 0:
                continue
            headers = part[:header_end].decode("utf-8", errors="replace")
            if 'name="file"' in headers or "filename=" in headers:
                body = part[header_end + 4:]
                # Remove trailing \r\n-- if present
                if body.endswith(b"\r\n"):
                    body = body[:-2]
                if body.endswith(b"--"):
                    body = body[:-2]
                if body.endswith(b"\r\n"):
                    body = body[:-2]
                return body
        return None

    def _parse_zip_upload(self, data: bytes) -> dict | list | None:
        """Extract and parse JSON content from a zip archive.

        Looks for conversations.json first (OpenAI export format),
        then tries each .json file until one parses successfully.
        """
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            # Prefer conversations.json (OpenAI export format)
            for name in names:
                if name.endswith("conversations.json"):
                    try:
                        return json.loads(zf.read(name))
                    except (json.JSONDecodeError, ValueError):
                        continue
            # Fall back to any .json file
            for name in names:
                if name.lower().endswith(".json"):
                    try:
                        return json.loads(zf.read(name))
                    except (json.JSONDecodeError, ValueError):
                        continue
        return None

    def _extract_from_upload(self, parsed: dict | list) -> dict:
        """Extract nodes and edges from uploaded data and add to graph."""
        from cortex.graph import Edge, Node, make_edge_id, make_node_id

        graph = self.__class__.graph
        nodes_created = 0
        edges_created = 0
        tag_set = set()

        # Handle different formats
        items = []
        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, dict):
            # Common chat export formats
            if "messages" in parsed:
                items = parsed["messages"]
            elif "conversations" in parsed:
                for conv in parsed["conversations"]:
                    items.extend(conv.get("messages", []))
            elif "nodes" in parsed:
                # Already in graph format — import directly
                for nd in parsed.get("nodes", []):
                    label = nd.get("label", nd.get("name", ""))
                    if not label:
                        continue
                    node_id = nd.get("id") or make_node_id(label)
                    tags = nd.get("tags", [])
                    node = Node(
                        id=node_id, label=label, tags=tags,
                        confidence=nd.get("confidence", 0.5),
                        brief=nd.get("brief", ""),
                    )
                    graph.add_node(node)
                    nodes_created += 1
                    tag_set.update(t.lower() for t in tags)
                for ed in parsed.get("edges", []):
                    source_id = ed.get("source_id", ed.get("source", ""))
                    target_id = ed.get("target_id", ed.get("target", ""))
                    relation = ed.get("relation", "related_to")
                    if source_id and target_id:
                        edge_id = ed.get("id") or make_edge_id(source_id, target_id, relation)
                        edge = Edge(id=edge_id, source_id=source_id, target_id=target_id, relation=relation)
                        graph.add_edge(edge)
                        edges_created += 1
                return {
                    "nodes_created": nodes_created,
                    "edges_created": edges_created,
                    "categories": len(tag_set),
                }
            elif "text" in parsed:
                # Plain text upload — create single node
                text = parsed["text"]
                label = text[:100].strip()
                if "\n" in label:
                    label = label.split("\n")[0]
                node_id = make_node_id(label)
                node = Node(id=node_id, label=label, tags=["import"], confidence=0.5, brief=text[:500])
                graph.add_node(node)
                return {"nodes_created": 1, "edges_created": 0, "categories": 1}

        # Process chat messages: extract unique topics/entities
        seen_labels = {}
        for msg in items:
            content = ""
            if isinstance(msg, str):
                content = msg
            elif isinstance(msg, dict):
                content = msg.get("content", msg.get("text", msg.get("message", "")))
                if isinstance(content, list):
                    # Handle multi-part messages (e.g., OpenAI format)
                    parts = []
                    for p in content:
                        if isinstance(p, str):
                            parts.append(p)
                        elif isinstance(p, dict) and p.get("type") == "text":
                            parts.append(p.get("text", ""))
                    content = " ".join(parts)

            if not content or not isinstance(content, str):
                continue

            # Simple extraction: split into sentences, create nodes for substantive ones
            sentences = [s.strip() for s in content.replace("\n", ". ").split(". ") if len(s.strip()) > 20]
            for sent in sentences[:5]:  # Cap per message
                label = sent[:100].strip()
                if label in seen_labels:
                    continue
                seen_labels[label] = True
                node_id = make_node_id(label)
                tags = ["import"]
                node = Node(id=node_id, label=label, tags=tags, confidence=0.4, brief=sent[:500])
                graph.add_node(node)
                nodes_created += 1
                tag_set.update(t.lower() for t in tags)

        # Create edges between sequential nodes
        node_ids = list(seen_labels.keys())
        for i in range(len(node_ids) - 1):
            src = make_node_id(node_ids[i])
            tgt = make_node_id(node_ids[i + 1])
            rel = "follows"
            eid = make_edge_id(src, tgt, rel)
            edge = Edge(id=eid, source_id=src, target_id=tgt, relation=rel)
            graph.add_edge(edge)
            edges_created += 1

        return {
            "nodes_created": nodes_created,
            "edges_created": edges_created,
            "categories": len(tag_set),
        }

    # ── Import helpers ──────────────────────────────────────────────

    def _extract_multipart_filename(self, raw: bytes, boundary: str) -> str | None:
        """Extract the filename from multipart form headers."""
        delimiter = b"--" + boundary.encode()
        parts = raw.split(delimiter)
        for part in parts:
            if b"Content-Disposition" not in part:
                continue
            header_end = part.find(b"\r\n\r\n")
            if header_end < 0:
                continue
            headers = part[:header_end].decode("utf-8", errors="replace")
            import re
            m = re.search(r'filename="([^"]*)"', headers)
            if m:
                return m.group(1)
        return None

    def _import_nodes_edges(self, import_result: dict) -> dict:
        """Import nodes/edges from an import result dict into the graph."""
        from cortex.graph import Edge, Node, make_edge_id, make_node_id

        graph = self.__class__.graph
        nodes_created = 0
        edges_created = 0
        tag_set: set[str] = set()

        for nd in import_result.get("nodes", []):
            label = nd.get("label", "")
            if not label:
                continue
            node_id = nd.get("id") or make_node_id(label)
            tags = nd.get("tags", [])
            node = Node(
                id=node_id, label=label, tags=tags,
                confidence=nd.get("confidence", 0.5),
                brief=nd.get("brief", ""),
            )
            graph.add_node(node)
            nodes_created += 1
            tag_set.update(t.lower() for t in tags)

        for ed in import_result.get("edges", []):
            source_id = ed.get("source_id", "")
            target_id = ed.get("target_id", "")
            relation = ed.get("relation", "related_to")
            if source_id and target_id:
                edge_id = ed.get("id") or make_edge_id(source_id, target_id, relation)
                edge = Edge(id=edge_id, source_id=source_id,
                            target_id=target_id, relation=relation)
                graph.add_edge(edge)
                edges_created += 1

        return {
            "nodes_created": nodes_created,
            "edges_created": edges_created,
            "categories": len(tag_set),
            "source_type": import_result.get("source_type", "import"),
        }

    # ── GitHub / LinkedIn import endpoints ───────────────────────────

    def _handle_github_import(self) -> None:
        """POST /api/import/github — import a GitHub repository."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return

        body = self._read_body()
        if body is None:
            return

        url = body.get("url", "")
        if not url:
            self._error_response(ERR_INVALID_REQUEST("Missing 'url' field"))
            return

        token = body.get("token") or None

        from cortex.caas.importers import fetch_github_repo
        import_result = fetch_github_repo(url, token=token)

        if "error" in import_result and not import_result.get("nodes"):
            self._error_response(ERR_INVALID_REQUEST(import_result["error"]))
            return

        result = self._import_nodes_edges(import_result)
        self._json_response(result, status=201)

    def _handle_linkedin_import(self) -> None:
        """POST /api/import/linkedin — import from a LinkedIn profile URL."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return

        body = self._read_body()
        if body is None:
            return

        url = body.get("url", "")
        if not url:
            self._error_response(ERR_INVALID_REQUEST("Missing 'url' field"))
            return

        from cortex.caas.importers import fetch_linkedin_profile
        import_result = fetch_linkedin_profile(url)

        if "error" in import_result and not import_result.get("nodes"):
            self._error_response(ERR_INVALID_REQUEST(import_result["error"]))
            return

        result = self._import_nodes_edges(import_result)
        if import_result.get("limited"):
            result["limited"] = True
            result["hint"] = ("LinkedIn blocks most scraping. "
                              "For richer data, use a LinkedIn data export (Settings > Get a copy of your data).")
        self._json_response(result, status=201)

    # ── Profile endpoints ─────────────────────────────────────────────

    def _get_profile_store(self):
        """Lazy-init the profile store."""
        if self.__class__.profile_store is None:
            from cortex.caas.profile import ProfileStore
            store_path = Path(".cortex") / "profiles.json"
            self.__class__.profile_store = ProfileStore(store_path)
        return self.__class__.profile_store

    def _handle_get_profile(self) -> None:
        """GET /api/profile — get the current profile config."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return

        store = self._get_profile_store()
        profiles = store.list_all()
        if profiles:
            self._json_response(profiles[0].to_dict())
        else:
            self._json_response({})

    def _handle_save_profile(self) -> None:
        """POST /api/profile — create or update profile config."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return

        body = self._read_body()
        if body is None:
            return

        handle = body.get("handle", "")

        from cortex.caas.profile import ProfileConfig, validate_handle

        store = self._get_profile_store()

        # Check if profile already exists
        existing = store.get(handle)
        if existing:
            # Update
            updated = store.update(handle, body)
            if updated:
                self._json_response(updated.to_dict())
            else:
                self._error_response(ERR_NOT_FOUND("profile"))
        else:
            # Create
            errors = validate_handle(handle)
            if errors:
                self._error_response(ERR_INVALID_REQUEST("; ".join(errors)))
                return
            config = ProfileConfig(
                handle=handle,
                display_name=body.get("display_name", ""),
                headline=body.get("headline", ""),
                bio=body.get("bio", ""),
                avatar_url=body.get("avatar_url", ""),
                policy=body.get("policy", "professional"),
                sections=body.get("sections", [
                    "about", "experience", "skills", "education",
                    "projects", "endorsements",
                ]),
                custom_tags=body.get("custom_tags", []),
            )
            try:
                created = store.create(config)
                self._json_response(created.to_dict(), status=201)
            except ValueError as exc:
                self._error_response(ERR_INVALID_REQUEST(str(exc)))

    def _handle_profile_preview(self) -> None:
        """GET /api/profile/preview — preview the profile page HTML."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return

        store = self._get_profile_store()
        profiles = store.list_all()
        if not profiles:
            self._respond(200, "text/html", b"<p>No profile configured.</p>")
            return

        config = profiles[0]
        graph = self.__class__.graph
        if graph is None:
            self._respond(200, "text/html", b"<p>No graph data.</p>")
            return

        from cortex.caas.api_keys import get_disclosed_graph
        from cortex.caas.profile import render_profile_html

        filtered = get_disclosed_graph(graph, config.policy, config.custom_tags or None)
        page_html = render_profile_html(filtered, config, self.__class__.credential_store)
        self._respond(200, "text/html", page_html.encode("utf-8"))

    def _serve_profile_page(self, handle: str) -> None:
        """GET /p/{handle} — serve the public profile page."""
        store = self._get_profile_store()
        config = store.get(handle)
        if config is None:
            self._error_response(ERR_NOT_FOUND("profile"))
            return

        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED("graph"))
            return

        from cortex.caas.api_keys import get_disclosed_graph
        from cortex.caas.profile import render_profile_html

        filtered = get_disclosed_graph(graph, config.policy, config.custom_tags or None)
        page_html = render_profile_html(filtered, config, self.__class__.credential_store)
        self._respond(200, "text/html", page_html.encode("utf-8"))

    # ── Attestation endpoints ─────────────────────────────────────────

    def _handle_list_attestations(self) -> None:
        """GET /api/attestations — list all attestation credentials."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return

        store = self.__class__.credential_store
        if store is None:
            self._json_response({"attestations": [], "count": 0})
            return

        from cortex.upai.attestations import ATTESTATION_TYPES
        attest_types = set(ATTESTATION_TYPES.keys())
        creds = store.list_all()
        attestations = [
            c.to_dict() for c in creds
            if attest_types.intersection(set(c.credential_type))
        ]
        self._json_response({"attestations": attestations, "count": len(attestations)})

    def _handle_get_attestations_for_node(self, node_id: str) -> None:
        """GET /api/attestations/{node_id} — get attestations for a node."""
        # Allow both authenticated and API key access
        store = self.__class__.credential_store
        if store is None:
            self._json_response({"attestations": [], "count": 0})
            return

        from cortex.upai.attestations import get_attestations_for_node, get_attestation_summary
        creds = get_attestations_for_node(store, node_id)
        summary = get_attestation_summary(store, node_id)
        self._json_response({
            "attestations": [c.to_dict() for c in creds],
            "summary": summary,
        })

    def _handle_create_attestation_request(self) -> None:
        """POST /api/attestations/request — create an attestation request."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return

        identity = self.__class__.identity
        if identity is None:
            self._error_response(ERR_NOT_CONFIGURED("No identity configured"))
            return

        body = self._read_body()
        if body is None:
            return

        attestor_did = body.get("attestor_did", "")
        attestation_type = body.get("attestation_type", "")
        proposed_claims = body.get("proposed_claims", {})
        bound_node_id = body.get("bound_node_id", "")

        if not attestor_did:
            self._error_response(ERR_INVALID_REQUEST("attestor_did required"))
            return

        from cortex.upai.attestations import (
            ATTESTATION_TYPES,
            create_attestation_request,
            validate_attestation_claims,
        )

        if attestation_type not in ATTESTATION_TYPES:
            self._error_response(ERR_INVALID_REQUEST(
                f"Invalid attestation_type. Must be one of: {', '.join(sorted(ATTESTATION_TYPES))}"))
            return

        errors = validate_attestation_claims(attestation_type, proposed_claims)
        if errors:
            self._error_response(ERR_INVALID_REQUEST("; ".join(errors)))
            return

        request, envelope = create_attestation_request(
            identity, attestor_did, attestation_type,
            proposed_claims, bound_node_id,
        )
        self._json_response({
            "request_id": request.request_id,
            "envelope": envelope.serialize() if hasattr(envelope, 'serialize') else str(envelope),
        }, status=201)

    def _handle_sign_attestation(self) -> None:
        """POST /api/attestations/sign — sign an attestation (public, self-authenticating)."""
        body = self._read_body()
        if body is None:
            return

        request_data = body.get("request", {})
        claims = body.get("claims", {})
        ttl_days = body.get("ttl_days", 365)

        # The attestor provides their signed credential directly
        credential_dict = body.get("credential")
        if credential_dict:
            # Store a pre-signed credential
            store = self.__class__.credential_store
            if store is None:
                self._error_response(ERR_NOT_CONFIGURED("credential_store"))
                return
            from cortex.upai.credentials import VerifiableCredential
            cred = VerifiableCredential.from_dict(credential_dict)
            store.add(cred)
            self._json_response({
                "stored": True,
                "credential_id": cred.credential_id,
            }, status=201)
            return

        # Otherwise require request data for local signing
        self._error_response(ERR_INVALID_REQUEST(
            "Provide 'credential' (pre-signed VerifiableCredential dict)"))

    def _handle_delete_attestation(self, credential_id: str) -> None:
        """DELETE /api/attestations/{credential_id} — delete an attestation."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return

        store = self.__class__.credential_store
        if store is None:
            self._error_response(ERR_NOT_FOUND("credential"))
            return

        if store.delete(credential_id):
            self._json_response({"deleted": True})
        else:
            self._error_response(ERR_NOT_FOUND("credential"))

    # ── JSON Resume endpoint ─────────────────────────────────────────

    def _handle_public_resume(self, path: str) -> None:
        """GET /api/resume/{key} — public JSON Resume export via API key."""
        key_secret = path[len("/api/resume/"):]
        if not key_secret:
            self._error_response(ERR_NOT_FOUND("api_key"))
            return

        store = self._get_api_key_store()
        key_info = store.get_by_secret(key_secret)
        if key_info is None:
            self._error_response(ERR_NOT_FOUND("api_key"))
            return

        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED("graph"))
            return

        from cortex.caas.api_keys import get_disclosed_graph
        filtered = get_disclosed_graph(graph, key_info["policy"], key_info.get("tags"))

        from cortex.caas.jsonresume import graph_to_jsonresume
        resume = graph_to_jsonresume(filtered, self.__class__.credential_store)
        import json as _json
        body = _json.dumps(resume, indent=2, default=str).encode("utf-8")
        self._respond(200, "application/json", body)

    # ── Timeline endpoints ────────────────────────────────────────────

    def _handle_get_timeline(self) -> None:
        """GET /api/timeline — list all work and education history entries."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED("graph"))
            return
        from cortex.professional_timeline import get_timeline
        entries = get_timeline(graph)
        self._json_response({
            "timeline": [n.to_dict() for n in entries],
            "count": len(entries),
        })

    def _handle_get_timeline_node(self, node_id: str) -> None:
        """GET /api/timeline/{node_id} — get a single timeline entry."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED("graph"))
            return
        node = graph.get_node(node_id)
        if node is None or not any(t in node.tags for t in ("work_history", "education_history")):
            self._error_response(ERR_NOT_FOUND("timeline_entry"))
            return
        self._json_response({"node": node.to_dict()})

    def _handle_create_timeline_entry(self) -> None:
        """POST /api/timeline — create a new timeline entry."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED("graph"))
            return

        body = self._read_body()
        if body is None:
            return

        entry_type = body.get("type", "")
        properties = body.get("properties", {})

        if entry_type not in ("work_history", "education_history"):
            self._error_response(ERR_INVALID_REQUEST(
                "type must be 'work_history' or 'education_history'"))
            return

        from cortex.professional_timeline import (
            WorkHistoryEntry, EducationHistoryEntry,
            create_work_history_node, create_education_node,
            validate_work_history_properties, validate_education_properties,
        )

        if entry_type == "work_history":
            errors = validate_work_history_properties(properties)
            if errors:
                self._error_response(ERR_INVALID_REQUEST("; ".join(errors)))
                return
            entry = WorkHistoryEntry.from_properties(properties)
            node = create_work_history_node(entry)
        else:
            errors = validate_education_properties(properties)
            if errors:
                self._error_response(ERR_INVALID_REQUEST("; ".join(errors)))
                return
            entry = EducationHistoryEntry.from_properties(properties)
            node = create_education_node(entry)

        graph.add_node(node)
        self._json_response({"node": node.to_dict(), "id": node.id}, status=201)

    def _handle_update_timeline_entry(self, node_id: str) -> None:
        """PUT /api/timeline/{node_id} — update a timeline entry."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED("graph"))
            return

        node = graph.get_node(node_id)
        if node is None or not any(t in node.tags for t in ("work_history", "education_history")):
            self._error_response(ERR_NOT_FOUND("timeline_entry"))
            return

        body = self._read_body()
        if body is None:
            return

        properties = body.get("properties", {})
        if not properties:
            self._error_response(ERR_INVALID_REQUEST("properties required"))
            return

        # Merge properties
        merged = dict(node.properties)
        merged.update(properties)

        # Validate merged result
        from cortex.professional_timeline import (
            validate_work_history_properties, validate_education_properties,
        )
        if "work_history" in node.tags:
            errors = validate_work_history_properties(merged)
        else:
            errors = validate_education_properties(merged)

        if errors:
            self._error_response(ERR_INVALID_REQUEST("; ".join(errors)))
            return

        # Derive current flag
        merged["current"] = merged.get("end_date", "") == ""

        graph.update_node(node_id, {"properties": merged})
        updated = graph.get_node(node_id)
        self._json_response({"node": updated.to_dict()})

    def _handle_delete_timeline_entry(self, node_id: str) -> None:
        """DELETE /api/timeline/{node_id} — delete a timeline entry."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED("graph"))
            return

        node = graph.get_node(node_id)
        if node is None or not any(t in node.tags for t in ("work_history", "education_history")):
            self._error_response(ERR_NOT_FOUND("timeline_entry"))
            return

        graph.remove_node(node_id)
        self._json_response({"deleted": True})

    # ── API Key endpoints ────────────────────────────────────────────

    def _get_api_key_store(self):
        """Lazy-init the API key store."""
        if self.__class__.api_key_store is None:
            from cortex.caas.api_keys import ApiKeyStore
            store_path = Path(".cortex") / "api_keys.json"
            self.__class__.api_key_store = ApiKeyStore(store_path)
        return self.__class__.api_key_store

    def _handle_create_api_key(self) -> None:
        """POST /api/keys — create a new shareable memory API key."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return

        body = self._read_body()
        if body is None:
            return

        label = body.get("label", "Untitled Key")
        policy = body.get("policy", "full")
        tags = body.get("tags")
        fmt = body.get("format", "json")

        valid_policies = {"full", "professional", "technical", "minimal", "custom"}
        if policy not in valid_policies:
            self._error_response(ERR_INVALID_REQUEST(
                f"Invalid policy. Must be one of: {', '.join(sorted(valid_policies))}"))
            return

        valid_formats = {"json", "claude_xml", "system_prompt", "markdown", "jsonresume"}
        if fmt not in valid_formats:
            self._error_response(ERR_INVALID_REQUEST(
                f"Invalid format. Must be one of: {', '.join(sorted(valid_formats))}"))
            return

        store = self._get_api_key_store()
        key_info = store.create(label, policy, tags=tags, fmt=fmt)
        self._json_response(key_info, status=201)

    def _handle_list_api_keys(self) -> None:
        """GET /api/keys — list all API keys (secrets masked)."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return

        store = self._get_api_key_store()
        self._json_response(store.list_keys())

    def _handle_revoke_api_key(self, key_id: str) -> None:
        """DELETE /api/keys/{key_id} — revoke an API key."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_auth_check():
            return

        store = self._get_api_key_store()
        if store.revoke(key_id):
            self._json_response({"revoked": True, "key_id": key_id})
        else:
            self._error_response(ERR_NOT_FOUND("api_key"))

    def _handle_public_memory(self, path: str, query: dict | None = None) -> None:
        """GET /api/memory/{key} — public endpoint, no auth required.

        Supports optional query parameters for filtering/searching:
        - ``?q=``              Full DSL query (FIND, SEARCH, NEIGHBORS, PATH)
        - ``?search=``         Shorthand full-text search
        - ``?tags=``           Comma-separated tag filter
        - ``?min_confidence=`` Confidence floor (0.0-1.0)
        - ``?limit=``          Max results (1-1000, default 100)
        """
        query = query or {}

        key_secret = path[len("/api/memory/"):]
        if not key_secret:
            self._error_response(ERR_NOT_FOUND("api_key"))
            return

        store = self._get_api_key_store()
        key_info = store.get_by_secret(key_secret)
        if key_info is None:
            self._error_response(ERR_NOT_FOUND("api_key"))
            return

        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED("graph"))
            return

        # ── Check for query params ──────────────────────────────────
        q_dsl = query.get("q", [""])[0] if "q" in query else ""
        search_text = query.get("search", [""])[0] if "search" in query else ""
        tags_param = query.get("tags", [""])[0] if "tags" in query else ""
        min_conf_raw = query.get("min_confidence", [""])[0] if "min_confidence" in query else ""
        limit_raw = query.get("limit", [""])[0] if "limit" in query else ""

        has_query = q_dsl or search_text or tags_param or min_conf_raw or limit_raw

        if not has_query:
            # No query params → existing behaviour: render in key's format
            from cortex.caas.api_keys import render_memory
            content, content_type = render_memory(
                graph, key_info["policy"], key_info.get("tags"), key_info["format"])
            self._respond(200, content_type, content.encode("utf-8"))
            return

        # ── Parse limit / min_confidence ────────────────────────────
        limit = 100
        if limit_raw:
            try:
                limit = int(limit_raw)
                if limit < 1 or limit > 1000:
                    raise ValueError
            except (ValueError, TypeError):
                self._error_response(ERR_INVALID_REQUEST(
                    "limit must be an integer between 1 and 1000"))
                return

        min_confidence = 0.0
        if min_conf_raw:
            try:
                min_confidence = float(min_conf_raw)
                if not (0.0 <= min_confidence <= 1.0):
                    raise ValueError
            except (ValueError, TypeError):
                self._error_response(ERR_INVALID_REQUEST(
                    "min_confidence must be a number between 0.0 and 1.0"))
                return

        # ── Security boundary: apply disclosure policy ──────────────
        from cortex.caas.api_keys import get_disclosed_graph
        filtered = get_disclosed_graph(
            graph, key_info["policy"], key_info.get("tags"))

        policy_name = key_info["policy"]

        # ── Execute query (precedence: q > search > tags > bare) ────
        _SYNTAX_HINT = (
            'Supported syntax: FIND nodes WHERE <field> <op> <value> LIMIT N | '
            'SEARCH "<text>" | NEIGHBORS OF "<label>" | PATH FROM "<a>" TO "<b>"'
        )

        if q_dsl:
            from cortex.query_lang import ParseError, execute_query
            try:
                result = execute_query(filtered, q_dsl)
            except ParseError as exc:
                err = ERR_INVALID_REQUEST(f"Query parse error: {exc}")
                err.hint = _SYNTAX_HINT
                self._error_response(err)
                return
            self._json_response({
                "query": q_dsl,
                "results": result,
                "count": result.get("count", len(result.get("nodes", result.get("results", [])))),
                "policy": policy_name,
            })
            return

        if search_text:
            nodes = filtered.search_nodes(
                search_text, limit=limit, min_confidence=min_confidence)
            results = [n.to_dict() for n in nodes]
            self._json_response({
                "query": f'SEARCH "{search_text}"',
                "results": results,
                "count": len(results),
                "policy": policy_name,
            })
            return

        if tags_param:
            tag_set = {t.strip() for t in tags_param.split(",") if t.strip()}
            results = []
            for node in filtered.nodes.values():
                if node.confidence < min_confidence:
                    continue
                if tag_set.intersection(set(node.tags)):
                    results.append(node.to_dict())
                    if len(results) >= limit:
                        break
            self._json_response({
                "query": f"tags={tags_param}",
                "results": results,
                "count": len(results),
                "policy": policy_name,
            })
            return

        # Bare min_confidence / limit only
        results = []
        for node in filtered.nodes.values():
            if node.confidence < min_confidence:
                continue
            results.append(node.to_dict())
            if len(results) >= limit:
                break
        self._json_response({
            "query": f"min_confidence={min_confidence}&limit={limit}",
            "results": results,
            "count": len(results),
            "policy": policy_name,
        })

    # ── Dashboard: static files ─────────────────────────────────────

    def _serve_dashboard_file(self, path: str) -> None:
        """Serve a static file from the dashboard directory."""
        resolved = resolve_dashboard_path(path)
        if resolved is None:
            self._error_response(ERR_NOT_FOUND("dashboard file"))
            return
        ct = guess_content_type(resolved)
        body = resolved.read_bytes()
        self._respond(200, ct, body, dashboard=True)

    # ── Webapp: session auth ────────────────────────────────────

    def _webapp_auth_check(self) -> bool:
        """Validate webapp session cookie (cortex_app_session) or fall back to dashboard session.

        Returns True if valid, sends 401 otherwise.
        """
        sm = self.__class__.session_manager
        if sm is None:
            self._respond(401, "application/json",
                          json.dumps({"error": "unauthorized"}).encode(),
                          dashboard=True)
            return False

        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("cortex_app_session="):
                token = part[len("cortex_app_session="):]
                if token and sm.validate(token):
                    return True
                self._respond(401, "application/json",
                              json.dumps({"error": "unauthorized"}).encode(),
                              dashboard=True)
                return False

        # Fall back to dashboard session cookie
        return self._dashboard_auth_check()

    def _handle_webapp_login(self) -> None:
        """POST /app/auth — authenticate webapp with derived password."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return

        sm = self.__class__.session_manager
        if sm is None:
            self._error_response(ERR_NOT_CONFIGURED("Webapp not configured"))
            return

        body = self._read_body()
        if body is None:
            return

        password = body.get("password", "")
        token = sm.authenticate(password)
        if token is None:
            self._audit("webapp.login_failed", {})
            self._respond(401, "application/json",
                          json.dumps({"error": "invalid_password"}).encode(),
                          dashboard=True)
            return

        self._audit("webapp.login", {})
        resp_body = json.dumps({"ok": True}).encode()
        self._respond(200, "application/json", resp_body, dashboard=True,
                      extra_headers={
                          "Set-Cookie": f"cortex_app_session={token}; HttpOnly; SameSite=Strict; Path=/",
                      })

    def _handle_webapp_logout(self) -> None:
        """POST /app/logout — revoke webapp session."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return

        sm = self.__class__.session_manager
        if sm is not None:
            cookie_header = self.headers.get("Cookie", "")
            for part in cookie_header.split(";"):
                part = part.strip()
                if part.startswith("cortex_app_session="):
                    token = part[len("cortex_app_session="):]
                    if token:
                        sm.revoke(token)
                    break

        self._audit("webapp.logout", {})
        resp_body = json.dumps({"ok": True}).encode()
        self._respond(200, "application/json", resp_body, dashboard=True,
                      extra_headers={
                          "Set-Cookie": "cortex_app_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0",
                      })

    # ── Dashboard: session auth ──────────────────────────────────

    def _handle_dashboard_login(self) -> None:
        """POST /dashboard/auth — authenticate with derived password."""
        sm = self.__class__.session_manager
        if sm is None:
            self._error_response(ERR_NOT_CONFIGURED("Dashboard not configured"))
            return

        body = self._read_body()
        if body is None:
            return

        password = body.get("password", "")
        token = sm.authenticate(password)
        if token is None:
            self._audit("dashboard.login_failed", {})
            self._respond(401, "application/json",
                          json.dumps({"error": "invalid_password"}).encode(),
                          dashboard=True)
            return

        self._audit("dashboard.login", {})
        resp_body = json.dumps({"ok": True}).encode()
        self._respond(200, "application/json", resp_body, dashboard=True,
                      extra_headers={
                          "Set-Cookie": f"cortex_session={token}; HttpOnly; SameSite=Strict; Path=/dashboard",
                      })

    def _dashboard_auth_check(self, check_csrf: bool = False) -> bool:
        """Validate dashboard session cookie. Returns True if valid, sends 401 otherwise.

        If *check_csrf* is True, also validates the X-CSRF-Token header against
        the session token.
        """
        sm = self.__class__.session_manager
        if sm is None:
            self._respond(401, "application/json",
                          json.dumps({"error": "dashboard_not_configured"}).encode(),
                          dashboard=True)
            return False

        cookie_header = self.headers.get("Cookie", "")
        token = None
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("cortex_session="):
                token = part[len("cortex_session="):]
                break

        if not token or not sm.validate(token):
            self._respond(401, "application/json",
                          json.dumps({"error": "unauthorized"}).encode(),
                          dashboard=True)
            return False

        # CSRF validation for mutating requests (only if enabled)
        if check_csrf and self.__class__.csrf_enabled and hasattr(sm, 'csrf_secret'):
            from cortex.caas.security import CSRFProtection
            csrf = CSRFProtection(sm.csrf_secret)
            csrf_token = self.headers.get("X-CSRF-Token", "")
            if not csrf.validate_token(token, csrf_token):
                self._respond(403, "application/json",
                              json.dumps({"error": "csrf_validation_failed"}).encode(),
                              dashboard=True)
                return False
        return True

    def _get_csrf_token_for_session(self) -> str | None:
        """Generate a CSRF token for the current session cookie, if present."""
        if not self.__class__.csrf_enabled:
            return None
        sm = self.__class__.session_manager
        if sm is None or not hasattr(sm, 'csrf_secret'):
            return None
        cookie_header = self.headers.get("Cookie", "")
        token = None
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("cortex_session="):
                token = part[len("cortex_session="):]
                break
        if not token or not sm.validate(token):
            return None
        from cortex.caas.security import CSRFProtection
        csrf = CSRFProtection(sm.csrf_secret)
        return csrf.generate_token(token)

    # ── Dashboard: API routing ───────────────────────────────────

    def _route_dashboard_api_get(self, path: str, query: dict) -> None:
        """Route GET /dashboard/api/* requests."""
        if not self._dashboard_auth_check():
            return
        # Generate CSRF token for mutating actions
        csrf_token = self._get_csrf_token_for_session()
        if csrf_token:
            self._csrf_token_for_response = csrf_token

        api_path = path[len("/dashboard/api"):]

        if api_path == "/identity":
            self._dashboard_api_identity()
        elif api_path == "/graph":
            self._dashboard_api_graph(query)
        elif api_path == "/stats":
            self._dashboard_api_stats()
        elif api_path == "/grants":
            self._dashboard_api_list_grants()
        elif api_path == "/versions":
            self._dashboard_api_versions(query)
        elif api_path == "/versions/diff":
            self._dashboard_api_version_diff(query)
        elif api_path == "/audit":
            self._dashboard_api_audit(query)
        elif api_path == "/webhooks":
            self._dashboard_api_list_webhooks()
        elif api_path == "/policies":
            self._serve_list_policies()
        elif api_path == "/config":
            self._dashboard_api_config()
        elif api_path == "/devices":
            self._serve_devices()
        elif api_path.startswith("/webhooks/") and api_path.endswith("/health"):
            webhook_id = api_path[len("/webhooks/"):-len("/health")]
            self._dashboard_api_webhook_health(webhook_id)
        else:
            self._error_response(ERR_NOT_FOUND("dashboard endpoint"))

    def _route_dashboard_api_post(self, path: str) -> None:
        """Route POST /dashboard/api/* requests."""
        if not self._dashboard_auth_check(check_csrf=True):
            return

        api_path = path[len("/dashboard/api"):]

        if api_path == "/grants":
            self._handle_create_grant()
        elif api_path == "/webhooks":
            self._handle_create_webhook()
        elif api_path == "/policies":
            self._handle_create_policy()
        elif api_path == "/backup":
            self._handle_create_backup()
        elif api_path == "/backup/restore":
            self._handle_restore_backup()
        elif api_path == "/backup/recovery-phrase":
            self._handle_generate_recovery()
        elif api_path == "/devices":
            self._handle_authorize_device()
        elif api_path.startswith("/webhooks/") and api_path.endswith("/retry"):
            webhook_id = api_path[len("/webhooks/"):-len("/retry")]
            self._dashboard_api_webhook_retry(webhook_id)
        else:
            self._error_response(ERR_NOT_FOUND("dashboard endpoint"))

    def _route_dashboard_api_delete(self, path: str) -> None:
        """Route DELETE /dashboard/api/* requests."""
        if not self._dashboard_auth_check(check_csrf=True):
            return

        api_path = path[len("/dashboard/api"):]

        if api_path.startswith("/grants/"):
            grant_id = api_path[len("/grants/"):]
            self._handle_revoke_grant(grant_id)
        elif api_path.startswith("/webhooks/"):
            webhook_id = api_path[len("/webhooks/"):]
            self._handle_delete_webhook(webhook_id)
        elif api_path.startswith("/policies/"):
            policy_name = api_path[len("/policies/"):]
            self._handle_delete_policy(policy_name)
        elif api_path.startswith("/devices/"):
            device_id = api_path[len("/devices/"):]
            self._handle_revoke_device(device_id)
        else:
            self._error_response(ERR_NOT_FOUND("dashboard endpoint"))

    # ── Dashboard: API handlers ──────────────────────────────────

    def _dashboard_api_identity(self) -> None:
        identity = self.__class__.identity
        if identity is None:
            self._error_response(ERR_NOT_CONFIGURED("No identity"))
            return
        self._json_response({
            "did": identity.did,
            "name": identity.name,
            "created_at": identity.created_at,
            "key_type": identity._key_type,
            "public_key_prefix": identity.public_key_b64[:24] + "...",
        })

    def _dashboard_api_graph(self, query: dict) -> None:
        graph = self.__class__.graph
        identity = self.__class__.identity
        if graph is None or identity is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        policy_name = query.get("policy", ["full"])[0]
        policy = self.__class__.policy_registry.get(policy_name)
        if policy is None:
            err = ERR_INVALID_POLICY(policy_name)
            from cortex.upai.error_hints import hint_for_policy
            known = [p.name for p in self.__class__.policy_registry.list_all()]
            err.hint = hint_for_policy(policy_name, known)
            self._error_response(err)
            return
        filtered = apply_disclosure(graph, policy)

        from cortex.viz.layout import fruchterman_reingold
        from cortex.viz.renderer import _node_radius, _tag_color

        layout = fruchterman_reingold(filtered, iterations=50, max_nodes=200)

        node_list = []
        node_index = {}
        for i, (nid, node) in enumerate(filtered.nodes.items()):
            pos = layout.get(nid, (0.5, 0.5))
            color = _tag_color(node.tags[0]) if node.tags else "#95a5a6"
            node_list.append({
                "id": nid,
                "label": node.label,
                "x": pos[0],
                "y": pos[1],
                "r": _node_radius(node.confidence),
                "color": color,
                "tags": node.tags,
                "confidence": node.confidence,
                "brief": node.brief,
            })
            node_index[nid] = i

        edge_list = []
        for edge in filtered.edges.values():
            si = node_index.get(edge.source_id)
            ti = node_index.get(edge.target_id)
            if si is not None and ti is not None:
                edge_list.append({
                    "s": si, "t": ti,
                    "relation": edge.relation,
                    "confidence": edge.confidence,
                })

        self._json_response({
            "nodes": node_list,
            "edges": edge_list,
            "policy": policy_name,
        })

    def _dashboard_api_stats(self) -> None:
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return
        self._json_response(graph.stats())

    def _dashboard_api_list_grants(self) -> None:
        grants = self.__class__.grant_store.list_all()
        self._json_response({"grants": grants})

    def _dashboard_api_versions(self, query: dict) -> None:
        vs = self.__class__.version_store
        if vs is None:
            self._json_response({"items": [], "has_more": False})
            return

        versions = vs.log(limit=100)
        items = [v.to_dict() for v in versions]

        limit = int(query.get("limit", ["20"])[0])
        cursor = query.get("cursor", [None])[0]
        page = paginate(items, limit=limit, cursor=cursor, sort_key="version_id")
        self._json_response(page.to_dict())

    def _dashboard_api_version_diff(self, query: dict) -> None:
        vs = self.__class__.version_store
        if vs is None:
            self._error_response(ERR_NOT_CONFIGURED("No version store"))
            return

        a = query.get("a", [None])[0]
        b = query.get("b", [None])[0]
        if not a or not b:
            self._error_response(ERR_INVALID_REQUEST("Both 'a' and 'b' params required"))
            return

        try:
            diff = vs.diff(a, b)
            self._json_response(diff)
        except FileNotFoundError as e:
            self._error_response(ERR_NOT_FOUND(str(e)))

    def _dashboard_api_audit(self, query: dict) -> None:
        log = self.__class__.audit_log
        if log is None:
            self._json_response({"entries": []})
            return

        limit = int(query.get("limit", ["50"])[0])
        entries = log.recent(limit=limit)
        self._json_response({"entries": entries})

    def _dashboard_api_list_webhooks(self) -> None:
        registrations = self.__class__.webhook_store.list_all()
        webhooks = []
        for reg in registrations:
            webhooks.append({
                "webhook_id": reg.webhook_id,
                "url": reg.url,
                "events": reg.events,
                "active": reg.active,
                "created_at": reg.created_at,
            })
        self._json_response({"webhooks": webhooks})

    def _dashboard_api_webhook_health(self, webhook_id: str) -> None:
        """GET /dashboard/api/webhooks/:id/health — circuit + dead-letter status."""
        worker = self.__class__.webhook_worker
        if worker is None:
            self._error_response(ERR_NOT_CONFIGURED("Webhook worker not configured"))
            return
        health = worker.get_health(webhook_id)
        self._json_response(health)

    def _dashboard_api_webhook_retry(self, webhook_id: str) -> None:
        """POST /dashboard/api/webhooks/:id/retry — replay dead-letter events."""
        worker = self.__class__.webhook_worker
        if worker is None:
            self._error_response(ERR_NOT_CONFIGURED("Webhook worker not configured"))
            return
        count = worker.retry_dead_letter(webhook_id)
        self._json_response({"replayed": count, "webhook_id": webhook_id})

    def _dashboard_api_config(self) -> None:
        identity = self.__class__.identity
        graph = self.__class__.graph
        om = self.__class__.oauth_manager
        cs = self.__class__.credential_store
        port = getattr(self.server, "server_port", 8421)
        self._json_response({
            "port": port,
            "did": identity.did if identity else None,
            "storage_backend": "sqlite" if hasattr(self.__class__.grant_store, '_db_path') else "json",
            "node_count": len(graph.nodes) if graph else 0,
            "edge_count": len(graph.edges) if graph else 0,
            "grant_count": len(self.__class__.grant_store.list_all()),
            "webhook_count": len(self.__class__.webhook_store.list_all()),
            "credential_count": cs.count if cs else 0,
            "policies": [p.name for p in self.__class__.policy_registry.list_all()],
            "oauth_providers": om.provider_names if om and om.enabled else [],
            "oauth_allowed_emails": sorted(om._allowed_emails) if om and om._allowed_emails else None,
            "sse_enabled": self.__class__.sse_manager is not None,
        })

    # ── Response helpers ─────────────────────────────────────────────

    def _read_body(self, require_json: bool = True) -> dict | None:
        """Read and parse JSON request body. Returns None and sends error on failure."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._error_response(ERR_INVALID_REQUEST("Empty request body"))
            return None
        if content_length > MAX_BODY_SIZE:
            self._error_response(ERR_PAYLOAD_TOO_LARGE())
            return None
        # Content-Type validation
        if require_json:
            from cortex.caas.security import require_json_content_type
            ct = self.headers.get("Content-Type", "")
            valid, ct_err = require_json_content_type(ct)
            if not valid:
                self._respond(415, "application/json",
                              json.dumps({"error": "unsupported_media_type", "detail": ct_err}).encode("utf-8"))
                return None
        try:
            raw = self.rfile.read(content_length)
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self._error_response(ERR_INVALID_REQUEST("Invalid JSON"))
            return None

    def _json_response(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode("utf-8")

        # HTTP caching: ETag + conditional 304
        etag = generate_etag(body)
        if_none_match = self.headers.get("If-None-Match", "")
        if status == 200 and if_none_match and check_if_none_match(if_none_match, etag):
            if self.__class__.metrics_registry is not None:
                try:
                    from cortex.caas.instrumentation import CACHE_HITS
                    CACHE_HITS.inc()
                except Exception:
                    pass
            self._respond(304, "application/json", b"", extra_headers={"ETag": etag})
            return

        if status == 200 and if_none_match:
            # Client sent If-None-Match but ETag didn't match
            if self.__class__.metrics_registry is not None:
                try:
                    from cortex.caas.instrumentation import CACHE_MISSES
                    CACHE_MISSES.inc()
                except Exception:
                    pass

        # Cache-Control
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        profile = get_cache_profile(path)

        self._respond(status, "application/json", body,
                      extra_headers={"ETag": etag, "Cache-Control": profile.to_header()})

    def _error_response(self, error: UPAIError) -> None:
        body = json.dumps(error.to_dict(request_id=self._request_id), default=str).encode("utf-8")
        self._respond(error.http_status, "application/json", body)

    def _respond(
        self,
        code: int,
        content_type: str,
        body: bytes,
        extra_headers: dict[str, str] | None = None,
        dashboard: bool = False,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))

        # CORS
        origin = self.headers.get("Origin", "")
        allowed = self.__class__._allowed_origins
        if origin and origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
        elif allowed:
            self.send_header("Access-Control-Allow-Origin", next(iter(allowed)))

        # Request correlation
        if self._request_id:
            self.send_header("X-Request-ID", self._request_id)

        # Security headers
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if dashboard:
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'")
            # Include CSRF token if available
            csrf = getattr(self, "_csrf_token_for_response", None)
            if csrf:
                self.send_header("X-CSRF-Token", csrf)
                self._csrf_token_for_response = None
        else:
            self.send_header("Content-Security-Policy", "default-src 'none'")

        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)

        self.end_headers()
        self.wfile.write(body)
        self._record_metrics(code)
        self._log_request(code)

    # ── Federation endpoints ─────────────────────────────────────────

    def _serve_federation_peers(self) -> None:
        """GET /federation/peers — return this instance's federation info."""
        fm = self.__class__.federation_manager
        if fm is None:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        self._json_response(fm.get_peer_info())

    def _handle_federation_export(self) -> None:
        """POST /federation/export — export graph as signed bundle."""
        fm = self.__class__.federation_manager
        if fm is None:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        body = self._read_json_body()
        if body is None:
            return
        policy = body.get("policy", "full")
        tag_filter = body.get("tag_filter")
        metadata = body.get("metadata")
        graph = self.__class__.graph
        try:
            bundle = fm.export_bundle(
                graph, policy=policy, tag_filter=tag_filter, metadata=metadata,
            )
            self._json_response(bundle.to_dict())
        except ValueError as exc:
            self._json_response({"error": str(exc)}, status=400)

    def _handle_federation_import(self) -> None:
        """POST /federation/import — import a signed bundle into local graph."""
        fm = self.__class__.federation_manager
        if fm is None:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        body = self._read_json_body()
        if body is None:
            return
        from cortex.federation import FederationBundle

        try:
            bundle = FederationBundle.from_dict(body)
        except (KeyError, TypeError) as exc:
            self._json_response({"error": f"Invalid bundle: {exc}"}, status=400)
            return
        graph = self.__class__.graph
        result = fm.import_bundle(graph, bundle)
        status = 200 if result.success else 403
        self._json_response(result.to_dict(), status=status)

    def log_message(self, format: str, *args: Any) -> None:
        """Route BaseHTTPRequestHandler logs through stdlib logging."""
        import logging
        logging.getLogger("caas.server").debug(format, *args)


# ---------------------------------------------------------------------------
# Server launcher
# ---------------------------------------------------------------------------

def start_caas_server(
    graph: CortexGraph,
    identity: UPAIIdentity,
    version_store: Any = None,
    port: int = 8421,
    allowed_origins: set[str] | None = None,
    grants_persist_path: str | None = None,
    storage_backend: str = "json",
    db_path: str | None = None,
    enable_metrics: bool = False,
    oauth_providers: dict | None = None,
    oauth_allowed_emails: set[str] | None = None,
    credential_store_path: str | None = None,
    enable_sse: bool = False,
    store_dir: str | None = None,
    config: Any = None,
    plugin_manager: Any = None,
    tracing_manager: Any = None,
    enable_federation: bool = False,
    federation_trusted_dids: list[str] | None = None,
    enable_webapp: bool = False,
) -> ThreadingHTTPServer:
    """Start the CaaS API server. Returns the server instance (call serve_forever()).

    If *config* (a CortexConfig) is provided, its values are used as defaults
    for any parameter not explicitly passed by the caller.
    """
    # Apply config defaults where explicit params weren't overridden
    if config is not None:
        if port == 8421:
            port = config.getint("server", "port", fallback=8421)
        if storage_backend == "json":
            storage_backend = config.get("storage", "backend", fallback="json")
        if db_path is None:
            if storage_backend == "postgres":
                _cfg_url = config.get("storage", "db_url", fallback="")
                if _cfg_url:
                    db_path = _cfg_url
            else:
                _cfg_db = config.get("storage", "db_path", fallback="")
                if _cfg_db:
                    db_path = _cfg_db
        if not enable_sse:
            enable_sse = config.getbool("sse", "enabled", fallback=False)
        if not enable_metrics:
            enable_metrics = config.getbool("metrics", "enabled", fallback=False)
        if store_dir is None:
            _cfg_dir = config.get("storage", "store_dir", fallback="")
            if _cfg_dir:
                store_dir = _cfg_dir

    CaaSHandler.graph = graph
    CaaSHandler.identity = identity
    CaaSHandler.version_store = version_store
    CaaSHandler.nonce_cache = NonceCache()
    CaaSHandler.session_manager = DashboardSessionManager(identity)
    CaaSHandler.enable_webapp = enable_webapp
    CaaSHandler.policy_registry = PolicyRegistry()
    # CSRF: enable via config
    if config is not None:
        CaaSHandler.csrf_enabled = config.getbool("security", "csrf_enabled", fallback=True)
    else:
        CaaSHandler.csrf_enabled = False  # off by default when no config provided

    # OAuth setup
    if oauth_providers:
        import hashlib as _hl

        from cortex.caas.oauth import PROVIDER_DEFAULTS, OAuthManager, OAuthProviderConfig
        providers = {}
        for name, creds in oauth_providers.items():
            defaults = PROVIDER_DEFAULTS.get(name, {})
            providers[name] = OAuthProviderConfig(
                name=name,
                client_id=creds["client_id"],
                client_secret=creds["client_secret"],
                authorize_url=defaults.get("authorize_url", ""),
                token_url=defaults.get("token_url", ""),
                userinfo_url=defaults.get("userinfo_url", ""),
                scopes=defaults.get("scopes", []),
            )
        # Derive state secret from identity private key
        pk = identity._private_key or identity.did.encode()
        state_secret = _hl.sha256(pk + b"cortex-oauth-state").digest()
        redirect_base = f"http://127.0.0.1:{port}"
        CaaSHandler.oauth_manager = OAuthManager(
            providers=providers,
            state_secret=state_secret,
            redirect_base=redirect_base,
            allowed_emails=oauth_allowed_emails,
        )
    else:
        CaaSHandler.oauth_manager = None

    if enable_metrics:
        from cortex.caas.instrumentation import create_default_registry
        CaaSHandler.metrics_registry = create_default_registry()
    else:
        CaaSHandler.metrics_registry = None

    # Plugin system
    CaaSHandler.plugin_manager = plugin_manager

    # Tracing
    CaaSHandler.tracing_manager = tracing_manager

    if storage_backend == "sqlite" and db_path:
        from cortex.caas.sqlite_store import (
            SqliteAuditLog,
            SqliteDeliveryLog,
            SqliteGrantStore,
            SqlitePolicyStore,
            SqliteWebhookStore,
        )
        # Set up field encryption for grant tokens
        _encryptor = None
        try:
            from cortex.caas.encryption import FieldEncryptor
            pk = identity._private_key or identity.did.encode()
            _encryptor = FieldEncryptor.from_identity_key(pk)
        except Exception:
            pass
        CaaSHandler.grant_store = SqliteGrantStore(db_path, encryptor=_encryptor)
        webhook_store = SqliteWebhookStore(db_path)
        CaaSHandler.webhook_store = webhook_store
        CaaSHandler.audit_log = SqliteAuditLog(db_path)
        CaaSHandler.policy_registry = PolicyRegistry(store=SqlitePolicyStore(db_path))
        delivery_log = SqliteDeliveryLog(db_path)
        from cortex.caas.webhook_worker import WebhookWorker
        worker = WebhookWorker(webhook_store, delivery_log=delivery_log)
        worker.start()
        CaaSHandler.webhook_worker = worker
    elif storage_backend == "postgres" and db_path:
        try:
            from cortex.caas.postgres_store import (
                PostgresAuditLog,
                PostgresDeliveryLog,
                PostgresGrantStore,
                PostgresPolicyStore,
                PostgresWebhookStore,
            )
        except ImportError:
            raise RuntimeError(
                'PostgreSQL storage requires psycopg: pip install "psycopg[binary]"'
            )
        _encryptor = None
        try:
            from cortex.caas.encryption import FieldEncryptor
            pk = identity._private_key or identity.did.encode()
            _encryptor = FieldEncryptor.from_identity_key(pk)
        except Exception:
            pass
        CaaSHandler.grant_store = PostgresGrantStore(db_path, encryptor=_encryptor)
        webhook_store = PostgresWebhookStore(db_path)
        CaaSHandler.webhook_store = webhook_store
        CaaSHandler.audit_log = PostgresAuditLog(db_path)
        CaaSHandler.policy_registry = PolicyRegistry(store=PostgresPolicyStore(db_path))
        delivery_log = PostgresDeliveryLog(db_path)
        from cortex.caas.webhook_worker import WebhookWorker
        worker = WebhookWorker(webhook_store, delivery_log=delivery_log)
        worker.start()
        CaaSHandler.webhook_worker = worker
    else:
        CaaSHandler.grant_store = JsonGrantStore(persist_path=grants_persist_path)
        json_webhook_store = JsonWebhookStore()
        CaaSHandler.webhook_store = json_webhook_store
        CaaSHandler.audit_log = None
        from cortex.caas.webhook_worker import WebhookWorker
        worker = WebhookWorker(json_webhook_store)
        worker.start()
        CaaSHandler.webhook_worker = worker

    # Credential store
    from cortex.upai.credentials import CredentialStore
    CaaSHandler.credential_store = CredentialStore(store_path=credential_store_path)

    # SSE
    if enable_sse:
        from cortex.caas.sse import SSEManager
        sse = SSEManager()
        sse.start()
        CaaSHandler.sse_manager = sse
    else:
        CaaSHandler.sse_manager = None

    # Keychain
    if store_dir:
        from cortex.upai.keychain import Keychain
        CaaSHandler.keychain = Keychain(Path(store_dir))
    else:
        CaaSHandler.keychain = None

    if allowed_origins:
        CaaSHandler._allowed_origins = allowed_origins
    else:
        CaaSHandler._allowed_origins = {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        }

    # Federation setup
    if enable_federation:
        from cortex.federation import FederationManager

        trusted = list(federation_trusted_dids or [])
        if config is not None and not trusted:
            trusted = config.getlist("federation", "trusted_dids")
        sign_exports = True
        bundle_ttl = 3600
        if config is not None:
            sign_exports = config.getbool("federation", "sign_exports", fallback=True)
            bundle_ttl = config.getint("federation", "bundle_ttl", fallback=3600)
        CaaSHandler.federation_manager = FederationManager(
            identity=identity,
            trusted_dids=trusted,
            sign_exports=sign_exports,
            bundle_ttl_seconds=bundle_ttl,
        )

    host = "127.0.0.1"
    if config is not None:
        host = config.get("server", "host", fallback="127.0.0.1")
    server = ThreadingHTTPServer((host, port), CaaSHandler)

    # Build shutdown coordinator
    from cortex.caas.shutdown import ShutdownCoordinator
    coordinator = ShutdownCoordinator()
    if CaaSHandler.sse_manager is not None:
        coordinator.register("sse", CaaSHandler.sse_manager.stop)
    if CaaSHandler.webhook_worker is not None:
        coordinator.register("webhook_worker", CaaSHandler.webhook_worker.stop)
    coordinator.register("http_server", server.shutdown)
    server._shutdown_coordinator = coordinator  # type: ignore[attr-defined]

    return server
