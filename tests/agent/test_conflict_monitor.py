"""Tests for the autonomous conflict monitor."""

from __future__ import annotations

import json
import time
from pathlib import Path

from cortex.agent.conflict_monitor import (
    ConflictMonitor,
    ConflictMonitorConfig,
    conflict_status,
    detect_conflicts,
    load_pending_conflicts,
    professional_history_flags,
    review_pending_conflicts,
)
from cortex.cli import main
from cortex.graph import CortexGraph, Node
from cortex.minds import _persist_mind_core_graph, init_mind, load_mind_core_graph, set_default_mind
from cortex.portable_runtime import load_canonical_graph, save_canonical_graph


def _graph_with(*nodes: Node) -> CortexGraph:
    graph = CortexGraph()
    for node in nodes:
        graph.add_node(node)
    return graph


def _node(
    label: str,
    tag: str,
    *,
    confidence: float,
    source: str,
    method: str,
    timestamp: str,
    snapshots: list[dict] | None = None,
    **kwargs,
) -> Node:
    payload = {
        "id": kwargs.pop("id", f"{tag}:{label}".replace(" ", "_").lower()),
        "label": label,
        "tags": kwargs.pop("tags", [tag]),
        "confidence": confidence,
        "provenance": [{"source": source, "method": method, "timestamp": timestamp}],
    }
    payload.update(kwargs)
    payload["snapshots"] = list(snapshots or [])
    return Node(**payload)


def _seed_default_mind(store_dir: Path, mind_id: str, graph: CortexGraph) -> None:
    init_mind(store_dir, mind_id, owner="tester")
    set_default_mind(store_dir, mind_id)
    _persist_mind_core_graph(
        store_dir,
        mind_id,
        graph,
        message=f"seed {mind_id}",
        source="tests.agent.seed",
    )


def _seed_canonical(store_dir: Path, graph: CortexGraph) -> None:
    state_path = store_dir / "portable"
    state_path.mkdir(parents=True, exist_ok=True)
    save_canonical_graph(store_dir, graph)


def test_detect_conflicts_groups_preference_nodes_from_different_sources():
    graph = _graph_with(
        _node(
            "Prefers terse answers",
            "communication_preferences",
            confidence=0.95,
            source="manual-chat",
            method="manual",
            timestamp="2026-04-10T12:00:00Z",
        ),
        _node(
            "Prefers detailed explanations",
            "communication_preferences",
            confidence=0.15,
            source="imported-profile",
            method="extract",
            timestamp="2026-03-01T08:00:00Z",
        ),
    )

    proposals = detect_conflicts(
        graph,
        graph_scope="mind:personal",
        graph_source="mind_branch",
        scope_entity="personal",
        mind_id="personal",
    )

    assert len(proposals) == 1
    assert proposals[0].attribute == "communication_preferences"


def test_detect_conflicts_captures_full_lineage():
    graph = _graph_with(
        _node(
            "Prefers terse answers",
            "communication_preferences",
            confidence=0.9,
            source="manual-chat",
            method="manual",
            timestamp="2026-04-10T12:00:00Z",
            snapshots=[{"source": "manual-chat", "method": "manual", "timestamp": "2026-04-10T12:05:00Z"}],
        ),
        _node(
            "Prefers detailed explanations",
            "communication_preferences",
            confidence=0.2,
            source="imported-profile",
            method="extract",
            timestamp="2026-03-01T08:00:00Z",
        ),
    )

    proposal = detect_conflicts(
        graph,
        graph_scope="mind:personal",
        graph_source="mind_branch",
        scope_entity="personal",
        mind_id="personal",
    )[0]

    manual_entry = next(item for item in proposal.sources_in_tension if item["value"] == "Prefers terse answers")
    assert len(manual_entry["lineage"]) == 2
    assert manual_entry["lineage"][0]["source"] == "manual-chat"


