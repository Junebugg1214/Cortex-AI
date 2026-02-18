"""
Integration tests for CaaS OAuth routes.

Uses the same HTTPServer-on-random-port pattern as test_dashboard_v2.py.
OAuth provider calls are mocked (no network required).
"""

import json
import secrets
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from unittest.mock import patch, MagicMock

from cortex.graph import CortexGraph, Node, Edge
from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.caas.server import CaaSHandler, GrantStore, NonceCache
from cortex.caas.storage import JsonWebhookStore
from cortex.caas.dashboard.auth import DashboardSessionManager
from cortex.caas.oauth import (
    OAuthManager, OAuthProviderConfig,
    GOOGLE_ENDPOINTS, GITHUB_ENDPOINTS,
)

SKIP_REASON = "Ed25519 crypto not available"


def _build_test_graph() -> CortexGraph:
    g = CortexGraph()
    g.add_node(Node(id="n1", label="Marc", tags=["identity"], confidence=0.95,
                     brief="Software developer"))
    return g


def _setup_server(oauth_providers=None, oauth_allowed_emails=None):
    """Set up test server with optional OAuth."""
    if not has_crypto():
        return None, None, None, None

    identity = UPAIIdentity.generate("OAuth Test")
    graph = _build_test_graph()

    CaaSHandler.graph = graph
    CaaSHandler.identity = identity
    CaaSHandler.grant_store = GrantStore()
    CaaSHandler.nonce_cache = NonceCache()
    CaaSHandler.version_store = None
    CaaSHandler.webhook_store = JsonWebhookStore()
    CaaSHandler.audit_log = None
    CaaSHandler.rate_limiter = None
    CaaSHandler.webhook_worker = None
    CaaSHandler._allowed_origins = set()

    sm = DashboardSessionManager(identity)
    CaaSHandler.session_manager = sm

    server = HTTPServer(("127.0.0.1", 0), CaaSHandler)
    port = server.server_address[1]
    CaaSHandler._allowed_origins = {f"http://127.0.0.1:{port}"}

    if oauth_providers:
        import hashlib
        pk = identity._private_key or identity.did.encode()
        state_secret = hashlib.sha256(pk + b"cortex-oauth-state").digest()
        CaaSHandler.oauth_manager = OAuthManager(
            providers=oauth_providers,
            state_secret=state_secret,
            redirect_base=f"http://127.0.0.1:{port}",
            allowed_emails=oauth_allowed_emails,
        )
    else:
        CaaSHandler.oauth_manager = None

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    return server, port, identity, sm


def _request(port, path, method="GET", body=None, headers=None, follow_redirects=False):
    """Make HTTP request. Returns (body, status_code, response_headers)."""
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    if not follow_redirects:
        # Use a custom opener that does NOT follow redirects
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise urllib.error.HTTPError(
                    newurl, code, msg, headers, fp
                )
        opener = urllib.request.build_opener(NoRedirectHandler)
    else:
        opener = urllib.request.build_opener()

    try:
        resp = opener.open(req)
        ct = resp.headers.get("Content-Type", "")
        raw = resp.read()
        if "json" in ct:
            return json.loads(raw), resp.status, dict(resp.headers)
        return raw.decode("utf-8", errors="replace"), resp.status, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        ct = e.headers.get("Content-Type", "")
        if "json" in ct:
            return json.loads(raw), e.code, dict(e.headers)
        return raw.decode("utf-8", errors="replace"), e.code, dict(e.headers)


def _make_google_provider():
    return {
        "google": OAuthProviderConfig(
            name="google",
            client_id="test-google-id",
            client_secret="test-google-secret",
            **GOOGLE_ENDPOINTS,
        ),
    }


class TestOAuthProviderEndpoint(unittest.TestCase):
    """Test GET /dashboard/oauth/providers."""

    @classmethod
    def setUpClass(cls):
        providers = _make_google_provider()
        cls.server, cls.port, cls.identity, cls.sm = _setup_server(
            oauth_providers=providers
        )

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_providers_returns_list(self):
        body, status, _ = _request(self.port, "/dashboard/oauth/providers")
        self.assertEqual(status, 200)
        self.assertIn("google", body["providers"])

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_providers_no_auth_required(self):
        """The providers endpoint should work without authentication."""
        body, status, _ = _request(self.port, "/dashboard/oauth/providers")
        self.assertEqual(status, 200)


class TestOAuthAuthorize(unittest.TestCase):
    """Test GET /dashboard/oauth/authorize."""

    @classmethod
    def setUpClass(cls):
        providers = _make_google_provider()
        cls.server, cls.port, cls.identity, cls.sm = _setup_server(
            oauth_providers=providers
        )

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_authorize_redirects_to_google(self):
        _, status, headers = _request(
            self.port,
            "/dashboard/oauth/authorize?provider=google",
        )
        self.assertEqual(status, 302)
        location = headers.get("Location", "")
        self.assertIn("accounts.google.com", location)
        self.assertIn("client_id=test-google-id", location)

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_authorize_unknown_provider(self):
        _, status, headers = _request(
            self.port,
            "/dashboard/oauth/authorize?provider=unknown",
        )
        self.assertEqual(status, 302)
        location = headers.get("Location", "")
        self.assertIn("oauth_error=unknown_provider", location)

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_authorize_missing_provider(self):
        _, status, headers = _request(
            self.port,
            "/dashboard/oauth/authorize",
        )
        self.assertEqual(status, 302)
        location = headers.get("Location", "")
        self.assertIn("oauth_error=missing_provider", location)


