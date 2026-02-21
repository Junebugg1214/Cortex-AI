"""
Tests for UPAI JSON Schema validation.

Covers:
- Positive: each schema validates known-good data
- Negative: missing required fields, wrong types, out-of-range values
- Compliance: real data structures pass their schemas
- Validator edge cases
"""

import json
import tempfile
from pathlib import Path

from cortex.graph import CortexGraph, Edge, Node
from cortex.upai.identity import UPAIIdentity
from cortex.upai.schemas import (
    DID_DOCUMENT_SCHEMA,
    DISCLOSURE_POLICY_SCHEMA,
    EDGE_SCHEMA,
    ENVELOPE_SCHEMA,
    GRANT_TOKEN_SCHEMA,
    GRAPH_SCHEMA,
    IDENTITY_SCHEMA,
    NODE_SCHEMA,
    SCHEMAS,
    VERSION_SCHEMA,
    is_valid,
    validate,
)
from cortex.upai.versioning import VersionStore

# ============================================================================
# Helpers
# ============================================================================

def _good_node() -> dict:
    return {
        "id": "abc123",
        "label": "Python",
        "tags": ["technical_expertise"],
        "confidence": 0.9,
        "properties": {},
        "brief": "A language",
        "full_description": "",
        "mention_count": 3,
        "extraction_method": "mentioned",
        "metrics": [],
        "timeline": [],
        "source_quotes": [],
        "first_seen": "2024-01-01T00:00:00+00:00",
        "last_seen": "",
        "relationship_type": "",
        "snapshots": [],
    }


def _good_edge() -> dict:
    return {
        "id": "e001",
        "source_id": "n1",
        "target_id": "n2",
        "relation": "uses",
        "confidence": 0.8,
        "properties": {},
        "first_seen": "",
        "last_seen": "",
    }


def _good_identity() -> dict:
    return {
        "did": "did:key:z6MkTest",
        "name": "Test User",
        "public_key_b64": "dGVzdA==",
        "created_at": "2024-01-01T00:00:00+00:00",
    }


def _good_grant_token() -> dict:
    return {
        "grant_id": "g-12345",
        "subject_did": "did:key:z6MkTest",
        "issuer_did": "did:key:z6MkTest",
        "audience": "Claude",
        "policy": "professional",
        "scopes": ["context:read"],
        "issued_at": "2024-01-01T00:00:00+00:00",
        "expires_at": "2024-01-02T00:00:00+00:00",
        "not_before": "",
    }


def _good_version() -> dict:
    return {
        "version_id": "abcd1234abcd1234abcd1234abcd1234",
        "parent_id": None,
        "timestamp": "2024-01-01T00:00:00+00:00",
        "source": "manual",
        "message": "Initial commit",
        "graph_hash": "a" * 64,
        "node_count": 5,
        "edge_count": 3,
        "signature": None,
    }


def _good_disclosure_policy() -> dict:
    return {
        "name": "professional",
        "include_tags": ["identity", "professional_context"],
        "exclude_tags": ["negations"],
        "min_confidence": 0.6,
        "redact_properties": [],
        "max_nodes": 0,
    }


def _good_envelope() -> dict:
    return {
        "header": {"alg": "Ed25519", "typ": "UPAI-Envelope"},
        "payload": {
            "data": {"key": "value"},
            "nonce": "a" * 32,
            "iat": "2024-01-01T00:00:00+00:00",
            "exp": "2024-01-01T01:00:00+00:00",
            "aud": "test-audience",
        },
        "signature": "dGVzdHNpZw==",
    }


# ============================================================================
# Positive: good data passes
# ============================================================================

