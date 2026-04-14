from __future__ import annotations

import pytest

from cortex.audience.policy import AudiencePolicy, PolicyEngine
from cortex.claims import stamp_graph_provenance
from cortex.cli import main
from cortex.completion import completion_candidates
from cortex.graph import CortexGraph, Node, make_node_id
from cortex.minds import adopt_graph_into_mind, init_mind
from cortex.sources import SourceRegistry


def _seed_source_graph(*, stable_source_id: str, source_label: str) -> CortexGraph:
    graph = CortexGraph()
    graph.add_node(
        Node(
            id=make_node_id("Project Atlas"),
            label="Project Atlas",
            tags=["project"],
            confidence=0.92,
            brief="A portable Mind demo project.",
        )
    )
    stamp_graph_provenance(
        graph,
        source=stable_source_id,
        stable_source_id=stable_source_id,
        source_label=source_label,
        method="ingest",
    )
    return graph


def test_structured_cli_errors_are_visible(capsys):
    rc = main(["connect"])
    output = capsys.readouterr().err

    assert rc == 1
    assert "What went wrong:" in output
    assert "What to do next:" in output
    assert "cortex connect --help" in output


def test_completion_script_exposes_dynamic_candidate_hooks(capsys):
    rc = main(["completion", "--shell", "bash"])
    script = capsys.readouterr().out

    assert rc == 0
    assert "--candidates mind" in script
    assert "CORTEX_STORE_DIR" in script
    assert "_cortex_completion" in script


def test_completion_candidates_surface_mind_audience_and_source_values(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", owner="marc")
    init_mind(store_dir, "ops", owner="tester")

    engine = PolicyEngine(store_dir)
    engine.add_policy(
        "ops",
        AudiencePolicy(
            audience_id="executive",
            display_name="Executive",
            allowed_node_types=["project"],
            blocked_node_types=[],
            allowed_claim_confidences=(0.5, 1.0),
            redact_fields=[],
            output_format="brief",
            delivery="stdout",
            delivery_target=None,
            include_provenance=False,
            include_contested=False,
        ),
    )

    registry = SourceRegistry.for_store(store_dir)
    payload = registry.register_bytes(b"Project Atlas launched", label="incident-a.md")
    adopt_graph_into_mind(
        store_dir,
        "ops",
        _seed_source_graph(stable_source_id=payload["stable_id"], source_label="incident-a.md"),
    )

    assert completion_candidates("mind", store_dir=store_dir) == ["marc", "ops"]
    assert completion_candidates("audience", store_dir=store_dir) == ["executive"]
    source_candidates = completion_candidates("source", store_dir=store_dir, mind="ops")
    assert payload["stable_id"] in source_candidates


def test_unknown_command_routing_is_no_longer_silent(tmp_path, capsys):
    unknown = tmp_path / "export.json"
    unknown.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit, match="2"):
        main([str(unknown)])
    stderr = capsys.readouterr().err

    assert "What went wrong:" in stderr
    assert "cortex migrate" in stderr