def test_detect_conflicts_uses_scope_entity_for_scalar_tags():
    graph = _graph_with(
        _node(
            "Senior Engineer",
            "professional_context",
            confidence=0.91,
            source="resume-v1",
            method="extract",
            timestamp="2026-02-01T00:00:00Z",
        ),
        _node(
            "Staff Engineer",
            "professional_context",
            confidence=0.92,
            source="resume-v2",
            method="extract",
            timestamp="2026-03-01T00:00:00Z",
        ),
    )

    proposal = detect_conflicts(
        graph,
        graph_scope="mind:career",
        graph_source="mind_branch",
        scope_entity="career",
        mind_id="career",
    )[0]

    assert proposal.entity == "career"


def test_detect_conflicts_does_not_treat_distinct_work_history_nodes_as_same_entity():
    graph = _graph_with(
        _node(
            "Engineer at Acme",
            "work_history",
            confidence=0.9,
            source="resume",
            method="extract",
            timestamp="2026-01-01T00:00:00Z",
            status="historical",
            valid_to="2023-12-31T00:00:00Z",
        ),
        _node(
            "Staff Engineer at Beta",
            "work_history",
            confidence=0.9,
            source="resume",
            method="extract",
            timestamp="2026-01-01T00:00:00Z",
            status="active",
            valid_from="2024-01-01T00:00:00Z",
        ),
    )

    proposals = detect_conflicts(
        graph,
        graph_scope="mind:career",
        graph_source="mind_branch",
        scope_entity="career",
        mind_id="career",
    )

    assert proposals == []


def test_severity_identity_conflicts_are_critical():
    graph = _graph_with(
        _node(
            "Jordan Lee", "identity", confidence=0.9, source="doc-a", method="extract", timestamp="2026-01-01T00:00:00Z"
        ),
        _node(
            "Jordan Li", "identity", confidence=0.6, source="doc-b", method="extract", timestamp="2026-01-02T00:00:00Z"
        ),
    )

    proposal = detect_conflicts(
        graph,
        graph_scope="mind:identity",
        graph_source="mind_branch",
        scope_entity="identity",
        mind_id="identity",
    )[0]

    assert proposal.severity == "CRITICAL"


def test_severity_professional_conflicts_are_high():
    graph = _graph_with(
        _node(
            "Engineer",
            "professional_context",
            confidence=0.9,
            source="resume-a",
            method="extract",
            timestamp="2026-01-01T00:00:00Z",
        ),
        _node(
            "Designer",
            "professional_context",
            confidence=0.8,
            source="resume-b",
            method="extract",
            timestamp="2026-01-02T00:00:00Z",
        ),
    )

    proposal = detect_conflicts(
        graph,
        graph_scope="mind:career",
        graph_source="mind_branch",
        scope_entity="career",
        mind_id="career",
    )[0]

    assert proposal.severity == "HIGH"


def test_severity_medical_keyword_conflicts_are_high():
    graph = _graph_with(
        _node(
            "Medication: penicillin",
            "mentions",
            confidence=0.7,
            source="intake-a",
            method="extract",
            timestamp="2026-01-01T00:00:00Z",
        ),
        _node(
            "Medication: none",
            "mentions",
            confidence=0.6,
            source="intake-b",
            method="extract",
            timestamp="2026-01-02T00:00:00Z",
        ),
    )

    proposal = detect_conflicts(
        graph,
        graph_scope="mind:health",
        graph_source="mind_branch",
        scope_entity="health",
        mind_id="health",
    )[0]

    assert proposal.severity == "HIGH"


def test_severity_financial_keyword_conflicts_are_high():
    graph = _graph_with(
        _node(
            "Salary expectation: 150k",
            "mentions",
            confidence=0.7,
            source="note-a",
            method="extract",
            timestamp="2026-01-01T00:00:00Z",
        ),
        _node(
            "Salary expectation: 180k",
            "mentions",
            confidence=0.6,
            source="note-b",
            method="extract",
            timestamp="2026-01-02T00:00:00Z",
        ),
    )

    proposal = detect_conflicts(
        graph,
        graph_scope="mind:career",
        graph_source="mind_branch",
        scope_entity="career",
        mind_id="career",
    )[0]

    assert proposal.severity == "HIGH"


