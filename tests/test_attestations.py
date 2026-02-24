"""Tests for cortex.upai.attestations — Peer Attestation Protocol (Feature 3)."""

from __future__ import annotations

import json
import unittest

from cortex.upai.attestations import (
    ATTESTATION_TYPES,
    AttestationRequest,
    create_attestation_request,
    get_attestation_summary,
    get_attestations_for_node,
    sign_attestation,
    validate_attestation_claims,
)
from cortex.upai.credentials import (
    CredentialIssuer,
    CredentialStore,
    CredentialVerifier,
    VerifiableCredential,
)
from cortex.upai.identity import UPAIIdentity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_identity(name: str = "Alice") -> UPAIIdentity:
    return UPAIIdentity.generate(name=name)


# ---------------------------------------------------------------------------
# AttestationTypes
# ---------------------------------------------------------------------------

class TestAttestationTypes(unittest.TestCase):

    def test_all_types_defined(self):
        self.assertIn("EmploymentAttestation", ATTESTATION_TYPES)
        self.assertIn("SkillEndorsement", ATTESTATION_TYPES)
        self.assertIn("ReferenceAttestation", ATTESTATION_TYPES)

    def test_each_type_has_required_claims(self):
        for name, type_def in ATTESTATION_TYPES.items():
            self.assertIn("required_claims", type_def, f"{name} missing required_claims")
            self.assertIn("optional_claims", type_def, f"{name} missing optional_claims")
            self.assertIsInstance(type_def["required_claims"], list)
            self.assertIsInstance(type_def["optional_claims"], list)

    def test_employment_required_claims(self):
        req = ATTESTATION_TYPES["EmploymentAttestation"]["required_claims"]
        self.assertIn("subject_name", req)
        self.assertIn("employer", req)
        self.assertIn("role", req)
        self.assertIn("relationship", req)

    def test_skill_required_claims(self):
        req = ATTESTATION_TYPES["SkillEndorsement"]["required_claims"]
        self.assertIn("subject_name", req)
        self.assertIn("skill", req)
        self.assertIn("proficiency_level", req)

    def test_reference_required_claims(self):
        req = ATTESTATION_TYPES["ReferenceAttestation"]["required_claims"]
        self.assertIn("subject_name", req)
        self.assertIn("relationship", req)
        self.assertIn("reference_text", req)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidateClaims(unittest.TestCase):

    def test_valid_employment_claims(self):
        claims = {
            "subject_name": "Alice",
            "employer": "Acme",
            "role": "Engineer",
            "relationship": "Manager",
        }
        errors = validate_attestation_claims("EmploymentAttestation", claims)
        self.assertEqual(errors, [])

    def test_missing_required_field(self):
        claims = {"subject_name": "Alice", "employer": "Acme"}
        errors = validate_attestation_claims("EmploymentAttestation", claims)
        self.assertTrue(any("role" in e for e in errors))
        self.assertTrue(any("relationship" in e for e in errors))

    def test_unknown_type(self):
        errors = validate_attestation_claims("UnknownType", {})
        self.assertTrue(any("unknown attestation type" in e for e in errors))

    def test_unknown_claim_warned(self):
        claims = {
            "subject_name": "Alice",
            "employer": "Acme",
            "role": "SWE",
            "relationship": "Manager",
            "banana": "yellow",
        }
        errors = validate_attestation_claims("EmploymentAttestation", claims)
        self.assertTrue(any("banana" in e for e in errors))

    def test_empty_required_field(self):
        claims = {
            "subject_name": "",
            "employer": "Acme",
            "role": "SWE",
            "relationship": "Manager",
        }
        errors = validate_attestation_claims("EmploymentAttestation", claims)
        self.assertTrue(any("subject_name" in e for e in errors))

    def test_valid_skill_endorsement(self):
        claims = {
            "subject_name": "Alice",
            "skill": "Python",
            "proficiency_level": "Expert",
        }
        errors = validate_attestation_claims("SkillEndorsement", claims)
        self.assertEqual(errors, [])

    def test_valid_reference(self):
        claims = {
            "subject_name": "Alice",
            "relationship": "Colleague",
            "reference_text": "Alice is amazing",
        }
        errors = validate_attestation_claims("ReferenceAttestation", claims)
        self.assertEqual(errors, [])

    def test_optional_claims_accepted(self):
        claims = {
            "subject_name": "Alice",
            "employer": "Acme",
            "role": "SWE",
            "relationship": "Manager",
            "start_date": "2020-01-01",
            "description": "Worked on systems",
        }
        errors = validate_attestation_claims("EmploymentAttestation", claims)
        self.assertEqual(errors, [])


