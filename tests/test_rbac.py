"""
Tests for WP-5.1: RBAC & Fine-Grained Access Control.

Covers:
- Role definitions and scope mappings
- Scope inference from scope sets
- Grant creation with role
- Backward compatibility (old tokens without role)
- Route enforcement for all newly-protected routes
- Dashboard session bypasses RBAC
- Unauthorized access scenarios
"""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from cortex.upai.rbac import (
    ALL_SCOPES,
    VALID_ROLES,
    infer_role,
    role_has_scope,
    scopes_for_role,
)
from cortex.upai.tokens import (
    SCOPE_CONTEXT_READ,
    SCOPE_CREDENTIALS_READ,
    SCOPE_CREDENTIALS_WRITE,
    SCOPE_DEVICES_MANAGE,
    SCOPE_GRANTS_MANAGE,
    SCOPE_IDENTITY_READ,
    SCOPE_POLICIES_MANAGE,
    SCOPE_VERSIONS_READ,
    SCOPE_WEBHOOKS_MANAGE,
    VALID_SCOPES,
    GrantToken,
)

# ── Role definitions ─────────────────────────────────────────────────────


class TestRoleDefinitions:
    def test_owner_has_all_scopes(self):
        assert scopes_for_role("owner") == ALL_SCOPES
        assert len(scopes_for_role("owner")) == 11

    def test_admin_has_all_except_devices(self):
        admin = scopes_for_role("admin")
        assert "devices:manage" not in admin
        assert len(admin) == 10

    def test_reader_scopes(self):
        reader = scopes_for_role("reader")
        assert reader == {"context:read", "versions:read", "identity:read", "credentials:read"}

    def test_subscriber_scopes(self):
        subscriber = scopes_for_role("subscriber")
        assert subscriber == {"context:read", "context:subscribe", "identity:read"}

    def test_unknown_role_returns_empty(self):
        assert scopes_for_role("unknown") == set()

    def test_valid_roles(self):
        assert VALID_ROLES == {"owner", "admin", "editor", "reader", "subscriber"}


class TestRoleHasScope:
    def test_owner_has_grants_manage(self):
        assert role_has_scope("owner", "grants:manage")

    def test_reader_has_context_read(self):
        assert role_has_scope("reader", "context:read")

    def test_reader_lacks_webhooks_manage(self):
        assert not role_has_scope("reader", "webhooks:manage")

    def test_subscriber_has_subscribe(self):
        assert role_has_scope("subscriber", "context:subscribe")

    def test_subscriber_lacks_versions(self):
        assert not role_has_scope("subscriber", "versions:read")

    def test_unknown_role_has_nothing(self):
        assert not role_has_scope("unknown", "context:read")


# ── Scope inference ──────────────────────────────────────────────────────


class TestScopeInference:
    def test_infer_owner(self):
        assert infer_role(ALL_SCOPES) == "owner"

    def test_infer_reader(self):
        assert infer_role({"context:read", "versions:read", "identity:read", "credentials:read"}) == "reader"

    def test_infer_subscriber(self):
        assert infer_role({"context:read", "context:subscribe", "identity:read"}) == "subscriber"

    def test_infer_admin(self):
        assert infer_role(ALL_SCOPES - {"devices:manage"}) == "admin"

    def test_infer_custom(self):
        assert infer_role({"context:read", "webhooks:manage"}) == "custom"

    def test_infer_empty(self):
        assert infer_role(set()) == "custom"


# ── Token role field ─────────────────────────────────────────────────────


class TestTokenRoleField:
    def test_role_in_to_dict(self):
        from cortex.upai.identity import UPAIIdentity
        identity = UPAIIdentity.generate("test-role")
        token = GrantToken.create(identity, audience="test")
        token.role = "reader"
        d = token.to_dict()
        assert d["role"] == "reader"

    def test_no_role_field_when_empty(self):
        from cortex.upai.identity import UPAIIdentity
        identity = UPAIIdentity.generate("test-role")
        token = GrantToken.create(identity, audience="test")
        d = token.to_dict()
        assert "role" not in d

    def test_role_roundtrip(self):
        from cortex.upai.identity import UPAIIdentity
        identity = UPAIIdentity.generate("test-role")
        token = GrantToken.create(identity, audience="test")
        token.role = "admin"
        d = token.to_dict()
        restored = GrantToken.from_dict(d)
        assert restored.role == "admin"

    def test_backward_compat_missing_role(self):
        d = {
            "grant_id": "g1",
            "subject_did": "did:upai:test",
            "issuer_did": "did:upai:test",
            "audience": "test",
            "policy": "professional",
            "scopes": ["context:read"],
            "issued_at": "2024-01-01T00:00:00",
            "expires_at": "2025-01-01T00:00:00",
        }
        token = GrantToken.from_dict(d)
        assert token.role == ""
        assert token.scopes == ["context:read"]


