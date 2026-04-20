from __future__ import annotations

from cortex.extraction import Document, ExtractionContext, ModelBackend, NodeHint, retrieve_similar_nodes
from cortex.extraction.eval.replay_cache import ReplayCache
from cortex.extraction.model_backend import _TYPED_EXTRACTION_TOOL_NAME
from cortex.graph.graph import CortexGraph, Node


class _Usage:
    input_tokens = 21
    output_tokens = 9


class _ToolBlock:
    type = "tool_use"
    name = _TYPED_EXTRACTION_TOOL_NAME

    def __init__(self, tool_input: dict) -> None:
        self.input = tool_input


class _Response:
    usage = _Usage()
    model = "claude-3-5-sonnet-20241022"

    def __init__(self, payload: dict) -> None:
        self.content = [_ToolBlock(payload)]


class _Messages:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.payload)


class _EmbeddingStub:
    def search_nodes(self, query: str, nodes: list[Node], top_k: int = 5, threshold: float = 0.0):
        assert "alice" in query.lower()
        node = nodes[0]
        return [
            {
                "id": node.id,
                "label": node.label,
                "type": node.tags[0],
                "confidence": node.confidence,
                "score": 0.88,
                "node": node,
            }
        ][:top_k]


def _install_stubbed_client(backend: ModelBackend, messages: _Messages, monkeypatch) -> None:
    class _Client:
        def __init__(self, *, api_key: str) -> None:
            self.api_key = api_key
            self.messages = messages

    monkeypatch.setattr(backend, "_anthropic_client_cls", lambda: _Client)


def test_retrieve_similar_nodes_returns_node_hints() -> None:
    graph = CortexGraph()
    graph.add_node(Node(id="alice-smith", label="Alice Smith", tags=["identity"], confidence=0.93))

    hints = retrieve_similar_nodes(_EmbeddingStub(), graph, "alice joined the team", top_k=8, threshold=0.72)

    assert hints == [
        NodeHint(
            node_id="alice-smith",
            label="Alice Smith",
            type="identity",
            confidence=0.93,
            similarity=0.88,
        )
    ]


def test_model_backend_uses_retrieval_hint_as_existing_node_alias(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CORTEX_EXTRACTION_LOG_PATH", str(tmp_path / "extractions.jsonl"))
    graph = CortexGraph()
    graph.add_node(Node(id="alice-smith", label="Alice Smith", tags=["identity"], confidence=0.93))
    response_payload = {
        "items": [
            {
                "extraction_type": "fact",
                "topic": "alice",
                "category": "identity",
                "brief": "alice joined the team",
                "confidence": 0.91,
                "attribute_name": "person",
                "attribute_value": "alice",
                "entity_resolution": "alice-smith",
            }
        ],
        "warnings": [],
    }
    messages = _Messages(response_payload)
    backend = ModelBackend(
        api_key="test-key",
        embedding_backend=_EmbeddingStub(),
        replay_cache=ReplayCache(mode="off"),
    )
    _install_stubbed_client(backend, messages, monkeypatch)

    result = backend.run(
        Document(source_id="retrieval-doc", source_type="chat", content="alice joined the team"),
        ExtractionContext(existing_graph=graph, prompt_version="retrieval-v1"),
    )

    assert len(result.items) == 1
    assert result.items[0].entity_resolution == "alice-smith"
    assert len(graph.nodes) == 1
    assert graph.find_node_ids_by_label("alice") == ["alice-smith"]
    assert "alice" in graph.nodes["alice-smith"].aliases
    prompt = messages.calls[0]["messages"][0]["content"]
    assert "## Existing known entities" in prompt
    assert "Reuse these IDs when a new mention refers to the same entity." in prompt
    assert "node_id: alice-smith" in prompt