# ---------------------------------------------------------------------------
# AttestationRequest
# ---------------------------------------------------------------------------

class TestAttestationRequest(unittest.TestCase):

    def test_creation(self):
        req = AttestationRequest(
            request_id="r1",
            subject_did="did:key:zAlice",
            attestor_did="did:key:zBob",
            attestation_type="EmploymentAttestation",
            bound_node_id="node123",
            proposed_claims={"subject_name": "Alice"},
            created_at="2024-01-01T00:00:00Z",
        )
        self.assertEqual(req.request_id, "r1")
        self.assertEqual(req.attestation_type, "EmploymentAttestation")

    def test_serialization_roundtrip(self):
        req = AttestationRequest(
            request_id="r2",
            subject_did="did:key:zAlice",
            attestor_did="did:key:zBob",
            attestation_type="SkillEndorsement",
            bound_node_id="",
            proposed_claims={"skill": "Python"},
            created_at="2024-01-01T00:00:00Z",
        )
        d = req.to_dict()
        restored = AttestationRequest.from_dict(d)
        self.assertEqual(restored.request_id, "r2")
        self.assertEqual(restored.attestation_type, "SkillEndorsement")
        self.assertEqual(restored.proposed_claims, {"skill": "Python"})

    def test_signing_request_with_envelope(self):
        identity = _make_identity("Alice")
        req, envelope = create_attestation_request(
            identity=identity,
            attestor_did="did:key:zBob",
            attestation_type="EmploymentAttestation",
            proposed_claims={
                "subject_name": "Alice",
                "employer": "Acme",
                "role": "SWE",
                "relationship": "Manager",
            },
            bound_node_id="node123",
        )
        self.assertTrue(req.request_id)
        self.assertEqual(req.subject_did, identity.did)
        self.assertEqual(req.attestor_did, "did:key:zBob")
        # Envelope should be serializable
        serialized = envelope.serialize()
        self.assertIn(".", serialized)


# ---------------------------------------------------------------------------
# Sign attestation
# ---------------------------------------------------------------------------

class TestSignAttestation(unittest.TestCase):

    def test_valid_signing(self):
        subject = _make_identity("Alice")
        attestor = _make_identity("Bob")

        req, _ = create_attestation_request(
            identity=subject,
            attestor_did=attestor.did,
            attestation_type="EmploymentAttestation",
            proposed_claims={
                "subject_name": "Alice",
                "employer": "Acme",
                "role": "Engineer",
                "relationship": "Manager",
            },
            bound_node_id="node123",
        )

        cred = sign_attestation(
            attestor_identity=attestor,
            request=req,
            claims={
                "subject_name": "Alice",
                "employer": "Acme",
                "role": "Engineer",
                "relationship": "Manager",
            },
        )

        self.assertEqual(cred.issuer_did, attestor.did)
        self.assertEqual(cred.subject_did, subject.did)
        self.assertIn("EmploymentAttestation", cred.credential_type)
        self.assertEqual(cred.bound_node_id, "node123")
        self.assertEqual(cred.status, "active")

    def test_invalid_claims_rejected(self):
        subject = _make_identity("Alice")
        attestor = _make_identity("Bob")

        req, _ = create_attestation_request(
            identity=subject,
            attestor_did=attestor.did,
            attestation_type="EmploymentAttestation",
            proposed_claims={"subject_name": "Alice"},
            bound_node_id="",
        )

        with self.assertRaises(ValueError):
            sign_attestation(
                attestor_identity=attestor,
                request=req,
                claims={"subject_name": "Alice"},  # Missing required
            )

    def test_bound_node_id_set(self):
        subject = _make_identity("Alice")
        attestor = _make_identity("Bob")

        req, _ = create_attestation_request(
            identity=subject,
            attestor_did=attestor.did,
            attestation_type="SkillEndorsement",
            proposed_claims={
                "subject_name": "Alice",
                "skill": "Python",
                "proficiency_level": "Expert",
            },
            bound_node_id="skill-node-42",
        )

        cred = sign_attestation(
            attestor_identity=attestor,
            request=req,
            claims={
                "subject_name": "Alice",
                "skill": "Python",
                "proficiency_level": "Expert",
            },
        )
        self.assertEqual(cred.bound_node_id, "skill-node-42")


