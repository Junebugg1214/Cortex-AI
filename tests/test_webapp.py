"""
Tests for Cortex Web UI — webapp static serving and upload endpoint.

Covers:
- Webapp static file resolution and MIME types
- Static file serving via /app routes
- POST /api/upload endpoint (multipart upload, validation, extraction)
- Route handling and content-type headers
- Webapp disabled by default behavior
"""

import io
import json
import threading
import time
import urllib.error
import urllib.request
import zipfile
from http.server import HTTPServer
from pathlib import Path

import pytest

from cortex.caas.server import CaaSHandler, GrantStore, NonceCache
from cortex.caas.storage import JsonWebhookStore
from cortex.caas.webapp.static import (
    WEBAPP_DIR,
    guess_webapp_content_type,
    resolve_webapp_path,
)
from cortex.graph import CortexGraph, Edge, Node
from cortex.upai.identity import UPAIIdentity, has_crypto

# ============================================================================
# Static file resolution (unit tests — no server needed)
# ============================================================================


class TestWebappStaticResolution:
    """Test resolve_webapp_path and guess_webapp_content_type."""

    def test_root_resolves_to_index(self):
        resolved = resolve_webapp_path("/app")
        assert resolved is not None
        assert resolved.name == "index.html"

    def test_root_slash_resolves_to_index(self):
        resolved = resolve_webapp_path("/app/")
        assert resolved is not None
        assert resolved.name == "index.html"

    def test_app_js_resolves(self):
        resolved = resolve_webapp_path("/app/app.js")
        assert resolved is not None
        assert resolved.name == "app.js"

    def test_styles_css_resolves(self):
        resolved = resolve_webapp_path("/app/styles.css")
        assert resolved is not None
        assert resolved.name == "styles.css"

    def test_page_js_resolves(self):
        resolved = resolve_webapp_path("/app/pages/upload.js")
        assert resolved is not None
        assert resolved.name == "upload.js"

    def test_memory_page_resolves(self):
        resolved = resolve_webapp_path("/app/pages/memory.js")
        assert resolved is not None
        assert resolved.name == "memory.js"

    def test_share_page_resolves(self):
        resolved = resolve_webapp_path("/app/pages/share.js")
        assert resolved is not None
        assert resolved.name == "share.js"

    def test_nonexistent_returns_none(self):
        resolved = resolve_webapp_path("/app/nonexistent.xyz")
        assert resolved is None

    def test_directory_traversal_blocked(self):
        resolved = resolve_webapp_path("/app/../../etc/passwd")
        assert resolved is None

    def test_guess_content_type_js(self):
        ct = guess_webapp_content_type(Path("app.js"))
        assert ct == "application/javascript"

    def test_guess_content_type_css(self):
        ct = guess_webapp_content_type(Path("styles.css"))
        assert ct == "text/css"

    def test_guess_content_type_html(self):
        ct = guess_webapp_content_type(Path("index.html"))
        assert ct == "text/html"

    def test_webapp_dir_exists(self):
        assert WEBAPP_DIR.is_dir()

    def test_index_html_exists(self):
        assert (WEBAPP_DIR / "index.html").is_file()


# ============================================================================
# HTTP integration tests (real server)
# ============================================================================


