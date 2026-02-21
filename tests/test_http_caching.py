"""
Tests for WP-5.4: HTTP Caching & Conditional Requests.

Covers:
- ETag generation (format, determinism, variation)
- If-None-Match → 304 responses
- Cache-Control header profiles per route
- Integration with real server
"""

from __future__ import annotations

import http.client
import threading

import pytest

from cortex.caas.caching import (
    CacheProfile,
    check_if_none_match,
    generate_etag,
    get_cache_profile,
)

# ── ETag generation ──────────────────────────────────────────────────────


class TestETagGeneration:
    def test_format(self):
        etag = generate_etag(b'{"hello": "world"}')
        assert etag.startswith('W/"')
        assert etag.endswith('"')
        # 16 hex chars inside quotes
        inner = etag[3:-1]
        assert len(inner) == 16

    def test_same_body_same_etag(self):
        body = b'{"data": [1, 2, 3]}'
        assert generate_etag(body) == generate_etag(body)

    def test_different_body_different_etag(self):
        assert generate_etag(b"body1") != generate_etag(b"body2")

    def test_empty_body(self):
        etag = generate_etag(b"")
        assert etag.startswith('W/"')


# ── If-None-Match checking ───────────────────────────────────────────────


class TestConditionalRequests:
    def test_exact_match_returns_true(self):
        etag = generate_etag(b"test")
        assert check_if_none_match(etag, etag) is True

    def test_mismatch_returns_false(self):
        assert check_if_none_match('W/"aaa"', 'W/"bbb"') is False

    def test_wildcard_matches(self):
        assert check_if_none_match("*", 'W/"anything"') is True

    def test_comma_separated_list(self):
        etag = 'W/"abc123def45678"'
        header = 'W/"xxxxxxxxxxxxxxxx", W/"abc123def45678"'
        assert check_if_none_match(header, etag) is True

    def test_empty_header(self):
        assert check_if_none_match("", 'W/"abc"') is False

    def test_empty_etag(self):
        assert check_if_none_match('W/"abc"', "") is False


# ── Cache profiles ───────────────────────────────────────────────────────


class TestCacheProfiles:
    def test_identity_has_max_age(self):
        profile = get_cache_profile("/identity")
        assert profile.max_age == 300
        assert "max-age=300" in profile.to_header()

    def test_discovery_has_max_age(self):
        profile = get_cache_profile("/.well-known/upai-configuration")
        assert profile.max_age == 300

    def test_context_has_no_cache(self):
        profile = get_cache_profile("/context")
        assert profile.no_cache is True
        assert "no-cache" in profile.to_header()

    def test_context_nodes_has_no_cache(self):
        profile = get_cache_profile("/context/nodes")
        assert profile.no_cache is True

    def test_credentials_has_no_cache(self):
        profile = get_cache_profile("/credentials")
        assert profile.no_cache is True

    def test_health_has_short_max_age(self):
        profile = get_cache_profile("/health")
        assert profile.max_age == 10
        assert "max-age=10" in profile.to_header()

    def test_unknown_path_no_store(self):
        profile = get_cache_profile("/something/unknown")
        assert profile.no_store is True
        assert profile.to_header() == "no-store"

    def test_grants_no_store(self):
        profile = get_cache_profile("/grants")
        assert profile.no_store is True


class TestCacheProfileHeader:
    def test_no_store(self):
        p = CacheProfile(no_store=True)
        assert p.to_header() == "no-store"

    def test_no_cache(self):
        p = CacheProfile(no_cache=True)
        assert p.to_header() == "no-cache"

    def test_max_age(self):
        p = CacheProfile(max_age=60)
        assert p.to_header() == "max-age=60"

    def test_immutable(self):
        p = CacheProfile(max_age=86400, immutable=True)
        header = p.to_header()
        assert "max-age=86400" in header
        assert "immutable" in header


# ── Integration tests ────────────────────────────────────────────────────


