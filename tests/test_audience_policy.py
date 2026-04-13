from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from cortex.audience.policy import AudiencePolicy, PolicyEngine, UnknownAudiencePolicyError
from cortex.audience.templates import BUILTIN_AUDIENCE_TEMPLATES
from cortex.claims import stamp_graph_provenance
from cortex.cli import main
from cortex.graph import CortexGraph, Node, make_node_id
from cortex.minds import adopt_graph_into_mind, init_mind


def _seed_mind(store_dir: Path, mind_id: str = "ops") -> None:
    init_mind(store_dir, mind_id, owner="tester")
    graph = CortexGraph()
    graph.add_node(
        Node(
            id=make_node_id("Executive decision"),
            label="Executive decision",
            tags=["decision"],
            confidence=0.95,
            brief="Ship Atlas to beta.",
            properties={"secret_note": "launch budget"},
        )
    )
    graph.add_node(
        Node(
            id=make_node_id("Atlas milestone"),
            label="Atlas milestone",
            tags=["milestone"],
            confidence=0.82,
            brief="Beta milestone reached.",
            properties={"contested": True, "secret_note": "internals"},
        )
    )
    graph.add_node(
        Node(
            id=make_node_id("Credential vault"),
            label="Credential vault",
            tags=["credential"],
            confidence=0.9,
            brief="Contains credentials.",
            properties={"secret_note": "do not disclose"},
        )
    )
    graph.add_node(
        Node(
            id=make_node_id("Personal preference"),
            label="Personal preference",
            tags=["personal"],
            confidence=0.88,
            brief="Prefers quiet mornings.",
        )
    )
    graph.add_node(
        Node(
            id=make_node_id("Low confidence project"),
            label="Low confidence project",
            tags=["project"],
            confidence=0.32,
            brief="Unconfirmed project.",
        )
    )
    stamp_graph_provenance(
        graph,
        source="source-1",
        stable_source_id="source-1",
        source_label="incident.md",
        method="ingest",
    )
    adopt_graph_into_mind(store_dir, mind_id, graph, message="Seed audience policy tests")


def _policy(**overrides) -> AudiencePolicy:
    payload = {
        "audience_id": "executive-lite",
        "display_name": "Executive Lite",
        "allowed_node_types": ["decision", "milestone", "project"],
        "blocked_node_types": ["credential", "personal"],
        "allowed_claim_confidences": (0.5, 1.0),
        "redact_fields": ["brief", "secret_note"],
        "output_format": "raw",
        "delivery": "stdout",
        "delivery_target": None,
        "include_provenance": False,
        "include_contested": False,
    }
    payload.update(overrides)
    return AudiencePolicy(**payload)


def test_policy_includes_and_excludes_node_types(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir)
    engine = PolicyEngine(store_dir)
    engine.add_policy("ops", _policy())

    preview = engine.preview("ops", "executive-lite")
    included = {item["label"] for item in preview["included"]}
    excluded = {item["label"]: item["reason"] for item in preview["excluded"]}

    assert "Executive decision" in included
    assert "Credential vault" not in included
    assert excluded["Credential vault"] == "blocked"
    assert excluded["Personal preference"] == "blocked"


def test_redacted_fields_are_absent_from_compiled_output(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir)
    engine = PolicyEngine(store_dir)
    engine.add_policy("ops", _policy())

    payload = engine.compile("ops", "executive-lite")
    nodes = list(payload["output"]["graph"]["nodes"].values())

    assert all("brief" not in node for node in nodes)
    assert all("secret_note" not in node.get("properties", {}) for node in nodes)


def test_confidence_range_filter_excludes_out_of_range_claims(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir)
    engine = PolicyEngine(store_dir)
    engine.add_policy("ops", _policy(allowed_claim_confidences=(0.8, 1.0), redact_fields=[]))

    preview = engine.preview("ops", "executive-lite")
    included = {item["label"] for item in preview["included"]}

    assert "Executive decision" in included
    assert "Low confidence project" not in included
    assert any(item["label"] == "Low confidence project" and item["reason"] == "confidence_excluded" for item in preview["excluded"])


