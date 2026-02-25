"""Tests for cortex.upai.discovery — DID resolution and configuration."""

import json
import threading
import unittest
import urllib.error
import urllib.request

from cortex.upai.discovery import DIDResolver, UPAIConfiguration
from cortex.upai.identity import UPAIIdentity, has_crypto


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestDIDResolver(unittest.TestCase):
    """Test DID resolution."""

    def setUp(self):
        self.resolver = DIDResolver()
        self.identity = UPAIIdentity.generate("Resolver Test")

    def test_resolve_local_did(self):
        doc = self.resolver.resolve(self.identity.did, identity=self.identity)
        self.assertIsNotNone(doc)
        self.assertEqual(doc["id"], self.identity.did)
        self.assertIn("verificationMethod", doc)

    def test_resolve_local_with_service_endpoints(self):
        endpoints = [{"id": f"{self.identity.did}#caas", "type": "ContextService",
                       "serviceEndpoint": "http://localhost:8421"}]
        doc = self.resolver.resolve(self.identity.did, identity=self.identity,
                                     service_endpoints=endpoints)
        self.assertIn("service", doc)
        self.assertEqual(len(doc["service"]), 1)

    def test_resolve_did_key(self):
        doc = self.resolver.resolve_did_key(self.identity.did)
        self.assertIsNotNone(doc)
        self.assertEqual(doc["id"], self.identity.did)
        self.assertEqual(doc["@context"], "https://www.w3.org/ns/did/v1")
        self.assertEqual(len(doc["verificationMethod"]), 1)
        vm = doc["verificationMethod"][0]
        self.assertEqual(vm["type"], "Ed25519VerificationKey2020")
        self.assertIn("publicKeyMultibase", vm)

    def test_resolve_unknown_method(self):
        doc = self.resolver.resolve("did:unknown:12345")
        self.assertIsNone(doc)

    def test_resolve_did_key_invalid(self):
        doc = self.resolver.resolve_did_key("did:key:invalid")
        self.assertIsNone(doc)

    def test_resolve_did_key_via_dispatch(self):
        """Test that resolve() dispatches did:key correctly."""
        doc = self.resolver.resolve(self.identity.did)
        self.assertIsNotNone(doc)
        self.assertEqual(doc["id"], self.identity.did)

    def test_resolve_mismatched_local_did(self):
        """Resolving a local DID that doesn't match the identity returns None."""
        other = UPAIIdentity.generate("Other")
        doc = self.resolver.resolve("did:upai:sha256:nonexistent", identity=other)
        self.assertIsNone(doc)


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestDIDKeyResolution(unittest.TestCase):
    """Test did:key resolution with known patterns."""

    def test_roundtrip(self):
        """Generate identity, resolve did:key, verify public key matches."""
        identity = UPAIIdentity.generate("Roundtrip")
        resolver = DIDResolver()
        doc = resolver.resolve_did_key(identity.did)
        self.assertIsNotNone(doc)

        vm = doc["verificationMethod"][0]
        multibase = vm["publicKeyMultibase"]
        self.assertTrue(multibase.startswith("z"))

    def test_multiple_identities(self):
        """Different identities produce different DID documents."""
        resolver = DIDResolver()
        id1 = UPAIIdentity.generate("A")
        id2 = UPAIIdentity.generate("B")
        doc1 = resolver.resolve_did_key(id1.did)
        doc2 = resolver.resolve_did_key(id2.did)
        self.assertNotEqual(doc1["id"], doc2["id"])

    def test_resolve_did_key_32_byte_key(self):
        """Ensure did:key resolution produces 32-byte Ed25519 key."""
        identity = UPAIIdentity.generate("KeyLen")
        resolver = DIDResolver()
        doc = resolver.resolve_did_key(identity.did)
        self.assertIsNotNone(doc)
        # The verification method should exist
        self.assertEqual(len(doc["verificationMethod"]), 1)


class TestUPAIConfiguration(unittest.TestCase):
    """Test UPAIConfiguration dataclass."""

    def test_to_dict_roundtrip(self):
        config = UPAIConfiguration(
            server_url="http://localhost:8421",
            did="did:key:z6MkTest",
            supported_policies=["full", "professional", "minimal"],
            supported_scopes=["context:read", "context:subscribe"],
            version="1.0",
        )
        d = config.to_dict()
        self.assertEqual(d["server_url"], "http://localhost:8421")
        self.assertEqual(d["did"], "did:key:z6MkTest")
        self.assertEqual(d["version"], "1.0")
        self.assertEqual(len(d["supported_policies"]), 3)

        config2 = UPAIConfiguration.from_dict(d)
        self.assertEqual(config2.server_url, config.server_url)
        self.assertEqual(config2.did, config.did)
        self.assertEqual(config2.supported_policies, config.supported_policies)

    def test_default_version(self):
        config = UPAIConfiguration(
            server_url="http://localhost",
            did="did:key:z6Mk1",
            supported_policies=[],
            supported_scopes=[],
        )
        self.assertEqual(config.version, "1.0")


# ── Integration tests for discovery routes ───────────────────────────


def _setup_server():
    if not has_crypto():
        return None, None, None, None

    from cortex.caas.dashboard.auth import DashboardSessionManager
    from cortex.caas.server import CaaSHandler, JsonGrantStore, NonceCache, ThreadingHTTPServer
    from cortex.caas.storage import JsonWebhookStore
    from cortex.graph import CortexGraph
    from cortex.upai.credentials import CredentialStore
    from cortex.upai.disclosure import PolicyRegistry

    identity = UPAIIdentity.generate("Discovery Test")
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
    CaaSHandler.login_rate_limiter = None
    CaaSHandler.oauth_manager = None
    CaaSHandler.credential_store = CredentialStore()
    CaaSHandler.sse_manager = None
    CaaSHandler.keychain = None

    server = ThreadingHTTPServer(("127.0.0.1", 0), CaaSHandler)
    port = server.server_address[1]
    CaaSHandler._allowed_origins = {f"http://127.0.0.1:{port}"}

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server, port, identity, None


def _request(port, path):
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw), resp.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return json.loads(raw), e.code
        except (json.JSONDecodeError, ValueError):
            return raw.decode(), e.code


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestDiscoveryRoutes(unittest.TestCase):
    """Integration tests for discovery endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port, cls.identity, _ = _setup_server()

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()

    def test_well_known_configuration(self):
        body, status = _request(self.port, "/.well-known/upai-configuration")
        self.assertEqual(status, 200)
        self.assertEqual(body["upai_version"], "1.0")
        self.assertEqual(body["did"], self.identity.did)
        self.assertIn("supported_policies", body)
        self.assertIn("supported_scopes", body)
        self.assertIn("credentials", body.get("endpoints", {}))

    def test_resolve_local_did(self):
        did_encoded = urllib.request.quote(self.identity.did, safe="")
        body, status = _request(self.port, f"/resolve/{did_encoded}")
        self.assertEqual(status, 200)
        self.assertEqual(body["id"], self.identity.did)
        self.assertIn("verificationMethod", body)

    def test_resolve_unknown_did(self):
        body, status = _request(self.port, "/resolve/did:unknown:12345")
        self.assertEqual(status, 404)

    def test_info_includes_discovery(self):
        body, status = _request(self.port, "/")
        self.assertEqual(status, 200)
        self.assertIn("discovery", body)


if __name__ == "__main__":
    unittest.main()