# ---------------------------------------------------------------------------
# GetAttestationsForNode
# ---------------------------------------------------------------------------

class TestGetAttestationsForNode(unittest.TestCase):

    def test_filter_by_bound_node_id(self):
        store = CredentialStore()
        subject = _make_identity("Alice")
        attestor = _make_identity("Bob")

        req, _ = create_attestation_request(
            identity=subject,
            attestor_did=attestor.did,
            attestation_type="EmploymentAttestation",
            proposed_claims={
                "subject_name": "Alice",
                "employer": "Acme",
                "role": "SWE",
                "relationship": "Manager",
            },
            bound_node_id="node-A",
        )
        cred_a = sign_attestation(attestor, req, {
            "subject_name": "Alice",
            "employer": "Acme",
            "role": "SWE",
            "relationship": "Manager",
        })
        store.add(cred_a)

        # Different node
        req2, _ = create_attestation_request(
            identity=subject,
            attestor_did=attestor.did,
            attestation_type="SkillEndorsement",
            proposed_claims={
                "subject_name": "Alice",
                "skill": "Python",
                "proficiency_level": "Expert",
            },
            bound_node_id="node-B",
        )
        cred_b = sign_attestation(attestor, req2, {
            "subject_name": "Alice",
            "skill": "Python",
            "proficiency_level": "Expert",
        })
        store.add(cred_b)

        result = get_attestations_for_node(store, "node-A")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].bound_node_id, "node-A")

    def test_empty_store(self):
        store = CredentialStore()
        result = get_attestations_for_node(store, "nonexistent")
        self.assertEqual(result, [])

    def test_multiple_attestors(self):
        store = CredentialStore()
        subject = _make_identity("Alice")

        for name in ["Bob", "Carol"]:
            attestor = _make_identity(name)
            req, _ = create_attestation_request(
                identity=subject,
                attestor_did=attestor.did,
                attestation_type="SkillEndorsement",
                proposed_claims={
                    "subject_name": "Alice",
                    "skill": "Python",
                    "proficiency_level": "Expert",
                },
                bound_node_id="skill-py",
            )
            cred = sign_attestation(attestor, req, {
                "subject_name": "Alice",
                "skill": "Python",
                "proficiency_level": "Expert",
            })
            store.add(cred)

        result = get_attestations_for_node(store, "skill-py")
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# Cross-identity attestation
# ---------------------------------------------------------------------------

class TestCrossIdentity(unittest.TestCase):

    def test_issuer_not_equal_subject(self):
        subject = _make_identity("Alice")
        attestor = _make_identity("Bob")

        req, _ = create_attestation_request(
            identity=subject,
            attestor_did=attestor.did,
            attestation_type="ReferenceAttestation",
            proposed_claims={
                "subject_name": "Alice",
                "relationship": "Colleague",
                "reference_text": "Great engineer",
            },
        )

        cred = sign_attestation(attestor, req, {
            "subject_name": "Alice",
            "relationship": "Colleague",
            "reference_text": "Great engineer",
        })

        self.assertNotEqual(cred.issuer_did, cred.subject_did)
        self.assertEqual(cred.issuer_did, attestor.did)
        self.assertEqual(cred.subject_did, subject.did)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

