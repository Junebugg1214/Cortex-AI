"""Integration tests for credential API routes in CaaS server."""

import json
import threading
import unittest
import urllib.error
import urllib.request

from cortex.upai.credentials import CredentialStore
from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.upai.tokens import GrantToken


def _setup_server():
    """Start a CaaS server for testing. Returns (server, port, identity, token_str)."""
    if not has_crypto():
        return None, None, None, None

    from cortex.caas.dashboard.auth import DashboardSessionManager
    from cortex.caas.server import CaaSHandler, JsonGrantStore, NonceCache, ThreadingHTTPServer
    from cortex.caas.storage import JsonWebhookStore
    from cortex.graph import CortexGraph
    from cortex.upai.disclosure import PolicyRegistry

    identity = UPAIIdentity.generate("Cred Test")
    graph = CortexGraph()

    CaaSHandler.identity = identity
    CaaSHandler.graph = graph
    CaaSHandler.grant_store = JsonGrantStore()
    CaaSHandler.nonce_cache = NonceCache()
    CaaSHandler.webhook_store = JsonWebhookStore()
    CaaSHandler.policy_registry = PolicyRegistry()
    CaaSHandler.session_manager = DashboardSessionManager(identity)
    CaaSHandler.audit_log = None
    CaaSHandler.webhook_worker = None
    CaaSHandler.metrics_registry = None
    CaaSHandler.rate_limiter = None
    CaaSHandler.oauth_manager = None
    CaaSHandler.credential_store = CredentialStore()
    CaaSHandler.sse_manager = None
    CaaSHandler.keychain = None

    server = ThreadingHTTPServer(("127.0.0.1", 0), CaaSHandler)
    port = server.server_address[1]
    CaaSHandler._allowed_origins = {f"http://127.0.0.1:{port}"}

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Create a grant token
    token = GrantToken.create(identity, audience="test", scopes=[
        "context:read", "context:subscribe", "credentials:read", "credentials:write",
    ])
    token_str = token.sign(identity)
    CaaSHandler.grant_store.add(token.grant_id, token_str, token.to_dict())

    return server, port, identity, token_str


def _request(port, path, method="GET", body=None, headers=None):
    """Make HTTP request. Returns (body, status_code, response_headers)."""
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            ct = resp.headers.get("Content-Type", "")
            if "json" in ct:
                return json.loads(raw), resp.status, dict(resp.headers)
            return raw.decode("utf-8", errors="replace"), resp.status, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return json.loads(raw), e.code, dict(e.headers)
        except (json.JSONDecodeError, ValueError):
            return raw.decode("utf-8", errors="replace"), e.code, dict(e.headers)


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestCredentialCRUD(unittest.TestCase):
    """Test credential CRUD operations via API."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port, cls.identity, cls.token = _setup_server()

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _session_headers(self):
        sm = self.server.RequestHandlerClass.session_manager
        token = sm.authenticate(sm._derive_password())
        return {"Cookie": f"cortex_session={token}"}

    def test_create_credential(self):
        body, status, _ = _request(self.port, "/credentials", method="POST", body={
            "credential_type": ["VerifiableCredential", "TestCredential"],
            "subject_did": self.identity.did,
            "claims": {"role": "Tester"},
            "ttl_days": 30,
        }, headers=self._auth_headers())
        self.assertEqual(status, 201)
        self.assertIn("id", body)
        self.assertEqual(body["issuer"], self.identity.did)
        self.assertEqual(body["credentialSubject"]["role"], "Tester")

    def test_list_credentials(self):
        # Create one first
        _request(self.port, "/credentials", method="POST", body={
            "credential_type": ["VerifiableCredential"],
            "subject_did": self.identity.did,
            "claims": {"list_test": True},
        }, headers=self._auth_headers())

        body, status, _ = _request(self.port, "/credentials",
                                    headers=self._auth_headers())
        self.assertEqual(status, 200)
        self.assertIn("credentials", body)
        self.assertGreater(len(body["credentials"]), 0)

    def test_get_credential_by_id(self):
        # Create
        create_body, _, _ = _request(self.port, "/credentials", method="POST", body={
            "credential_type": ["VerifiableCredential"],
            "subject_did": self.identity.did,
            "claims": {"detail_test": True},
        }, headers=self._auth_headers())

        cred_id = create_body["id"]
        body, status, _ = _request(self.port, f"/credentials/{cred_id}",
                                    headers=self._auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(body["id"], cred_id)

    def test_delete_credential(self):
        # Create
        create_body, _, _ = _request(self.port, "/credentials", method="POST", body={
            "credential_type": ["VerifiableCredential"],
            "subject_did": self.identity.did,
            "claims": {},
        }, headers=self._auth_headers())

        cred_id = create_body["id"]
        # Delete requires dashboard session
        body, status, _ = _request(self.port, f"/credentials/{cred_id}",
                                    method="DELETE", headers=self._session_headers())
        self.assertEqual(status, 200)
        self.assertTrue(body["deleted"])

    def test_get_nonexistent(self):
        body, status, _ = _request(self.port, "/credentials/nonexistent",
                                    headers=self._auth_headers())
        self.assertEqual(status, 404)


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestCredentialFiltering(unittest.TestCase):
    """Test credential filtering by node_id."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port, cls.identity, cls.token = _setup_server()

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_filter_by_node_id(self):
        # Create bound credential
        _request(self.port, "/credentials", method="POST", body={
            "credential_type": ["VerifiableCredential"],
            "subject_did": self.identity.did,
            "claims": {},
            "bound_node_id": "filter-node-1",
        }, headers=self._auth_headers())

        body, status, _ = _request(self.port, "/credentials?node_id=filter-node-1",
                                    headers=self._auth_headers())
        self.assertEqual(status, 200)
        for cred in body["credentials"]:
            self.assertEqual(cred["boundNodeId"], "filter-node-1")


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestCredentialVerification(unittest.TestCase):
    """Test credential verification endpoint."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port, cls.identity, cls.token = _setup_server()

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_verify_credential(self):
        # Create
        create_body, _, _ = _request(self.port, "/credentials", method="POST", body={
            "credential_type": ["VerifiableCredential"],
            "subject_did": self.identity.did,
            "claims": {"verify_test": True},
            "ttl_days": 365,
        }, headers=self._auth_headers())

        cred_id = create_body["id"]
        body, status, _ = _request(self.port, f"/credentials/{cred_id}/verify",
                                    method="POST", headers=self._auth_headers())
        self.assertEqual(status, 200)
        self.assertTrue(body["valid"])
        self.assertEqual(body["status"], "active")


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestCredentialAuth(unittest.TestCase):
    """Test credential endpoint authentication."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port, cls.identity, cls.token = _setup_server()

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()

    def test_unauthenticated_get(self):
        body, status, _ = _request(self.port, "/credentials")
        self.assertEqual(status, 401)

    def test_unauthenticated_post(self):
        body, status, _ = _request(self.port, "/credentials", method="POST", body={
            "credential_type": ["VerifiableCredential"],
            "subject_did": "did:key:z6MkTest",
            "claims": {},
        })
        self.assertEqual(status, 401)

    def test_wrong_scope(self):
        # Create token with only versions:read scope
        token = GrantToken.create(self.identity, audience="test", scopes=["versions:read"])
        token_str = token.sign(self.identity)
        self.server.RequestHandlerClass.grant_store.add(token.grant_id, token_str, token.to_dict())

        body, status, _ = _request(self.port, "/credentials",
                                    headers={"Authorization": f"Bearer {token_str}"})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