class TestCachingIntegration:
    @pytest.fixture(autouse=True)
    def _setup_server(self):
        from cortex.caas.server import CaaSHandler, JsonGrantStore, ThreadingHTTPServer
        from cortex.caas.storage import JsonWebhookStore
        from cortex.graph import CortexGraph, Node
        from cortex.upai.disclosure import PolicyRegistry
        from cortex.upai.identity import UPAIIdentity
        from cortex.upai.tokens import VALID_SCOPES, GrantToken

        self.identity = UPAIIdentity.generate(name="test-caching")
        graph = CortexGraph()
        graph.add_node(Node(id="n1", label="Test", tags=["identity"], confidence=0.9))

        CaaSHandler.graph = graph
        CaaSHandler.identity = self.identity
        CaaSHandler.grant_store = JsonGrantStore()
        CaaSHandler.audit_log = None
        CaaSHandler.metrics_registry = None
        CaaSHandler.rate_limiter = None
        CaaSHandler.webhook_worker = None
        CaaSHandler.sse_manager = None
        CaaSHandler.session_manager = None
        CaaSHandler.oauth_manager = None
        CaaSHandler.credential_store = None
        CaaSHandler.keychain = None
        CaaSHandler.webhook_store = JsonWebhookStore()
        CaaSHandler.policy_registry = PolicyRegistry()
        CaaSHandler._allowed_origins = {"http://127.0.0.1:0"}
        CaaSHandler.version_store = None
        CaaSHandler.nonce_cache = __import__(
            "cortex.caas.server", fromlist=["NonceCache"]
        ).NonceCache()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), CaaSHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        token = GrantToken.create(self.identity, audience="test", scopes=list(VALID_SCOPES))
        self.token_str = token.sign(self.identity)
        CaaSHandler.grant_store.add(token.grant_id, self.token_str, token.to_dict())
        yield
        self.server.shutdown()

    def _get(self, path: str, headers: dict | None = None) -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdrs = {"Authorization": f"Bearer {self.token_str}"}
        if headers:
            hdrs.update(headers)
        conn.request("GET", path, headers=hdrs)
        return conn.getresponse()

    def test_etag_in_response(self):
        resp = self._get("/health")
        resp.read()
        etag = resp.getheader("ETag")
        assert etag is not None
        assert etag.startswith('W/"')

    def test_conditional_304(self):
        # First request to get ETag
        resp1 = self._get("/context/nodes")
        resp1.read()
        etag = resp1.getheader("ETag")
        assert etag is not None

        # Second request with If-None-Match
        resp2 = self._get("/context/nodes", headers={"If-None-Match": etag})
        body = resp2.read()
        assert resp2.status == 304
        assert len(body) == 0

    def test_different_data_returns_200(self):
        resp1 = self._get("/health")
        resp1.read()
        etag = resp1.getheader("ETag")

        # Request a different endpoint — different ETag
        resp2 = self._get("/", headers={"If-None-Match": etag})
        resp2.read()
        # Different data should return 200 (etag won't match)
        assert resp2.status == 200

    def test_cache_control_on_identity(self):
        resp = self._get("/identity")
        resp.read()
        cc = resp.getheader("Cache-Control")
        assert "max-age=300" in cc

    def test_cache_control_on_context(self):
        resp = self._get("/context/nodes")
        resp.read()
        cc = resp.getheader("Cache-Control")
        assert "no-cache" in cc

    def test_cache_control_no_store_default(self):
        resp = self._get("/")
        resp.read()
        cc = resp.getheader("Cache-Control")
        assert cc == "no-store"

    def test_304_has_no_body_but_has_headers(self):
        resp1 = self._get("/health")
        resp1.read()
        etag = resp1.getheader("ETag")

        resp2 = self._get("/health", headers={"If-None-Match": etag})
        body = resp2.read()
        assert resp2.status == 304
        assert len(body) == 0
        assert resp2.getheader("ETag") == etag