# ── VALID_SCOPES constant ──────────────────────────────────────────────


class TestValidScopes:
    def test_ten_scopes(self):
        assert len(VALID_SCOPES) == 11

    def test_all_scope_constants(self):
        assert SCOPE_CONTEXT_READ in VALID_SCOPES
        assert SCOPE_VERSIONS_READ in VALID_SCOPES
        assert SCOPE_IDENTITY_READ in VALID_SCOPES
        assert SCOPE_CREDENTIALS_READ in VALID_SCOPES
        assert SCOPE_CREDENTIALS_WRITE in VALID_SCOPES
        assert SCOPE_WEBHOOKS_MANAGE in VALID_SCOPES
        assert SCOPE_POLICIES_MANAGE in VALID_SCOPES
        assert SCOPE_GRANTS_MANAGE in VALID_SCOPES
        assert SCOPE_DEVICES_MANAGE in VALID_SCOPES


# ── Integration: route enforcement ───────────────────────────────────────


class TestRouteEnforcement:
    """Test that routes enforce correct scopes."""

    @pytest.fixture(autouse=True)
    def _setup_server(self):
        from cortex.caas.server import CaaSHandler, JsonGrantStore, ThreadingHTTPServer
        from cortex.caas.storage import JsonWebhookStore
        from cortex.graph import CortexGraph
        from cortex.upai.disclosure import PolicyRegistry
        from cortex.upai.identity import UPAIIdentity

        self.identity = UPAIIdentity.generate(name="test-rbac")
        graph = CortexGraph()

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

        # Create tokens with different scopes
        self._grant_store = CaaSHandler.grant_store
        yield
        self.server.shutdown()

    def _make_token(self, scopes: list[str]) -> str:
        token = GrantToken.create(self.identity, audience="test", scopes=scopes)
        token_str = token.sign(self.identity)
        self._grant_store.add(token.grant_id, token_str, token.to_dict())
        return token_str

    def _get(self, path: str, token: str | None = None) -> tuple:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, json.loads(body) if body else {}

    def _post(self, path: str, data: dict, token: str | None = None) -> tuple:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request("POST", path, body=json.dumps(data), headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, json.loads(body) if body else {}

    def _delete(self, path: str, token: str | None = None) -> tuple:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request("DELETE", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, json.loads(body) if body else {}

    # ── Grant routes require grants:manage ────────────────────────────

    def test_create_grant_requires_grants_manage(self):
        reader_token = self._make_token(["context:read"])
        status, _ = self._post("/grants", {"audience": "test"}, token=reader_token)
        assert status == 403

    def test_create_grant_succeeds_with_grants_manage(self):
        admin_token = self._make_token(["grants:manage"])
        status, data = self._post("/grants", {"audience": "test", "policy": "professional"}, token=admin_token)
        assert status == 201

    def test_list_grants_requires_grants_manage(self):
        reader_token = self._make_token(["context:read"])
        status, _ = self._get("/grants", token=reader_token)
        assert status == 403

    def test_revoke_grant_requires_grants_manage(self):
        # Create a grant first
        admin_token = self._make_token(list(VALID_SCOPES))
        _, data = self._post("/grants", {"audience": "rtest", "policy": "professional"}, token=admin_token)
        gid = data["grant_id"]

        reader_token = self._make_token(["context:read"])
        status, _ = self._delete(f"/grants/{gid}", token=reader_token)
        assert status == 403

    # ── Webhook routes require webhooks:manage ────────────────────────

    def test_create_webhook_requires_webhooks_manage(self):
        reader_token = self._make_token(["context:read"])
        status, _ = self._post("/webhooks", {"url": "http://test.com/hook"}, token=reader_token)
        assert status == 403

    def test_list_webhooks_requires_webhooks_manage(self):
        reader_token = self._make_token(["context:read"])
        status, _ = self._get("/webhooks", token=reader_token)
        assert status == 403

    def test_delete_webhook_requires_webhooks_manage(self):
        reader_token = self._make_token(["context:read"])
        status, _ = self._delete("/webhooks/fake-id", token=reader_token)
        assert status == 403

    # ── Policy routes ─────────────────────────────────────────────────

    def test_list_policies_allows_any_token(self):
        reader_token = self._make_token(["context:read"])
        status, data = self._get("/policies", token=reader_token)
        assert status == 200

    def test_get_policy_allows_any_token(self):
        reader_token = self._make_token(["identity:read"])
        status, _ = self._get("/policies/professional", token=reader_token)
        assert status == 200

    def test_create_policy_requires_policies_manage(self):
        reader_token = self._make_token(["context:read"])
        status, _ = self._post("/policies", {"name": "test-pol"}, token=reader_token)
        assert status == 403

    def test_delete_policy_requires_policies_manage(self):
        reader_token = self._make_token(["context:read"])
        status, _ = self._delete("/policies/test-pol", token=reader_token)
        assert status == 403

    # ── Credential routes ─────────────────────────────────────────────

    def test_credentials_list_requires_credentials_read(self):
        t = self._make_token(["context:read"])
        status, _ = self._get("/credentials", token=t)
        assert status == 403

    def test_credentials_read_with_correct_scope(self):
        t = self._make_token(["credentials:read"])
        status, data = self._get("/credentials", token=t)
        # 200 with empty list since no credential store configured
        assert status == 200

    # ── No auth = 401 ─────────────────────────────────────────────────

    def test_grants_no_auth_401(self):
        status, _ = self._get("/grants")
        assert status == 401

    def test_webhooks_no_auth_401(self):
        status, _ = self._get("/webhooks")
        assert status == 401

    def test_policies_no_auth_401(self):
        status, _ = self._get("/policies")
        assert status == 401


# ── Grant creation with role ──────────────────────────────────────────


class TestGrantCreationWithRole:
    @pytest.fixture(autouse=True)
    def _setup_server(self):
        from cortex.caas.server import CaaSHandler, JsonGrantStore, ThreadingHTTPServer
        from cortex.caas.storage import JsonWebhookStore
        from cortex.graph import CortexGraph
        from cortex.upai.disclosure import PolicyRegistry
        from cortex.upai.identity import UPAIIdentity

        self.identity = UPAIIdentity.generate(name="test-role-grant")
        graph = CortexGraph()

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

        # Owner token for creating grants
        owner = GrantToken.create(self.identity, audience="test", scopes=list(VALID_SCOPES))
        self.owner_token = owner.sign(self.identity)
        CaaSHandler.grant_store.add(owner.grant_id, self.owner_token, owner.to_dict())
        yield
        self.server.shutdown()

    def _post(self, data: dict) -> tuple:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/grants", body=json.dumps(data),
                     headers={"Content-Type": "application/json",
                              "Authorization": f"Bearer {self.owner_token}"})
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, json.loads(body) if body else {}

    def test_create_with_role_reader(self):
        status, data = self._post({"audience": "test", "role": "reader"})
        assert status == 201
        assert data["role"] == "reader"
        assert set(data["scopes"]) == scopes_for_role("reader")

    def test_create_with_role_subscriber(self):
        status, data = self._post({"audience": "test", "role": "subscriber"})
        assert status == 201
        assert "context:subscribe" in data["scopes"]
        assert "webhooks:manage" not in data["scopes"]

    def test_create_with_role_owner(self):
        status, data = self._post({"audience": "test", "role": "owner"})
        assert status == 201
        assert set(data["scopes"]) == ALL_SCOPES

    def test_create_with_unknown_role_fails(self):
        status, data = self._post({"audience": "test", "role": "superadmin"})
        assert status == 400

    def test_role_overrides_scopes(self):
        # Even if scopes are provided, role takes precedence
        status, data = self._post({
            "audience": "test",
            "role": "reader",
            "scopes": list(ALL_SCOPES),
        })
        assert status == 201
        assert set(data["scopes"]) == scopes_for_role("reader")


# ── Backward compatibility ───────────────────────────────────────────


class TestBackwardCompatibility:
    def test_old_token_without_role_still_works(self):
        """Old tokens without role field should continue working."""
        from cortex.upai.identity import UPAIIdentity

        identity = UPAIIdentity.generate("compat-test")
        # Create token with only old scopes (no role)
        token = GrantToken.create(identity, audience="old-app",
                                  scopes=["context:read", "versions:read", "identity:read"])
        assert token.role == ""
        d = token.to_dict()
        assert "role" not in d

        # Verify it round-trips
        restored = GrantToken.from_dict(d)
        assert restored.role == ""
        assert restored.has_scope("context:read")
        assert restored.has_scope("versions:read")

    def test_old_scopes_remain_valid(self):
        """The original 4 scopes are still in VALID_SCOPES."""
        old_scopes = {"context:read", "context:subscribe", "versions:read", "identity:read"}
        assert old_scopes.issubset(VALID_SCOPES)


# ── Discovery lists all scopes ──────────────────────────────────────


class TestDiscoveryScopes:
    @pytest.fixture(autouse=True)
    def _setup_server(self):
        from cortex.caas.server import CaaSHandler, JsonGrantStore, ThreadingHTTPServer
        from cortex.caas.storage import JsonWebhookStore
        from cortex.graph import CortexGraph
        from cortex.upai.disclosure import PolicyRegistry
        from cortex.upai.identity import UPAIIdentity

        identity = UPAIIdentity.generate(name="test-disc")
        graph = CortexGraph()

        CaaSHandler.graph = graph
        CaaSHandler.identity = identity
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
        yield
        self.server.shutdown()

    def test_discovery_has_all_10_scopes(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/.well-known/upai-configuration")
        resp = conn.getresponse()
        data = json.loads(resp.read())
        assert set(data["supported_scopes"]) == VALID_SCOPES
