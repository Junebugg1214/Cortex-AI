"""
Tests for CaaS Dashboard — static file serving, session auth, and API endpoints.

Uses the same HTTPServer-on-random-port pattern as test_caas_server.py.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

from cortex.caas.dashboard.auth import DashboardSessionManager
from cortex.caas.dashboard.static import guess_content_type, resolve_dashboard_path
from cortex.caas.server import CaaSHandler, GrantStore, NonceCache
from cortex.caas.storage import JsonWebhookStore
from cortex.graph import CortexGraph, Edge, Node
from cortex.upai.identity import UPAIIdentity, has_crypto


def _build_test_graph() -> CortexGraph:
    g = CortexGraph()
    g.add_node(Node(id="n1", label="Marc", tags=["identity"], confidence=0.95,
                     brief="Software developer"))
    g.add_node(Node(id="n2", label="Python", tags=["technical_expertise"], confidence=0.9))
    g.add_node(Node(id="n3", label="CEO", tags=["professional_context"], confidence=0.85))
    g.add_edge(Edge(id="e1", source_id="n1", target_id="n3", relation="has_role"))
    g.add_edge(Edge(id="e2", source_id="n1", target_id="n2", relation="uses"))
    return g


def _setup_dashboard_server():
    """Set up test server with dashboard session manager."""
    if not has_crypto():
        return None, None, None, None

    identity = UPAIIdentity.generate("Dashboard Test")
    graph = _build_test_graph()

    CaaSHandler.graph = graph
    CaaSHandler.identity = identity
    CaaSHandler.grant_store = GrantStore()
    CaaSHandler.nonce_cache = NonceCache()
    CaaSHandler.version_store = None
    CaaSHandler.webhook_store = JsonWebhookStore()
    CaaSHandler.audit_log = None
    CaaSHandler.rate_limiter = None
    CaaSHandler.login_rate_limiter = None
    CaaSHandler.webhook_worker = None
    CaaSHandler._allowed_origins = set()

    sm = DashboardSessionManager(identity)
    CaaSHandler.session_manager = sm

    server = HTTPServer(("127.0.0.1", 0), CaaSHandler)
    port = server.server_address[1]
    CaaSHandler._allowed_origins = {f"http://127.0.0.1:{port}"}

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    return server, port, identity, sm


def _request(port, path, method="GET", body=None, headers=None, expect_error=False):
    """Make HTTP request and return (parsed_body, status_code, response_headers)."""
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        resp = urllib.request.urlopen(req)
        ct = resp.headers.get("Content-Type", "")
        raw = resp.read()
        if "json" in ct:
            return json.loads(raw), resp.status, dict(resp.headers)
        return raw.decode("utf-8", errors="replace"), resp.status, dict(resp.headers)
    except urllib.error.HTTPError as e:
        if expect_error:
            raw = e.read()
            ct = e.headers.get("Content-Type", "")
            if "json" in ct:
                return json.loads(raw), e.code, dict(e.headers)
            return raw.decode("utf-8", errors="replace"), e.code, dict(e.headers)
        raise


# ── Static file tests ────────────────────────────────────────────


class TestDashboardStaticFiles:
    def test_resolve_index(self):
        """Dashboard root resolves to index.html."""
        p = resolve_dashboard_path("/dashboard")
        assert p is not None
        assert p.name == "index.html"

    def test_resolve_index_with_slash(self):
        p = resolve_dashboard_path("/dashboard/")
        assert p is not None
        assert p.name == "index.html"

    def test_resolve_css(self):
        p = resolve_dashboard_path("/dashboard/styles.css")
        assert p is not None
        assert p.name == "styles.css"

    def test_resolve_js(self):
        p = resolve_dashboard_path("/dashboard/app.js")
        assert p is not None
        assert p.name == "app.js"

    def test_resolve_page_js(self):
        p = resolve_dashboard_path("/dashboard/pages/overview.js")
        assert p is not None
        assert p.name == "overview.js"

    def test_resolve_nonexistent(self):
        p = resolve_dashboard_path("/dashboard/nonexistent.xyz")
        assert p is None

    def test_directory_traversal_blocked(self):
        p = resolve_dashboard_path("/dashboard/../../etc/passwd")
        assert p is None

    def test_guess_content_type_html(self):
        assert guess_content_type(Path("index.html")) == "text/html"

    def test_guess_content_type_js(self):
        assert guess_content_type(Path("app.js")) == "application/javascript"

    def test_guess_content_type_css(self):
        assert guess_content_type(Path("styles.css")) == "text/css"


# ── Session auth tests ───────────────────────────────────────────


class TestDashboardSessionAuth:
    def test_derive_password_deterministic(self):
        """Same identity produces same password."""
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        sm1 = DashboardSessionManager(identity)
        sm2 = DashboardSessionManager(identity)
        assert sm1.password == sm2.password

    def test_authenticate_correct_password(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        sm = DashboardSessionManager(identity)
        token = sm.authenticate(sm.password)
        assert token is not None
        assert len(token) == 64  # 32 bytes hex

    def test_authenticate_wrong_password(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        sm = DashboardSessionManager(identity)
        token = sm.authenticate("wrong_password")
        assert token is None

    def test_validate_valid_session(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        sm = DashboardSessionManager(identity)
        token = sm.authenticate(sm.password)
        assert sm.validate(token) is True

    def test_validate_invalid_token(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        sm = DashboardSessionManager(identity)
        assert sm.validate("invalid_token") is False

    def test_validate_expired_session(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        sm = DashboardSessionManager(identity, session_ttl=0.01)
        token = sm.authenticate(sm.password)
        time.sleep(0.02)
        assert sm.validate(token) is False

    def test_revoke_session(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        sm = DashboardSessionManager(identity)
        token = sm.authenticate(sm.password)
        sm.revoke(token)
        assert sm.validate(token) is False


# ── HTTP endpoint tests ──────────────────────────────────────────


class TestDashboardHTTPEndpoints:
    @classmethod
    def setup_class(cls):
        result = _setup_dashboard_server()
        cls.server, cls.port, cls.identity, cls.sm = result
        if cls.port is None:
            return

    def _login(self):
        """Login and return session cookie header."""
        body, status, headers = _request(
            self.port, "/dashboard/auth", method="POST",
            body={"password": self.sm.password}
        )
        assert status == 200
        cookie = headers.get("Set-Cookie", headers.get("set-cookie", ""))
        # Extract just the cookie name=value
        cookie_val = cookie.split(";")[0] if cookie else ""
        return {"Cookie": cookie_val}

    def test_serve_index_html(self):
        if self.port is None:
            return
        body, status, headers = _request(self.port, "/dashboard")
        assert status == 200
        assert "Cortex Dashboard" in body

    def test_serve_css(self):
        if self.port is None:
            return
        body, status, headers = _request(self.port, "/dashboard/styles.css")
        assert status == 200
        assert "sidebar" in body

    def test_serve_js(self):
        if self.port is None:
            return
        body, status, headers = _request(self.port, "/dashboard/app.js")
        assert status == 200
        assert "CortexDashboard" in body

    def test_dashboard_csp_relaxed(self):
        if self.port is None:
            return
        _, _, headers = _request(self.port, "/dashboard")
        csp = headers.get("Content-Security-Policy", "")
        assert "unsafe-inline" in csp

    def test_api_csp_strict(self):
        if self.port is None:
            return
        _, _, headers = _request(self.port, "/health")
        csp = headers.get("Content-Security-Policy", "")
        assert csp == "default-src 'none'"

    def test_login_success(self):
        if self.port is None:
            return
        body, status, headers = _request(
            self.port, "/dashboard/auth", method="POST",
            body={"password": self.sm.password}
        )
        assert status == 200
        assert body.get("ok") is True
        cookie = headers.get("Set-Cookie", headers.get("set-cookie", ""))
        assert "cortex_session=" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=Strict" in cookie

    def test_login_sets_secure_cookie_when_forwarded_https(self):
        if self.port is None:
            return
        body, status, headers = _request(
            self.port, "/dashboard/auth", method="POST",
            body={"password": self.sm.password},
            headers={"X-Forwarded-Proto": "https"},
        )
        assert status == 200
        assert body.get("ok") is True
        cookie = headers.get("Set-Cookie", headers.get("set-cookie", ""))
        assert "cortex_session=" in cookie
        assert "Secure" in cookie

    def test_login_failure(self):
        if self.port is None:
            return
        body, status, _ = _request(
            self.port, "/dashboard/auth", method="POST",
            body={"password": "wrong"}, expect_error=True
        )
        assert status == 401

    def test_api_requires_auth(self):
        if self.port is None:
            return
        _, status, _ = _request(
            self.port, "/dashboard/api/identity", expect_error=True
        )
        assert status == 401

    def test_api_identity(self):
        if self.port is None:
            return
        auth = self._login()
        body, status, _ = _request(self.port, "/dashboard/api/identity", headers=auth)
        assert status == 200
        assert "did" in body
        assert "name" in body
        assert body["name"] == "Dashboard Test"

    def test_api_stats(self):
        if self.port is None:
            return
        auth = self._login()
        body, status, _ = _request(self.port, "/dashboard/api/stats", headers=auth)
        assert status == 200
        assert body["node_count"] == 3
        assert body["edge_count"] == 2

    def test_api_graph(self):
        if self.port is None:
            return
        auth = self._login()
        body, status, _ = _request(self.port, "/dashboard/api/graph", headers=auth)
        assert status == 200
        assert "nodes" in body
        assert "edges" in body
        assert len(body["nodes"]) == 3
        assert len(body["edges"]) == 2
        # Each node should have layout position
        node = body["nodes"][0]
        assert "x" in node
        assert "y" in node
        assert "r" in node
        assert "color" in node

    def test_api_graph_with_policy(self):
        if self.port is None:
            return
        auth = self._login()
        body, status, _ = _request(
            self.port, "/dashboard/api/graph?policy=minimal", headers=auth
        )
        assert status == 200
        # Minimal policy filters to high confidence + identity tags
        assert len(body["nodes"]) <= 3
        assert body["policy"] == "minimal"

    def test_api_grants_empty(self):
        if self.port is None:
            return
        auth = self._login()
        body, status, _ = _request(self.port, "/dashboard/api/grants", headers=auth)
        assert status == 200
        assert "grants" in body

    def test_api_create_and_revoke_grant(self):
        if self.port is None:
            return
        auth = self._login()
        # Create
        body, status, _ = _request(
            self.port, "/dashboard/api/grants", method="POST",
            body={"audience": "test-consumer", "policy": "professional", "ttl_hours": 1},
            headers=auth
        )
        assert status == 201
        assert "grant_id" in body
        assert "token" in body
        grant_id = body["grant_id"]

        # Verify in list
        body, status, _ = _request(self.port, "/dashboard/api/grants", headers=auth)
        assert any(g["grant_id"] == grant_id for g in body["grants"])

        # Revoke
        body, status, _ = _request(
            self.port, f"/dashboard/api/grants/{grant_id}",
            method="DELETE", headers=auth
        )
        assert status == 200
        assert body["revoked"] is True

    def test_api_versions_empty(self):
        if self.port is None:
            return
        auth = self._login()
        body, status, _ = _request(self.port, "/dashboard/api/versions", headers=auth)
        assert status == 200
        # items or empty list
        assert "items" in body or "has_more" in body

    def test_api_audit_empty(self):
        if self.port is None:
            return
        auth = self._login()
        body, status, _ = _request(self.port, "/dashboard/api/audit", headers=auth)
        assert status == 200
        assert "entries" in body

    def test_api_webhooks_empty(self):
        if self.port is None:
            return
        auth = self._login()
        body, status, _ = _request(self.port, "/dashboard/api/webhooks", headers=auth)
        assert status == 200
        assert "webhooks" in body

    def test_api_config(self):
        if self.port is None:
            return
        auth = self._login()
        body, status, _ = _request(self.port, "/dashboard/api/config", headers=auth)
        assert status == 200
        assert "port" in body
        assert "did" in body
        assert "node_count" in body
        assert body["node_count"] == 3

    def test_api_unknown_endpoint_404(self):
        if self.port is None:
            return
        auth = self._login()
        _, status, _ = _request(
            self.port, "/dashboard/api/nonexistent",
            headers=auth, expect_error=True
        )
        assert status == 404

    def test_api_invalid_policy_400(self):
        if self.port is None:
            return
        auth = self._login()
        _, status, _ = _request(
            self.port, "/dashboard/api/graph?policy=invalid",
            headers=auth, expect_error=True
        )
        assert status == 400


# ── Pull adapter CLI tests ───────────────────────────────────────


class TestPullCLI:
    def test_pull_subcommand_help(self):
        from cortex.cli import build_parser
        parser = build_parser()
        # Verify the pull subcommand exists
        args = parser.parse_args(["pull", "test.md", "--from", "notion"])
        assert args.subcommand == "pull"
        assert args.from_platform == "notion"

    def test_pull_known_subcommand(self):
        from cortex.cli import main
        # Non-existent file should print error and return 1
        result = main(["pull", "/nonexistent/file.md", "--from", "notion"])
        assert result == 1