def test_preview_output_matches_compile_output_exactly(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir)
    engine = PolicyEngine(store_dir)
    engine.add_policy("ops", _policy(redact_fields=[]))

    preview = engine.preview("ops", "executive-lite")
    compiled = engine.compile("ops", "executive-lite")

    assert compiled["output"] == preview["output"]
    assert compiled["included"] == preview["included"]
    assert compiled["excluded"] == preview["excluded"]


@pytest.mark.parametrize("template_name", ["executive", "attorney", "onboarding", "audit"])
def test_all_builtin_templates_compile_without_error_on_populated_mind(tmp_path, template_name):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir)
    engine = PolicyEngine(store_dir)
    template = AudiencePolicy.from_dict(deepcopy(BUILTIN_AUDIENCE_TEMPLATES[template_name].to_dict()))
    engine.add_policy("ops", template)

    payload = engine.compile("ops", template_name)

    assert payload["status"] == "ok"
    assert payload["audience_id"] == template_name
    assert payload["node_count_out"] >= 0


def test_compilation_log_is_written_with_correct_metadata(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir)
    target_path = tmp_path / "executive.md"
    engine = PolicyEngine(store_dir)
    engine.add_policy(
        "ops",
        _policy(output_format="brief", delivery="file", delivery_target=str(target_path), redact_fields=[]),
    )

    compiled = engine.compile("ops", "executive-lite")
    log_payload = engine.read_log("ops", "executive-lite")

    assert compiled["delivered_to"] == str(target_path)
    assert target_path.exists()
    assert log_payload["entry_count"] == 1
    entry = log_payload["entries"][0]
    assert entry["audience_id"] == "executive-lite"
    assert entry["mind_id"] == "ops"
    assert entry["node_count_in"] >= entry["node_count_out"]


def test_unknown_audience_compile_raises_clear_error(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir)
    engine = PolicyEngine(store_dir)

    with pytest.raises(UnknownAudiencePolicyError) as exc:
        engine.compile("ops", "missing")

    assert "not configured" in str(exc.value)


def test_executive_policy_excludes_contested_nodes_by_default(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir)
    engine = PolicyEngine(store_dir)
    template = AudiencePolicy.from_dict(deepcopy(BUILTIN_AUDIENCE_TEMPLATES["executive"].to_dict()))
    engine.add_policy("ops", template)

    preview = engine.preview("ops", "executive")
    included = {item["label"] for item in preview["included"]}

    assert "Atlas milestone" not in included


def test_audit_policy_preserves_provenance_and_contested_state(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir)
    engine = PolicyEngine(store_dir)
    template = AudiencePolicy.from_dict(deepcopy(BUILTIN_AUDIENCE_TEMPLATES["audit"].to_dict()))
    engine.add_policy("ops", template)

    payload = engine.compile("ops", "audit")
    nodes = list(payload["output"]["graph"]["nodes"].values())

    assert any(node["provenance"] for node in nodes)
    assert any(node.get("properties", {}).get("contested") for node in nodes)


def test_audience_cli_apply_template_and_compile_json(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir)

    apply_rc = main(
        ["audience", "apply-template", "--mind", "ops", "--template", "executive", "--store-dir", str(store_dir), "--format", "json"]
    )
    applied = json.loads(capsys.readouterr().out)
    compile_rc = main(
        ["audience", "compile", "--mind", "ops", "--audience", "executive", "--store-dir", str(store_dir), "--format", "json"]
    )
    compiled = json.loads(capsys.readouterr().out)

    assert apply_rc == 0
    assert applied["audience_id"] == "executive"
    assert compile_rc == 0
    assert compiled["audience_id"] == "executive"


def test_audience_cli_preview_matches_compile_output(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir)
    engine = PolicyEngine(store_dir)
    engine.add_policy("ops", _policy(redact_fields=[]))

    preview_rc = main(
        ["audience", "preview", "--mind", "ops", "--audience", "executive-lite", "--store-dir", str(store_dir), "--format", "json"]
    )
    preview = json.loads(capsys.readouterr().out)
    compile_rc = main(
        ["audience", "compile", "--mind", "ops", "--audience", "executive-lite", "--store-dir", str(store_dir), "--format", "json"]
    )
    compiled = json.loads(capsys.readouterr().out)

    assert preview_rc == 0
    assert compile_rc == 0
    assert preview["output"] == compiled["output"]
