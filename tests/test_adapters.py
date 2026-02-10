"""
Tests for UPAI Phase 3: Platform Adapters

Covers:
- ClaudeAdapter push generates preferences.txt and memories.json
- ClaudeAdapter push with disclosure policy filters correctly
- ClaudeAdapter pull parses memories JSON back to graph
- SystemPromptAdapter push generates system_prompt.txt
- NotionAdapter push generates markdown + database JSON
- GDocsAdapter push generates HTML
- Push with identity adds UPAI metadata
- Push output files exist at expected paths
- Adapter registry contains all 4
- Empty graph produces valid (but minimal) output
"""

import json
import tempfile
from pathlib import Path

from cortex.graph import CortexGraph, Node, Edge
from cortex.upai.identity import UPAIIdentity
from cortex.upai.disclosure import BUILTIN_POLICIES, DisclosurePolicy
from cortex.adapters import (
    ADAPTERS, ClaudeAdapter, SystemPromptAdapter,
    NotionAdapter, GDocsAdapter,
)


def _sample_graph() -> CortexGraph:
    g = CortexGraph()
    g.add_node(Node(id="n1", label="Marc", tags=["identity"],
                    confidence=0.95, brief="Marc Saint-Jour"))
    g.add_node(Node(id="n2", label="Python", tags=["technical_expertise"],
                    confidence=0.9, brief="Python programming"))
    g.add_node(Node(id="n3", label="Healthcare", tags=["domain_knowledge"],
                    confidence=0.8, brief="Healthcare domain"))
    g.add_node(Node(id="n4", label="Direct style", tags=["communication_preferences"],
                    confidence=0.85, brief="Prefers direct communication"))
    g.add_edge(Edge(id="e1", source_id="n2", target_id="n3", relation="used_in"))
    return g


class TestClaudeAdapter:

    def test_push_generates_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ClaudeAdapter()
            paths = adapter.push(_sample_graph(), BUILTIN_POLICIES["full"],
                                output_dir=Path(tmpdir))
            assert len(paths) == 2
            filenames = {p.name for p in paths}
            assert "claude_preferences.txt" in filenames
            assert "claude_memories.json" in filenames
            for p in paths:
                assert p.exists()
                assert p.stat().st_size > 0

    def test_push_with_policy_filters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ClaudeAdapter()
            # Minimal policy: only identity + communication_preferences, conf >= 0.8
            paths = adapter.push(_sample_graph(), BUILTIN_POLICIES["minimal"],
                                output_dir=Path(tmpdir))
            prefs_path = Path(tmpdir) / "claude_preferences.txt"
            prefs = prefs_path.read_text()
            # Should contain Marc (identity) and Direct style (communication)
            assert "Marc" in prefs

    def test_pull_parses_memories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # First push
            adapter = ClaudeAdapter()
            adapter.push(_sample_graph(), BUILTIN_POLICIES["full"],
                        output_dir=Path(tmpdir))
            # Then pull
            mem_path = Path(tmpdir) / "claude_memories.json"
            graph = adapter.pull(mem_path)
            assert len(graph.nodes) > 0

    def test_push_with_identity_adds_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ClaudeAdapter()
            identity = UPAIIdentity.generate("Test")
            adapter.push(_sample_graph(), BUILTIN_POLICIES["full"],
                        identity=identity, output_dir=Path(tmpdir))
            mem_path = Path(tmpdir) / "claude_memories.json"
            data = json.loads(mem_path.read_text())
            # Should be wrapped in UPAI envelope
            assert "upai_version" in data
            assert "upai_identity" in data
            assert data["upai_identity"]["did"] == identity.did
            assert "integrity_hash" in data
            assert "signature" in data


class TestSystemPromptAdapter:

    def test_push_generates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = SystemPromptAdapter()
            paths = adapter.push(_sample_graph(), BUILTIN_POLICIES["full"],
                                output_dir=Path(tmpdir))
            assert len(paths) == 1
            assert paths[0].name == "system_prompt.txt"
            assert paths[0].exists()
            content = paths[0].read_text()
            assert "<user_context>" in content

    def test_push_with_identity_adds_did(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = SystemPromptAdapter()
            identity = UPAIIdentity.generate("Test")
            paths = adapter.push(_sample_graph(), BUILTIN_POLICIES["full"],
                                identity=identity, output_dir=Path(tmpdir))
            content = paths[0].read_text()
            assert identity.did in content


class TestNotionAdapter:

    def test_push_generates_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = NotionAdapter()
            paths = adapter.push(_sample_graph(), BUILTIN_POLICIES["full"],
                                output_dir=Path(tmpdir))
            assert len(paths) == 2
            filenames = {p.name for p in paths}
            assert "notion_page.md" in filenames
            assert "notion_database.json" in filenames
            for p in paths:
                assert p.exists()

    def test_pull_not_supported(self):
        adapter = NotionAdapter()
        try:
            adapter.pull(Path("fake.md"))
            assert False, "Should have raised NotImplementedError"
        except NotImplementedError:
            pass


class TestGDocsAdapter:

    def test_push_generates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = GDocsAdapter()
            paths = adapter.push(_sample_graph(), BUILTIN_POLICIES["full"],
                                output_dir=Path(tmpdir))
            assert len(paths) == 1
            assert paths[0].name == "google_docs.html"
            assert paths[0].exists()
            content = paths[0].read_text()
            assert "<html>" in content

    def test_pull_not_supported(self):
        adapter = GDocsAdapter()
        try:
            adapter.pull(Path("fake.html"))
            assert False, "Should have raised NotImplementedError"
        except NotImplementedError:
            pass


class TestAdapterRegistry:

    def test_all_adapters_registered(self):
        assert "claude" in ADAPTERS
        assert "system-prompt" in ADAPTERS
        assert "notion" in ADAPTERS
        assert "gdocs" in ADAPTERS
        assert len(ADAPTERS) == 4

    def test_adapter_names(self):
        assert ADAPTERS["claude"].name == "claude"
        assert ADAPTERS["system-prompt"].name == "system-prompt"
        assert ADAPTERS["notion"].name == "notion"
        assert ADAPTERS["gdocs"].name == "gdocs"


class TestEmptyGraph:

    def test_empty_graph_claude(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ClaudeAdapter()
            paths = adapter.push(CortexGraph(), BUILTIN_POLICIES["full"],
                                output_dir=Path(tmpdir))
            assert len(paths) == 2
            for p in paths:
                assert p.exists()

    def test_empty_graph_system_prompt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = SystemPromptAdapter()
            paths = adapter.push(CortexGraph(), BUILTIN_POLICIES["full"],
                                output_dir=Path(tmpdir))
            assert len(paths) == 1
            assert paths[0].exists()
