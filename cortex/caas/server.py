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
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import TYPE_CHECKING, Any

from cortex.caas.caching import check_if_none_match, generate_etag, get_cache_profile
from cortex.caas.correlation import parse_request_id
from cortex.caas.dashboard.auth import DashboardSessionManager
from cortex.caas.dashboard.static import guess_content_type, resolve_dashboard_path
from cortex.caas.storage import (
    AbstractAuditLog,
    AbstractConnectorStore,
    AbstractGrantStore,
    AbstractWebhookStore,
    JsonConnectorStore,
    JsonWebhookStore,
)
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

# Multi-user authentication imports (optional, graceful fallback if not available)
try:
    from cortex.caas.users import (
        LoginRequest,
        MultiUserSessionManager,
        SignupRequest,
        SqliteUserStore,
        User,
        UserGraphResolver,
    )
    _MULTI_USER_AVAILABLE = True
except ImportError:
    _MULTI_USER_AVAILABLE = False

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
                token_data = g.get("token_data", {})
                result.append({
                    "grant_id": gid,
                    "audience": token_data.get("audience", ""),
                    "policy": token_data.get("policy", ""),
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
# Connector auto-sync worker
# ---------------------------------------------------------------------------

CONNECTOR_AUTO_SYNC_INTERVAL_SECONDS = 24 * 60 * 60  # 24h
CONNECTOR_AUTO_SYNC_POLL_SECONDS = 60  # scheduler loop


def _parse_iso_ts(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


class ConnectorAutoSyncWorker:
    """Background worker that auto-runs due connector jobs."""

    def __init__(
        self,
        connector_store: AbstractConnectorStore,
        graph_getter: Any,
        context_path_getter: Any,
    ) -> None:
        self._connector_store = connector_store
        self._graph_getter = graph_getter
        self._context_path_getter = context_path_getter
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._logger = None

    def _get_logger(self):
        if self._logger is None:
            import logging
            self._logger = logging.getLogger("caas.connector_autosync")
        return self._logger

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="connector-auto-sync")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        logger = self._get_logger()
        logger.info("connector auto-sync worker started")
        while not self._stop_event.wait(CONNECTOR_AUTO_SYNC_POLL_SECONDS):
            try:
                self._tick()
            except Exception as exc:
                logger.warning("connector auto-sync tick failed: %s", exc)
        logger.info("connector auto-sync worker stopped")

    def _tick(self) -> None:
        from cortex.caas.connectors import ConnectorService

        now = datetime.now(timezone.utc)
        svc = ConnectorService(self._connector_store)
        connectors = svc.list_all()
        for connector in connectors:
            if self._stop_event.is_set():
                return
            if str(connector.get("status", "active")).strip().lower() != "active":
                continue
            metadata = connector.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            if metadata.get("_auto_sync_enabled", True) is False:
                continue

            interval_s = metadata.get("_auto_sync_interval_seconds", CONNECTOR_AUTO_SYNC_INTERVAL_SECONDS)
            try:
                interval_s = int(interval_s)
            except Exception:
                interval_s = CONNECTOR_AUTO_SYNC_INTERVAL_SECONDS
            if interval_s <= 0:
                continue

            last_sync = _parse_iso_ts(connector.get("last_sync_at", ""))
            if last_sync is not None and (now - last_sync).total_seconds() < interval_s:
                continue

            result = self._run_connector_job(connector)
            updated_meta = dict(metadata)
            updated_meta["_last_sync_error"] = ""
            updated_meta["_last_sync_message"] = str(result.get("message", "Auto-sync complete"))
            updated_meta["_last_sync_status"] = "ok"
            if result.get("error"):
                updated_meta["_last_sync_error"] = str(result["error"])
                updated_meta["_last_sync_message"] = "Auto-sync failed."
                updated_meta["_last_sync_status"] = "error"
            svc.update(connector["connector_id"], {
                "metadata": updated_meta,
                "last_sync_at": now.isoformat(),
            })

    def _persist_graph(self, graph: Any) -> None:
        context_path = self._context_path_getter()
        if not context_path:
            return
        try:
            payload = graph.export_v5()
            Path(context_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            # Best effort persistence for auto-sync.
            pass

    def _import_nodes_edges(self, import_result: dict[str, Any]) -> dict[str, Any]:
        from cortex.graph import Edge, Node, make_edge_id, make_node_id

        graph = self._graph_getter()
        if graph is None:
            return {"error": "No graph configured"}

        nodes_created = 0
        edges_created = 0
        tag_set: set[str] = set()
        imported_node_ids: set[str] = set()

        for nd in import_result.get("nodes", []):
            label = nd.get("label", "")
            if not label:
                continue
            node_id = nd.get("id") or make_node_id(label)
            tags = nd.get("tags", [])
            node = Node(
                id=node_id,
                label=label,
                tags=tags,
                confidence=nd.get("confidence", 0.5),
                brief=nd.get("brief", ""),
                properties=nd.get("properties", {}),
                full_description=nd.get("full_description", ""),
            )
            graph.add_node(node)
            imported_node_ids.add(node_id)
            nodes_created += 1
            tag_set.update(str(t).lower() for t in tags)

        for ed in import_result.get("edges", []):
            source_id = ed.get("source_id", "")
            target_id = ed.get("target_id", "")
            relation = ed.get("relation", "related_to")
            if not source_id or not target_id:
                continue
            source_exists = source_id in imported_node_ids or graph.get_node(source_id) is not None
            target_exists = target_id in imported_node_ids or graph.get_node(target_id) is not None
            if not source_exists or not target_exists:
                continue
            edge_id = ed.get("id") or make_edge_id(source_id, target_id, relation)
            edge = Edge(
                id=edge_id,
                source_id=source_id,
                target_id=target_id,
                relation=relation,
                confidence=ed.get("confidence", 0.5),
                properties=ed.get("properties", {}),
            )
            graph.add_edge(edge)
            edges_created += 1

        if nodes_created or edges_created:
            self._persist_graph(graph)
        return {
            "nodes_created": nodes_created,
            "edges_created": edges_created,
            "categories": len(tag_set),
            "source_type": import_result.get("source_type", "connector_auto_sync"),
        }

    def _run_connector_job(self, connector: dict[str, Any]) -> dict[str, Any]:
        metadata = connector.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        job = str(metadata.get("_job", "memory_pull_prompt")).strip().lower()
        job_config = metadata.get("_job_config", {})
        if not isinstance(job_config, dict):
            job_config = {}

        if job == "memory_pull_prompt":
            return {
                "message": "Auto-sync pending manual memory export paste.",
                "action_required": True,
            }

        if job == "github_repo_sync":
            url = str(job_config.get("repo_url") or metadata.get("repo_url") or "").strip()
            token = job_config.get("token") or metadata.get("token") or None
            if not url:
                return {"error": "github_repo_sync requires repo_url in connector job config"}
            from cortex.caas.importers import fetch_github_repo
            import_result = fetch_github_repo(url, token=token)
            if "error" in import_result and not import_result.get("nodes"):
                return {"error": str(import_result["error"])}
            result = self._import_nodes_edges(import_result)
            if result.get("error"):
                return result
            result["message"] = "Auto-synced GitHub repository."
            return result

        if job == "custom_json_sync":
            url = str(job_config.get("url") or "").strip()
            if not url:
                return {"error": "custom_json_sync requires url in connector job config"}
            headers = job_config.get("headers", {})
            if not isinstance(headers, dict):
                headers = {}
            req = urllib.request.Request(url, headers={str(k): str(v) for k, v in headers.items()}, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    payload = resp.read()
            except Exception as exc:
                return {"error": f"custom_json_sync fetch failed: {exc}"}
            try:
                parsed = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                return {"error": "custom_json_sync endpoint returned invalid JSON"}

            if isinstance(parsed, dict) and ("nodes" in parsed or "edges" in parsed):
                parsed.setdefault("source_type", "custom_json_sync")
                result = self._import_nodes_edges(parsed)
            else:
                return {"error": "custom_json_sync currently requires graph-style nodes/edges JSON"}

            if result.get("error"):
                return result
            result["message"] = "Auto-synced custom JSON source."
            return result

        return {"error": f"Unsupported connector job: {job}"}


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
    login_rate_limiter: Any = None  # Stricter rate limiter for dashboard login
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
    hsts_enabled: bool = False  # Add Strict-Transport-Security header
    enable_webapp: bool = False  # Enable /app web UI
    token_cache: Any = None  # Optional TokenCache for verified token caching
    api_key_store: Any = None  # Optional ApiKeyStore for shareable memory
    profile_store: Any = None  # Optional ProfileStore for public profiles
    connector_store: AbstractConnectorStore | None = None  # External connector store
    connector_auto_sync_worker: Any = None  # Optional ConnectorAutoSyncWorker
    store_dir: str | None = None  # Storage directory for data files
    context_path: str | None = None  # Path to context.json for persistence

    # Multi-user authentication
    multi_user_enabled: bool = False  # Enable multi-user mode
    multi_user_session_manager: Any = None  # MultiUserSessionManager instance
    user_graph_resolver: Any = None  # UserGraphResolver for per-user graphs
    user_store: Any = None  # SqliteUserStore for user data
    registration_open: bool = True  # Allow new user signups
    default_user_quota: int = 5_368_709_120  # 5GB default
    max_upload_bytes: int = 3_221_225_472  # 3GB max upload
    storage_modes: list[str] = ["local", "byos"]  # Supported user storage modes
    default_storage_mode: str = "local"  # Default storage mode shown in UI

    _request_id: str = ""
    _current_user: Any = None  # Set during request processing for multi-user
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

    def _validate_path_id(self, value: str, id_type: str = "path_param") -> bool:
        """Validate a path-extracted ID. Returns True if valid, else sends 400 and returns False."""
        from cortex.caas.validation import validate_path_param
        # URL-decode before validation to catch encoded attacks (%00, %2F, etc.)
        decoded = urllib.parse.unquote(value)
        ok, msg = validate_path_param(decoded)
        if not ok:
            self._json_response({"error": {"type": "invalid_request", "message": msg}}, status=400)
            return False
        return True

    def _parse_int_param(
        self, query: dict, name: str, default: int, min_val: int = 0, max_val: int = 10000
    ) -> int | None:
        """Parse an integer query parameter safely. Returns None and sends 400 on error."""
        raw = query.get(name, [str(default)])[0]
        try:
            value = int(raw)
            if value < min_val or value > max_val:
                self._error_response(ERR_INVALID_REQUEST(
                    f"{name} must be between {min_val} and {max_val}"
                ))
                return None
            return value
        except (ValueError, TypeError):
            self._error_response(ERR_INVALID_REQUEST(f"{name} must be an integer"))
            return None

    def _parse_content_length(self) -> int | None:
        """Parse Content-Length header safely. Returns None and sends 400 on error."""
        raw = self.headers.get("Content-Length", "0")
        try:
            length = int(raw)
            if length < 0:
                self._error_response(ERR_INVALID_REQUEST("Content-Length must be non-negative"))
                return None
            return length
        except (ValueError, TypeError):
            self._error_response(ERR_INVALID_REQUEST("Invalid Content-Length header"))
            return None

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
        elif path == "/readyz":
            self._serve_readyz()
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
            if self._validate_path_id(node_id):
                self._serve_node_neighbors(node_id, query)
        elif path.startswith("/context/nodes/"):
            node_id = path[len("/context/nodes/"):]
            if self._validate_path_id(node_id):
                self._serve_context_node(node_id, query)
        elif path == "/versions":
            self._serve_versions(query)
        elif path == "/versions/diff":
            self._serve_version_diff(query)
        elif path.startswith("/versions/"):
            version_id = path[len("/versions/"):]
            if self._validate_path_id(version_id):
                self._serve_version(version_id, query)
        elif path == "/webhooks":
            self._serve_list_webhooks()
        elif path == "/credentials":
            self._serve_credentials(query)
        elif path.startswith("/credentials/"):
            cred_id = path[len("/credentials/"):]
            if self._validate_path_id(cred_id):
                self._serve_credential_detail(cred_id)
        elif path == "/policies":
            self._serve_list_policies()
        elif path.startswith("/policies/"):
            policy_name = path[len("/policies/"):]
            if self._validate_path_id(policy_name):
                self._serve_get_policy(policy_name)
        elif path.startswith("/resolve/"):
            did_encoded = path[len("/resolve/"):]
            if self._validate_path_id(did_encoded):
                self._serve_resolve_did(did_encoded)
        elif path == "/audit":
            self._serve_audit(query)
        elif path == "/audit/verify":
            self._serve_audit_verify()
        elif path == "/audit/export":
            self._serve_audit_export(query)
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
        elif path == "/api/profiles":
            self._handle_list_profiles()
        elif path == "/api/profile/auto":
            self._handle_auto_profile()
        elif path == "/api/profile/preview":
            self._handle_profile_preview()
        elif path == "/api/profile/qr":
            self._handle_profile_qr(query)
        elif path.startswith("/p/"):
            handle = path[len("/p/"):]
            if self._validate_path_id(handle):
                self._serve_profile_page(handle)
        # ── Attestation routes ─────────────────────────────────
        elif path == "/api/attestations":
            self._handle_list_attestations()
        elif path.startswith("/api/attestations/"):
            node_id = path[len("/api/attestations/"):]
            if self._validate_path_id(node_id):
                self._handle_get_attestations_for_node(node_id)
        # ── Timeline routes ────────────────────────────────────
        elif path == "/api/timeline":
            self._handle_get_timeline()
        elif path.startswith("/api/timeline/"):
            tid = path[len("/api/timeline/"):]
            if self._validate_path_id(tid):
                self._handle_get_timeline_node(tid)
        # ── API key routes ──────────────────────────────────────
        elif path == "/api/keys":
            self._handle_list_api_keys()
        # ── Connector routes ────────────────────────────────────
        elif path == "/api/connectors":
            self._handle_list_connectors()
        elif path == "/api/connectors/capabilities":
            self._handle_get_connector_capabilities()
        elif path.startswith("/api/connectors/"):
            connector_id = path[len("/api/connectors/"):]
            if self._validate_path_id(connector_id):
                self._handle_get_connector(connector_id)
        elif path == "/api/storage/preferences":
            self._handle_get_storage_preferences()
        elif path.startswith("/api/memory/"):
            self._handle_public_memory(path, query)
        elif path.startswith("/api/resume/"):
            self._handle_public_resume(path)
        # ── Multi-user routes ─────────────────────────────────────
        elif path == "/api/me":
            self._handle_get_current_user()
        elif path == "/api/users/config":
            self._handle_get_users_config()
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
            if self._validate_path_id(cred_id):
                self._handle_verify_credential(cred_id)
        elif path == "/policies":
            self._handle_create_policy()
        elif path == "/api/token-exchange":
            self._handle_token_exchange()
        elif path == "/api/upload":
            self._handle_webapp_upload()
        elif path == "/api/import/github":
            self._handle_github_import()
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
        elif path.startswith("/api/connectors/") and path.endswith("/sync"):
            connector_id = path[len("/api/connectors/"):-len("/sync")]
            if self._validate_path_id(connector_id):
                self._handle_sync_connector(connector_id)
        elif path == "/api/storage/preferences/check":
            self._handle_check_storage_preferences()
        elif path == "/api/connectors":
            self._handle_create_connector()
        # ── Webapp auth routes ────────────────────────────────────
        elif path == "/app/auth":
            self._handle_webapp_login()
        elif path == "/app/logout":
            self._handle_webapp_logout()
        # ── Multi-user auth routes ────────────────────────────────
        elif path == "/api/signup":
            self._handle_user_signup()
        elif path == "/api/login":
            self._handle_user_login()
        elif path == "/api/logout":
            self._handle_user_logout()
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
            if self._validate_path_id(grant_id):
                self._handle_revoke_grant(grant_id)
        elif path.startswith("/context/nodes/"):
            node_id = path[len("/context/nodes/"):]
            if self._validate_path_id(node_id):
                self._handle_delete_node(node_id)
        elif path.startswith("/context/edges/"):
            edge_id = path[len("/context/edges/"):]
            if self._validate_path_id(edge_id):
                self._handle_delete_edge(edge_id)
        elif path.startswith("/webhooks/"):
            webhook_id = path[len("/webhooks/"):]
            if self._validate_path_id(webhook_id):
                self._handle_delete_webhook(webhook_id)
        elif path.startswith("/credentials/"):
            cred_id = path[len("/credentials/"):]
            if self._validate_path_id(cred_id):
                self._handle_delete_credential(cred_id)
        elif path.startswith("/policies/"):
            policy_name = path[len("/policies/"):]
            if self._validate_path_id(policy_name):
                self._handle_delete_policy(policy_name)
        elif path == "/api/profile":
            self._handle_delete_profile()
        elif path.startswith("/api/attestations/"):
            cred_id = path[len("/api/attestations/"):]
            if self._validate_path_id(cred_id):
                self._handle_delete_attestation(cred_id)
        elif path.startswith("/api/timeline/"):
            node_id = path[len("/api/timeline/"):]
            if self._validate_path_id(node_id):
                self._handle_delete_timeline_entry(node_id)
        elif path.startswith("/api/keys/"):
            key_id = path[len("/api/keys/"):]
            if self._validate_path_id(key_id):
                self._handle_revoke_api_key(key_id)
        elif path.startswith("/api/connectors/"):
            connector_id = path[len("/api/connectors/"):]
            if self._validate_path_id(connector_id):
                self._handle_delete_connector(connector_id)
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
            if self._validate_path_id(node_id):
                self._handle_update_timeline_entry(node_id)
        elif path.startswith("/context/nodes/"):
            node_id = path[len("/context/nodes/"):]
            if self._validate_path_id(node_id):
                self._handle_update_node(node_id)
        elif path.startswith("/policies/"):
            policy_name = path[len("/policies/"):]
            if self._validate_path_id(policy_name):
                self._handle_update_policy(policy_name)
        elif path.startswith("/api/connectors/"):
            connector_id = path[len("/api/connectors/"):]
            if self._validate_path_id(connector_id):
                self._handle_update_connector(connector_id)
        elif path == "/api/storage/preferences":
            self._handle_update_storage_preferences()
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
        client_ip = self.client_address[0] if self.client_address else "unknown"

        # Support both plain RateLimiter and TieredRateLimiter
        from cortex.caas.rate_limit import TieredRateLimiter
        if isinstance(limiter, TieredRateLimiter):
            from cortex.caas.rate_limit import classify_tier
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            method = self.command or "GET"
            tier = classify_tier(method, path)
            allowed = limiter.allow(client_ip, tier)
        else:
            allowed = limiter.allow(client_ip)

        if not allowed:
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

        # Try token cache first
        cache = self.__class__.token_cache
        cached_data = cache.get(token_str) if cache is not None else None

        if cached_data is not None:
            token_data = cached_data["token_data"]
            grant_id = cached_data["grant_id"]
            token_obj = cached_data["token"]
        else:
            # In stdlib-only environments we run in HMAC fallback mode where
            # signatures are self-verifiable (via identity secret) but not
            # publicly verifiable from ``public_key_b64`` alone.
            if identity._key_type == "sha256":
                try:
                    token_obj = GrantToken.decode(token_str)
                except Exception:
                    self._audit("auth.failed", {"reason": "malformed token"})
                    self._error_response(ERR_INVALID_TOKEN("malformed token"))
                    return None

                parts = token_str.split(".")
                if len(parts) != 3:
                    self._audit("auth.failed", {"reason": "malformed token"})
                    self._error_response(ERR_INVALID_TOKEN("malformed token"))
                    return None

                signing_input = f"{parts[0]}.{parts[1]}".encode("utf-8")
                import base64
                from cortex.upai.identity import _base64url_decode

                try:
                    sig_b64_standard = base64.b64encode(
                        _base64url_decode(parts[2])
                    ).decode("ascii")
                except Exception:
                    self._audit("auth.failed", {"reason": "malformed signature"})
                    self._error_response(ERR_INVALID_TOKEN("malformed token signature"))
                    return None

                if not identity.verify_own(signing_input, sig_b64_standard):
                    self._audit("auth.failed", {"reason": "invalid signature"})
                    self._error_response(ERR_INVALID_TOKEN("invalid signature"))
                    return None

                if token_obj.is_expired():
                    self._audit("auth.failed", {"reason": "token expired"})
                    self._error_response(ERR_INVALID_TOKEN("token expired"))
                    return None

                if token_obj.not_before:
                    try:
                        nbf = datetime.fromisoformat(token_obj.not_before)
                    except ValueError:
                        self._audit("auth.failed", {"reason": "invalid not_before timestamp"})
                        self._error_response(ERR_INVALID_TOKEN("invalid not_before timestamp"))
                        return None
                    now = datetime.now(timezone.utc)
                    if now.timestamp() < nbf.timestamp() - 60:
                        self._audit("auth.failed", {"reason": "token not yet valid"})
                        self._error_response(ERR_INVALID_TOKEN("token not yet valid"))
                        return None
                token_data = token_obj.to_dict()
                grant_id = token_obj.grant_id
            else:
                token_obj, err = GrantToken.verify_and_decode(
                    token_str, identity.public_key_b64
                )
                if token_obj is None:
                    self._audit("auth.failed", {"reason": err})
                    self._error_response(ERR_INVALID_TOKEN(err))
                    return None
                token_data = token_obj.to_dict()
                grant_id = token_obj.grant_id
            # Cache the verified result
            if cache is not None:
                cache.put(token_str, {
                    "token_data": token_data,
                    "grant_id": grant_id,
                    "token": token_obj,
                })

        # Check grant not revoked (always, even for cached tokens)
        grant_info = self.__class__.grant_store.get(grant_id)
        if grant_info and grant_info.get("revoked"):
            self._audit("auth.failed", {"reason": "grant_revoked", "grant_id": grant_id})
            if cache is not None:
                cache.invalidate(token_str)
            self._error_response(ERR_INVALID_TOKEN("Grant has been revoked"))
            return None

        # Check scope
        if required_scope and not token_obj.has_scope(required_scope):
            err = ERR_INSUFFICIENT_SCOPE(required_scope)
            from cortex.upai.error_hints import hint_for_insufficient_scope
            err.hint = hint_for_insufficient_scope(required_scope)
            self._error_response(err)
            return None

        return token_data

    def _authenticate_or_dashboard(self, required_scope: str = "") -> dict | None:
        """Authenticate via Bearer token, webapp session cookie, or dashboard session.

        For routes that accept either. Returns token_data dict (or synthetic
        owner dict for dashboard/webapp sessions), or None (error already sent).
        """
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return self._authenticate(required_scope)

        cookie_header = self.headers.get("Cookie", "")

        # Check multi-user session cookie (cortex_user_session)
        if self.__class__.multi_user_enabled and _MULTI_USER_AVAILABLE:
            mu_sm = self.__class__.multi_user_session_manager
            if mu_sm is not None:
                for part in cookie_header.split(";"):
                    part = part.strip()
                    if part.startswith("cortex_user_session="):
                        token = part[len("cortex_user_session="):]
                        if token and mu_sm.validate_user_session(token) is not None:
                            return {
                                "_user_session": True,
                                "scopes": list(VALID_SCOPES),
                                "policy": "full",
                            }
                        break

        sm = self.__class__.session_manager

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
            "version": "1.4.0",
            "has_identity": identity is not None,
            "has_graph": graph is not None,
            "grant_count": grant_count,
        })

    # ── Readiness probe ─────────────────────────────────────────────

    def _serve_readyz(self) -> None:
        """Kubernetes readiness probe — verifies storage and identity."""
        reasons = []
        if self.__class__.identity is None:
            reasons.append("identity not loaded")
        try:
            self.__class__.grant_store.list_all()
        except Exception as exc:
            reasons.append(f"storage error: {exc}")
        if reasons:
            self._json_response(
                {"status": "not_ready", "reasons": reasons}, status=503,
            )
        else:
            self._json_response({"status": "ready"})

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
            "version": "1.4.0",
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
        if token_data.get("_webapp") or token_data.get("_dashboard") or token_data.get("_user_session"):
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

        if token_data.get("_webapp") or token_data.get("_dashboard") or token_data.get("_user_session"):
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

        limit = self._parse_int_param(query, "limit", 20, min_val=1, max_val=1000)
        if limit is None:
            return
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

        limit = self._parse_int_param(query, "limit", 20, min_val=1, max_val=1000)
        if limit is None:
            return
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

        limit = self._parse_int_param(query, "limit", 20, min_val=1, max_val=100)
        if limit is None:
            return
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
        limit = self._parse_int_param(query, "limit", 50, min_val=1, max_val=1000)
        if limit is None:
            return
        offset = self._parse_int_param(query, "offset", 0, min_val=0, max_val=100000)
        if offset is None:
            return

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

    def _serve_audit_export(self, query: dict) -> None:
        """GET /audit/export — export audit log as JSON or CSV. Requires grants:manage."""
        token_data = self._authenticate_or_dashboard("grants:manage")
        if token_data is None:
            return

        log = self.__class__.audit_log
        if log is None or not hasattr(log, 'query'):
            self._json_response({"entries": []})
            return

        from cortex.caas.audit_export import export_csv, export_json, filter_since, parse_since

        fmt = query.get("format", ["json"])[0]
        if fmt not in ("json", "csv"):
            self._json_response(
                {"error": {"type": "invalid_request", "message": "format must be 'json' or 'csv'"}},
                status=400,
            )
            return

        event_type = query.get("event_type", [None])[0]
        # Fetch all matching entries (up to 10k for export)
        entries_raw = log.query(event_type=event_type, limit=10000)
        entries = [e.to_dict() if hasattr(e, 'to_dict') else e for e in entries_raw]

        # Time filter
        since_str = query.get("since", [None])[0]
        if since_str:
            try:
                since_dt = parse_since(since_str)
                entries = filter_since(entries, since_dt)
            except ValueError as exc:
                self._json_response(
                    {"error": {"type": "invalid_request", "message": str(exc)}},
                    status=400,
                )
                return

        if fmt == "csv":
            body = export_csv(entries).encode("utf-8")
            self._respond(200, "text/csv", body, extra_headers={
                "Content-Disposition": "attachment; filename=audit_export.csv",
            })
        else:
            body = export_json(entries).encode("utf-8")
            self._respond(200, "application/json", body, extra_headers={
                "Content-Disposition": "attachment; filename=audit_export.json",
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

        In single-user mode: requires a valid dashboard/webapp session.
        In multi-user mode: requires a valid user session and checks quota.
        Accepts multipart/form-data with a single 'file' field.
        Parses JSON chat exports to create nodes + edges in the graph.
        """
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return

        # Multi-user or single-user auth
        current_user = None
        if self.__class__.multi_user_enabled and _MULTI_USER_AVAILABLE:
            is_auth, current_user = self._multi_user_auth_check()
            if not is_auth:
                return  # Already sent 401
        else:
            if not self._webapp_or_multiuser_auth_check():
                return

        content_type = self.headers.get("Content-Type", "")
        content_length = self._parse_content_length()
        if content_length is None:
            return

        # Size limit: use configured max or default 3 GB
        max_upload = self.__class__.max_upload_bytes or (3 * 1024 * 1024 * 1024)
        if content_length > max_upload:
            self._error_response(
                ERR_PAYLOAD_TOO_LARGE(
                    "Request payload exceeds configured upload limit",
                    max_upload_bytes=max_upload,
                    received_bytes=content_length,
                )
            )
            return

        # Check user storage quota (only in multi-user mode with a user)
        if current_user is not None:
            if not current_user.can_upload(content_length):
                self._respond(413, "application/json",
                              json.dumps({
                                  "error": {
                                      "type": "quota_exceeded",
                                      "message": "Storage quota exceeded",
                                      "quota": current_user.storage_quota,
                                      "used": current_user.storage_used,
                                  }
                              }).encode())
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

        def _loads_json_bytes(raw: bytes) -> dict | list | None:
            # Try direct bytes parse first.
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

            # Then try common encodings for exported archives.
            for enc in ("utf-8-sig", "utf-16", "utf-16le", "utf-16be", "latin-1"):
                try:
                    txt = raw.decode(enc)
                except Exception:
                    continue
                try:
                    parsed = json.loads(txt)
                    if isinstance(parsed, (dict, list)):
                        return parsed
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
            return None

        def _loads_jsonl_bytes(raw: bytes) -> list | None:
            # Best effort JSONL support (e.g., one JSON object per line).
            for enc in ("utf-8-sig", "utf-16", "utf-16le", "utf-16be", "latin-1"):
                try:
                    txt = raw.decode(enc)
                except Exception:
                    continue
                items = []
                ok = True
                for line in txt.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except (json.JSONDecodeError, ValueError, TypeError):
                        ok = False
                        break
                    items.append(obj)
                if ok and items:
                    return items
            return None

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            # Prefer conversations.json (OpenAI export format)
            for name in names:
                if name.endswith("conversations.json"):
                    parsed = _loads_json_bytes(zf.read(name))
                    if parsed is not None:
                        return parsed
            # Fall back to any .json/.jsonl file
            for name in names:
                lower = name.lower()
                raw = zf.read(name)
                if lower.endswith(".json"):
                    parsed = _loads_json_bytes(raw)
                    if parsed is not None:
                        return parsed
                elif lower.endswith(".jsonl"):
                    parsed_jsonl = _loads_jsonl_bytes(raw)
                    if parsed_jsonl is not None:
                        return parsed_jsonl
        return None

    def _extract_from_upload(self, parsed: dict | list) -> dict:
        """Extract nodes and edges from uploaded data and add to graph."""
        from cortex.graph import Edge, Node, make_edge_id, make_node_id

        graph = self.__class__.graph
        nodes_created = 0
        edges_created = 0
        tag_set = set()

        def _collect_text(value: object) -> str:
            """Best-effort flattening of text-like message payloads."""
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, list):
                parts: list[str] = []
                for item in value:
                    txt = _collect_text(item)
                    if txt:
                        parts.append(txt)
                return " ".join(parts).strip()
            if isinstance(value, dict):
                # Common message carriers across OpenAI/Claude/Gemini exports.
                for key in ("parts", "text", "content", "value"):
                    if key in value:
                        txt = _collect_text(value.get(key))
                        if txt:
                            return txt
            return ""

        def _message_text(msg: object) -> str:
            if isinstance(msg, str):
                return msg.strip()
            if not isinstance(msg, dict):
                return ""
            for key in (
                "content",
                "text",
                "message",
                "body",
                "prompt",
                "response",
                "input",
                "output",
            ):
                if key in msg:
                    txt = _collect_text(msg.get(key))
                    if txt:
                        return txt
            return ""

        def _text_from_openai_mapping(conv: dict) -> list[str]:
            """Extract text chunks from OpenAI export conversations[].mapping."""
            mapping = conv.get("mapping")
            if not isinstance(mapping, dict):
                return []
            out: list[str] = []
            for node in mapping.values():
                if not isinstance(node, dict):
                    continue
                msg = node.get("message")
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content")
                if isinstance(content, dict):
                    parts = content.get("parts")
                    if isinstance(parts, list):
                        joined = " ".join(
                            p.strip() for p in parts
                            if isinstance(p, str) and p.strip()
                        ).strip()
                        if joined:
                            out.append(joined)
                elif isinstance(content, str) and content.strip():
                    out.append(content.strip())
            return out

        def _messages_from_conversation(conv: dict) -> list[dict]:
            out: list[dict] = []
            for key in ("messages", "chat_messages", "turns", "items", "entries"):
                maybe = conv.get(key)
                if isinstance(maybe, list):
                    for msg in maybe:
                        txt = _message_text(msg)
                        if txt:
                            out.append({"content": txt})
            for txt in _text_from_openai_mapping(conv):
                out.append({"content": txt})
            return out

        # Handle different formats
        items = []
        if isinstance(parsed, list):
            mapping_items: list[dict] = []
            for entry in parsed:
                if isinstance(entry, dict):
                    extracted = _messages_from_conversation(entry)
                    if extracted:
                        mapping_items.extend(extracted)
                    else:
                        txt = _message_text(entry)
                        if txt:
                            mapping_items.append({"content": txt})
                elif isinstance(entry, str) and entry.strip():
                    mapping_items.append({"content": entry.strip()})
            items = mapping_items if mapping_items else parsed
        elif isinstance(parsed, dict):
            # Common chat export formats
            if "messages" in parsed:
                items = parsed["messages"]
            elif "chat_messages" in parsed and isinstance(parsed["chat_messages"], list):
                items = parsed["chat_messages"]
            elif "turns" in parsed and isinstance(parsed["turns"], list):
                items = parsed["turns"]
            elif "conversations" in parsed:
                convs = parsed["conversations"]
                if isinstance(convs, list):
                    for conv in convs:
                        if isinstance(conv, dict):
                            extracted = _messages_from_conversation(conv)
                            if extracted:
                                items.extend(extracted)
                            elif isinstance(conv.get("messages"), list):
                                items.extend(conv["messages"])
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
                content = _message_text(msg)

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
        if graph is None:
            return {
                "nodes_created": 0,
                "edges_created": 0,
                "categories": 0,
                "source_type": import_result.get("source_type", "import"),
                "error": "No graph configured",
            }

        nodes_created = 0
        edges_created = 0
        edges_skipped = 0
        tag_set: set[str] = set()
        imported_node_ids: set[str] = set()

        for nd in import_result.get("nodes", []):
            label = nd.get("label", "")
            if not label:
                continue
            node_id = nd.get("id") or make_node_id(label)
            tags = nd.get("tags", [])
            properties = nd.get("properties", {})
            node = Node(
                id=node_id, label=label, tags=tags,
                confidence=nd.get("confidence", 0.5),
                brief=nd.get("brief", ""),
                properties=properties,
                full_description=nd.get("full_description", ""),
            )
            graph.add_node(node)
            imported_node_ids.add(node_id)
            nodes_created += 1
            tag_set.update(t.lower() for t in tags)

        for ed in import_result.get("edges", []):
            source_id = ed.get("source_id", "")
            target_id = ed.get("target_id", "")
            relation = ed.get("relation", "related_to")
            if source_id and target_id:
                # Validate that both source and target nodes exist
                source_exists = source_id in imported_node_ids or graph.get_node(source_id) is not None
                target_exists = target_id in imported_node_ids or graph.get_node(target_id) is not None
                if not source_exists or not target_exists:
                    edges_skipped += 1
                    continue

                edge_id = ed.get("id") or make_edge_id(source_id, target_id, relation)
                edge = Edge(
                    id=edge_id, source_id=source_id,
                    target_id=target_id, relation=relation,
                    confidence=ed.get("confidence", 0.5),
                    properties=ed.get("properties", {}),
                )
                graph.add_edge(edge)
                edges_created += 1

        # Persist the graph to context.json
        import sys
        print(f"[DEBUG _import_nodes_edges] nodes_created={nodes_created}, edges_created={edges_created}", file=sys.stderr, flush=True)
        print(f"[DEBUG _import_nodes_edges] graph id={id(graph)}, nodes={len(graph.nodes)}, edges={len(graph.edges)}", file=sys.stderr, flush=True)
        if nodes_created > 0 or edges_created > 0:
            print(f"[DEBUG _import_nodes_edges] Calling _save_graph()", file=sys.stderr, flush=True)
            self._save_graph()

        result = {
            "nodes_created": nodes_created,
            "edges_created": edges_created,
            "categories": len(tag_set),
            "source_type": import_result.get("source_type", "import"),
        }
        if edges_skipped > 0:
            result["edges_skipped"] = edges_skipped
        return result

    def _save_graph(self) -> None:
        """Persist the current graph to context.json."""
        import sys
        graph = self.__class__.graph
        context_path = self.__class__.context_path
        print(f"[DEBUG _save_graph] graph id={id(graph) if graph else None}, context_path={context_path}", file=sys.stderr, flush=True)
        print(f"[DEBUG _save_graph] graph.nodes count={len(graph.nodes) if graph else 0}", file=sys.stderr, flush=True)
        if graph is None or context_path is None:
            print(f"[DEBUG _save_graph] Skipping save: graph or context_path is None", file=sys.stderr, flush=True)
            return
        try:
            graph_data = graph.export_v5()
            node_count = len(graph_data.get("nodes", []))
            edge_count = len(graph_data.get("edges", []))
            print(f"[DEBUG _save_graph] Saving {node_count} nodes, {edge_count} edges to {context_path}", file=sys.stderr, flush=True)
            storage_prefs = self._get_storage_preferences_for_request()
            mode = str(storage_prefs.get("mode", "local")).strip().lower()
            graph_json = json.dumps(graph_data, indent=2)

            if mode == "byos":
                byos_location = str(storage_prefs.get("byos_location", "")).strip()
                parsed = urllib.parse.urlparse(byos_location)
                mirrored = False
                if parsed.scheme in {"http", "https"}:
                    req = urllib.request.Request(
                        byos_location,
                        data=graph_json.encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="PUT",
                    )
                    with urllib.request.urlopen(req, timeout=12):
                        mirrored = True
                elif parsed.scheme == "file" or byos_location.startswith("/"):
                    target = Path(parsed.path if parsed.scheme == "file" else byos_location)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(graph_json, encoding="utf-8")
                    mirrored = True

                if mirrored:
                    print(f"[DEBUG _save_graph] BYOS write successful ({byos_location})", file=sys.stderr, flush=True)
                else:
                    # Fallback for unsupported BYOS schemes until provider-specific SDKs are configured.
                    Path(context_path).write_text(graph_json, encoding="utf-8")
                    print("[DEBUG _save_graph] BYOS scheme unsupported for direct write; used local fallback", file=sys.stderr, flush=True)
            else:
                Path(context_path).write_text(graph_json, encoding="utf-8")
            print(f"[DEBUG _save_graph] Successfully saved to {context_path}", file=sys.stderr, flush=True)
        except (OSError, IOError) as e:
            print(f"[DEBUG _save_graph] Save failed: {e}", file=sys.stderr, flush=True)
            pass  # Best effort — don't fail the request if save fails
        except Exception as e:
            print(f"[DEBUG _save_graph] Save failed: {e}", file=sys.stderr, flush=True)
            pass

    # ── GitHub import endpoint ────────────────────────────────────────

    def _handle_github_import(self) -> None:
        """POST /api/import/github — import a GitHub repository."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return

        # Support both multi-user and single-user auth
        if self.__class__.multi_user_enabled and _MULTI_USER_AVAILABLE:
            is_auth, _ = self._multi_user_auth_check()
            if not is_auth:
                return
        else:
            if not self._webapp_or_multiuser_auth_check():
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
        if result.get("error"):
            self._error_response(ERR_NOT_CONFIGURED(result["error"]))
            return
        self._json_response(result, status=201)

    # ── Profile endpoints ─────────────────────────────────────────────

    def _get_profile_store(self):
        """Lazy-init the profile store."""
        if self.__class__.profile_store is None:
            from cortex.caas.profile import ProfileStore
            base_dir = self._get_store_base_dir()
            store_path = base_dir / "profiles.json"
            self.__class__.profile_store = ProfileStore(store_path)
        return self.__class__.profile_store

    def _get_store_base_dir(self) -> Path:
        """Resolve a writable storage directory for profile/key metadata."""
        if self.__class__.store_dir:
            base = Path(self.__class__.store_dir)
            base.mkdir(parents=True, exist_ok=True)
            return base

        # In container deployments, /data is writable and persisted.
        # Fall back to local .cortex for non-container/dev usage.
        for candidate in (Path("/data/.cortex"), Path(".cortex")):
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except OSError:
                continue

        # Last resort: current working directory (non-persistent).
        return Path(".")

    def _storage_preferences_path(self) -> Path:
        return self._get_store_base_dir() / "storage_prefs.json"

    def _storage_actor_key(self) -> str:
        user = self._get_current_user()
        if user is not None and getattr(user, "user_id", ""):
            return f"user:{user.user_id}"
        return "admin:default"

    def _load_storage_preferences_all(self) -> dict[str, dict[str, Any]]:
        path = self._storage_preferences_path()
        try:
            if not path.exists():
                return {}
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {}
            out: dict[str, dict[str, Any]] = {}
            for key, value in raw.items():
                if isinstance(value, dict):
                    out[str(key)] = dict(value)
            return out
        except Exception:
            return {}

    def _save_storage_preferences_all(self, data: dict[str, dict[str, Any]]) -> None:
        path = self._storage_preferences_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _validate_storage_preferences(self, payload: dict[str, Any]) -> tuple[bool, str]:
        mode = str(payload.get("mode", "")).strip().lower()
        if mode not in {"local", "byos"}:
            return False, "mode must be 'local' or 'byos'"
        if mode == "local":
            return True, ""
        provider = str(payload.get("byos_provider", "")).strip()
        location = str(payload.get("byos_location", "")).strip()
        if not provider:
            return False, "byos_provider is required for BYOS mode"
        if not location:
            return False, "byos_location is required for BYOS mode"
        parsed = urllib.parse.urlparse(location)
        if parsed.scheme in {"http", "https", "file"}:
            return True, ""
        if "://" in location:
            scheme = location.split("://", 1)[0].lower()
            if scheme in {"s3", "r2", "gs", "az", "webdav"}:
                return True, ""
        if location.startswith("/"):
            return True, ""
        return False, "Unsupported byos_location format"

    def _try_check_storage_preferences(self, payload: dict[str, Any]) -> dict[str, Any]:
        mode = str(payload.get("mode", "")).strip().lower()
        if mode == "local":
            return {"ok": True, "message": "Local Vault is ready.", "check": "local"}

        location = str(payload.get("byos_location", "")).strip()
        parsed = urllib.parse.urlparse(location)
        if parsed.scheme in {"http", "https"}:
            req = urllib.request.Request(location, method="HEAD")
            with urllib.request.urlopen(req, timeout=8) as resp:
                status = getattr(resp, "status", 200)
            if status >= 400:
                return {"ok": False, "message": f"BYOS endpoint health-check returned {status}", "check": "remote_head"}
            return {"ok": True, "message": "BYOS endpoint is reachable.", "check": "remote_head"}

        if parsed.scheme == "file" or location.startswith("/"):
            target = Path(parsed.path if parsed.scheme == "file" else location)
            target.parent.mkdir(parents=True, exist_ok=True)
            probe = target.with_name(target.name + ".probe")
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return {"ok": True, "message": "BYOS filesystem location is writable.", "check": "filesystem_write"}

        return {
            "ok": True,
            "message": "BYOS location accepted. Runtime write checks depend on provider-specific credentials.",
            "check": "syntax_only",
        }

    def _get_storage_preferences_for_request(self) -> dict[str, Any]:
        all_prefs = self._load_storage_preferences_all()
        actor = self._storage_actor_key()
        prefs = all_prefs.get(actor, {})
        if not isinstance(prefs, dict):
            prefs = {}
        mode = str(prefs.get("mode", self.__class__.default_storage_mode)).strip().lower()
        if mode not in {"local", "byos"}:
            mode = self.__class__.default_storage_mode
        return {
            "mode": mode,
            "byos_provider": str(prefs.get("byos_provider", "")).strip(),
            "byos_location": str(prefs.get("byos_location", "")).strip(),
            "updated_at": str(prefs.get("updated_at", "")).strip(),
        }

    def _handle_get_profile(self) -> None:
        """GET /api/profile — get a profile config. ?handle= for specific, else first."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return

        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        handle = query.get("handle", [None])[0]

        store = self._get_profile_store()

        if handle:
            config = store.get(handle)
            if config:
                self._json_response(config.to_dict())
            else:
                self._error_response(ERR_NOT_FOUND("profile"))
            return

        profiles = store.list_all()
        if profiles:
            self._json_response(profiles[0].to_dict())
        else:
            # No saved profile — return auto-populated suggestion
            graph = self.__class__.graph
            if graph is not None:
                from cortex.caas.profile import auto_populate_profile
                suggestion = auto_populate_profile(graph)
                data = suggestion.to_dict()
                data["_auto"] = True
                self._json_response(data)
            else:
                self._json_response({})

    def _handle_list_profiles(self) -> None:
        """GET /api/profiles — list all profiles."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return
        store = self._get_profile_store()
        profiles = store.list_all()
        self._json_response({
            "profiles": [p.to_dict() for p in profiles],
            "count": len(profiles),
        })

    def _handle_delete_profile(self) -> None:
        """DELETE /api/profile?handle= — delete a profile."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return

        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        handle = query.get("handle", [None])[0]
        if not handle:
            self._error_response(ERR_INVALID_REQUEST("handle query parameter required"))
            return

        store = self._get_profile_store()
        if store.delete(handle):
            self._audit("profile.deleted", {"handle": handle})
            self._json_response({"deleted": handle})
        else:
            self._error_response(ERR_NOT_FOUND("profile"))

    def _handle_profile_qr(self, query: dict) -> None:
        """GET /api/profile/qr?handle= — generate QR code SVG for profile URL."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return

        store = self._get_profile_store()
        handle = query.get("handle", [None])[0]

        if handle:
            config = store.get(handle)
        else:
            profiles = store.list_all()
            config = profiles[0] if profiles else None

        if config is None:
            self._error_response(ERR_NOT_FOUND("profile"))
            return

        # Build profile URL from Host header
        host = self.headers.get("Host", "localhost")
        scheme = "https" if "443" in host else "http"
        url = f"{scheme}://{host}/p/{config.handle}"

        from cortex.caas.qr import generate_qr_svg
        svg = generate_qr_svg(url)
        self._respond(200, "image/svg+xml", svg.encode("utf-8"),
                      extra_headers={"Cache-Control": "public, max-age=3600"})

    def _handle_auto_profile(self) -> None:
        """GET /api/profile/auto — auto-populate profile from graph data."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return

        graph = self.__class__.graph
        if graph is None:
            self._json_response({})
            return

        from cortex.caas.profile import auto_populate_profile
        suggestion = auto_populate_profile(graph)
        data = suggestion.to_dict()
        data["_auto"] = True
        self._json_response(data)

    def _handle_save_profile(self) -> None:
        """POST /api/profile — create or update profile config."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
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
                github_url=body.get("github_url", ""),
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
        if not self._webapp_or_multiuser_auth_check():
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

    # Class-level rate limit state for profile views (handle -> monotonic timestamp)
    _profile_view_rate: dict[str, float] = {}

    def _fire_profile_viewed(self, handle: str, user_agent: str = "") -> None:
        """Fire profile.viewed webhook with 60s per-handle cooldown."""
        now = _time.monotonic()
        rate = self.__class__._profile_view_rate

        # Evict stale entries (> 120s)
        stale = [h for h, t in rate.items() if now - t > 120]
        for h in stale:
            del rate[h]

        last = rate.get(handle)
        if last is not None and now - last < 60:
            return  # cooldown active

        rate[handle] = now
        self._fire_webhook("profile.viewed", {
            "handle": handle,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_agent": user_agent,
        })

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

        # Capture user-agent before responding (getattr for test safety)
        headers = getattr(self, "headers", None)
        user_agent = headers.get("User-Agent", "") if headers else ""

        filtered = get_disclosed_graph(graph, config.policy, config.custom_tags or None)
        page_html = render_profile_html(filtered, config, self.__class__.credential_store)
        self._respond(200, "text/html", page_html.encode("utf-8"))

        # Fire profile.viewed webhook (rate-limited)
        self._fire_profile_viewed(handle, user_agent)

    # ── Attestation endpoints ─────────────────────────────────────────

    def _handle_list_attestations(self) -> None:
        """GET /api/attestations — list all attestation credentials."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
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
        if not self._webapp_or_multiuser_auth_check():
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
        if not self._webapp_or_multiuser_auth_check():
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
        if not self._webapp_or_multiuser_auth_check():
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
        if not self._webapp_or_multiuser_auth_check():
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
        if not self._webapp_or_multiuser_auth_check():
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
        if not self._webapp_or_multiuser_auth_check():
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
        if not self._webapp_or_multiuser_auth_check():
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

    def _get_connector_service(self):
        """Lazy-init connector service + store."""
        from cortex.caas.connectors import ConnectorService

        if self.__class__.connector_store is None:
            self.__class__.connector_store = JsonConnectorStore()
        return ConnectorService(self.__class__.connector_store)

    def _connector_memory_export_prompt(self, provider: str) -> str:
        safe_provider = str(provider or "assistant").strip() or "assistant"
        return (
            "I'm moving to another service and need to export my data. "
            "List every memory you have stored about me and any context learned from past conversations. "
            "Output everything in one code block. Format each entry as: "
            "[date saved, if available] - memory content. "
            "Preserve wording verbatim where possible. Include response instructions, personal details, "
            "projects/goals, tools/frameworks, preferences/corrections, and any other stored context. "
            "Do not summarize, group, or omit entries. After the code block, confirm if complete.\n\n"
            f"Run this exactly in {safe_provider}, then paste the full response back into Cortex connector sync."
        )

    def _import_connector_memory_dump(self, dump: str, provider: str) -> dict[str, Any]:
        from cortex.graph import Edge, Node, make_edge_id, make_node_id

        graph = self.__class__.graph
        if graph is None:
            return {"error": "No graph configured"}

        cleaned_lines: list[str] = []
        for raw_line in (dump or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("```"):
                continue
            cleaned_lines.append(line)

        nodes_created = 0
        edges_created = 0
        prev_id = ""
        for idx, line in enumerate(cleaned_lines):
            date_saved = ""
            content = line
            if line.startswith("[") and "] - " in line:
                prefix, content = line.split("] - ", 1)
                date_saved = prefix[1:].strip()
                content = content.strip()
            if not content:
                continue

            label = content[:140].strip()
            node_id = make_node_id(f"{provider}:{idx}:{label}")
            props = {
                "source": "connector_memory_export",
                "provider": provider,
            }
            if date_saved:
                props["date_saved"] = date_saved
            node = Node(
                id=node_id,
                label=label,
                tags=["memory_export", "connector", str(provider).lower()],
                confidence=0.55,
                brief=content[:500],
                properties=props,
                full_description=content[:2000],
            )
            graph.add_node(node)
            nodes_created += 1

            if prev_id:
                relation = "follows"
                edge_id = make_edge_id(prev_id, node_id, relation)
                edge = Edge(id=edge_id, source_id=prev_id, target_id=node_id, relation=relation, confidence=0.5)
                graph.add_edge(edge)
                edges_created += 1
            prev_id = node_id

        if nodes_created or edges_created:
            self._save_graph()
        return {
            "nodes_created": nodes_created,
            "edges_created": edges_created,
            "categories": 3 if nodes_created else 0,
            "source_type": "connector_memory_export",
        }

    def _run_connector_job(self, connector: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        metadata = connector.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        job = str(metadata.get("_job", "memory_pull_prompt")).strip().lower()
        job_config = metadata.get("_job_config", {})
        if not isinstance(job_config, dict):
            job_config = {}
        provider = str(connector.get("provider", "unknown")).strip().lower()

        if job == "github_repo_sync":
            url = str(body.get("url") or job_config.get("repo_url") or metadata.get("repo_url") or "").strip()
            token = body.get("token") or job_config.get("token") or metadata.get("token") or None
            if not url:
                return {"error": "github_repo_sync requires repo_url in job_config or request body"}

            from cortex.caas.importers import fetch_github_repo
            import_result = fetch_github_repo(url, token=token)
            if "error" in import_result and not import_result.get("nodes"):
                return {"error": str(import_result["error"])}
            result = self._import_nodes_edges(import_result)
            if result.get("error"):
                return {"error": str(result["error"])}
            result["job"] = job
            result["action_required"] = False
            result["message"] = "GitHub repository sync completed."
            return result

        if job == "custom_json_sync":
            url = str(body.get("url") or job_config.get("url") or "").strip()
            if not url:
                return {"error": "custom_json_sync requires url in job_config or request body"}
            headers = job_config.get("headers", {})
            if not isinstance(headers, dict):
                headers = {}
            req = urllib.request.Request(url, headers={str(k): str(v) for k, v in headers.items()}, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    payload = resp.read()
            except Exception as exc:
                return {"error": f"custom_json_sync fetch failed: {exc}"}
            try:
                parsed = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                return {"error": "custom_json_sync endpoint returned invalid JSON"}

            if isinstance(parsed, dict) and ("nodes" in parsed or "edges" in parsed):
                parsed.setdefault("source_type", "custom_json_sync")
                result = self._import_nodes_edges(parsed)
            else:
                result = self._extract_from_upload(parsed)
                result["source_type"] = "custom_json_sync"

            if result.get("error"):
                return {"error": str(result["error"])}
            result["job"] = job
            result["action_required"] = False
            result["message"] = "Custom JSON sync completed."
            return result

        if job == "memory_pull_prompt":
            memory_dump = str(body.get("memory_dump", "")).strip()
            prompt = self._connector_memory_export_prompt(provider)
            if not memory_dump:
                return {
                    "job": job,
                    "action_required": True,
                    "prompt": prompt,
                    "message": "Action required: run this prompt in your connected assistant, then paste the response as memory_dump.",
                }
            result = self._import_connector_memory_dump(memory_dump, provider)
            if result.get("error"):
                return {"error": str(result["error"])}
            result["job"] = job
            result["action_required"] = False
            result["message"] = "Memory export imported successfully."
            return result

        return {"error": f"Unsupported connector job: {job}"}

    def _handle_create_connector(self) -> None:
        """POST /api/connectors — create a connector link."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return

        body = self._read_body()
        if body is None:
            return

        try:
            connector = self._get_connector_service().create(body)
        except ValueError as exc:
            self._error_response(ERR_INVALID_REQUEST(str(exc)))
            return
        self._json_response(connector, status=201)

    def _handle_list_connectors(self) -> None:
        """GET /api/connectors — list all connector links."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return

        connectors = self._get_connector_service().list_all()
        self._json_response({"connectors": connectors, "count": len(connectors)})

    def _handle_get_connector_capabilities(self) -> None:
        """GET /api/connectors/capabilities — supported jobs and provider matrix."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return
        from cortex.caas.connectors import get_connector_capabilities
        self._json_response(get_connector_capabilities())

    def _handle_get_connector(self, connector_id: str) -> None:
        """GET /api/connectors/{id} — get one connector."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return

        connector = self._get_connector_service().get(connector_id)
        if connector is None:
            self._error_response(ERR_NOT_FOUND("connector"))
            return
        self._json_response(connector)

    def _handle_update_connector(self, connector_id: str) -> None:
        """PUT /api/connectors/{id} — update connector metadata/status."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return

        body = self._read_body()
        if body is None:
            return

        try:
            connector = self._get_connector_service().update(connector_id, body)
        except ValueError as exc:
            self._error_response(ERR_INVALID_REQUEST(str(exc)))
            return
        if connector is None:
            self._error_response(ERR_NOT_FOUND("connector"))
            return
        self._json_response(connector)

    def _handle_delete_connector(self, connector_id: str) -> None:
        """DELETE /api/connectors/{id} — delete connector link."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return

        deleted = self._get_connector_service().delete(connector_id)
        if not deleted:
            self._error_response(ERR_NOT_FOUND("connector"))
            return
        self._json_response({"deleted": True, "connector_id": connector_id})

    def _handle_sync_connector(self, connector_id: str) -> None:
        """POST /api/connectors/{id}/sync — run the connector's assigned job."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return

        body = self._read_body()
        if body is None:
            return

        svc = self._get_connector_service()
        connector = svc.get(connector_id)
        if connector is None:
            self._error_response(ERR_NOT_FOUND("connector"))
            return

        result = self._run_connector_job(connector, body)
        now = datetime.now(timezone.utc).isoformat()
        metadata = connector.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        updated_meta = dict(metadata)

        if result.get("error"):
            updated_meta["_last_sync_status"] = "error"
            updated_meta["_last_sync_error"] = str(result["error"])
            updated_meta["_last_sync_message"] = "Sync failed."
            svc.update(connector_id, {
                "status": "error",
                "metadata": updated_meta,
                "last_sync_at": now,
            })
            self._error_response(ERR_INVALID_REQUEST(str(result["error"])))
            return

        if result.get("action_required"):
            updated_meta["_last_sync_status"] = "action_required"
            updated_meta["_last_sync_error"] = ""
            updated_meta["_last_sync_message"] = str(result.get("message", "Action required"))
            svc.update(connector_id, {
                "metadata": updated_meta,
                "last_sync_at": now,
            })
            self._json_response(result, status=202)
            return

        updated_meta["_last_sync_status"] = "ok"
        updated_meta["_last_sync_error"] = ""
        updated_meta["_last_sync_message"] = str(result.get("message", "Sync complete"))
        svc.update(connector_id, {
            "status": "active",
            "metadata": updated_meta,
            "last_sync_at": now,
        })
        self._json_response(result, status=201)

    def _handle_get_storage_preferences(self) -> None:
        """GET /api/storage/preferences — get storage mode preferences for current actor."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return
        self._json_response(self._get_storage_preferences_for_request())

    def _handle_update_storage_preferences(self) -> None:
        """PUT /api/storage/preferences — persist storage mode preferences."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return

        body = self._read_body()
        if body is None:
            return
        valid, error = self._validate_storage_preferences(body)
        if not valid:
            self._error_response(ERR_INVALID_REQUEST(error))
            return

        actor = self._storage_actor_key()
        now = datetime.now(timezone.utc).isoformat()
        data = self._load_storage_preferences_all()
        data[actor] = {
            "mode": str(body.get("mode", "local")).strip().lower(),
            "byos_provider": str(body.get("byos_provider", "")).strip(),
            "byos_location": str(body.get("byos_location", "")).strip(),
            "updated_at": now,
        }
        try:
            self._save_storage_preferences_all(data)
        except Exception as exc:
            self._error_response(ERR_INTERNAL(f"Failed to save storage preferences: {exc}"))
            return
        self._json_response(data[actor])

    def _handle_check_storage_preferences(self) -> None:
        """POST /api/storage/preferences/check — verify storage connectivity."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return

        body = self._read_body()
        if body is None:
            return
        valid, error = self._validate_storage_preferences(body)
        if not valid:
            self._error_response(ERR_INVALID_REQUEST(error))
            return

        try:
            result = self._try_check_storage_preferences(body)
        except Exception as exc:
            self._error_response(ERR_INVALID_REQUEST(f"Storage check failed: {exc}"))
            return
        self._json_response(result, status=(200 if result.get("ok") else 400))

    def _get_api_key_store(self):
        """Lazy-init the API key store."""
        if self.__class__.api_key_store is None:
            from cortex.caas.api_keys import ApiKeyStore
            store_path = self._get_store_base_dir() / "api_keys.json"
            self.__class__.api_key_store = ApiKeyStore(store_path)
        return self.__class__.api_key_store

    def _handle_create_api_key(self) -> None:
        """POST /api/keys — create a new shareable memory API key."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
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
        try:
            key_info = store.create(label, policy, tags=tags, fmt=fmt)
        except OSError as exc:
            self._error_response(ERR_INTERNAL(f"Failed to persist API key: {exc}"))
            return
        self._json_response(key_info, status=201)

    def _handle_list_api_keys(self) -> None:
        """GET /api/keys — list all API keys (secrets masked)."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
            return

        store = self._get_api_key_store()
        self._json_response(store.list_keys())

    def _handle_revoke_api_key(self, key_id: str) -> None:
        """DELETE /api/keys/{key_id} — revoke an API key."""
        if not self.__class__.enable_webapp:
            self._error_response(ERR_NOT_FOUND("endpoint"))
            return
        if not self._webapp_or_multiuser_auth_check():
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

    def _webapp_or_multiuser_auth_check(self) -> bool:
        """Validate auth for webapp APIs in both single-user and multi-user modes."""
        if self.__class__.multi_user_enabled and _MULTI_USER_AVAILABLE:
            is_auth, _ = self._multi_user_auth_check()
            return is_auth
        return self._webapp_auth_check()

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

    # ── Multi-user authentication ─────────────────────────────────

    def _handle_user_signup(self) -> None:
        """POST /api/signup — create a new user account."""
        if not _MULTI_USER_AVAILABLE:
            self._error_response(ERR_NOT_CONFIGURED("Multi-user module not available"))
            return

        if not self.__class__.multi_user_enabled:
            self._error_response(ERR_NOT_CONFIGURED("Multi-user mode not enabled"))
            return

        if not self.__class__.registration_open:
            self._error_response(ERR_INVALID_REQUEST("Registration is closed"))
            return

        mu_sm = self.__class__.multi_user_session_manager
        if mu_sm is None:
            self._error_response(ERR_NOT_CONFIGURED("Multi-user session manager not configured"))
            return

        body = self._read_body()
        if body is None:
            return

        email = body.get("email", "").strip()
        password = body.get("password", "")
        display_name = body.get("display_name", "").strip()

        request = SignupRequest(email=email, password=password, display_name=display_name)
        user, errors = mu_sm.signup(request)

        if errors:
            self._respond(400, "application/json",
                          json.dumps({"error": {"type": "validation_error", "messages": errors}}).encode())
            return

        if user is None:
            self._error_response(ERR_INTERNAL("Failed to create user account"))
            return

        self._audit("user.signup", {"user_id": user.user_id, "email": user.email})
        self._json_response({
            "user_id": user.user_id,
            "email": user.email,
            "display_name": user.display_name,
            "message": "Account created successfully",
        }, status=201)

    def _handle_user_login(self) -> None:
        """POST /api/login — authenticate with email/password."""
        if not _MULTI_USER_AVAILABLE:
            self._error_response(ERR_NOT_CONFIGURED("Multi-user module not available"))
            return

        if not self.__class__.multi_user_enabled:
            self._error_response(ERR_NOT_CONFIGURED("Multi-user mode not enabled"))
            return

        mu_sm = self.__class__.multi_user_session_manager
        if mu_sm is None:
            self._error_response(ERR_NOT_CONFIGURED("Multi-user session manager not configured"))
            return

        body = self._read_body()
        if body is None:
            return

        email = body.get("email", "").strip()
        password = body.get("password", "")

        request = LoginRequest(email=email, password=password)

        # Get client info for session
        ip_address = self.client_address[0] if self.client_address else None
        user_agent = self.headers.get("User-Agent", "")[:256]  # Truncate long UAs

        token, user, errors = mu_sm.login(request, ip_address=ip_address, user_agent=user_agent)

        if errors:
            self._audit("user.login_failed", {"email": email})
            self._respond(401, "application/json",
                          json.dumps({"error": {"type": "auth_error", "messages": errors}}).encode())
            return

        self._audit("user.login", {"user_id": user.user_id, "email": user.email})
        resp_body = json.dumps({
            "user_id": user.user_id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role.value,
        }).encode()
        self._respond(200, "application/json", resp_body,
                      extra_headers={
                          "Set-Cookie": f"cortex_user_session={token}; HttpOnly; SameSite=Strict; Path=/",
                      })

    def _handle_user_logout(self) -> None:
        """POST /api/logout — revoke user session."""
        if not _MULTI_USER_AVAILABLE or not self.__class__.multi_user_enabled:
            self._error_response(ERR_NOT_CONFIGURED("Multi-user mode not enabled"))
            return

        mu_sm = self.__class__.multi_user_session_manager
        if mu_sm is not None:
            cookie_header = self.headers.get("Cookie", "")
            for part in cookie_header.split(";"):
                part = part.strip()
                if part.startswith("cortex_user_session="):
                    token = part[len("cortex_user_session="):]
                    if token:
                        mu_sm.logout_user(token)
                    break

        self._audit("user.logout", {})
        resp_body = json.dumps({"ok": True}).encode()
        self._respond(200, "application/json", resp_body,
                      extra_headers={
                          "Set-Cookie": "cortex_user_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0",
                      })

    def _handle_get_current_user(self) -> None:
        """GET /api/me — get current user info."""
        if not _MULTI_USER_AVAILABLE:
            # Fall back to admin mode info
            sm = self.__class__.session_manager
            if sm is not None and self._webapp_auth_check():
                self._json_response({
                    "mode": "admin",
                    "authenticated": True,
                })
            return

        if not self.__class__.multi_user_enabled:
            # Single-user mode
            if self._webapp_auth_check():
                self._json_response({
                    "mode": "admin",
                    "authenticated": True,
                })
            return

        mu_sm = self.__class__.multi_user_session_manager
        if mu_sm is None:
            self._error_response(ERR_NOT_CONFIGURED("Session manager not configured"))
            return

        # Check for user session
        cookie_header = self.headers.get("Cookie", "")
        token = None
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("cortex_user_session="):
                token = part[len("cortex_user_session="):]
                break

        if token:
            user = mu_sm.validate_user_session(token)
            if user:
                self._json_response(user.to_public_dict())
                return

        # Check for admin session
        if self._check_admin_session():
            self._json_response({
                "mode": "admin",
                "authenticated": True,
                "role": "admin",
            })
            return

        self._respond(401, "application/json",
                      json.dumps({"error": "unauthorized"}).encode())

    def _handle_get_users_config(self) -> None:
        """GET /api/users/config — get multi-user configuration (public info)."""
        self._json_response({
            "multi_user_enabled": self.__class__.multi_user_enabled,
            "registration_open": self.__class__.registration_open,
            "max_upload_bytes": self.__class__.max_upload_bytes,
            "storage_modes": list(self.__class__.storage_modes),
            "default_storage_mode": self.__class__.default_storage_mode,
            "managed_cloud_enabled": False,
            "connector_capabilities_url": "/api/connectors/capabilities",
            "storage_preferences_url": "/api/storage/preferences",
            "storage_preferences_check_url": "/api/storage/preferences/check",
        })

    def _check_admin_session(self) -> bool:
        """Check if current request has valid admin session (dashboard or webapp)."""
        sm = self.__class__.session_manager
        if sm is None:
            return False

        cookie_header = self.headers.get("Cookie", "")

        # Check webapp session
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("cortex_app_session="):
                token = part[len("cortex_app_session="):]
                if token and sm.validate(token):
                    return True
                break

        # Check dashboard session
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("cortex_session="):
                token = part[len("cortex_session="):]
                if token and sm.validate(token):
                    return True
                break

        return False

    def _get_current_user(self) -> "User | None":
        """Get the current authenticated user from session, or None."""
        if not _MULTI_USER_AVAILABLE or not self.__class__.multi_user_enabled:
            return None

        mu_sm = self.__class__.multi_user_session_manager
        if mu_sm is None:
            return None

        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("cortex_user_session="):
                token = part[len("cortex_user_session="):]
                if token:
                    return mu_sm.validate_user_session(token)
        return None

    def _multi_user_auth_check(self) -> tuple[bool, "User | None"]:
        """Validate multi-user or admin session.

        Returns:
            (is_authenticated, user_or_none)
            user_or_none is None for admin sessions
        """
        if not _MULTI_USER_AVAILABLE or not self.__class__.multi_user_enabled:
            # Fall back to admin-only mode
            if self._webapp_auth_check():
                return True, None
            return False, None

        # Check user session first
        user = self._get_current_user()
        if user:
            self._current_user = user
            return True, user

        # Fall back to admin session
        if self._check_admin_session():
            return True, None

        self._respond(401, "application/json",
                      json.dumps({"error": "unauthorized"}).encode())
        return False, None

    # ── Dashboard: session auth ──────────────────────────────────

    def _handle_dashboard_login(self) -> None:
        """POST /dashboard/auth — authenticate with derived password."""
        # Login brute-force protection
        login_limiter = self.__class__.login_rate_limiter
        if login_limiter is not None:
            client_ip = self.client_address[0] if self.client_address else "unknown"
            if not login_limiter.allow(client_ip):
                self._respond(429, "application/json",
                              json.dumps({"error": "too_many_attempts"}).encode(),
                              dashboard=True)
                return

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
        elif api_path == "/health":
            self._dashboard_api_graph_health(query)
        elif api_path == "/changelog":
            self._dashboard_api_changelog(query)
        elif api_path == "/export/archive":
            self._dashboard_api_export_archive()
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
        elif api_path == "/import/archive":
            self._dashboard_api_import_archive()
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

        limit = self._parse_int_param(query, "limit", 20, min_val=1, max_val=100)
        if limit is None:
            return
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

        limit = self._parse_int_param(query, "limit", 50, min_val=1, max_val=1000)
        if limit is None:
            return
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

    # ── Dashboard: Graph Health & Changelog ────────────────────────

    def _dashboard_api_graph_health(self, query: dict) -> None:
        """GET /dashboard/api/health — graph health metrics."""
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return
        stale_days = self._parse_int_param(query, "stale_days", 30, min_val=1, max_val=365)
        if stale_days is None:
            return
        self._json_response(graph.graph_health(stale_days=stale_days))

    def _dashboard_api_changelog(self, query: dict) -> None:
        """GET /dashboard/api/changelog — recent graph diffs from version history."""
        vs = self.__class__.version_store
        if vs is None:
            self._json_response({"entries": []})
            return

        from cortex.graph import diff_graphs
        limit = self._parse_int_param(query, "limit", 10, min_val=1, max_val=100)
        if limit is None:
            return
        versions = vs.log(limit=limit + 1)  # need pairs

        entries: list[dict] = []
        for i in range(len(versions) - 1):
            newer, older = versions[i], versions[i + 1]
            try:
                graph_new = vs.checkout(newer.version_id, verify=False)
                graph_old = vs.checkout(older.version_id, verify=False)
                diff = diff_graphs(graph_old, graph_new)
            except (FileNotFoundError, ValueError):
                diff = {"summary": {}}
            entries.append({
                "version_id": newer.version_id,
                "timestamp": newer.timestamp,
                "message": newer.message,
                "diff": diff,
            })
            if len(entries) >= limit:
                break

        self._json_response({"entries": entries})

    # ── Dashboard: Archive Export/Import ──────────────────────────

    def _dashboard_api_export_archive(self) -> None:
        """GET /dashboard/api/export/archive — download ZIP archive."""
        graph = self.__class__.graph
        if graph is None:
            self._error_response(ERR_NOT_CONFIGURED())
            return

        from cortex.caas.archive import create_archive

        archive_bytes = create_archive(
            graph,
            profile_store=self._get_profile_store(),
            credential_store=self.__class__.credential_store,
            identity=self.__class__.identity,
        )
        self._respond(200, "application/zip", archive_bytes,
                      extra_headers={
                          "Content-Disposition": "attachment; filename=cortex-archive.zip",
                      })

    def _dashboard_api_import_archive(self) -> None:
        """POST /dashboard/api/import/archive — import ZIP archive."""
        content_length = self._parse_content_length()
        if content_length is None:
            return
        if content_length == 0:
            self._error_response(ERR_INVALID_REQUEST("Empty request body"))
            return
        if content_length > 10_485_760:  # 10 MB
            self._error_response(ERR_PAYLOAD_TOO_LARGE())
            return

        raw = self.rfile.read(content_length)

        from cortex.caas.archive import import_archive
        try:
            result = import_archive(raw)
        except ValueError as exc:
            self._error_response(ERR_INVALID_REQUEST(str(exc)))
            return

        # Replace graph if graph data present
        if result.get("graph"):
            from cortex.graph import CortexGraph
            new_graph = CortexGraph.from_v5_json(result["graph"])
            self.__class__.graph = new_graph

        self._audit("archive.imported", {
            "node_count": result.get("manifest", {}).get("node_count", 0),
            "edge_count": result.get("manifest", {}).get("edge_count", 0),
        })

        self._json_response({
            "imported": True,
            "manifest": result.get("manifest", {}),
        })

    # ── Response helpers ─────────────────────────────────────────────

    def _read_body(self, require_json: bool = True) -> dict | None:
        """Read and parse JSON request body. Returns None and sends error on failure."""
        content_length = self._parse_content_length()
        if content_length is None:
            return None
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

        # HSTS (opt-in — only safe behind TLS reverse proxy)
        if self.__class__.hsts_enabled:
            self.send_header(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains",
            )

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
    pool: Any = None,
    context_path: str | None = None,
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

    # Token verification cache
    from cortex.caas.token_cache import TokenCache
    CaaSHandler.token_cache = TokenCache(max_size=1024, ttl=30.0)
    CaaSHandler.enable_webapp = enable_webapp
    CaaSHandler.multi_user_enabled = False
    CaaSHandler.multi_user_session_manager = None
    CaaSHandler.user_graph_resolver = None
    CaaSHandler.user_store = None
    CaaSHandler.storage_modes = ["local", "byos"]
    CaaSHandler.default_storage_mode = "local"
    if config is not None:
        # Upload cap used by /api/upload (applies in both single-user and multi-user modes).
        _cfg_upload_max = config.getint(
            "users", "max_upload_bytes", fallback=CaaSHandler.max_upload_bytes
        )
        if _cfg_upload_max > 0:
            CaaSHandler.max_upload_bytes = _cfg_upload_max
        CaaSHandler.registration_open = config.getbool("users", "registration_open", fallback=True)
        _cfg_quota = config.getint("users", "default_quota_bytes", fallback=CaaSHandler.default_user_quota)
        if _cfg_quota > 0:
            CaaSHandler.default_user_quota = _cfg_quota
        _cfg_modes_raw = config.get("users", "storage_modes", fallback="local,byos")
        _cfg_modes = [m.strip().lower() for m in _cfg_modes_raw.split(",") if m.strip()]
        _valid_modes = [m for m in _cfg_modes if m in {"local", "byos"}]
        if _valid_modes:
            CaaSHandler.storage_modes = _valid_modes
        _cfg_default_mode = config.get("users", "default_storage_mode", fallback="local").strip().lower()
        if _cfg_default_mode in CaaSHandler.storage_modes:
            CaaSHandler.default_storage_mode = _cfg_default_mode

    # HSTS (opt-in)
    if config is not None:
        CaaSHandler.hsts_enabled = config.getbool("security", "hsts_enabled", fallback=False)

    # Rate limiters — tiered by default
    from cortex.caas.rate_limit import RateLimiter, TieredRateLimiter
    CaaSHandler.rate_limiter = TieredRateLimiter()
    CaaSHandler.login_rate_limiter = RateLimiter(max_requests=10, window=60)
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
            SqliteConnectorStore,
            SqliteDeliveryLog,
            SqliteGrantStore,
            SqlitePolicyStore,
            SqliteWebhookStore,
        )
        # Set up field encryption for grant tokens and webhook secrets
        _encryptor = None
        try:
            from cortex.caas.encryption import FieldEncryptor
            pk = identity._private_key or identity.did.encode()
            _encryptor = FieldEncryptor.from_identity_key(pk)
        except Exception:
            pass
        if _encryptor is not None:
            import cortex.upai.webhooks as _wh_mod
            _wh_mod._webhook_encryptor = _encryptor
        CaaSHandler.grant_store = SqliteGrantStore(db_path, encryptor=_encryptor)
        webhook_store = SqliteWebhookStore(db_path)
        CaaSHandler.webhook_store = webhook_store
        CaaSHandler.audit_log = SqliteAuditLog(db_path)
        CaaSHandler.policy_registry = PolicyRegistry(store=SqlitePolicyStore(db_path))
        CaaSHandler.connector_store = SqliteConnectorStore(db_path)
        delivery_log = SqliteDeliveryLog(db_path)
        from cortex.caas.webhook_worker import WebhookWorker
        worker = WebhookWorker(webhook_store, delivery_log=delivery_log)
        worker.start()
        CaaSHandler.webhook_worker = worker
    elif storage_backend == "postgres" and db_path:
        try:
            from cortex.caas.postgres_store import (
                PostgresAuditLog,
                PostgresConnectorStore,
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
        if _encryptor is not None:
            import cortex.upai.webhooks as _wh_mod
            _wh_mod._webhook_encryptor = _encryptor
        CaaSHandler.grant_store = PostgresGrantStore(db_path, encryptor=_encryptor, pool=pool)
        webhook_store = PostgresWebhookStore(db_path, pool=pool)
        CaaSHandler.webhook_store = webhook_store
        CaaSHandler.audit_log = PostgresAuditLog(db_path, pool=pool)
        CaaSHandler.policy_registry = PolicyRegistry(store=PostgresPolicyStore(db_path, pool=pool))
        CaaSHandler.connector_store = PostgresConnectorStore(db_path, pool=pool)
        delivery_log = PostgresDeliveryLog(db_path, pool=pool)
        from cortex.caas.webhook_worker import WebhookWorker
        worker = WebhookWorker(webhook_store, delivery_log=delivery_log)
        worker.start()
        CaaSHandler.webhook_worker = worker
    else:
        # Set up field encryption for webhook secrets in JSON backend
        try:
            from cortex.caas.encryption import FieldEncryptor
            pk = identity._private_key or identity.did.encode()
            _json_encryptor = FieldEncryptor.from_identity_key(pk)
            import cortex.upai.webhooks as _wh_mod
            _wh_mod._webhook_encryptor = _json_encryptor
        except Exception:
            pass
        CaaSHandler.grant_store = JsonGrantStore(persist_path=grants_persist_path)
        json_webhook_store = JsonWebhookStore()
        CaaSHandler.webhook_store = json_webhook_store
        CaaSHandler.connector_store = JsonConnectorStore()
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

    # Keychain and store_dir
    CaaSHandler.store_dir = store_dir
    CaaSHandler.context_path = context_path
    print(f"[DEBUG start_caas_server] Set CaaSHandler.context_path = {context_path}")
    print(f"[DEBUG start_caas_server] Set CaaSHandler.store_dir = {store_dir}")
    if store_dir:
        from cortex.upai.keychain import Keychain
        CaaSHandler.keychain = Keychain(Path(store_dir))
    else:
        CaaSHandler.keychain = None

    # Connector auto-sync worker (24h cadence, minute-level scheduler polling)
    if CaaSHandler.connector_store is not None:
        auto_worker = ConnectorAutoSyncWorker(
            connector_store=CaaSHandler.connector_store,
            graph_getter=lambda: CaaSHandler.graph,
            context_path_getter=lambda: CaaSHandler.context_path,
        )
        auto_worker.start()
        CaaSHandler.connector_auto_sync_worker = auto_worker
    else:
        CaaSHandler.connector_auto_sync_worker = None

    # Multi-user mode (signup/login + per-user sessions/graphs)
    if config is not None and config.getbool("users", "enabled", fallback=False):
        if not _MULTI_USER_AVAILABLE:
            print("[WARN] Multi-user mode requested but module is unavailable; running single-user.")
        elif storage_backend != "sqlite" or not db_path:
            print("[WARN] Multi-user mode requires SQLite storage with --db-path; running single-user.")
        else:
            try:
                _user_session_ttl = config.getint("users", "session_ttl_seconds", fallback=604800)
                if _user_session_ttl <= 0:
                    _user_session_ttl = 604800
                CaaSHandler.user_store = SqliteUserStore(db_path)
                CaaSHandler.multi_user_session_manager = MultiUserSessionManager(
                    identity,
                    CaaSHandler.user_store,
                    user_session_ttl=float(_user_session_ttl),
                )
                resolver_base = Path(store_dir) if store_dir else Path(".cortex")
                CaaSHandler.user_graph_resolver = UserGraphResolver(resolver_base)
                CaaSHandler.multi_user_enabled = True
            except Exception as exc:
                print(f"[WARN] Failed to initialize multi-user mode: {exc}; running single-user.")

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
    if CaaSHandler.connector_auto_sync_worker is not None:
        coordinator.register("connector_auto_sync_worker", CaaSHandler.connector_auto_sync_worker.stop)
    if pool is not None:
        coordinator.register("pg_pool", pool.close)
    coordinator.register("http_server", server.shutdown)
    server._shutdown_coordinator = coordinator  # type: ignore[attr-defined]

    return server
