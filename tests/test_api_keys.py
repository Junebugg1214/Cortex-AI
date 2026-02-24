"""Tests for cortex.caas.api_keys — API key store and memory rendering."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from cortex.caas.api_keys import ApiKeyStore, get_disclosed_graph, render_memory


# ── ApiKeyStore ──────────────────────────────────────────────────────

class TestApiKeyStore:
    """Test ApiKeyStore CRUD operations."""

    def setup_method(self):
        self.store = ApiKeyStore()

    def test_create_key(self):
        key = self.store.create("Test Key", "full", fmt="json")
        assert key["label"] == "Test Key"
        assert key["policy"] == "full"
        assert key["format"] == "json"
        assert key["active"] is True
        assert key["key_secret"].startswith("cmk_")
        assert len(key["key_id"]) == 8

    def test_list_keys_masks_secrets(self):
        self.store.create("Key A", "full")
        self.store.create("Key B", "technical")
        keys = self.store.list_keys()
        assert len(keys) == 2
        for k in keys:
            # Secret should be masked
            assert "..." in k["key_secret"]

    def test_get_by_secret(self):
        created = self.store.create("My Key", "professional", fmt="markdown")
        found = self.store.get_by_secret(created["key_secret"])
        assert found is not None
        assert found["label"] == "My Key"
        assert found["last_used"] is not None

    def test_revoke_key(self):
        created = self.store.create("Revokable", "minimal")
        assert self.store.revoke(created["key_id"]) is True
        # Revoked key should not be found
        assert self.store.get_by_secret(created["key_secret"]) is None

    def test_revoke_nonexistent(self):
        assert self.store.revoke("nonexistent") is False

    def test_get_nonexistent_secret(self):
        assert self.store.get_by_secret("cmk_fake_secret") is None

    def test_last_used_updated(self):
        created = self.store.create("Track Usage", "full")
        assert created["last_used"] is None
        found = self.store.get_by_secret(created["key_secret"])
        assert found["last_used"] is not None

    def test_custom_policy_with_tags(self):
        key = self.store.create("Custom", "custom",
                                tags=["identity", "technical_expertise"],
                                fmt="system_prompt")
        assert key["policy"] == "custom"
        assert key["tags"] == ["identity", "technical_expertise"]
        assert key["format"] == "system_prompt"


# ── File persistence ─────────────────────────────────────────────────

class TestApiKeyStoreFile:
    """Test file-backed persistence."""

    def test_persistence_to_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            store1 = ApiKeyStore(path)
            created = store1.create("Persist Key", "full", fmt="json")
            secret = created["key_secret"]

            # Create a new store from the same file
            store2 = ApiKeyStore(path)
            found = store2.get_by_secret(secret)
            assert found is not None
            assert found["label"] == "Persist Key"
        finally:
            path.unlink(missing_ok=True)

    def test_reload_after_revoke(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            store1 = ApiKeyStore(path)
            created = store1.create("Revoke Me", "full")
            store1.revoke(created["key_id"])

            store2 = ApiKeyStore(path)
            assert store2.get_by_secret(created["key_secret"]) is None
        finally:
            path.unlink(missing_ok=True)


# ── render_memory ────────────────────────────────────────────────────

class TestRenderMemory:
    """Test render_memory() output formats."""

    def setup_method(self):
        from cortex.graph import CortexGraph, Edge, Node, make_edge_id

        self.graph = CortexGraph()
        self.graph.add_node(Node(
            id="n1", label="Python", tags=["technical_expertise"],
            confidence=0.9, brief="Programming language",
        ))
        self.graph.add_node(Node(
            id="n2", label="John Doe", tags=["identity"],
            confidence=0.95, brief="Full name",
        ))
        self.graph.add_node(Node(
            id="n3", label="Machine Learning", tags=["domain_knowledge"],
            confidence=0.8, brief="Research area",
        ))
        eid = make_edge_id("n1", "n3", "related_to")
        self.graph.add_edge(Edge(
            id=eid, source_id="n1", target_id="n3", relation="related_to",
        ))

    def test_json_format(self):
        content, ct = render_memory(self.graph, "full", None, "json")
        assert ct == "application/json"
        data = json.loads(content)
        assert "graph" in data
        assert "nodes" in data["graph"]

    def test_claude_xml_format(self):
        content, ct = render_memory(self.graph, "full", None, "claude_xml")
        assert ct == "application/xml"
        assert "<user-context>" in content
        assert "</user-context>" in content
        assert "<fact" in content
        assert "Python" in content

    def test_system_prompt_format(self):
        content, ct = render_memory(self.graph, "full", None, "system_prompt")
        assert ct == "text/plain"
        assert "# User Context" in content
        assert "Python" in content

    def test_markdown_format(self):
        content, ct = render_memory(self.graph, "full", None, "markdown")
        assert ct == "text/markdown"
        assert "# Knowledge Graph" in content
        assert "Python" in content

    def test_professional_policy_filters(self):
        content, ct = render_memory(self.graph, "professional", None, "json")
        data = json.loads(content)
        nodes = data["graph"]["nodes"]
        # Professional includes identity and technical_expertise but not domain_knowledge
        labels = [n["label"] for n in nodes.values()]
        assert "Python" in labels
        assert "John Doe" in labels

    def test_custom_tags_filter(self):
        content, ct = render_memory(
            self.graph, "custom", ["identity"], "json")
        data = json.loads(content)
        nodes = data["graph"]["nodes"]
        labels = [n["label"] for n in nodes.values()]
        assert "John Doe" in labels
        # technical_expertise nodes should be excluded
        assert "Python" not in labels


# ── get_disclosed_graph ─────────────────────────────────────────────

class TestGetDisclosedGraph:
    """Test the get_disclosed_graph() helper returns correctly filtered graphs."""

    def setup_method(self):
        from cortex.graph import CortexGraph, Node

        self.graph = CortexGraph()
        self.graph.add_node(Node(
            id="n1", label="Python", tags=["technical_expertise"],
            confidence=0.9, brief="Programming language",
        ))
        self.graph.add_node(Node(
            id="n2", label="John Doe", tags=["identity"],
            confidence=0.95, brief="Full name",
        ))
        self.graph.add_node(Node(
            id="n3", label="Machine Learning", tags=["domain_knowledge"],
            confidence=0.8, brief="Research area",
        ))

    def test_technical_policy_includes_correct_nodes(self):
        filtered = get_disclosed_graph(self.graph, "technical", None)
        labels = [n.label for n in filtered.nodes.values()]
        assert "Python" in labels
        assert "Machine Learning" in labels

    def test_technical_policy_excludes_identity(self):
        filtered = get_disclosed_graph(self.graph, "technical", None)
        labels = [n.label for n in filtered.nodes.values()]
        assert "John Doe" not in labels

    def test_custom_tags_filtering(self):
        filtered = get_disclosed_graph(self.graph, "custom", ["identity"])
        labels = [n.label for n in filtered.nodes.values()]
        assert "John Doe" in labels
        assert "Python" not in labels

    def test_render_memory_unchanged_after_refactor(self):
        """Regression: render_memory still produces the same output via get_disclosed_graph."""
        content, ct = render_memory(self.graph, "full", None, "json")
        data = json.loads(content)
        labels = [n["label"] for n in data["graph"]["nodes"].values()]
        assert "Python" in labels
        assert "John Doe" in labels
        assert "Machine Learning" in labels
        assert ct == "application/json"
