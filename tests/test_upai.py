"""
Tests for UPAI Phase 3: Identity + Disclosure

Covers:
- Identity generation (both Ed25519 and HMAC fallback)
- DID format correctness
- Identity save/load roundtrip
- Sign and verify
- Integrity hash determinism
- to_did_document() structure
- Disclosure policies: full, professional, technical, minimal
- Disclosure: min_confidence, max_nodes, redact_properties, edge removal
- apply_disclosure returns deep copy (original unchanged)
"""

import tempfile
from pathlib import Path

from cortex.graph import CortexGraph, Edge, Node
from cortex.upai.disclosure import (
    BUILTIN_POLICIES,
    DisclosurePolicy,
    apply_disclosure,
)
from cortex.upai.identity import UPAIIdentity, has_crypto

# ============================================================================
# Identity
# ============================================================================


class TestIdentityGeneration:
    def test_generate_creates_identity(self):
        identity = UPAIIdentity.generate("Test User")
        assert identity.name == "Test User"
        assert identity.did.startswith("did:")
        assert identity.public_key_b64
        assert identity.created_at
        assert identity._private_key is not None

    def test_did_format_ed25519(self):
        if not has_crypto():
            return  # skip
        identity = UPAIIdentity.generate("Test")
        assert identity.did.startswith("did:key:z6Mk")
        # did:key format: z + base58btc(multicodec_prefix + public_key)
        assert len(identity.did) > 20

    def test_did_format_hmac_fallback(self):
        # Force HMAC mode by temporarily disabling crypto
        import cortex.upai.identity as id_mod

        orig = id_mod._HAS_CRYPTO
        id_mod._HAS_CRYPTO = False
        try:
            identity = UPAIIdentity.generate("Test")
            assert identity.did.startswith("did:upai:sha256:")
            fingerprint = identity.did.split(":")[-1]
            assert len(fingerprint) == 32
        finally:
            id_mod._HAS_CRYPTO = orig

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir) / ".cortex"
            identity = UPAIIdentity.generate("Roundtrip Test")
            identity.save(store_dir)

            loaded = UPAIIdentity.load(store_dir)
            assert loaded.did == identity.did
            assert loaded.name == identity.name
            assert loaded.public_key_b64 == identity.public_key_b64
            assert loaded.created_at == identity.created_at
            assert loaded._private_key == identity._private_key

    def test_sign_and_verify_ed25519(self):
        if not has_crypto():
            return  # skip
        identity = UPAIIdentity.generate("Signer")
        data = b"hello world"
        sig = identity.sign(data)
        assert sig  # non-empty
        assert UPAIIdentity.verify(data, sig, identity.public_key_b64) is True

    def test_sign_and_verify_tampered_data(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Signer")
        data = b"hello world"
        sig = identity.sign(data)
        assert UPAIIdentity.verify(b"tampered", sig, identity.public_key_b64) is False

    def test_sign_and_verify_hmac_fallback(self):
        import cortex.upai.identity as id_mod

        orig = id_mod._HAS_CRYPTO
        id_mod._HAS_CRYPTO = False
        try:
            identity = UPAIIdentity.generate("HMAC Signer")
            data = b"test data"
            sig = identity.sign(data)
            assert sig
            # Static verify returns False for HMAC (needs secret)
            assert UPAIIdentity.verify(data, sig, identity.public_key_b64) is False
            # But verify_own works
            assert identity.verify_own(data, sig) is True
        finally:
            id_mod._HAS_CRYPTO = orig

    def test_integrity_hash_deterministic(self):
        identity = UPAIIdentity.generate("Hash Test")
        data = b"deterministic"
        hash1 = identity.integrity_hash(data)
        hash2 = identity.integrity_hash(data)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def test_to_did_document_structure(self):
        identity = UPAIIdentity.generate("Doc Test")
        doc = identity.to_did_document()
        assert doc["@context"] == "https://www.w3.org/ns/did/v1"
        assert doc["id"] == identity.did
        assert doc["controller"] == identity.did
        assert doc["created"] == identity.created_at
        assert len(doc["verificationMethod"]) == 1
        vm = doc["verificationMethod"][0]
        assert vm["id"] == f"{identity.did}#key-1"
        # Ed25519 keys use publicKeyMultibase; HMAC keys use publicKeyBase64
        if "publicKeyMultibase" in vm:
            assert vm["publicKeyMultibase"].startswith("z")
        else:
            assert vm["publicKeyBase64"] == identity.public_key_b64
        assert len(doc["authentication"]) == 1

    def test_to_public_dict(self):
        identity = UPAIIdentity.generate("Public Test")
        pub = identity.to_public_dict()
        assert "did" in pub
        assert "name" in pub
        assert "public_key_b64" in pub
        assert "created_at" in pub
        assert "_private_key" not in pub
        assert "private_key" not in str(pub)


# ============================================================================
# Disclosure
# ============================================================================


def _build_test_graph() -> CortexGraph:
    """Build a graph with diverse tags and confidence levels for testing."""
    g = CortexGraph()
    g.add_node(Node(id="n1", label="Marc", tags=["identity"], confidence=0.95))
    g.add_node(Node(id="n2", label="Python", tags=["technical_expertise"], confidence=0.9))
    g.add_node(Node(id="n3", label="CEO", tags=["professional_context"], confidence=0.85))
    g.add_node(Node(id="n4", label="Healthcare", tags=["domain_knowledge"], confidence=0.8))
    g.add_node(Node(id="n5", label="Hates meetings", tags=["negations"], confidence=0.7))
    g.add_node(Node(id="n6", label="Old correction", tags=["correction_history"], confidence=0.6))
    g.add_node(Node(id="n7", label="Low conf item", tags=["mentions"], confidence=0.3))
    g.add_node(
        Node(
            id="n8",
            label="Direct style",
            tags=["communication_preferences"],
            confidence=0.85,
            properties={"secret": "value", "public": "info"},
        )
    )
    g.add_node(Node(id="n9", label="Ship fast", tags=["active_priorities"], confidence=0.75))
    g.add_node(Node(id="n10", label="Acme Corp", tags=["business_context"], confidence=0.88))

    g.add_edge(Edge(id="e1", source_id="n1", target_id="n3", relation="has_role"))
    g.add_edge(Edge(id="e2", source_id="n2", target_id="n4", relation="used_in"))
    g.add_edge(Edge(id="e3", source_id="n1", target_id="n7", relation="mentioned"))
    return g


class TestDisclosure:
    def test_full_policy_passes_everything(self):
        g = _build_test_graph()
        result = apply_disclosure(g, BUILTIN_POLICIES["full"])
        assert len(result.nodes) == len(g.nodes)
        assert len(result.edges) == len(g.edges)

    def test_professional_filters_negations_and_corrections(self):
        g = _build_test_graph()
        result = apply_disclosure(g, BUILTIN_POLICIES["professional"])
        labels = {n.label for n in result.nodes.values()}
        assert "Hates meetings" not in labels  # negations excluded
        assert "Old correction" not in labels  # correction_history excluded
        # Professional tags included
        assert "Marc" in labels
        assert "CEO" in labels
        assert "Python" in labels

    def test_min_confidence_filters_low(self):
        g = _build_test_graph()
        policy = DisclosurePolicy(
            name="test",
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.7,
            redact_properties=[],
        )
        result = apply_disclosure(g, policy)
        for node in result.nodes.values():
            assert node.confidence >= 0.7
        assert "n7" not in result.nodes  # confidence 0.3

    def test_max_nodes_caps_output(self):
        g = _build_test_graph()
        policy = DisclosurePolicy(
            name="test",
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
            max_nodes=3,
        )
        result = apply_disclosure(g, policy)
        assert len(result.nodes) == 3
        # Should be highest confidence nodes
        confs = [n.confidence for n in result.nodes.values()]
        assert min(confs) >= 0.85  # top 3 are >= 0.85

    def test_redact_properties_strips_keys(self):
        g = _build_test_graph()
        policy = DisclosurePolicy(
            name="test",
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=["secret"],
        )
        result = apply_disclosure(g, policy)
        n8 = result.nodes.get("n8")
        assert n8 is not None
        assert "secret" not in n8.properties
        assert "public" in n8.properties

    def test_edges_removed_when_endpoints_filtered(self):
        g = _build_test_graph()
        policy = DisclosurePolicy(
            name="test",
            include_tags=["identity"],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )
        result = apply_disclosure(g, policy)
        assert len(result.nodes) == 1  # only Marc
        assert len(result.edges) == 0  # all edges require 2 endpoints

    def test_apply_disclosure_returns_deep_copy(self):
        g = _build_test_graph()
        result = apply_disclosure(g, BUILTIN_POLICIES["full"])
        # Modify the result
        result.nodes["n1"].label = "CHANGED"
        # Original unchanged
        assert g.nodes["n1"].label == "Marc"

    def test_custom_policy(self):
        g = _build_test_graph()
        policy = DisclosurePolicy(
            name="custom",
            include_tags=["technical_expertise", "domain_knowledge"],
            exclude_tags=[],
            min_confidence=0.5,
            redact_properties=[],
        )
        result = apply_disclosure(g, policy)
        labels = {n.label for n in result.nodes.values()}
        assert labels == {"Python", "Healthcare"}

    def test_technical_policy(self):
        g = _build_test_graph()
        result = apply_disclosure(g, BUILTIN_POLICIES["technical"])
        labels = {n.label for n in result.nodes.values()}
        assert "Python" in labels
        assert "Healthcare" in labels
        assert "Ship fast" in labels
        # Identity/professional not in technical policy
        assert "Marc" not in labels

    def test_minimal_policy(self):
        g = _build_test_graph()
        result = apply_disclosure(g, BUILTIN_POLICIES["minimal"])
        labels = {n.label for n in result.nodes.values()}
        assert "Marc" in labels
        assert "Direct style" in labels
        # Only identity + communication_preferences with conf >= 0.8
        assert len(result.nodes) == 2

    def test_builtin_policies_dict(self):
        assert "full" in BUILTIN_POLICIES
        assert "professional" in BUILTIN_POLICIES
        assert "technical" in BUILTIN_POLICIES
        assert "minimal" in BUILTIN_POLICIES
        assert len(BUILTIN_POLICIES) == 4