class TestSchemaPositive:

    def test_node_valid(self):
        assert is_valid(_good_node(), NODE_SCHEMA)

    def test_edge_valid(self):
        assert is_valid(_good_edge(), EDGE_SCHEMA)

    def test_identity_valid(self):
        assert is_valid(_good_identity(), IDENTITY_SCHEMA)

    def test_grant_token_valid(self):
        assert is_valid(_good_grant_token(), GRANT_TOKEN_SCHEMA)

    def test_version_valid(self):
        assert is_valid(_good_version(), VERSION_SCHEMA)

    def test_disclosure_policy_valid(self):
        assert is_valid(_good_disclosure_policy(), DISCLOSURE_POLICY_SCHEMA)

    def test_envelope_valid(self):
        assert is_valid(_good_envelope(), ENVELOPE_SCHEMA)

    def test_graph_valid(self):
        data = {
            "schema_version": "6.0",
            "meta": {"node_count": 1, "edge_count": 0},
            "graph": {
                "nodes": {"n1": _good_node()},
                "edges": {},
            },
            "categories": {},
        }
        assert is_valid(data, GRAPH_SCHEMA)

    def test_did_document_valid(self):
        doc = {
            "@context": "https://www.w3.org/ns/did/v1",
            "id": "did:key:z6MkTest",
            "controller": "did:key:z6MkTest",
            "created": "2024-01-01T00:00:00+00:00",
            "verificationMethod": [
                {
                    "id": "did:key:z6MkTest#key-1",
                    "type": "Ed25519VerificationKey2020",
                    "controller": "did:key:z6MkTest",
                    "publicKeyMultibase": "z6MkTest",
                }
            ],
            "authentication": ["did:key:z6MkTest#key-1"],
        }
        assert is_valid(doc, DID_DOCUMENT_SCHEMA)


# ============================================================================
# Negative: bad data rejected
# ============================================================================

class TestSchemaNegative:

    def test_node_missing_id(self):
        d = _good_node()
        del d["id"]
        errors = validate(d, NODE_SCHEMA)
        assert any("id" in e for e in errors)

    def test_node_missing_label(self):
        d = _good_node()
        del d["label"]
        errors = validate(d, NODE_SCHEMA)
        assert any("label" in e for e in errors)

    def test_node_confidence_too_high(self):
        d = _good_node()
        d["confidence"] = 1.5
        errors = validate(d, NODE_SCHEMA)
        assert any("maximum" in e for e in errors)

    def test_node_confidence_too_low(self):
        d = _good_node()
        d["confidence"] = -0.1
        errors = validate(d, NODE_SCHEMA)
        assert any("minimum" in e for e in errors)

    def test_node_wrong_type_tags(self):
        d = _good_node()
        d["tags"] = "not-an-array"
        errors = validate(d, NODE_SCHEMA)
        assert len(errors) > 0

    def test_edge_missing_source(self):
        d = _good_edge()
        del d["source_id"]
        errors = validate(d, EDGE_SCHEMA)
        assert any("source_id" in e for e in errors)

    def test_edge_empty_relation(self):
        d = _good_edge()
        d["relation"] = ""
        errors = validate(d, EDGE_SCHEMA)
        assert any("minLength" in e for e in errors)

    def test_identity_bad_did_prefix(self):
        d = _good_identity()
        d["did"] = "not-a-did"
        errors = validate(d, IDENTITY_SCHEMA)
        assert any("pattern" in e for e in errors)

    def test_grant_token_missing_scopes(self):
        d = _good_grant_token()
        del d["scopes"]
        errors = validate(d, GRANT_TOKEN_SCHEMA)
        assert any("scopes" in e for e in errors)

    def test_grant_token_empty_scopes(self):
        d = _good_grant_token()
        d["scopes"] = []
        errors = validate(d, GRANT_TOKEN_SCHEMA)
        assert any("minItems" in e for e in errors)

    def test_grant_token_bad_policy(self):
        d = _good_grant_token()
        d["policy"] = "nonexistent"
        errors = validate(d, GRANT_TOKEN_SCHEMA)
        assert any("enum" in e for e in errors)

    def test_version_short_hash(self):
        d = _good_version()
        d["graph_hash"] = "tooshort"
        errors = validate(d, VERSION_SCHEMA)
        assert any("minLength" in e for e in errors)

    def test_envelope_bad_alg(self):
        d = _good_envelope()
        d["header"]["alg"] = "RSA"
        errors = validate(d, ENVELOPE_SCHEMA)
        assert any("enum" in e for e in errors)

    def test_wrong_type_root(self):
        errors = validate("not-an-object", NODE_SCHEMA)
        assert any("type" in e for e in errors)

    def test_boolean_is_not_integer(self):
        d = _good_node()
        d["mention_count"] = True
        errors = validate(d, NODE_SCHEMA)
        assert any("type" in e for e in errors)


