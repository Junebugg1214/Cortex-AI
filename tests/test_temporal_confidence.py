from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from cortex.cli import main
from cortex.cli_extract_commands import finalize_extraction_output
from cortex.compat import upgrade_v4_to_v5
from cortex.extract_memory_context import ExtractionContext
from cortex.graph import CortexGraph, Node, make_node_id
from cortex.minds import _persist_mind_core_graph, init_mind
from cortex.temporal import (
    TEMPORAL_REVIEW_QUEUE_KEY,
    analyze_temporal_context,
    apply_temporal_review_policy,
    temporal_confidence_threshold,
)


@pytest.mark.parametrize(
    ("text", "document_timestamp", "expected_confidence", "expected_signal", "review_required"),
    [
        ("On 2026-02-01 Atlas launched.", None, 1.0, "explicit_timestamp", False),
        ("Launch happened on 02/01/2026.", None, 1.0, "explicit_timestamp", False),
        ("Update at 11:45 PM UTC.", None, 1.0, "explicit_timestamp", False),
        (
            "Yesterday Atlas launched.",
            datetime(2026, 2, 2, 10, 0, tzinfo=timezone.utc),
            0.75,
            "relative_reference",
            False,
        ),
        ("Atlas is currently active.", None, 0.45, "contextual_inference", True),
        ("Atlas exists.", None, 0.1, "no_recoverable_signal", True),
    ],
)
def test_analyze_temporal_context_returns_expected_band(
    text,
    document_timestamp,
    expected_confidence,
    expected_signal,
    review_required,
):
    result = analyze_temporal_context(text, document_timestamp=document_timestamp)

    assert result["temporal_confidence"] == expected_confidence
    assert result["temporal_signal"] == expected_signal
    assert result["review_required"] is review_required


@pytest.mark.parametrize(
    ("text", "timeline", "expected_confidence", "expected_signal"),
    [
        ("On 2026-02-01 Atlas launched.", ["past"], 1.0, "explicit_timestamp"),
        (
            "Yesterday Atlas launched.",
            ["past"],
            0.75,
            "relative_reference",
        ),
        ("Atlas is currently active.", ["current"], 0.45, "contextual_inference"),
        ("Atlas exists.", ["current"], 0.1, "no_recoverable_signal"),
    ],
)
def test_active_source_context_attaches_temporal_metadata(text, timeline, expected_confidence, expected_signal):
    ctx = ExtractionContext()
    ctx.set_active_source_context(text, datetime(2026, 2, 2, 10, 0, tzinfo=timezone.utc))
    ctx.add_topic("active_priorities", "Project Atlas", timeline=timeline, extraction_method="explicit_statement")

    topic = ctx.export()["categories"]["active_priorities"][0]

    assert topic["_temporal_confidence"] == expected_confidence
    assert topic["_temporal_signal"] == expected_signal


def _temporal_graph(confidence: float, signal: str, *, label: str = "Project Atlas") -> CortexGraph:
    node = Node(
        id=make_node_id(label),
        label=label,
        tags=["active_priorities"],
        properties={"temporal_confidence": confidence, "temporal_signal": signal},
        timeline=["current"],
        status="active",
    )
    graph = CortexGraph()
    graph.add_node(node)
    return graph


@pytest.mark.parametrize(
    ("confidence", "threshold", "expected_queue_count", "expected_pending"),
    [
        (0.45, 0.5, 1, True),
        (0.1, 0.5, 1, True),
        (0.5, 0.5, 0, False),
        (0.75, 0.5, 0, False),
    ],
)
def test_apply_temporal_review_policy_respects_threshold(confidence, threshold, expected_queue_count, expected_pending):
    graph = _temporal_graph(confidence, "contextual_inference")

    payload = apply_temporal_review_policy(graph, threshold=threshold)
    node = next(iter(graph.nodes.values()))

    assert payload["queue_count"] == expected_queue_count
    assert len(graph.meta[TEMPORAL_REVIEW_QUEUE_KEY]) == expected_queue_count
    assert bool(node.properties.get("temporal_review_pending", False)) is expected_pending


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        ("0.65", 0.65),
        ("1.5", 0.5),
        ("not-a-number", 0.5),
        ("", 0.5),
    ],
)
def test_temporal_confidence_threshold_reads_environment(monkeypatch, env_value, expected):
    monkeypatch.setenv("CORTEX_TEMPORAL_CONFIDENCE_THRESHOLD", env_value)

    assert temporal_confidence_threshold() == expected


