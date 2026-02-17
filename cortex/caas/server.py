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
"""

from __future__ import annotations

import json
import re
import threading
import time as _time
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import TYPE_CHECKING, Any

from cortex.upai.disclosure import BUILTIN_POLICIES, apply_disclosure
from cortex.upai.errors import (
    UPAIError,
    ERR_INVALID_TOKEN, ERR_INSUFFICIENT_SCOPE, ERR_NOT_FOUND,
    ERR_INVALID_REQUEST, ERR_INVALID_POLICY, ERR_INTERNAL, ERR_NOT_CONFIGURED,
)
from cortex.upai.pagination import paginate
from cortex.caas.storage import AbstractGrantStore, AbstractWebhookStore, AbstractAuditLog, JsonWebhookStore

if TYPE_CHECKING:
    from cortex.graph import CortexGraph
    from cortex.upai.identity import UPAIIdentity
    from cortex.upai.versioning import VersionStore


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

VALID_SCOPES = {"context:read", "context:subscribe", "versions:read", "identity:read"}


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
    rate_limiter: Any = None  # Optional RateLimiter
    webhook_worker: Any = None  # Optional WebhookWorker
    _allowed_origins: set[str] = set()

    def do_GET(self) -> None:
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
        else:
            self._error_response(ERR_NOT_FOUND("endpoint"))

    def do_POST(self) -> None:
        if self._check_rate_limit():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/grants":
            self._handle_create_grant()
        elif path == "/webhooks":
            self._handle_create_webhook()
        else:
            self._error_response(ERR_NOT_FOUND("endpoint"))

    def do_DELETE(self) -> None:
        if self._check_rate_limit():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith("/grants/"):
            grant_id = path[len("/grants/"):]
            self._handle_revoke_grant(grant_id)
        elif path.startswith("/webhooks/"):
            webhook_id = path[len("/webhooks/"):]
            self._handle_delete_webhook(webhook_id)
        else:
            self._error_response(ERR_NOT_FOUND("endpoint"))

    def do_OPTIONS(self) -> None:
        self._respond(204, "text/plain", b"", extra_headers={
            "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
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
            error = ERR_RATE_LIMITED()
            body = json.dumps(error.to_dict(), default=str).encode("utf-8")
            self._respond(error.http_status, "application/json", body, extra_headers={
                "Retry-After": str(limiter.window),
            })
            return True
        return False

    # ── Auth helpers ─────────────────────────────────────────────────

    def _authenticate(self, required_scope: str = "") -> dict | None:
        """Authenticate request via Bearer token. Returns token_data or None (sends error)."""
        from cortex.upai.tokens import GrantToken

        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._audit("auth.failed", {"reason": "missing_or_malformed_header"})
            self._error_response(ERR_INVALID_TOKEN("Missing or malformed Authorization header"))
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
            self._error_response(ERR_INSUFFICIENT_SCOPE(required_scope))
            return None

        return token.to_dict()

    # ── Audit helper ─────────────────────────────────────────────────

    def _audit(self, event_type: str, details: dict | None = None) -> None:
        """Log an audit event if audit_log is configured."""
        log = self.__class__.audit_log
        if log is not None:
            log.log(event_type, details)

    # ── Webhook fire helper ──────────────────────────────────────────

    def _fire_webhook(self, event: str, data: dict) -> None:
        """Enqueue a webhook event for delivery if worker is configured."""
        worker = self.__class__.webhook_worker
        if worker is not None:
            worker.enqueue(event, data)

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

    # ── Info / Discovery ─────────────────────────────────────────────

    def _serve_info(self) -> None:
        identity = self.__class__.identity
        self._json_response({
            "service": "UPAI Context-as-a-Service",
            "version": "1.0.0",
            "upai_version": "1.0",
            "did": identity.did if identity else None,
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
            },
            "supported_policies": list(BUILTIN_POLICIES.keys()),
            "supported_scopes": [
                "context:read", "context:subscribe",
                "versions:read", "identity:read",
            ],
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
        from cortex.upai.tokens import GrantToken

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
        ttl_hours = body.get("ttl_hours", 24)

        if not audience:
            self._error_response(ERR_INVALID_REQUEST("'audience' is required"))
            return

        # Validate audience length
        if len(audience) > 256:
            self._error_response(ERR_INVALID_REQUEST("'audience' must be at most 256 characters"))
            return

        if policy not in BUILTIN_POLICIES:
            self._error_response(ERR_INVALID_POLICY(policy))
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
        token_str = token.sign(identity)

        self.__class__.grant_store.add(token.grant_id, token_str, token.to_dict())
        self._audit("grant.created", {"grant_id": token.grant_id, "audience": audience, "policy": policy})
        self._fire_webhook("grant.created", {"grant_id": token.grant_id, "audience": audience, "policy": policy})

        self._json_response({
            "grant_id": token.grant_id,
            "token": token_str,
            "expires_at": token.expires_at,
            "policy": token.policy,
            "scopes": token.scopes,
        }, status=201)

    def _serve_list_grants(self) -> None:
        grants = self.__class__.grant_store.list_all()
        self._json_response({"grants": grants})

    def _handle_revoke_grant(self, grant_id: str) -> None:
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
        token_data = self._authenticate("context:read")
        if token_data is None:
            return

        graph = self.__class__.graph
        identity = self.__class__.identity
        if graph is None or identity is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        policy_name = self._get_policy_for_token(token_data)
        policy = BUILTIN_POLICIES.get(policy_name, BUILTIN_POLICIES["professional"])
        filtered = apply_disclosure(graph, policy)
        data = filtered.export_v5()

        self._json_response(data)

    def _serve_context_compact(self, query: dict) -> None:
        token_data = self._authenticate("context:read")
        if token_data is None:
            return

        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        policy_name = self._get_policy_for_token(token_data)
        policy = BUILTIN_POLICIES.get(policy_name, BUILTIN_POLICIES["professional"])
        filtered = apply_disclosure(graph, policy)

        lines = []
        for node in filtered.nodes.values():
            tags = ", ".join(node.tags) if node.tags else "untagged"
            lines.append(f"- **{node.label}** ({tags}, {node.confidence:.0%}): {node.brief}")

        self._respond(200, "text/markdown; charset=utf-8", "\n".join(lines).encode("utf-8"))

    def _serve_context_nodes(self, query: dict) -> None:
        token_data = self._authenticate("context:read")
        if token_data is None:
            return

        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        policy_name = self._get_policy_for_token(token_data)
        policy = BUILTIN_POLICIES.get(policy_name, BUILTIN_POLICIES["professional"])
        filtered = apply_disclosure(graph, policy)

        items = [n.to_dict() for n in filtered.nodes.values()]
        items.sort(key=lambda x: x.get("id", ""))

        limit = int(query.get("limit", ["20"])[0])
        cursor = query.get("cursor", [None])[0]
        page = paginate(items, limit=limit, cursor=cursor)
        self._json_response(page.to_dict())

    def _serve_context_node(self, node_id: str, query: dict) -> None:
        token_data = self._authenticate("context:read")
        if token_data is None:
            return

        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        policy_name = self._get_policy_for_token(token_data)
        policy = BUILTIN_POLICIES.get(policy_name, BUILTIN_POLICIES["professional"])
        filtered = apply_disclosure(graph, policy)

        node = filtered.nodes.get(node_id)
        if node is None:
            self._error_response(ERR_NOT_FOUND("node"))
            return

        self._json_response(node.to_dict())

    def _serve_context_edges(self, query: dict) -> None:
        token_data = self._authenticate("context:read")
        if token_data is None:
            return

        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        policy_name = self._get_policy_for_token(token_data)
        policy = BUILTIN_POLICIES.get(policy_name, BUILTIN_POLICIES["professional"])
        filtered = apply_disclosure(graph, policy)

        items = [e.to_dict() for e in filtered.edges.values()]
        items.sort(key=lambda x: x.get("id", ""))

        limit = int(query.get("limit", ["20"])[0])
        cursor = query.get("cursor", [None])[0]
        page = paginate(items, limit=limit, cursor=cursor)
        self._json_response(page.to_dict())

    def _serve_context_stats(self, query: dict) -> None:
        token_data = self._authenticate("context:read")
        if token_data is None:
            return

        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        self._json_response(graph.stats())

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

        try:
            from cortex.upai.webhooks import create_webhook, VALID_EVENTS
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
        if self.__class__.webhook_store.delete(webhook_id):
            self._audit("webhook.deleted", {"webhook_id": webhook_id})
            self._json_response({"deleted": True, "webhook_id": webhook_id})
        else:
            self._error_response(ERR_NOT_FOUND("webhook"))

    # ── Response helpers ─────────────────────────────────────────────

    def _read_body(self) -> dict | None:
        """Read and parse JSON request body. Returns None and sends error on failure."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._error_response(ERR_INVALID_REQUEST("Empty request body"))
            return None
        if content_length > MAX_BODY_SIZE:
            self._respond(413, "application/json", json.dumps({
                "error": {"code": "UPAI-4004", "type": "invalid_request",
                          "message": "Request body too large", "details": {}}
            }).encode("utf-8"))
            return None
        try:
            raw = self.rfile.read(content_length)
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self._error_response(ERR_INVALID_REQUEST("Invalid JSON"))
            return None

    def _json_response(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self._respond(status, "application/json", body)

    def _error_response(self, error: UPAIError) -> None:
        body = json.dumps(error.to_dict(), default=str).encode("utf-8")
        self._respond(error.http_status, "application/json", body)

    def _respond(
        self,
        code: int,
        content_type: str,
        body: bytes,
        extra_headers: dict[str, str] | None = None,
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

        # Security headers
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'")

        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)

        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress noisy request logging."""
        pass


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
) -> ThreadingHTTPServer:
    """Start the CaaS API server. Returns the server instance (call serve_forever())."""
    CaaSHandler.graph = graph
    CaaSHandler.identity = identity
    CaaSHandler.version_store = version_store
    CaaSHandler.nonce_cache = NonceCache()

    if storage_backend == "sqlite" and db_path:
        from cortex.caas.sqlite_store import SqliteGrantStore, SqliteWebhookStore, SqliteAuditLog, SqliteDeliveryLog
        CaaSHandler.grant_store = SqliteGrantStore(db_path)
        webhook_store = SqliteWebhookStore(db_path)
        CaaSHandler.webhook_store = webhook_store
        CaaSHandler.audit_log = SqliteAuditLog(db_path)
        delivery_log = SqliteDeliveryLog(db_path)
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

    if allowed_origins:
        CaaSHandler._allowed_origins = allowed_origins
    else:
        CaaSHandler._allowed_origins = {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        }

    server = ThreadingHTTPServer(("127.0.0.1", port), CaaSHandler)
    return server