class TestOAuthCallback(unittest.TestCase):
    """Test GET /dashboard/oauth/callback."""

    @classmethod
    def setUpClass(cls):
        providers = _make_google_provider()
        cls.server, cls.port, cls.identity, cls.sm = _setup_server(
            oauth_providers=providers
        )

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_callback_invalid_state(self):
        _, status, headers = _request(
            self.port,
            "/dashboard/oauth/callback?code=testcode&state=badstate",
        )
        self.assertEqual(status, 302)
        location = headers.get("Location", "")
        self.assertIn("oauth_error=invalid_state", location)

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_callback_missing_code(self):
        _, status, headers = _request(
            self.port,
            "/dashboard/oauth/callback?state=somestate",
        )
        self.assertEqual(status, 302)
        location = headers.get("Location", "")
        self.assertIn("oauth_error=missing_code_or_state", location)

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_callback_provider_error(self):
        _, status, headers = _request(
            self.port,
            "/dashboard/oauth/callback?error=access_denied",
        )
        self.assertEqual(status, 302)
        location = headers.get("Location", "")
        self.assertIn("oauth_error=provider_error", location)


class TestTokenExchange(unittest.TestCase):
    """Test POST /api/token-exchange."""

    @classmethod
    def setUpClass(cls):
        providers = _make_google_provider()
        cls.server, cls.port, cls.identity, cls.sm = _setup_server(
            oauth_providers=providers,
            oauth_allowed_emails={"allowed@example.com"},
        )

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    @patch("cortex.caas.oauth.validate_google_id_token")
    def test_exchange_success(self, mock_validate):
        mock_validate.return_value = {"email": "allowed@example.com", "sub": "12345"}
        body, status, _ = _request(
            self.port,
            "/api/token-exchange",
            method="POST",
            body={
                "provider": "google",
                "token": "fake-id-token",
                "audience": "test-app",
            },
        )
        self.assertEqual(status, 201)
        self.assertIn("grant_id", body)
        self.assertIn("token", body)

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    @patch("cortex.caas.oauth.validate_google_id_token")
    def test_exchange_disallowed_email(self, mock_validate):
        mock_validate.return_value = {"email": "notallowed@example.com", "sub": "999"}
        body, status, _ = _request(
            self.port,
            "/api/token-exchange",
            method="POST",
            body={
                "provider": "google",
                "token": "fake-id-token",
                "audience": "test-app",
            },
        )
        self.assertEqual(status, 403)

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_exchange_missing_fields(self):
        body, status, _ = _request(
            self.port,
            "/api/token-exchange",
            method="POST",
            body={"provider": "google"},
        )
        self.assertEqual(status, 400)

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_exchange_unsupported_provider(self):
        body, status, _ = _request(
            self.port,
            "/api/token-exchange",
            method="POST",
            body={"provider": "facebook", "token": "tok", "audience": "app"},
        )
        self.assertEqual(status, 400)


class TestOAuthDisabled(unittest.TestCase):
    """Test server without OAuth configured."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port, cls.identity, cls.sm = _setup_server(
            oauth_providers=None
        )

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_providers_returns_empty(self):
        body, status, _ = _request(self.port, "/dashboard/oauth/providers")
        self.assertEqual(status, 200)
        self.assertEqual(body["providers"], [])

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_authorize_redirects_with_error(self):
        _, status, headers = _request(
            self.port,
            "/dashboard/oauth/authorize?provider=google",
        )
        self.assertEqual(status, 302)
        location = headers.get("Location", "")
        self.assertIn("oauth_error", location)

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_token_exchange_not_configured(self):
        body, status, _ = _request(
            self.port,
            "/api/token-exchange",
            method="POST",
            body={"provider": "google", "token": "tok", "audience": "app"},
        )
        self.assertEqual(status, 503)


class TestDashboardSessionManagerOAuth(unittest.TestCase):
    """Test the OAuth session creation in DashboardSessionManager."""

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_create_oauth_session(self):
        identity = UPAIIdentity.generate("Test")
        sm = DashboardSessionManager(identity)
        token = sm.create_oauth_session("google", "user@example.com", "User")
        self.assertTrue(sm.validate(token))

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_oauth_session_meta(self):
        identity = UPAIIdentity.generate("Test")
        sm = DashboardSessionManager(identity)
        token = sm.create_oauth_session("github", "dev@example.com", "Dev")
        meta = sm.get_session_meta(token)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["auth_method"], "oauth")
        self.assertEqual(meta["provider"], "github")
        self.assertEqual(meta["email"], "dev@example.com")

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_revoke_cleans_meta(self):
        identity = UPAIIdentity.generate("Test")
        sm = DashboardSessionManager(identity)
        token = sm.create_oauth_session("google", "user@example.com")
        sm.revoke(token)
        self.assertFalse(sm.validate(token))
        self.assertIsNone(sm.get_session_meta(token))

    @unittest.skipUnless(has_crypto(), SKIP_REASON)
    def test_password_session_no_meta(self):
        identity = UPAIIdentity.generate("Test")
        sm = DashboardSessionManager(identity)
        token = sm.authenticate(sm.password)
        self.assertIsNotNone(token)
        self.assertIsNone(sm.get_session_meta(token))


if __name__ == "__main__":
    unittest.main()