def test_apply_temporal_review_policy_strips_canonical_temporal_fields_when_queued():
    graph = _temporal_graph(0.45, "contextual_inference")

    apply_temporal_review_policy(graph, threshold=0.5)
    node = next(iter(graph.nodes.values()))

    assert node.timeline == []
    assert node.valid_from == ""
    assert node.valid_to == ""
    assert node.status == ""


def test_finalize_extraction_output_queues_subthreshold_temporal_facts(tmp_path):
    input_path = tmp_path / "incident.md"
    input_path.write_text("Atlas is currently active.", encoding="utf-8")
    v4_output = {
        "schema_version": "4.0",
        "categories": {
            "active_priorities": [
                {
                    "topic": "Project Atlas",
                    "brief": "Project Atlas",
                    "confidence": 0.9,
                    "timeline": ["current"],
                    "_temporal_confidence": 0.45,
                    "_temporal_signal": "contextual_inference",
                }
            ]
        },
    }

    result, _ = finalize_extraction_output(v4_output, input_path=input_path, fmt="text", record_claims=False)
    graph = upgrade_v4_to_v5(result)
    node = next(iter(graph.nodes.values()))

    assert len(graph.meta[TEMPORAL_REVIEW_QUEUE_KEY]) == 1
    assert node.properties["temporal_review_pending"] is True
    assert node.timeline == []


def test_finalize_extraction_output_keeps_high_confidence_temporal_facts(tmp_path):
    input_path = tmp_path / "incident.md"
    input_path.write_text("On 2026-02-01 Atlas launched.", encoding="utf-8")
    v4_output = {
        "schema_version": "4.0",
        "categories": {
            "active_priorities": [
                {
                    "topic": "Project Atlas",
                    "brief": "Project Atlas",
                    "confidence": 0.9,
                    "timeline": ["past"],
                    "_temporal_confidence": 1.0,
                    "_temporal_signal": "explicit_timestamp",
                }
            ]
        },
    }

    result, _ = finalize_extraction_output(v4_output, input_path=input_path, fmt="text", record_claims=False)
    graph = upgrade_v4_to_v5(result)
    node = next(iter(graph.nodes.values()))

    assert graph.meta[TEMPORAL_REVIEW_QUEUE_KEY] == []
    assert node.timeline == ["past"]
    assert "temporal_review_pending" not in node.properties


def test_timeline_review_cli_lists_pending_temporal_items(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "ops", owner="tester")
    graph = _temporal_graph(0.45, "contextual_inference")
    apply_temporal_review_policy(graph, threshold=0.5)
    _persist_mind_core_graph(store_dir, "ops", graph, message="seed temporal queue", source="tests.temporal")

    rc = main(
        [
            "timeline",
            "review",
            "--mind",
            "ops",
            "--min-confidence",
            "0.5",
            "--store-dir",
            str(store_dir),
        ]
    )
    output = capsys.readouterr().out

    assert rc == 0
    assert "Temporal review queue" in output
    assert "Project Atlas" in output


def test_timeline_review_cli_handles_empty_queue(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "ops", owner="tester")
    graph = _temporal_graph(1.0, "explicit_timestamp")
    apply_temporal_review_policy(graph, threshold=0.5)
    _persist_mind_core_graph(store_dir, "ops", graph, message="seed empty temporal queue", source="tests.temporal")

    rc = main(["timeline", "review", "--mind", "ops", "--store-dir", str(store_dir)])
    output = capsys.readouterr().out

    assert rc == 0
    assert "No pending temporal review items" in output

