"""Tests for cortex.federation — cross-instance context sharing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cortex.federation import (
    FederationBundle,
    FederationManager,
    ImportResult,
    _apply_policy,
    _compute_content_hash,
    _compute_signing_input,
)
from cortex.graph import CortexGraph, Edge, Node, make_edge_id, make_node_id
from cortex.upai.identity import UPAIIdentity

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _node(label, tags=None, confidence=0.9, brief="", props=None):
    nid = make_node_id(label)
    return Node(
        id=nid, label=label, tags=tags or [], confidence=confidence,
        properties=props or {}, brief=brief, full_description="",
    )


@pytest.fixture
def graph():
    g = CortexGraph()
    g.add_node(_node("Python", tags=["technology", "language"], confidence=0.95, brief="Programming language"))
    g.add_node(_node("Machine Learning", tags=["technology", "ai"], confidence=0.9, brief="Subset of AI"))
    g.add_node(_node("Healthcare", tags=["domain"], confidence=0.8, brief="Medical services"))
    marc_id = make_node_id("Marc")
    g.add_node(Node(id=marc_id, label="Marc", tags=["person"], confidence=0.99, properties={}, brief="Developer", full_description=""))
    python_id = make_node_id("Python")
    ml_id = make_node_id("Machine Learning")
    g.add_edge(Edge(id=make_edge_id(marc_id, python_id, "uses"), source_id=marc_id, target_id=python_id, relation="uses", confidence=0.9, properties={}))
    g.add_edge(Edge(id=make_edge_id(python_id, ml_id, "used_in"), source_id=python_id, target_id=ml_id, relation="used_in", confidence=0.8, properties={}))
    return g


@pytest.fixture
def identity_a():
    return UPAIIdentity.generate("TestNodeA")


@pytest.fixture
def identity_b():
    return UPAIIdentity.generate("TestNodeB")


# ---------------------------------------------------------------------------
# Bundle serialization
# ---------------------------------------------------------------------------

class TestFederationBundle:
    def test_round_trip(self):
        bundle = FederationBundle(
            version="1.0", exporter_did="did:key:z6Mk123",
            exporter_public_key_b64="cHViX2tleQ==", nonce="abc123",
            created_at="2026-01-01T00:00:00+00:00",
            expires_at="2026-01-01T01:00:00+00:00",
            policy="full",
            graph_data={"nodes": {}, "edges": {}},
            node_count=0, edge_count=0,
            content_hash="abc", signature="sig",
            metadata={"source": "test"},
        )
        d = bundle.to_dict()
        restored = FederationBundle.from_dict(d)
        assert restored.version == bundle.version
        assert restored.exporter_did == bundle.exporter_did
        assert restored.nonce == bundle.nonce
        assert restored.content_hash == bundle.content_hash
        assert restored.signature == bundle.signature
        assert restored.metadata == {"source": "test"}

    def test_from_dict_defaults(self):
        d = {"exporter_did": "did:key:z6Mktest"}
        bundle = FederationBundle.from_dict(d)
        assert bundle.version == "1.0"
        assert bundle.policy == "full"
        assert bundle.graph_data == {}


# ---------------------------------------------------------------------------
# Import result
# ---------------------------------------------------------------------------

class TestImportResult:
    def test_to_dict(self):
        r = ImportResult(success=True, nodes_added=3, edges_added=1, errors=["warn"])
        d = r.to_dict()
        assert d["success"] is True
        assert d["nodes_added"] == 3
        assert d["errors"] == ["warn"]


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------

class TestContentHash:
    def test_deterministic(self):
        data = {"nodes": {"a": 1}, "edges": {"b": 2}}
        h1 = _compute_content_hash(data)
        h2 = _compute_content_hash(data)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_different_data(self):
        h1 = _compute_content_hash({"nodes": {}})
        h2 = _compute_content_hash({"nodes": {"a": 1}})
        assert h1 != h2


# ---------------------------------------------------------------------------
# Export policies
# ---------------------------------------------------------------------------

class TestExportPolicies:
    def test_full_policy(self):
        nd = {
            "id": "n1", "label": "Test", "tags": ["t"],
            "confidence": 0.9, "brief": "A node",
            "full_description": "Full desc", "properties": {"k": "v"},
            "timeline": [{"date": "2026-01-01"}], "first_seen": "2026-01-01",
            "last_seen": "2026-01-02",
        }
        result = _apply_policy(nd, "full")
        assert result["confidence"] == 0.9
        assert result["brief"] == "A node"
        assert result["properties"] == {"k": "v"}
        assert result["timeline"] == [{"date": "2026-01-01"}]

    def test_summary_policy(self):
        nd = {
            "id": "n1", "label": "Test", "tags": [],
            "confidence": 0.9, "brief": "A node",
            "full_description": "Full", "properties": {"k": "v"},
            "timeline": [{"x": 1}], "first_seen": "d1", "last_seen": "d2",
        }
        result = _apply_policy(nd, "summary")
        assert result["confidence"] == 0.9
        assert result["brief"] == "A node"
        assert "properties" not in result
        assert "timeline" not in result

    def test_minimal_policy(self):
        nd = {
            "id": "n1", "label": "Test", "tags": ["a"],
            "confidence": 0.9, "brief": "A node",
        }
        result = _apply_policy(nd, "minimal")
        assert result["id"] == "n1"
        assert result["label"] == "Test"
        assert result["tags"] == ["a"]
        assert "confidence" not in result
        assert "brief" not in result

    def test_unknown_policy_defaults_to_full(self):
        nd = {"id": "n1", "label": "Test", "tags": [], "confidence": 0.5}
        result = _apply_policy(nd, "nonexistent")
        assert "confidence" in result


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class TestExportBundle:
    def test_basic_export(self, graph, identity_a):
        mgr = FederationManager(identity=identity_a, sign_exports=False)
        bundle = mgr.export_bundle(graph)
        assert bundle.version == "1.0"
        assert bundle.exporter_did == identity_a.did
        assert bundle.node_count == 4
        assert bundle.edge_count == 2
        assert bundle.content_hash
        assert bundle.nonce

    def test_export_with_tag_filter(self, graph, identity_a):
        mgr = FederationManager(identity=identity_a, sign_exports=False)
        bundle = mgr.export_bundle(graph, tag_filter="technology")
        assert bundle.node_count == 2
        labels = {n["label"] for n in bundle.graph_data["nodes"].values()}
        assert "Python" in labels
        assert "Machine Learning" in labels

    def test_export_with_minimal_policy(self, graph, identity_a):
        mgr = FederationManager(identity=identity_a, sign_exports=False)
        bundle = mgr.export_bundle(graph, policy="minimal")
        for nd in bundle.graph_data["nodes"].values():
            assert "confidence" not in nd
            assert "brief" not in nd

    def test_export_invalid_policy(self, graph, identity_a):
        mgr = FederationManager(identity=identity_a)
        with pytest.raises(ValueError, match="Unknown export policy"):
            mgr.export_bundle(graph, policy="secret")

    def test_export_edges_filtered_by_nodes(self, graph, identity_a):
        mgr = FederationManager(identity=identity_a, sign_exports=False)
        bundle = mgr.export_bundle(graph, tag_filter="domain")
        assert bundle.node_count == 1  # Only Healthcare
        assert bundle.edge_count == 0  # No edges between single node

    def test_export_metadata(self, graph, identity_a):
        mgr = FederationManager(identity=identity_a, sign_exports=False)
        bundle = mgr.export_bundle(graph, metadata={"reason": "sync"})
        assert bundle.metadata == {"reason": "sync"}


# ---------------------------------------------------------------------------
# Signing and verification
# ---------------------------------------------------------------------------

class TestSigning:
    def test_signed_export(self, graph, identity_a):
        mgr = FederationManager(identity=identity_a, sign_exports=True)
        bundle = mgr.export_bundle(graph)
        if identity_a._key_type == "ed25519":
            assert bundle.signature != ""
        # Even HMAC identities should produce a signature
        assert bundle.exporter_public_key_b64 == identity_a.public_key_b64

    def test_unsigned_export(self, graph, identity_a):
        mgr = FederationManager(identity=identity_a, sign_exports=False)
        bundle = mgr.export_bundle(graph)
        assert bundle.signature == ""


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

class TestImportBundle:
    def test_basic_import(self, graph, identity_a, identity_b):
        mgr_a = FederationManager(identity=identity_a, sign_exports=False)
        bundle = mgr_a.export_bundle(graph)

        target = CortexGraph()
        mgr_b = FederationManager(
            identity=identity_b,
            trusted_dids=[identity_a.did],
        )
        result = mgr_b.import_bundle(target, bundle, verify_signature=False)
        assert result.success is True
        assert result.nodes_added == 4
        assert result.edges_added == 2

    def test_import_untrusted(self, graph, identity_a, identity_b):
        mgr_a = FederationManager(identity=identity_a, sign_exports=False)
        bundle = mgr_a.export_bundle(graph)

        target = CortexGraph()
        mgr_b = FederationManager(identity=identity_b, trusted_dids=[])
        result = mgr_b.import_bundle(target, bundle, verify_signature=False)
        assert result.success is False
        assert "Untrusted" in result.errors[0]

    def test_import_skip_trust_check(self, graph, identity_a, identity_b):
        mgr_a = FederationManager(identity=identity_a, sign_exports=False)
        bundle = mgr_a.export_bundle(graph)

        target = CortexGraph()
        mgr_b = FederationManager(identity=identity_b, trusted_dids=[])
        result = mgr_b.import_bundle(target, bundle, verify_signature=False, check_trust=False)
        assert result.success is True

    def test_replay_protection(self, graph, identity_a, identity_b):
        mgr_a = FederationManager(identity=identity_a, sign_exports=False)
        bundle = mgr_a.export_bundle(graph)

        target = CortexGraph()
        mgr_b = FederationManager(
            identity=identity_b, trusted_dids=[identity_a.did],
        )
        # First import succeeds
        r1 = mgr_b.import_bundle(target, bundle, verify_signature=False)
        assert r1.success is True
        # Second import with same nonce fails
        r2 = mgr_b.import_bundle(target, bundle, verify_signature=False)
        assert r2.success is False
        assert "Replay" in r2.errors[0]

    def test_expired_bundle(self, graph, identity_a, identity_b):
        mgr_a = FederationManager(identity=identity_a, sign_exports=False, bundle_ttl_seconds=0)
        bundle = mgr_a.export_bundle(graph)
        # Force expiration by setting expires_at in the past
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        bundle.expires_at = past

        target = CortexGraph()
        mgr_b = FederationManager(
            identity=identity_b, trusted_dids=[identity_a.did],
        )
        result = mgr_b.import_bundle(target, bundle, verify_signature=False)
        assert result.success is False
        assert "expired" in result.errors[0].lower()

    def test_content_hash_tamper(self, graph, identity_a, identity_b):
        mgr_a = FederationManager(identity=identity_a, sign_exports=False)
        bundle = mgr_a.export_bundle(graph)
        bundle.content_hash = "tampered_hash"

        target = CortexGraph()
        mgr_b = FederationManager(
            identity=identity_b, trusted_dids=[identity_a.did],
        )
        result = mgr_b.import_bundle(target, bundle, verify_signature=False)
        assert result.success is False
        assert "hash mismatch" in result.errors[0].lower()

    def test_merge_updates_existing_nodes(self, graph, identity_a, identity_b):
        mgr_a = FederationManager(identity=identity_a, sign_exports=False)
        bundle = mgr_a.export_bundle(graph)

        # Pre-populate target with one overlapping node
        target = CortexGraph()
        target.add_node(_node("Python", tags=["old-tag"], confidence=0.5, brief=""))

        mgr_b = FederationManager(
            identity=identity_b, trusted_dids=[identity_a.did],
        )
        result = mgr_b.import_bundle(target, bundle, verify_signature=False)
        assert result.success is True
        assert result.nodes_updated >= 1

        python_id = make_node_id("Python")
        merged = target.nodes[python_id]
        # Should have merged tags
        assert "old-tag" in merged.tags
        assert "technology" in merged.tags
        # Higher confidence wins
        assert merged.confidence == 0.95

    def test_import_with_signature_verification(self, graph, identity_a, identity_b):
        mgr_a = FederationManager(identity=identity_a, sign_exports=True)
        bundle = mgr_a.export_bundle(graph)

        target = CortexGraph()
        mgr_b = FederationManager(
            identity=identity_b, trusted_dids=[identity_a.did],
        )
        result = mgr_b.import_bundle(target, bundle, verify_signature=True)
        # Should succeed if Ed25519 is available, or succeed without sig check
        if identity_a._key_type == "ed25519" and bundle.signature:
            assert result.success is True
        else:
            # HMAC identities can't be verified remotely, but import still works
            # since signature verification only fails on actual bad sigs
            assert result.success is True


# ---------------------------------------------------------------------------
# Peer management
# ---------------------------------------------------------------------------

class TestPeerManagement:
    def test_add_trusted_did(self, identity_a):
        mgr = FederationManager(identity=identity_a)
        mgr.add_trusted_did("did:key:z6Mktest1")
        assert "did:key:z6Mktest1" in mgr.trusted_dids

    def test_remove_trusted_did(self, identity_a):
        mgr = FederationManager(identity=identity_a, trusted_dids=["did:key:z6Mktest1"])
        assert mgr.remove_trusted_did("did:key:z6Mktest1") is True
        assert "did:key:z6Mktest1" not in mgr.trusted_dids

    def test_remove_nonexistent_did(self, identity_a):
        mgr = FederationManager(identity=identity_a)
        assert mgr.remove_trusted_did("did:key:z6MkNothing") is False

    def test_list_trusted_dids(self, identity_a):
        mgr = FederationManager(identity=identity_a, trusted_dids=["b", "a", "c"])
        assert mgr.list_trusted_dids() == ["a", "b", "c"]

    def test_get_peer_info(self, identity_a):
        mgr = FederationManager(identity=identity_a)
        info = mgr.get_peer_info()
        assert info["did"] == identity_a.did
        assert info["public_key_b64"] == identity_a.public_key_b64
        assert info["federation_version"] == "1.0"


# ---------------------------------------------------------------------------
# Signing input
# ---------------------------------------------------------------------------

class TestSigningInput:
    def test_deterministic(self):
        d = {"version": "1.0", "exporter_did": "did:key:z6Mk1",
             "nonce": "abc", "created_at": "2026-01-01", "content_hash": "hash1"}
        s1 = _compute_signing_input(d)
        s2 = _compute_signing_input(d)
        assert s1 == s2

    def test_different_nonces(self):
        d1 = {"version": "1.0", "exporter_did": "d", "nonce": "a",
              "created_at": "t", "content_hash": "h"}
        d2 = {"version": "1.0", "exporter_did": "d", "nonce": "b",
              "created_at": "t", "content_hash": "h"}
        assert _compute_signing_input(d1) != _compute_signing_input(d2)