def test_severity_preference_conflicts_are_low():
    graph = _graph_with(
        _node(
            "Use bullet points",
            "communication_preferences",
            confidence=0.7,
            source="pref-a",
            method="extract",
            timestamp="2026-01-01T00:00:00Z",
        ),
        _node(
            "Use prose only",
            "communication_preferences",
            confidence=0.6,
            source="pref-b",
            method="extract",
            timestamp="2026-01-02T00:00:00Z",
        ),
    )

    proposal = detect_conflicts(
        graph,
        graph_scope="mind:style",
        graph_source="mind_branch",
        scope_entity="style",
        mind_id="style",
    )[0]

    assert proposal.severity == "LOW"


def test_monitor_auto_resolves_low_conflicts_above_threshold_on_default_mind(tmp_path):
    store_dir = tmp_path / ".cortex"
    graph = _graph_with(
        _node(
            "Prefers terse answers",
            "communication_preferences",
            confidence=0.99,
            source="manual",
            method="manual",
            timestamp="2026-04-10T12:00:00Z",
        ),
        _node(
            "Prefers detailed explanations",
            "communication_preferences",
            confidence=0.01,
            source="import",
            method="extract",
            timestamp="2026-01-01T12:00:00Z",
        ),
    )
    _seed_default_mind(store_dir, "personal", graph)

    monitor = ConflictMonitor(
        ConflictMonitorConfig(
            store_dir=store_dir,
            interval_seconds=1,
            interactive=False,
            log_dir=tmp_path / "logs",
        )
    )
    result = monitor.run_cycle()
    updated = load_mind_core_graph(store_dir, "personal")["graph"]

    assert result["auto_resolved"] == 1
    assert result["queued"] == 0
    assert [node.label for node in updated.nodes.values()] == ["Prefers terse answers"]


def test_monitor_auto_resolve_clears_pending_queue(tmp_path):
    store_dir = tmp_path / ".cortex"
    graph = _graph_with(
        _node(
            "Keep messages short",
            "user_preferences",
            confidence=0.99,
            source="manual",
            method="manual",
            timestamp="2026-04-10T12:00:00Z",
        ),
        _node(
            "Prefer very long messages",
            "user_preferences",
            confidence=0.01,
            source="import",
            method="extract",
            timestamp="2026-01-01T12:00:00Z",
        ),
    )
    _seed_default_mind(store_dir, "personal", graph)

    monitor = ConflictMonitor(ConflictMonitorConfig(store_dir=store_dir, interactive=False, log_dir=tmp_path / "logs"))
    monitor.run_cycle()

    assert load_pending_conflicts(store_dir) == []


def test_monitor_queues_low_conflicts_below_threshold(tmp_path):
    store_dir = tmp_path / ".cortex"
    graph = _graph_with(
        _node(
            "Use short replies",
            "communication_preferences",
            confidence=0.8,
            source="pref-a",
            method="manual",
            timestamp="2026-04-10T12:00:00Z",
        ),
        _node(
            "Use medium replies",
            "communication_preferences",
            confidence=0.78,
            source="pref-b",
            method="manual",
            timestamp="2026-04-09T12:00:00Z",
        ),
    )
    _seed_default_mind(store_dir, "personal", graph)

    monitor = ConflictMonitor(ConflictMonitorConfig(store_dir=store_dir, interactive=False, log_dir=tmp_path / "logs"))
    result = monitor.run_cycle()

    assert result["auto_resolved"] == 0
    assert result["queued"] == 1
    assert len(load_pending_conflicts(store_dir)) == 1


def test_monitor_queues_high_conflicts_without_auto_resolving(tmp_path):
    store_dir = tmp_path / ".cortex"
    graph = _graph_with(
        _node(
            "Senior Engineer",
            "professional_context",
            confidence=0.99,
            source="resume-a",
            method="extract",
            timestamp="2026-04-10T12:00:00Z",
        ),
        _node(
            "Product Designer",
            "professional_context",
            confidence=0.01,
            source="resume-b",
            method="extract",
            timestamp="2026-01-01T12:00:00Z",
        ),
    )
    _seed_default_mind(store_dir, "career", graph)

    monitor = ConflictMonitor(ConflictMonitorConfig(store_dir=store_dir, interactive=False, log_dir=tmp_path / "logs"))
    result = monitor.run_cycle()

    assert result["auto_resolved"] == 0
    assert result["queued"] == 1
    assert len(load_mind_core_graph(store_dir, "career")["graph"].nodes) == 2