# ============================================================================
# Compliance: real objects pass their schemas
# ============================================================================

class TestSchemaCompliance:

    def test_node_to_dict_passes(self):
        node = Node(id="n1", label="Test", tags=["identity"], confidence=0.8)
        assert is_valid(node.to_dict(), NODE_SCHEMA)

    def test_edge_to_dict_passes(self):
        edge = Edge(id="e1", source_id="n1", target_id="n2", relation="uses", confidence=0.7)
        assert is_valid(edge.to_dict(), EDGE_SCHEMA)

    def test_graph_export_v5_passes(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Test", tags=["identity"], confidence=0.9))
        data = g.export_v5()
        assert is_valid(data, GRAPH_SCHEMA)

    def test_identity_to_public_dict_passes(self):
        identity = UPAIIdentity.generate("Test")
        assert is_valid(identity.to_public_dict(), IDENTITY_SCHEMA)

    def test_identity_did_document_passes(self):
        identity = UPAIIdentity.generate("Test")
        doc = identity.to_did_document()
        assert is_valid(doc, DID_DOCUMENT_SCHEMA)

    def test_version_to_dict_passes(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Test", tags=["identity"], confidence=0.9))
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            identity = UPAIIdentity.generate("Test")
            version = store.commit(g, "test commit", identity=identity)
            assert is_valid(version.to_dict(), VERSION_SCHEMA)

    def test_disclosure_policy_dict_passes(self):
        from cortex.upai.disclosure import BUILTIN_POLICIES
        for name, policy in BUILTIN_POLICIES.items():
            d = {
                "name": policy.name,
                "include_tags": policy.include_tags,
                "exclude_tags": policy.exclude_tags,
                "min_confidence": policy.min_confidence,
                "redact_properties": policy.redact_properties,
                "max_nodes": policy.max_nodes,
            }
            assert is_valid(d, DISCLOSURE_POLICY_SCHEMA), f"Policy {name} failed"


# ============================================================================
# Schema registry
# ============================================================================

class TestSchemaRegistry:

    def test_all_schemas_present(self):
        expected = {
            "node", "edge", "graph", "identity", "envelope",
            "grant_token", "disclosure_policy", "version", "did_document",
            "credential", "credential_proof",
        }
        assert set(SCHEMAS.keys()) == expected

    def test_schemas_are_dicts(self):
        for name, schema in SCHEMAS.items():
            assert isinstance(schema, dict), f"Schema {name} is not a dict"
            assert "type" in schema, f"Schema {name} missing 'type'"


# ============================================================================
# Validator edge cases
# ============================================================================

class TestValidatorEdgeCases:

    def test_empty_schema_passes_anything(self):
        assert is_valid(42, {})
        assert is_valid("hello", {})
        assert is_valid(None, {})

    def test_null_type(self):
        assert is_valid(None, {"type": "null"})
        assert not is_valid("hello", {"type": "null"})

    def test_union_types(self):
        schema = {"type": ["string", "null"]}
        assert is_valid("hello", schema)
        assert is_valid(None, schema)
        assert not is_valid(42, schema)

    def test_nested_validation(self):
        schema = {
            "type": "object",
            "properties": {
                "inner": {
                    "type": "object",
                    "required": ["x"],
                    "properties": {"x": {"type": "integer"}},
                }
            },
        }
        assert is_valid({"inner": {"x": 5}}, schema)
        errors = validate({"inner": {}}, schema)
        assert any("x" in e for e in errors)

    def test_array_item_validation(self):
        schema = {
            "type": "array",
            "items": {"type": "string"},
        }
        assert is_valid(["a", "b"], schema)
        errors = validate(["a", 42], schema)
        assert len(errors) > 0

    def test_canonical_serialization_determinism(self):
        """Ensure JSON serialization order is deterministic for integrity checks."""
        d1 = {"b": 2, "a": 1}
        d2 = {"a": 1, "b": 2}
        assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)
