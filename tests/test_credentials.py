"""Tests for cortex.upai.credentials — Verifiable Credentials."""

import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cortex.upai.credentials import (
    W3C_CREDENTIALS_V1,
    CredentialIssuer,
    CredentialStore,
    CredentialVerifier,
    VerifiableCredential,
)
from cortex.upai.identity import UPAIIdentity, has_crypto


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestVerifiableCredential(unittest.TestCase):
    """Test VerifiableCredential dataclass."""

    def test_to_dict_roundtrip(self):
        cred = VerifiableCredential(
            credential_id="test-123",
            context=[W3C_CREDENTIALS_V1],
            credential_type=["VerifiableCredential", "TestCredential"],
            issuer_did="did:key:z6MkTest",
            subject_did="did:key:z6MkSubject",
            issuance_date="2026-01-01T00:00:00+00:00",
            expiration_date="2027-01-01T00:00:00+00:00",
            claims={"role": "Engineer"},
            proof={"type": "Ed25519Signature2020", "proofValue": "abc"},
            status="active",
            bound_node_id="n1",
        )
        d = cred.to_dict()
        self.assertEqual(d["@context"], [W3C_CREDENTIALS_V1])
        self.assertEqual(d["id"], "test-123")
        self.assertEqual(d["type"], ["VerifiableCredential", "TestCredential"])
        self.assertEqual(d["issuer"], "did:key:z6MkTest")
        self.assertEqual(d["credentialSubject"]["id"], "did:key:z6MkSubject")
        self.assertEqual(d["credentialSubject"]["role"], "Engineer")
        self.assertEqual(d["status"], "active")
        self.assertEqual(d["boundNodeId"], "n1")

        # Roundtrip
        cred2 = VerifiableCredential.from_dict(d)
        self.assertEqual(cred2.credential_id, cred.credential_id)
        self.assertEqual(cred2.issuer_did, cred.issuer_did)
        self.assertEqual(cred2.subject_did, cred.subject_did)
        self.assertEqual(cred2.claims, cred.claims)

    def test_w3c_context_present(self):
        cred = VerifiableCredential(
            credential_id="x",
            context=[W3C_CREDENTIALS_V1],
            credential_type=["VerifiableCredential"],
            issuer_did="did:key:z6Mk1",
            subject_did="did:key:z6Mk2",
            issuance_date="2026-01-01T00:00:00+00:00",
            expiration_date="",
            claims={},
            proof={},
            status="active",
            bound_node_id="",
        )
        d = cred.to_dict()
        self.assertIn(W3C_CREDENTIALS_V1, d["@context"])


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestCredentialIssuer(unittest.TestCase):
    """Test credential issuance."""

    def setUp(self):
        self.identity = UPAIIdentity.generate("Test Issuer")
        self.issuer = CredentialIssuer()

    def test_issue_self_signed(self):
        cred = self.issuer.issue(
            identity=self.identity,
            subject_did=self.identity.did,
            credential_type=["VerifiableCredential", "EmploymentCredential"],
            claims={"role": "Engineer", "company": "Acme"},
            ttl_days=365,
            bound_node_id="n1",
        )
        self.assertEqual(cred.issuer_did, self.identity.did)
        self.assertEqual(cred.subject_did, self.identity.did)
        self.assertEqual(cred.claims["role"], "Engineer")
        self.assertEqual(cred.status, "active")
        self.assertEqual(cred.bound_node_id, "n1")
        self.assertIn("VerifiableCredential", cred.credential_type)
        self.assertTrue(cred.expiration_date)

    def test_proof_structure(self):
        cred = self.issuer.issue(
            identity=self.identity,
            subject_did="did:key:z6MkOther",
            credential_type=["VerifiableCredential"],
            claims={"level": "senior"},
        )
        proof = cred.proof
        self.assertIn("type", proof)
        self.assertIn("created", proof)
        self.assertIn("verificationMethod", proof)
        self.assertIn("proofPurpose", proof)
        self.assertIn("proofValue", proof)
        self.assertEqual(proof["proofPurpose"], "assertionMethod")
        self.assertTrue(proof["verificationMethod"].endswith("#key-1"))

    def test_no_expiry(self):
        cred = self.issuer.issue(
            identity=self.identity,
            subject_did=self.identity.did,
            credential_type=["VerifiableCredential"],
            claims={},
            ttl_days=0,
        )
        self.assertEqual(cred.expiration_date, "")

    def test_auto_adds_verifiable_credential_type(self):
        cred = self.issuer.issue(
            identity=self.identity,
            subject_did=self.identity.did,
            credential_type=["CustomType"],
            claims={},
        )
        self.assertIn("VerifiableCredential", cred.credential_type)


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestCredentialVerifier(unittest.TestCase):
    """Test credential verification."""

    def setUp(self):
        self.identity = UPAIIdentity.generate("Verifier Test")
        self.issuer = CredentialIssuer()
        self.verifier = CredentialVerifier()

    def test_verify_valid(self):
        cred = self.issuer.issue(
            identity=self.identity,
            subject_did=self.identity.did,
            credential_type=["VerifiableCredential"],
            claims={"verified": True},
            ttl_days=365,
        )
        valid, err = self.verifier.verify(cred.to_dict(), self.identity.public_key_b64)
        self.assertTrue(valid, f"Verification failed: {err}")
        self.assertEqual(err, "")

    def test_reject_tampered_claims(self):
        cred = self.issuer.issue(
            identity=self.identity,
            subject_did=self.identity.did,
            credential_type=["VerifiableCredential"],
            claims={"role": "Engineer"},
            ttl_days=365,
        )
        d = cred.to_dict()
        d["credentialSubject"]["role"] = "CEO"  # Tamper
        valid, err = self.verifier.verify(d, self.identity.public_key_b64)
        self.assertFalse(valid)
        self.assertIn("signature", err)

    def test_reject_expired(self):
        cred = self.issuer.issue(
            identity=self.identity,
            subject_did=self.identity.did,
            credential_type=["VerifiableCredential"],
            claims={},
            ttl_days=365,
        )
        d = cred.to_dict()
        # Set expiration to the past
        d["expirationDate"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        valid, err = self.verifier.verify(d, self.identity.public_key_b64)
        self.assertFalse(valid)
        self.assertIn("expired", err)

    def test_reject_wrong_issuer_key(self):
        other_identity = UPAIIdentity.generate("Other")
        cred = self.issuer.issue(
            identity=self.identity,
            subject_did=self.identity.did,
            credential_type=["VerifiableCredential"],
            claims={},
            ttl_days=365,
        )
        valid, err = self.verifier.verify(cred.to_dict(), other_identity.public_key_b64)
        self.assertFalse(valid)
        self.assertIn("signature", err)

    def test_check_status_active(self):
        cred = self.issuer.issue(
            identity=self.identity,
            subject_did=self.identity.did,
            credential_type=["VerifiableCredential"],
            claims={},
            ttl_days=365,
        )
        self.assertEqual(self.verifier.check_status(cred), "active")

    def test_check_status_revoked(self):
        cred = self.issuer.issue(
            identity=self.identity,
            subject_did=self.identity.did,
            credential_type=["VerifiableCredential"],
            claims={},
        )
        cred.status = "revoked"
        self.assertEqual(self.verifier.check_status(cred), "revoked")

    def test_reject_revoked_credential(self):
        cred = self.issuer.issue(
            identity=self.identity,
            subject_did=self.identity.did,
            credential_type=["VerifiableCredential"],
            claims={},
            ttl_days=365,
        )
        d = cred.to_dict()
        d["status"] = "revoked"
        valid, err = self.verifier.verify(d, self.identity.public_key_b64)
        self.assertFalse(valid)
        self.assertIn("revoked", err)


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestCredentialStore(unittest.TestCase):
    """Test credential storage."""

    def setUp(self):
        self.identity = UPAIIdentity.generate("Store Test")
        self.issuer = CredentialIssuer()
        self.tmpdir = tempfile.mkdtemp()
        self.store_path = str(Path(self.tmpdir) / "creds.json")

    def _make_cred(self, node_id=""):
        return self.issuer.issue(
            identity=self.identity,
            subject_did=self.identity.did,
            credential_type=["VerifiableCredential"],
            claims={"test": True},
            bound_node_id=node_id,
        )

    def test_add_and_get(self):
        store = CredentialStore(self.store_path)
        cred = self._make_cred()
        store.add(cred)
        retrieved = store.get(cred.credential_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.credential_id, cred.credential_id)

    def test_list_all(self):
        store = CredentialStore(self.store_path)
        store.add(self._make_cred())
        store.add(self._make_cred())
        self.assertEqual(len(store.list_all()), 2)

    def test_list_by_node(self):
        store = CredentialStore(self.store_path)
        store.add(self._make_cred(node_id="n1"))
        store.add(self._make_cred(node_id="n2"))
        store.add(self._make_cred(node_id="n1"))
        self.assertEqual(len(store.list_by_node("n1")), 2)
        self.assertEqual(len(store.list_by_node("n2")), 1)
        self.assertEqual(len(store.list_by_node("n3")), 0)

    def test_revoke(self):
        store = CredentialStore(self.store_path)
        cred = self._make_cred()
        store.add(cred)
        self.assertTrue(store.revoke(cred.credential_id))
        retrieved = store.get(cred.credential_id)
        self.assertEqual(retrieved.status, "revoked")

    def test_revoke_nonexistent(self):
        store = CredentialStore(self.store_path)
        self.assertFalse(store.revoke("nonexistent"))

    def test_delete(self):
        store = CredentialStore(self.store_path)
        cred = self._make_cred()
        store.add(cred)
        self.assertTrue(store.delete(cred.credential_id))
        self.assertIsNone(store.get(cred.credential_id))
        self.assertEqual(store.count, 0)

    def test_persistence(self):
        store1 = CredentialStore(self.store_path)
        cred = self._make_cred()
        store1.add(cred)

        # Load from same file
        store2 = CredentialStore(self.store_path)
        self.assertEqual(store2.count, 1)
        retrieved = store2.get(cred.credential_id)
        self.assertEqual(retrieved.credential_id, cred.credential_id)

    def test_thread_safety(self):
        store = CredentialStore(self.store_path)
        errors = []

        def add_creds():
            try:
                for _ in range(10):
                    store.add(self._make_cred())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_creds) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(store.count, 40)

    def test_count_property(self):
        store = CredentialStore(self.store_path)
        self.assertEqual(store.count, 0)
        store.add(self._make_cred())
        self.assertEqual(store.count, 1)


if __name__ == "__main__":
    unittest.main()