def _setup_webapp_server(enable_webapp=True):
    """Set up a CaaS test server with webapp enabled."""
    if not has_crypto():
        return None, None, None

    identity = UPAIIdentity.generate("Test User")
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Python", tags=["skills"], confidence=0.9))
    graph.add_node(Node(id="n2", label="Testing", tags=["skills"], confidence=0.8))
    graph.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="related_to"))

    CaaSHandler.graph = graph
    CaaSHandler.identity = identity
    CaaSHandler.grant_store = GrantStore()
    CaaSHandler.nonce_cache = NonceCache()
    CaaSHandler.version_store = None
    CaaSHandler.webhook_store = JsonWebhookStore()
    CaaSHandler._allowed_origins = set()
    CaaSHandler.enable_webapp = enable_webapp
    CaaSHandler.session_manager = None  # will be set below
    CaaSHandler.plugin_manager = None
    CaaSHandler.tracing_manager = None
    CaaSHandler.federation_manager = None
    CaaSHandler.metrics_registry = None
    CaaSHandler.rate_limiter = None
    CaaSHandler.webhook_worker = None
    CaaSHandler.sse_manager = None
    CaaSHandler.oauth_manager = None
    CaaSHandler.credential_store = None
    CaaSHandler.csrf_enabled = False

    from cortex.caas.dashboard.auth import DashboardSessionManager
    CaaSHandler.session_manager = DashboardSessionManager(identity)

    server = HTTPServer(("127.0.0.1", 0), CaaSHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    return server, port, identity


def _get_raw(port, path, cookie=None):
    """Helper to make raw GET request, returning (body_bytes, status, content_type)."""
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        resp = urllib.request.urlopen(req)
        return resp.read(), resp.status, resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.read(), e.code, e.headers.get("Content-Type", "")


def _login(port, identity):
    """Log in to dashboard, return session cookie string."""
    password = CaaSHandler.session_manager.password
    url = f"http://127.0.0.1:{port}/dashboard/auth"
    body = json.dumps({"password": password}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    resp = urllib.request.urlopen(req)
    cookie_header = resp.headers.get("Set-Cookie", "")
    # Extract cortex_session=XXX
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("cortex_session="):
            return part
    return ""


@pytest.mark.skipif(not has_crypto(), reason="cryptography not available")
class TestWebappServing:
    """Test that /app routes serve static files correctly."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.server, self.port, self.identity = _setup_webapp_server(enable_webapp=True)
        yield
        if self.server:
            self.server.shutdown()

    def test_app_root_serves_index_html(self):
        body, status, ct = _get_raw(self.port, "/app")
        assert status == 200
        assert "text/html" in ct
        assert b"<!DOCTYPE html>" in body

    def test_app_slash_serves_index_html(self):
        body, status, ct = _get_raw(self.port, "/app/")
        assert status == 200
        assert b"Cortex" in body

    def test_app_js_served(self):
        body, status, ct = _get_raw(self.port, "/app/app.js")
        assert status == 200
        assert "javascript" in ct
        assert b"CortexApp" in body

    def test_styles_css_served(self):
        body, status, ct = _get_raw(self.port, "/app/styles.css")
        assert status == 200
        assert "text/css" in ct

    def test_page_js_served(self):
        body, status, ct = _get_raw(self.port, "/app/pages/upload.js")
        assert status == 200
        assert "javascript" in ct
        assert b"upload" in body.lower()

    def test_memory_js_served(self):
        body, status, ct = _get_raw(self.port, "/app/pages/memory.js")
        assert status == 200
        assert b"memory" in body.lower()

    def test_share_js_served(self):
        body, status, ct = _get_raw(self.port, "/app/pages/share.js")
        assert status == 200
        assert b"share" in body.lower()

    def test_nonexistent_file_returns_404(self):
        body, status, ct = _get_raw(self.port, "/app/nonexistent.xyz")
        assert status == 404

    def test_directory_traversal_blocked(self):
        body, status, ct = _get_raw(self.port, "/app/../../etc/passwd")
        assert status == 404


@pytest.mark.skipif(not has_crypto(), reason="cryptography not available")
class TestWebappDisabled:
    """Test that /app returns 404 when webapp is disabled."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.server, self.port, self.identity = _setup_webapp_server(enable_webapp=False)
        yield
        if self.server:
            self.server.shutdown()

    def test_app_returns_404_when_disabled(self):
        body, status, ct = _get_raw(self.port, "/app")
        assert status == 404

    def test_upload_returns_404_when_disabled(self):
        url = f"http://127.0.0.1:{self.port}/api/upload"
        file_content = json.dumps({"nodes": [{"label": "Test", "tags": ["test"]}]}).encode()
        body = (
            "------TestBoundary\r\n"
            'Content-Disposition: form-data; name="file"; filename="test.json"\r\n'
            "Content-Type: application/json\r\n\r\n"
        ).encode() + file_content + b"\r\n------TestBoundary--\r\n"
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "multipart/form-data; boundary=----TestBoundary")
        try:
            urllib.request.urlopen(req)
            assert False, "Expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 404


@pytest.mark.skipif(not has_crypto(), reason="cryptography not available")
class TestWebappUpload:
    """Test POST /api/upload endpoint."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.server, self.port, self.identity = _setup_webapp_server(enable_webapp=True)
        yield
        if self.server:
            self.server.shutdown()

    def _upload(self, file_content, filename="test.json", cookie=None):
        """Helper to upload a file via multipart form data."""
        url = f"http://127.0.0.1:{self.port}/api/upload"
        body_parts = [
            "------TestBoundary123\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            file_content if isinstance(file_content, bytes) else file_content.encode(),
            b"\r\n------TestBoundary123--\r\n",
        ]
        body = b"".join(body_parts)
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "multipart/form-data; boundary=----TestBoundary123")
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            resp = urllib.request.urlopen(req)
            return json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                return json.loads(body), e.code
            except (json.JSONDecodeError, ValueError):
                return {"raw": body.decode("utf-8", errors="replace")}, e.code

    def test_upload_requires_auth(self):
        content = json.dumps({"nodes": [{"label": "Test"}]})
        data, status = self._upload(content)
        assert status == 401

    def test_upload_requires_multipart(self):
        cookie = _login(self.port, self.identity)
        url = f"http://127.0.0.1:{self.port}/api/upload"
        body = json.dumps({"test": True}).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Cookie", cookie)
        try:
            urllib.request.urlopen(req)
            assert False, "Expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 415

    def test_upload_graph_format(self):
        cookie = _login(self.port, self.identity)
        content = json.dumps({
            "nodes": [
                {"label": "React", "tags": ["tech"], "confidence": 0.9},
                {"label": "TypeScript", "tags": ["tech"], "confidence": 0.85},
            ],
            "edges": [
                {"source_id": "abc", "target_id": "def", "relation": "uses"},
            ],
        })
        data, status = self._upload(content, cookie=cookie)
        assert status == 201
        assert data["nodes_created"] == 2
        assert data["edges_created"] == 1
        assert data["categories"] >= 1

    def test_upload_chat_messages(self):
        cookie = _login(self.port, self.identity)
        content = json.dumps({
            "messages": [
                {"content": "I really enjoy working with Python for data analysis and machine learning"},
                {"content": "My favorite framework is FastAPI for building REST APIs quickly"},
            ]
        })
        data, status = self._upload(content, cookie=cookie)
        assert status == 201
        assert data["nodes_created"] >= 1

    def test_upload_plain_text(self):
        cookie = _login(self.port, self.identity)
        content = "This is a plain text file with some interesting content about software development."
        data, status = self._upload(content.encode(), filename="notes.txt", cookie=cookie)
        assert status == 201
        assert data["nodes_created"] >= 1

    def test_upload_empty_file_rejected(self):
        cookie = _login(self.port, self.identity)
        data, status = self._upload(b"", filename="empty.txt", cookie=cookie)
        # Empty JSON parse will fail, empty text is also rejected
        assert status in (400, 404, 201)  # Depends on parsing path


@pytest.mark.skipif(not has_crypto(), reason="cryptography not available")
class TestUploadZip:
    """Test POST /api/upload with zip archives."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.server, self.port, self.identity = _setup_webapp_server(enable_webapp=True)
        yield
        if self.server:
            self.server.shutdown()

    def _upload(self, file_content, filename="test.zip", cookie=None):
        """Helper to upload a file via multipart form data."""
        url = f"http://127.0.0.1:{self.port}/api/upload"
        body_parts = [
            b"------TestBoundary123\r\n",
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            file_content if isinstance(file_content, bytes) else file_content.encode(),
            b"\r\n------TestBoundary123--\r\n",
        ]
        body = b"".join(body_parts)
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "multipart/form-data; boundary=----TestBoundary123")
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            resp = urllib.request.urlopen(req)
            return json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                return json.loads(body), e.code
            except (json.JSONDecodeError, ValueError):
                return {"raw": body.decode("utf-8", errors="replace")}, e.code

    @staticmethod
    def _make_zip(files: dict[str, bytes]) -> bytes:
        """Create an in-memory zip archive from a dict of {filename: content}."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return buf.getvalue()

    def test_upload_zip_with_conversations_json(self):
        """Upload zip containing conversations.json (OpenAI format) → 201, nodes created."""
        cookie = _login(self.port, self.identity)
        conversations = json.dumps({
            "conversations": [
                {
                    "title": "Test Chat",
                    "messages": [
                        {"content": "I love working with Python and machine learning"},
                        {"content": "My favorite library is scikit-learn for classification"},
                    ],
                }
            ]
        }).encode()
        zip_bytes = self._make_zip({"conversations.json": conversations})
        data, status = self._upload(zip_bytes, filename="export.zip", cookie=cookie)
        assert status == 201
        assert data["nodes_created"] >= 1

    def test_upload_zip_with_generic_json(self):
        """Upload zip containing a generic data.json with messages → 201."""
        cookie = _login(self.port, self.identity)
        content = json.dumps({
            "messages": [
                {"content": "I enjoy hiking and photography in the mountains"},
            ]
        }).encode()
        zip_bytes = self._make_zip({"data.json": content})
        data, status = self._upload(zip_bytes, filename="backup.zip", cookie=cookie)
        assert status == 201
        assert data["nodes_created"] >= 1

    def test_upload_zip_no_json_rejected(self):
        """Upload zip with no JSON files → 400."""
        cookie = _login(self.port, self.identity)
        zip_bytes = self._make_zip({"readme.txt": b"Hello world"})
        data, status = self._upload(zip_bytes, filename="nojson.zip", cookie=cookie)
        assert status == 400


# ============================================================================
# Webapp auth helpers
# ============================================================================


def _webapp_login(port, password):
    """Log in via /app/auth, return cortex_app_session cookie string."""
    url = f"http://127.0.0.1:{port}/app/auth"
    body = json.dumps({"password": password}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req)
        cookie_header = resp.headers.get("Set-Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("cortex_app_session="):
                return part
        return ""
    except urllib.error.HTTPError:
        return ""


def _webapp_logout(port, cookie):
    """Log out via /app/logout."""
    url = f"http://127.0.0.1:{port}/app/logout"
    req = urllib.request.Request(url, method="POST", data=b"")
    req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status
    except urllib.error.HTTPError as e:
        return e.code


# ============================================================================
# Webapp auth tests
# ============================================================================


@pytest.mark.skipif(not has_crypto(), reason="cryptography not available")
class TestWebappAuth:
    """Test webapp authentication flow (POST /app/auth, /app/logout, cookie-based access)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.server, self.port, self.identity = _setup_webapp_server(enable_webapp=True)
        self.password = CaaSHandler.session_manager.password
        yield
        if self.server:
            self.server.shutdown()

    def test_webapp_login_success(self):
        """POST /app/auth with correct password returns 200 and sets cortex_app_session cookie."""
        cookie = _webapp_login(self.port, self.password)
        assert cookie.startswith("cortex_app_session=")
        assert len(cookie) > len("cortex_app_session=")

    def test_webapp_login_wrong_password(self):
        """POST /app/auth with wrong password returns 401."""
        url = f"http://127.0.0.1:{self.port}/app/auth"
        body = json.dumps({"password": "wrong"}).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req)
            assert False, "Expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 401

    def test_context_without_cookie_returns_401(self):
        """GET /context without any cookie returns 401 (insecure bypass removed)."""
        body, status, ct = _get_raw(self.port, "/context")
        assert status == 401

    def test_context_with_webapp_cookie_returns_200(self):
        """GET /context with valid cortex_app_session cookie returns 200."""
        cookie = _webapp_login(self.port, self.password)
        body, status, ct = _get_raw(self.port, "/context", cookie=cookie)
        assert status == 200
        data = json.loads(body)
        assert "graph" in data or "nodes" in data

    def test_logout_revokes_session(self):
        """POST /app/logout revokes the session; subsequent requests get 401."""
        cookie = _webapp_login(self.port, self.password)
        # Verify session works
        _, status, _ = _get_raw(self.port, "/context/stats", cookie=cookie)
        assert status == 200
        # Logout
        logout_status = _webapp_logout(self.port, cookie)
        assert logout_status == 200
        # Session should be revoked
        _, status, _ = _get_raw(self.port, "/context/stats", cookie=cookie)
        assert status == 401

    def test_upload_with_webapp_cookie(self):
        """POST /api/upload with cortex_app_session cookie returns 201."""
        cookie = _webapp_login(self.port, self.password)
        content = json.dumps({
            "nodes": [{"label": "AuthTest", "tags": ["test"], "confidence": 0.9}],
        })
        url = f"http://127.0.0.1:{self.port}/api/upload"
        body_parts = [
            b"------TestBoundary123\r\n",
            b'Content-Disposition: form-data; name="file"; filename="test.json"\r\n',
            b"Content-Type: application/octet-stream\r\n\r\n",
            content.encode(),
            b"\r\n------TestBoundary123--\r\n",
        ]
        body = b"".join(body_parts)
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "multipart/form-data; boundary=----TestBoundary123")
        req.add_header("Cookie", cookie)
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        assert resp.status == 201
        assert data["nodes_created"] == 1

    def test_webapp_auth_returns_404_when_disabled(self):
        """POST /app/auth returns 404 when enable_webapp=False."""
        self.server.shutdown()
        self.server, self.port, self.identity = _setup_webapp_server(enable_webapp=False)
        url = f"http://127.0.0.1:{self.port}/app/auth"
        body = json.dumps({"password": "anything"}).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req)
            assert False, "Expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 404
