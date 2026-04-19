from __future__ import annotations

from cortex.extraction.eval.metrics import (
    MetricReport,
    canonicalization_accuracy,
    completeness_score,
    contradiction_recall,
    node_prf,
    relation_prf,
)
from cortex.graph.graph import CortexGraph, Edge, Node


def test_node_prf_exact_matches_on_type_and_canonical_label() -> None:
    gold = {
        "expected_graph": {
            "nodes": [
                {"canonical_id": "person:maya", "label": "Maya Chen", "type": "identity"},
                {"canonical_id": "role:lead", "label": "Platform Lead", "type": "professional_context"},
            ],
            "edges": [],
        }
    }
    predicted = {
        "nodes": [
            {"canonical_id": "pred-1", "canonical_label": "maya chen", "type": "identity"},
            {"canonical_id": "pred-2", "label": "Platform Lead", "type": "professional_context"},
        ],
        "edges": [],
    }

    precision, recall, f1 = node_prf(predicted, gold)

    assert isinstance(precision, MetricReport)
    assert precision.value == 1.0
    assert precision.numerator == 2
    assert precision.denominator == 2
    assert recall.value == 1.0
    assert f1.value == 1.0
    assert precision.per_class_breakdown["identity"]["value"] == 1.0


def test_node_prf_partial_match_counts_false_positive_and_false_negative() -> None:
    gold = {
        "nodes": [
            {"canonical_id": "person:maya", "label": "Maya Chen", "type": "identity"},
            {"canonical_id": "pref:short", "label": "Concise status updates", "type": "preference"},
        ]
    }
    predicted = {
        "nodes": [
            {"canonical_id": "person:maya", "label": "Maya Chen", "type": "identity"},
            {"canonical_id": "stack:fastapi", "label": "FastAPI", "type": "technical_expertise"},
        ]
    }

    precision, recall, f1 = node_prf(predicted, gold)

    assert precision.value == 0.5
    assert recall.value == 0.5
    assert f1.value == 0.5
    assert recall.per_class_breakdown["preference"]["value"] == 0.0
    assert precision.per_class_breakdown["technical_expertise"]["value"] == 0.0
    assert [failure.kind for failure in recall.failures] == ["missed_node"]
    assert [failure.kind for failure in precision.failures] == ["hallucinated_node"]


def test_relation_prf_matches_on_endpoint_labels_and_relation() -> None:
    gold = {
        "nodes": [
            {"canonical_id": "person:maya", "label": "Maya Chen", "type": "identity"},
            {"canonical_id": "role:lead", "label": "Platform Lead", "type": "professional_context"},
            {"canonical_id": "pref:short", "label": "Concise status updates", "type": "preference"},
        ],
        "edges": [
            {"source": "person:maya", "target": "role:lead", "type": "has_role"},
            {"source": "person:maya", "target": "pref:short", "type": "prefers"},
        ],
    }
    predicted = CortexGraph()
    predicted.add_node(Node(id="n1", label="Maya Chen", tags=["identity"]))
    predicted.add_node(Node(id="n2", label="Platform Lead", tags=["professional_context"]))
    predicted.add_node(Node(id="n3", label="FastAPI", tags=["technical_expertise"]))
    predicted.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="has_role"))
    predicted.add_edge(Edge(id="e2", source_id="n1", target_id="n3", relation="uses_stack"))

    precision, recall, f1 = relation_prf(predicted, gold)

    assert precision.value == 0.5
    assert recall.value == 0.5
    assert f1.value == 0.5
    assert recall.per_class_breakdown["prefers"]["value"] == 0.0
    assert precision.per_class_breakdown["uses_stack"]["value"] == 0.0
    assert [failure.kind for failure in recall.failures] == ["missed_relation"]
    assert [failure.kind for failure in precision.failures] == ["hallucinated_relation"]


def test_canonicalization_accuracy_scores_aliases_mapped_to_gold_ids() -> None:
    gold = {
        "nodes": [
            {
                "canonical_id": "person:alice-smith",
                "label": "Alice Smith",
                "type": "identity",
                "aliases": ["alice", "a. smith"],
            },
            {
                "canonical_id": "project:atlas",
                "label": "Atlas",
                "type": "business_context",
                "aliases": ["atlas project"],
            },
        ]
    }
    predicted = {
        "nodes": [
            {
                "canonical_id": "person:alice-smith",
                "label": "Alice Smith",
                "type": "identity",
                "aliases": ["Alice"],
            },
            {
                "canonical_id": "wrong:atlas",
                "label": "Atlas",
                "type": "business_context",
                "aliases": ["atlas project"],
            },
        ],
        "alias_resolutions": [{"alias": "A. Smith", "canonical_id": "person:alice-smith"}],
    }

    report = canonicalization_accuracy(predicted, gold)

    assert report.value == 2 / 3
    assert report.numerator == 2
    assert report.denominator == 3
    assert report.per_class_breakdown["atlas project"]["value"] == 0.0
    assert [failure.kind for failure in report.failures] == ["bad_canonicalization"]


def test_contradiction_recall_matches_detected_contradictions_independent_of_direction() -> None:
    gold = {
        "nodes": [
            {"canonical_id": "claim:june", "label": "Phoenix launches June 1", "type": "claim"},
            {"canonical_id": "claim:july", "label": "Phoenix launches July 15", "type": "claim"},
            {"canonical_id": "claim:ga", "label": "Phoenix is generally available", "type": "claim"},
        ],
        "edges": [
            {"source": "claim:june", "target": "claim:july", "type": "contradicts"},
            {"source": "claim:july", "target": "claim:ga", "type": "contradicts"},
        ],
    }
    predicted = {
        "nodes": [
            {"canonical_id": "claim:june", "label": "Phoenix launches June 1", "type": "claim"},
            {"canonical_id": "claim:july", "label": "Phoenix launches July 15", "type": "claim"},
        ],
        "edges": [
            {"source": "claim:july", "target": "claim:june", "type": "contradicts"},
        ],
    }

    report = contradiction_recall(predicted, gold)

    assert report.value == 0.5
    assert report.numerator == 1
    assert report.denominator == 2
    assert report.per_class_breakdown["contradicts"]["value"] == 0.5
    assert [failure.kind for failure in report.failures] == ["missed_contradiction"]


def test_completeness_score_ignores_type_when_gold_label_is_present() -> None:
    gold = {
        "nodes": [
            {"canonical_id": "person:maya", "label": "Maya Chen", "type": "identity"},
            {"canonical_id": "role:lead", "label": "Platform Lead", "type": "professional_context"},
        ]
    }
    predicted = {
        "nodes": [
            {"canonical_id": "person:maya", "label": "Maya Chen", "type": "mentions"},
        ]
    }

    report = completeness_score(predicted, gold)

    assert report.value == 0.5
    assert report.numerator == 1
    assert report.denominator == 2
    assert report.per_class_breakdown["identity"]["value"] == 1.0
    assert report.per_class_breakdown["professional_context"]["value"] == 0.0
