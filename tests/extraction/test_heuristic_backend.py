from __future__ import annotations

import json
from pathlib import Path

from cortex.compat import upgrade_v4_to_v5
from cortex.extract_memory_context import ExtractedClaim, ExtractedFact, ExtractedRelationship
from cortex.extraction import (
    HeuristicBackend,
    graph_from_result,
    merged_graph_from_results,
    merged_v4_from_results,
    result_from_graph,
    v4_from_result,
)
from cortex.extraction.heuristic_rules import HeuristicRuleExtractor
from cortex.extraction.pipeline import Document, ExtractionContext
from cortex.temporal import apply_temporal_review_policy


def _rule_statement_graph(text: str):
    extractor = HeuristicRuleExtractor()
    extractor.extract_from_text(text)
    extractor.post_process()
    payload = extractor.context.export()
    graph = upgrade_v4_to_v5(payload)
    if graph.nodes:
        apply_temporal_review_policy(graph)
    return graph, payload


def _normalize_v5(graph):
    payload = graph.export_v5()
    payload["meta"]["generated_at"] = "<normalized>"
    return payload


def _normalize_v4(payload):
    normalized = json.loads(json.dumps(payload))
    normalized["meta"]["generated_at"] = "<normalized>"
    return normalized


def _sample_chat_content() -> str:
    fixture = Path(__file__).parents[1] / "fixtures" / "sample_chat.json"
    messages = json.loads(fixture.read_text())
    return "\n\n".join(message["content"] for message in messages if message.get("role") == "user")


def test_run_emits_typed_sample_chat_counts():
    backend = HeuristicBackend()
    result = backend.run(
        Document(source_id="sample-chat", source_type="chat", content=_sample_chat_content()),
        ExtractionContext(),
    )

    facts = [item for item in result.items if isinstance(item, ExtractedFact)]
    claims = [item for item in result.items if isinstance(item, ExtractedClaim)]
    relationships = [item for item in result.items if isinstance(item, ExtractedRelationship)]

    assert (len(facts), len(claims), len(relationships)) == (5, 1, 1)
    assert len(result.items) == 7


def test_extract_statement_matches_rule_graph_output():
    backend = HeuristicBackend()
    text = "My name is Alex and I use Python for data science work."
    result = backend.extract_statement(text)
    rule_graph, _ = _rule_statement_graph(text)
    assert _normalize_v5(graph_from_result(result)) == _normalize_v5(rule_graph)


def test_extract_statement_matches_rule_graph_output_for_relationships():
    backend = HeuristicBackend()
    text = "We partner with Mayo Clinic and I use Python."
    result = backend.extract_statement(text)
    rule_graph, _ = _rule_statement_graph(text)
    assert _normalize_v5(graph_from_result(result)) == _normalize_v5(rule_graph)


def test_extract_statement_uses_heuristic_method():
    backend = HeuristicBackend()
    result = backend.extract_statement("I use Rust.")
    assert result.extraction_method == "heuristic"


def test_extract_statement_fallback_graph_when_no_nodes_found():
    backend = HeuristicBackend()
    result = backend.extract_statement("short")
    graph = graph_from_result(result, fallback_statement="short")
    assert len(graph.nodes) == 1


def test_extract_statement_preserves_raw_source():
    backend = HeuristicBackend()
    result = backend.extract_statement("I use Python.")
    assert result.raw_source == "I use Python."


def test_extract_bulk_with_context_matches_rule_v4_payload():
    backend = HeuristicBackend()
    extractor = HeuristicRuleExtractor()
    data = {"messages": [{"role": "user", "content": "I use Python and Rust."}]}
    results = backend.extract_bulk([], context={"extractor": extractor, "data": data, "fmt": "messages"})
    rule_extractor = HeuristicRuleExtractor()
    rule_extractor.process_messages_list(data["messages"])
    assert _normalize_v4(v4_from_result(results[0])) == _normalize_v4(rule_extractor.context.export())


def test_extract_bulk_without_context_returns_one_result_per_text():
    backend = HeuristicBackend()
    results = backend.extract_bulk(["I use Python.", "I use Rust."])
    assert len(results) == 2
    assert all(result.extraction_method == "heuristic" for result in results)


def test_v4_from_result_uses_cached_heuristic_payload_exactly():
    backend = HeuristicBackend()
    text = "I use Python."
    result = backend.extract_statement(text)
    _, payload = _rule_statement_graph(text)
    assert _normalize_v4(v4_from_result(result)) == _normalize_v4(payload)


def test_graph_from_result_uses_cached_heuristic_graph_exactly():
    backend = HeuristicBackend()
    text = "I use Python."
    result = backend.extract_statement(text)
    rule_graph, _ = _rule_statement_graph(text)
    assert _normalize_v5(graph_from_result(result)) == _normalize_v5(rule_graph)


def test_merged_v4_from_results_single_result_stays_exact():
    backend = HeuristicBackend()
    result = backend.extract_statement("I use Python.")
    assert merged_v4_from_results([result]) == v4_from_result(result)


def test_merged_graph_from_results_merges_multiple_statements():
    backend = HeuristicBackend()
    results = backend.extract_bulk(["I use Python.", "I use Rust."])
    graph = merged_graph_from_results(results)
    labels = {node.label for node in graph.nodes.values()}
    assert "Python" in labels
    assert "Rust" in labels


def test_canonical_match_always_returns_none():
    backend = HeuristicBackend()
    match = backend.canonical_match(
        result_from_graph(
            _rule_statement_graph("I use Python.")[0], raw_source="", extraction_method="heuristic"
        ).nodes[0],
        [],
    )
    assert match == (None, 0.0)


def test_support_flags_are_false():
    backend = HeuristicBackend()
    assert backend.supports_async_rescoring is False
    assert backend.supports_embeddings is False
