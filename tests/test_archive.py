"""Tests for archive export/import — Feature 3."""

import json
import zipfile
import io
import hashlib
import pytest

from cortex.graph import CortexGraph, Node, Edge, make_node_id, make_edge_id
from cortex.caas.archive import create_archive, import_archive


def _sample_graph():
    g = CortexGraph()
    a = make_node_id("Alice")
    b = make_node_id("Bob")
    g.add_node(Node(id=a, label="Alice", tags=["identity"], confidence=0.9))
    g.add_node(Node(id=b, label="Bob", tags=["relationships"], confidence=0.7))
    eid = make_edge_id(a, b, "knows")
    g.add_edge(Edge(id=eid, source_id=a, target_id=b, relation="knows"))
    return g


class FakeProfileStore:
    """Minimal mock for profile store."""
    def __init__(self, profiles=None):
        self._profiles = profiles or []

    def list_all(self):
        return self._profiles


class FakeProfile:
    def __init__(self, handle):
        self.handle = handle

    def to_dict(self):
        return {"handle": self.handle, "display_name": self.handle.title()}


class FakeCredentialStore:
    def __init__(self, creds=None):
        self._creds = creds or []

    def list_all(self):
        return self._creds


class FakeCredential:
    def to_dict(self):
        return {"id": "cred-1", "type": "VerifiableCredential"}


class TestCreateArchive:
    def test_basic_archive_is_valid_zip(self):
        g = _sample_graph()
        data = create_archive(g)
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        assert "cortex-archive/manifest.json" in names
        assert "cortex-archive/graph.json" in names
        assert "cortex-archive/profiles.json" in names
        assert "cortex-archive/credentials.json" in names

    def test_manifest_contains_counts(self):
        g = _sample_graph()
        data = create_archive(g)
        zf = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf.read("cortex-archive/manifest.json"))
        assert manifest["node_count"] == 2
        assert manifest["edge_count"] == 1
        assert manifest["version"] == "1.0"
        assert "timestamp" in manifest
        assert "checksums" in manifest

    def test_manifest_checksums_match(self):
        g = _sample_graph()
        data = create_archive(g)
        zf = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf.read("cortex-archive/manifest.json"))
        for filename, expected_hash in manifest["checksums"].items():
            raw = zf.read(f"cortex-archive/{filename}")
            actual = hashlib.sha256(raw).hexdigest()
            assert actual == expected_hash, f"Checksum mismatch for {filename}"

    def test_includes_profiles(self):
        g = _sample_graph()
        ps = FakeProfileStore([FakeProfile("alice"), FakeProfile("bob")])
        data = create_archive(g, profile_store=ps)
        zf = zipfile.ZipFile(io.BytesIO(data))
        profiles = json.loads(zf.read("cortex-archive/profiles.json"))
        assert len(profiles) == 2

    def test_includes_credentials(self):
        g = _sample_graph()
        cs = FakeCredentialStore([FakeCredential()])
        data = create_archive(g, credential_store=cs)
        zf = zipfile.ZipFile(io.BytesIO(data))
        creds = json.loads(zf.read("cortex-archive/credentials.json"))
        assert len(creds) == 1

    def test_identity_did_in_manifest(self):
        g = _sample_graph()

        class FakeIdentity:
            did = "did:key:z6Mktest"

        data = create_archive(g, identity=FakeIdentity())
        zf = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf.read("cortex-archive/manifest.json"))
        assert manifest["did"] == "did:key:z6Mktest"


class TestImportArchive:
    def test_roundtrip(self):
        g = _sample_graph()
        data = create_archive(g)
        result = import_archive(data)
        assert "manifest" in result
        assert "graph" in result
        graph_data = result["graph"]
        restored = CortexGraph.from_v5_json(graph_data)
        assert len(restored.nodes) == 2
        assert len(restored.edges) == 1

    def test_invalid_zip_raises(self):
        with pytest.raises(ValueError, match="Invalid ZIP"):
            import_archive(b"not a zip file")

    def test_missing_manifest_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("random.txt", "hello")
        with pytest.raises(ValueError, match="missing manifest"):
            import_archive(buf.getvalue())

    def test_checksum_mismatch_raises(self):
        g = _sample_graph()
        data = create_archive(g)
        # Tamper with graph.json
        buf = io.BytesIO(data)
        zf = zipfile.ZipFile(buf, "r")
        manifest = json.loads(zf.read("cortex-archive/manifest.json"))
        profiles = zf.read("cortex-archive/profiles.json")
        creds = zf.read("cortex-archive/credentials.json")
        zf.close()

        # Rebuild with tampered graph
        tampered_graph = b'{"tampered": true}'
        new_buf = io.BytesIO()
        with zipfile.ZipFile(new_buf, "w") as zf2:
            zf2.writestr("cortex-archive/manifest.json", json.dumps(manifest))
            zf2.writestr("cortex-archive/graph.json", tampered_graph)
            zf2.writestr("cortex-archive/profiles.json", profiles)
            zf2.writestr("cortex-archive/credentials.json", creds)

        with pytest.raises(ValueError, match="Checksum mismatch"):
            import_archive(new_buf.getvalue())

    def test_empty_graph_archive(self):
        g = CortexGraph()
        data = create_archive(g)
        result = import_archive(data)
        assert result["manifest"]["node_count"] == 0
        assert result["manifest"]["edge_count"] == 0
