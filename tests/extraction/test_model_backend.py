from __future__ import annotations

import json

import pytest

from cortex.extraction import ExtractedNode, ExtractionBackendError, ExtractionParseError, ModelBackend


def test_extract_statement_parses_json_payload(monkeypatch):
    backend = ModelBackend(api_key="test-key")
    monkeypatch.setattr(
        backend,
        "_request_json",
        lambda **_: json.dumps(
            {
                "nodes": [
                    {"label": "Python", "category": "technical_expertise", "value": "Python", "confidence": 0.91}
                ],
                "edges": [
                    {
                        "source": "Python",
                        "target": "Data Science",
                        "relationship": "used_in",
                        "direction_confidence": 0.72,
                    }
                ],
                "warnings": ["review temporal phrasing"],
            }
        ),
    )
    result = backend.extract_statement("I use Python for data science.")
    assert result.extraction_method == "model"
    assert result.nodes[0].label == "Python"
    assert result.edges[0].relationship == "used_in"
    assert result.warnings == ["review temporal phrasing"]


def test_extract_statement_sets_model_method(monkeypatch):
    backend = ModelBackend(api_key="test-key")
    monkeypatch.setattr(backend, "_request_json", lambda **_: '{"nodes":[],"edges":[],"warnings":[]}')
    assert backend.extract_statement("hello").extraction_method == "model"


def test_extract_statement_json_parse_failure_raises_with_raw_response(monkeypatch):
    backend = ModelBackend(api_key="test-key")
    raw = "not json"
    monkeypatch.setattr(backend, "_request_json", lambda **_: raw)
    with pytest.raises(ExtractionParseError) as excinfo:
        backend.extract_statement("I use Python.")
    assert excinfo.value.raw_response == raw


def test_missing_api_key_raises_actionable_error(monkeypatch):
    backend = ModelBackend()
    monkeypatch.delenv("CORTEX_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("cortex.extraction.model_backend.load_extraction_config", lambda: {})
    with pytest.raises(ExtractionBackendError) as excinfo:
        backend.extract_statement("I use Python.")
    assert str(excinfo.value) == (
        "ModelBackend requires an API key. Set CORTEX_ANTHROPIC_API_KEY\n"
        "or ANTHROPIC_API_KEY. See CONFIG.md for details."
    )
    assert "CONFIG.md" in str(excinfo.value)


def test_ambiguous_edges_both_marked_for_review(monkeypatch):
    backend = ModelBackend(api_key="test-key")
    monkeypatch.setattr(
        backend,
        "_request_json",
        lambda **_: json.dumps(
            {
                "nodes": [],
                "edges": [
                    {"source": "self", "target": "Alice", "relationship": "works_with", "direction_confidence": 0.45},
                    {"source": "Alice", "target": "self", "relationship": "works_with", "direction_confidence": 0.44},
                ],
                "warnings": [],
            }
        ),
    )
    result = backend.extract_statement("Working with Alice.")
    assert len(result.edges) == 2
    assert all(edge.direction_confidence < 0.6 for edge in result.edges)
    assert all(edge.needs_review for edge in result.edges)


def test_canonical_match_returns_match(monkeypatch):
    backend = ModelBackend(api_key="test-key")
    monkeypatch.setattr(backend, "_request_json", lambda **_: '{"canonical_match":"n1","confidence":0.93}')
    match = backend.canonical_match(
        node=ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.9),
        existing_nodes=[{"id": "n1", "label": "Python", "value": "Python"}],
    )
    assert match == ("n1", 0.93)


def test_canonical_match_returns_none_when_model_says_no_match(monkeypatch):
    backend = ModelBackend(api_key="test-key")
    monkeypatch.setattr(backend, "_request_json", lambda **_: '{"canonical_match":null,"confidence":0.0}')

    match = backend.canonical_match(
        ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.9),
        [{"id": "n1", "label": "Rust", "value": "Rust"}],
    )
    assert match == (None, 0.0)


def test_canonical_match_ignores_unknown_model_match(monkeypatch):
    backend = ModelBackend(api_key="test-key")
    monkeypatch.setattr(backend, "_request_json", lambda **_: '{"canonical_match":"missing","confidence":0.99}')

    match = backend.canonical_match(
        ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.9),
        [{"id": "n1", "label": "Rust", "value": "Rust"}],
    )
    assert match == (None, 0.0)


def test_extract_bulk_batches_in_groups_of_ten(monkeypatch):
    backend = ModelBackend(api_key="test-key")
    calls: list[dict] = []

    def _fake_request_json(**kwargs):
        calls.append(kwargs)
        batch = json.loads(kwargs["user_prompt"])["texts"]
        return json.dumps(
            {
                "results": [
                    {
                        "nodes": [{"label": text, "category": "mentions", "value": text, "confidence": 0.9}],
                        "edges": [],
                        "warnings": [],
                    }
                    for text in batch
                ]
            }
        )

    monkeypatch.setattr(backend, "_request_json", _fake_request_json)
    results = backend.extract_bulk([f"text-{index}" for index in range(25)])
    assert len(results) == 25
    assert len(calls) == 3


def test_extract_bulk_accepts_list_payload(monkeypatch):
    backend = ModelBackend(api_key="test-key")
    monkeypatch.setattr(
        backend,
        "_request_json",
        lambda **_: json.dumps(
            [{"nodes": [], "edges": [], "warnings": []}, {"nodes": [], "edges": [], "warnings": []}]
        ),
    )
    results = backend.extract_bulk(["a", "b"])
    assert len(results) == 2


def test_extract_bulk_accepts_single_dict_payload_for_one_item(monkeypatch):
    backend = ModelBackend(api_key="test-key")
    monkeypatch.setattr(backend, "_request_json", lambda **_: json.dumps({"nodes": [], "edges": [], "warnings": []}))
    results = backend.extract_bulk(["a"])
    assert len(results) == 1


def test_extract_bulk_mismatched_result_count_raises(monkeypatch):
    backend = ModelBackend(api_key="test-key")
    monkeypatch.setattr(
        backend, "_request_json", lambda **_: json.dumps({"results": [{"nodes": [], "edges": [], "warnings": []}]})
    )
    with pytest.raises(ExtractionParseError):
        backend.extract_bulk(["a", "b"])


def test_extract_bulk_non_object_item_raises(monkeypatch):
    backend = ModelBackend(api_key="test-key")
    monkeypatch.setattr(backend, "_request_json", lambda **_: json.dumps({"results": ["bad"]}))
    with pytest.raises(ExtractionParseError):
        backend.extract_bulk(["a"])


def test_extract_bulk_unexpected_shape_raises(monkeypatch):
    backend = ModelBackend(api_key="test-key")
    monkeypatch.setattr(backend, "_request_json", lambda **_: '"bad"')
    with pytest.raises(ExtractionParseError):
        backend.extract_bulk(["a", "b"])


def test_api_key_falls_back_to_config(monkeypatch):
    backend = ModelBackend()
    monkeypatch.delenv("CORTEX_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        "cortex.extraction.model_backend.load_extraction_config", lambda: {"anthropic_api_key": "cfg-key"}
    )
    assert backend._api_key() == "cfg-key"


def test_support_flags():
    backend = ModelBackend(api_key="test-key")
    assert backend.supports_async_rescoring is True
    assert backend.supports_embeddings is False