class TestVerification(unittest.TestCase):

    def test_verify_with_attestor_public_key(self):
        subject = _make_identity("Alice")
        attestor = _make_identity("Bob")

        req, _ = create_attestation_request(
            identity=subject,
            attestor_did=attestor.did,
            attestation_type="EmploymentAttestation",
            proposed_claims={
                "subject_name": "Alice",
                "employer": "Acme",
                "role": "SWE",
                "relationship": "Manager",
            },
        )

        cred = sign_attestation(attestor, req, {
            "subject_name": "Alice",
            "employer": "Acme",
            "role": "SWE",
            "relationship": "Manager",
        })

        verifier = CredentialVerifier()
        ok, err = verifier.verify(cred.to_dict(), attestor.public_key_b64)
        self.assertTrue(ok, f"Verification failed: {err}")

    def test_reject_tampered_credential(self):
        subject = _make_identity("Alice")
        attestor = _make_identity("Bob")

        req, _ = create_attestation_request(
            identity=subject,
            attestor_did=attestor.did,
            attestation_type="EmploymentAttestation",
            proposed_claims={
                "subject_name": "Alice",
                "employer": "Acme",
                "role": "SWE",
                "relationship": "Manager",
            },
        )

        cred = sign_attestation(attestor, req, {
            "subject_name": "Alice",
            "employer": "Acme",
            "role": "SWE",
            "relationship": "Manager",
        })

        # Tamper with the credential
        cred_dict = cred.to_dict()
        cred_dict["credentialSubject"]["role"] = "CEO"

        verifier = CredentialVerifier()
        ok, err = verifier.verify(cred_dict, attestor.public_key_b64)
        self.assertFalse(ok)
        self.assertIn("invalid signature", err)

    def test_reject_wrong_key(self):
        subject = _make_identity("Alice")
        attestor = _make_identity("Bob")
        wrong_key_identity = _make_identity("Eve")

        req, _ = create_attestation_request(
            identity=subject,
            attestor_did=attestor.did,
            attestation_type="SkillEndorsement",
            proposed_claims={
                "subject_name": "Alice",
                "skill": "Python",
                "proficiency_level": "Expert",
            },
        )

        cred = sign_attestation(attestor, req, {
            "subject_name": "Alice",
            "skill": "Python",
            "proficiency_level": "Expert",
        })

        verifier = CredentialVerifier()
        ok, err = verifier.verify(cred.to_dict(), wrong_key_identity.public_key_b64)
        self.assertFalse(ok)


# ---------------------------------------------------------------------------
# Attestation summary
# ---------------------------------------------------------------------------

class TestAttestationSummary(unittest.TestCase):

    def test_summary(self):
        store = CredentialStore()
        subject = _make_identity("Alice")
        attestor = _make_identity("Bob")

        req, _ = create_attestation_request(
            identity=subject,
            attestor_did=attestor.did,
            attestation_type="EmploymentAttestation",
            proposed_claims={
                "subject_name": "Alice",
                "employer": "Acme",
                "role": "SWE",
                "relationship": "Manager",
            },
            bound_node_id="node-X",
        )
        cred = sign_attestation(attestor, req, {
            "subject_name": "Alice",
            "employer": "Acme",
            "role": "SWE",
            "relationship": "Manager",
        })
        store.add(cred)

        summary = get_attestation_summary(store, "node-X")
        self.assertEqual(summary["node_id"], "node-X")
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["active"], 1)
        self.assertIn(attestor.did, summary["issuer_dids"])
        self.assertIn("EmploymentAttestation", summary["types"])

    def test_summary_empty(self):
        store = CredentialStore()
        summary = get_attestation_summary(store, "no-node")
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["active"], 0)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TestAttestationSchemas(unittest.TestCase):

    def test_schemas_registered(self):
        from cortex.upai.schemas import SCHEMAS
        self.assertIn("attestation_request", SCHEMAS)
        self.assertIn("employment_attestation_claims", SCHEMAS)
        self.assertIn("skill_endorsement_claims", SCHEMAS)
        self.assertIn("reference_attestation_claims", SCHEMAS)

    def test_attestation_request_schema_validation(self):
        from cortex.upai.schemas import SCHEMAS, validate
        schema = SCHEMAS["attestation_request"]
        valid = {
            "request_id": "r1",
            "subject_did": "did:key:zAlice",
            "attestor_did": "did:key:zBob",
            "attestation_type": "EmploymentAttestation",
            "proposed_claims": {"subject_name": "Alice"},
        }
        self.assertEqual(validate(valid, schema), [])

    def test_employment_claims_schema(self):
        from cortex.upai.schemas import SCHEMAS, validate
        schema = SCHEMAS["employment_attestation_claims"]
        valid = {
            "subject_name": "Alice",
            "employer": "Acme",
            "role": "SWE",
            "relationship": "Manager",
        }
        self.assertEqual(validate(valid, schema), [])

        invalid = {"subject_name": "Alice"}
        errors = validate(invalid, schema)
        self.assertTrue(len(errors) > 0)


if __name__ == "__main__":
    unittest.main()