def test_monitor_queues_critical_conflicts_without_auto_resolving(tmp_path):
    store_dir = tmp_path / ".cortex"
    graph = _graph_with(
        _node(
            "Jordan Lee",
            "identity",
            confidence=0.99,
            source="passport",
            method="manual",
            timestamp="2026-04-10T12:00:00Z",
        ),
        _node(
            "Jordan Li",
            "identity",
            confidence=0.01,
            source="profile",
            method="extract",
            timestamp="2026-01-01T12:00:00Z",
        ),
    )
    _seed_default_mind(store_dir, "identity", graph)

    monitor = ConflictMonitor(ConflictMonitorConfig(store_dir=store_dir, interactive=False, log_dir=tmp_path / "logs"))
    result = monitor.run_cycle()

    assert result["auto_resolved"] == 0
    assert result["queued"] == 1
    assert len(load_pending_conflicts(store_dir)) == 1


def test_monitor_can_operate_on_canonical_graph_without_default_mind(tmp_path):
    store_dir = tmp_path / ".cortex"
    graph = _graph_with(
        _node(
            "Use terse answers",
            "communication_preferences",
            confidence=0.99,
            source="manual",
            method="manual",
            timestamp="2026-04-10T12:00:00Z",
        ),
        _node(
            "Use essay answers",
            "communication_preferences",
            confidence=0.01,
            source="import",
            method="extract",
            timestamp="2026-01-01T12:00:00Z",
        ),
    )
    _seed_canonical(store_dir, graph)

    monitor = ConflictMonitor(ConflictMonitorConfig(store_dir=store_dir, interactive=False, log_dir=tmp_path / "logs"))
    result = monitor.run_cycle()
    updated_graph, _ = load_canonical_graph(store_dir)

    assert result["graph_scope"] == "portable:canonical"
    assert [node.label for node in updated_graph.nodes.values()] == ["Use terse answers"]


def test_conflict_status_reports_active_monitors_and_pending_conflicts(tmp_path):
    store_dir = tmp_path / ".cortex"
    graph = _graph_with(
        _node(
            "Engineer",
            "professional_context",
            confidence=0.9,
            source="a",
            method="extract",
            timestamp="2026-01-01T00:00:00Z",
        ),
        _node(
            "Designer",
            "professional_context",
            confidence=0.8,
            source="b",
            method="extract",
            timestamp="2026-01-02T00:00:00Z",
        ),
    )
    _seed_default_mind(store_dir, "career", graph)

    monitor = ConflictMonitor(
        ConflictMonitorConfig(store_dir=store_dir, interval_seconds=1, interactive=False, log_dir=tmp_path / "logs")
    )
    monitor.start()
    time.sleep(0.1)
    monitor.run_cycle()
    status = conflict_status(store_dir)
    monitor.stop()

    assert len(status["active_monitors"]) >= 1
    assert status["pending_count"] == 1


def test_review_pending_conflicts_applies_selected_candidate(tmp_path):
    store_dir = tmp_path / ".cortex"
    graph = _graph_with(
        _node(
            "Engineer",
            "professional_context",
            confidence=0.95,
            source="resume-a",
            method="extract",
            timestamp="2026-04-10T12:00:00Z",
        ),
        _node(
            "Designer",
            "professional_context",
            confidence=0.15,
            source="resume-b",
            method="extract",
            timestamp="2026-01-01T12:00:00Z",
        ),
    )
    _seed_default_mind(store_dir, "career", graph)

    monitor = ConflictMonitor(ConflictMonitorConfig(store_dir=store_dir, interactive=False, log_dir=tmp_path / "logs"))
    monitor.run_cycle()

    review = review_pending_conflicts(
        store_dir,
        input_func=lambda prompt: "1",
        echo=lambda *args, **kwargs: None,
        log_dir=tmp_path / "logs",
    )
    updated = load_mind_core_graph(store_dir, "career")["graph"]

    assert review["resolved"] == 1
    assert load_pending_conflicts(store_dir) == []
    assert [node.label for node in updated.nodes.values()] == ["Engineer"]


