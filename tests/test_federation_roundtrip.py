import json

import pytest

pytest.importorskip("nacl.signing")

from cortex.federation import FederationBundle, FederationManager, FederationSignatureError
from cortex.graph import CortexGraph, Node, make_node_id
from cortex.upai.identity import UPAIIdentity


def _roundtrip_graph() -> CortexGraph:
    graph = CortexGraph()
    source = {"source": "test", "source_id": "federation-roundtrip"}
    python_id = make_node_id("Python")
    cortex_id = make_node_id("Cortex")

    graph.add_node(
        Node(
            id=python_id,
            label="Python",
            tags=["technology"],
            confidence=0.95,
            provenance=[dict(source)],
        )
    )
    graph.add_node(
        Node(
            id=cortex_id,
            label="Cortex",
            tags=["project"],
            confidence=0.9,
            provenance=[dict(source)],
        )
    )
    return graph


def _clone_bundle(bundle: FederationBundle) -> FederationBundle:
    return FederationBundle.from_dict(json.loads(json.dumps(bundle.to_dict())))


def test_signed_bundle_import_roundtrip_with_pinned_did(tmp_path):
    identity_a = UPAIIdentity.generate("store-a")
    identity_b = UPAIIdentity.generate("store-b")
    graph_a = _roundtrip_graph()

    manager_a = FederationManager(
        identity=identity_a,
        store_dir=tmp_path / "store-a" / ".cortex",
    )
    bundle = manager_a.export_bundle(graph_a, policy="full")

    target = CortexGraph()
    manager_b = FederationManager(
        identity=identity_b,
        trusted_dids=[identity_a.did],
        store_dir=tmp_path / "store-b" / ".cortex",
    )
    result = manager_b.import_bundle(target, bundle)

    assert result.success is True
    assert len(target.nodes) == bundle.node_count
    assert len(target.edges) == bundle.edge_count


def test_signed_bundle_tamper_raises_signature_invalid(tmp_path):
    identity_a = UPAIIdentity.generate("store-a")
    identity_b = UPAIIdentity.generate("store-b")
    manager_a = FederationManager(
        identity=identity_a,
        store_dir=tmp_path / "store-a" / ".cortex",
    )
    bundle = manager_a.export_bundle(_roundtrip_graph(), policy="full")
    tampered = _clone_bundle(bundle)
    first_node = next(iter(tampered.graph_data["nodes"].values()))
    first_node["label"] = first_node["label"] + "!"

    manager_b = FederationManager(
        identity=identity_b,
        trusted_dids=[identity_a.did],
        store_dir=tmp_path / "store-b" / ".cortex",
    )
    with pytest.raises(FederationSignatureError, match="signature invalid"):
        manager_b.import_bundle(CortexGraph(), tampered)


def test_signed_bundle_wrong_pinned_did_raises_untrusted_key(tmp_path):
    identity_a = UPAIIdentity.generate("store-a")
    identity_b = UPAIIdentity.generate("store-b")
    manager_a = FederationManager(
        identity=identity_a,
        store_dir=tmp_path / "store-a" / ".cortex",
    )
    bundle = manager_a.export_bundle(_roundtrip_graph(), policy="full")

    manager_b = FederationManager(
        identity=identity_b,
        trusted_dids=[identity_b.did],
        store_dir=tmp_path / "store-b" / ".cortex",
    )
    with pytest.raises(FederationSignatureError, match="untrusted key"):
        manager_b.import_bundle(CortexGraph(), bundle)
