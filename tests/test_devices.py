"""Tests for device management in keychain and device API routes."""

import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path

from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.upai.keychain import Keychain, DeviceRecord


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestDeviceRecord(unittest.TestCase):
    """Test DeviceRecord dataclass."""

    def test_to_dict_roundtrip(self):
        record = DeviceRecord(
            device_id="dev-123",
            device_name="MacBook Pro",
            device_did="did:key:z6MkDevice",
            device_public_key_b64="AAAA==",
            authorized_at="2026-01-01T00:00:00+00:00",
            authorized_by_did="did:key:z6MkPrimary",
            authorization_proof="sig123",
            revoked_at="",
        )
        d = record.to_dict()
        self.assertEqual(d["device_id"], "dev-123")
        self.assertEqual(d["device_name"], "MacBook Pro")
        self.assertEqual(d["revoked_at"], "")

        record2 = DeviceRecord.from_dict(d)
        self.assertEqual(record2.device_id, record.device_id)
        self.assertEqual(record2.device_name, record.device_name)
        self.assertEqual(record2.device_did, record.device_did)


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestKeychainDevices(unittest.TestCase):
    """Test device management in Keychain."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store_dir = Path(self.tmpdir)
        self.identity = UPAIIdentity.generate("Device Test")
        self.identity.save(self.store_dir)
        self.keychain = Keychain(self.store_dir)

    def test_authorize_device(self):
        record, device_identity = self.keychain.authorize_device(self.identity, "Test Device")
        self.assertEqual(record.device_name, "Test Device")
        self.assertTrue(record.device_did.startswith("did:key:"))
        self.assertEqual(record.authorized_by_did, self.identity.did)
        self.assertTrue(record.authorization_proof)
        self.assertFalse(record.revoked_at)
        self.assertIsNotNone(device_identity._private_key)

    def test_revoke_device(self):
        record, _ = self.keychain.authorize_device(self.identity, "Revoke Me")
        revoked_at = self.keychain.revoke_device(record.device_id)
        self.assertTrue(revoked_at)

        device = self.keychain.get_device(record.device_id)
        self.assertTrue(device.revoked_at)

    def test_revoke_nonexistent(self):
        result = self.keychain.revoke_device("nonexistent")
        self.assertEqual(result, "")

    def test_list_devices(self):
        self.keychain.authorize_device(self.identity, "Device A")
        self.keychain.authorize_device(self.identity, "Device B")
        devices = self.keychain.list_devices()
        self.assertEqual(len(devices), 2)

    def test_get_device(self):
        record, _ = self.keychain.authorize_device(self.identity, "Get Me")
        found = self.keychain.get_device(record.device_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.device_name, "Get Me")

    def test_get_device_nonexistent(self):
        self.assertIsNone(self.keychain.get_device("nonexistent"))

    def test_is_device_authorized(self):
        record, _ = self.keychain.authorize_device(self.identity, "Auth Check")
        self.assertTrue(self.keychain.is_device_authorized(record.device_did))

        self.keychain.revoke_device(record.device_id)
        self.assertFalse(self.keychain.is_device_authorized(record.device_did))

    def test_is_device_authorized_unknown(self):
        self.assertFalse(self.keychain.is_device_authorized("did:key:z6MkUnknown"))

    def test_persistence_roundtrip(self):
        self.keychain.authorize_device(self.identity, "Persist Me")

        # Reload
        kc2 = Keychain(self.store_dir)
        devices = kc2.list_devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].device_name, "Persist Me")

    def test_authorization_proof_is_valid(self):
        """Verify the authorization proof is a valid signature by the primary identity."""
        record, _ = self.keychain.authorize_device(self.identity, "Proof Test")

        # Reconstruct signed data
        auth_data = json.dumps({
            "action": "authorize_device",
            "primary_did": self.identity.did,
            "device_did": record.device_did,
            "device_name": "Proof Test",
            "timestamp": record.authorized_at,
        }, sort_keys=True).encode("utf-8")

        valid = UPAIIdentity.verify(
            auth_data, record.authorization_proof, self.identity.public_key_b64
        )
        self.assertTrue(valid)


# ── Integration tests for device API routes ──────────────────────────


def _setup_server():
    if not has_crypto():
        return None, None, None, None

    from cortex.caas.server import CaaSHandler, ThreadingHTTPServer, NonceCache, JsonGrantStore
    from cortex.caas.storage import JsonWebhookStore
    from cortex.caas.dashboard.auth import DashboardSessionManager
    from cortex.upai.disclosure import PolicyRegistry
    from cortex.upai.credentials import CredentialStore
    from cortex.graph import CortexGraph

    tmpdir = tempfile.mkdtemp()
    store_dir = Path(tmpdir)
    identity = UPAIIdentity.generate("Device API Test")
    identity.save(store_dir)
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
    CaaSHandler.keychain = Keychain(store_dir)

    server = ThreadingHTTPServer(("127.0.0.1", 0), CaaSHandler)
    port = server.server_address[1]
    CaaSHandler._allowed_origins = {f"http://127.0.0.1:{port}"}

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server, port, identity, CaaSHandler.session_manager


def _request(port, path, method="GET", body=None, headers=None):
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
            return json.loads(raw), resp.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return json.loads(raw), e.code
        except (json.JSONDecodeError, ValueError):
            return raw.decode(), e.code


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestDeviceAPI(unittest.TestCase):
    """Integration tests for device endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port, cls.identity, cls.sm = _setup_server()

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()

    def _session_headers(self):
        token = self.sm.authenticate(self.sm._derive_password())
        return {"Cookie": f"cortex_session={token}"}

    def test_create_device(self):
        body, status = _request(self.port, "/dashboard/api/devices",
                                 method="POST",
                                 body={"device_name": "API Test Device"},
                                 headers=self._session_headers())
        self.assertEqual(status, 201)
        self.assertIn("device_id", body)
        self.assertEqual(body["device_name"], "API Test Device")
        self.assertTrue(body["device_did"].startswith("did:key:"))

    def test_list_devices(self):
        body, status = _request(self.port, "/dashboard/api/devices",
                                 headers=self._session_headers())
        self.assertEqual(status, 200)
        self.assertIn("devices", body)

    def test_revoke_device(self):
        # Create
        create_body, _ = _request(self.port, "/dashboard/api/devices",
                                   method="POST",
                                   body={"device_name": "Revoke API Test"},
                                   headers=self._session_headers())
        device_id = create_body["device_id"]

        # Revoke
        body, status = _request(self.port, f"/dashboard/api/devices/{device_id}",
                                 method="DELETE", headers=self._session_headers())
        self.assertEqual(status, 200)
        self.assertTrue(body["revoked"])

    def test_unauthenticated_create(self):
        body, status = _request(self.port, "/dashboard/api/devices",
                                 method="POST",
                                 body={"device_name": "Unauth"})
        self.assertEqual(status, 401)

    def test_create_missing_name(self):
        body, status = _request(self.port, "/dashboard/api/devices",
                                 method="POST",
                                 body={},
                                 headers=self._session_headers())
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