def test_review_pending_conflicts_can_skip_items(tmp_path):
    store_dir = tmp_path / ".cortex"
    graph = _graph_with(
        _node(
            "Engineer",
            "professional_context",
            confidence=0.95,
            source="resume-a",
            method="extract",
            timestamp="2026-04-10T12:00:00Z",
        ),
        _node(
            "Designer",
            "professional_context",
            confidence=0.15,
            source="resume-b",
            method="extract",
            timestamp="2026-01-01T12:00:00Z",
        ),
    )
    _seed_default_mind(store_dir, "career", graph)

    monitor = ConflictMonitor(ConflictMonitorConfig(store_dir=store_dir, interactive=False, log_dir=tmp_path / "logs"))
    monitor.run_cycle()

    review = review_pending_conflicts(
        store_dir,
        input_func=lambda prompt: "s",
        echo=lambda *args, **kwargs: None,
        log_dir=tmp_path / "logs",
    )

    assert review["resolved"] == 0
    assert len(load_pending_conflicts(store_dir)) == 1


def test_professional_history_flags_detect_temporal_gap():
    graph = _graph_with(
        _node(
            "Engineer at Acme",
            "work_history",
            confidence=0.9,
            source="resume",
            method="extract",
            timestamp="2026-01-01T00:00:00Z",
            status="historical",
            valid_to="2023-12-31T00:00:00Z",
        ),
        _node(
            "Staff Engineer at Beta",
            "work_history",
            confidence=0.9,
            source="resume",
            method="extract",
            timestamp="2026-01-01T00:00:00Z",
            status="active",
            valid_from="2024-02-01T00:00:00Z",
        ),
    )

    flags = professional_history_flags(graph)

    assert any(flag["type"] == "employment_gap" for flag in flags)


def test_professional_history_flags_detect_conflict_flags():
    graph = _graph_with(
        _node(
            "Engineer",
            "professional_context",
            confidence=0.8,
            source="resume-a",
            method="extract",
            timestamp="2026-01-01T00:00:00Z",
        ),
        _node(
            "Designer",
            "professional_context",
            confidence=0.75,
            source="resume-b",
            method="extract",
            timestamp="2026-01-02T00:00:00Z",
        ),
    )

    flags = professional_history_flags(graph)

    assert any(flag["type"] == "conflict" for flag in flags)


def test_agent_cli_monitor_once_json_contract(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    graph = _graph_with(
        _node(
            "Use terse answers",
            "communication_preferences",
            confidence=0.9,
            source="a",
            method="manual",
            timestamp="2026-04-10T12:00:00Z",
        ),
        _node(
            "Use long answers",
            "communication_preferences",
            confidence=0.85,
            source="b",
            method="manual",
            timestamp="2026-04-09T12:00:00Z",
        ),
    )
    _seed_default_mind(store_dir, "personal", graph)

    rc = main(["agent", "monitor", "--store-dir", str(store_dir), "--once", "--no-prompt", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "ok"
    assert payload["detected"] == 1


def test_agent_cli_status_json_shows_pending_conflicts(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    graph = _graph_with(
        _node(
            "Engineer",
            "professional_context",
            confidence=0.95,
            source="resume-a",
            method="extract",
            timestamp="2026-04-10T12:00:00Z",
        ),
        _node(
            "Designer",
            "professional_context",
            confidence=0.15,
            source="resume-b",
            method="extract",
            timestamp="2026-01-01T12:00:00Z",
        ),
    )
    _seed_default_mind(store_dir, "career", graph)

    monitor = ConflictMonitor(ConflictMonitorConfig(store_dir=store_dir, interactive=False, log_dir=tmp_path / "logs"))
    monitor.run_cycle()

    rc = main(["agent", "status", "--store-dir", str(store_dir), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["pending_count"] == 1
    assert payload["pending_conflicts"][0]["severity"] == "HIGH"
