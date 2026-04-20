from __future__ import annotations

import pytest

from cortex.audience.policy import AudiencePolicy, PolicyEngine
from cortex.cli import main
from cortex.completion import completion_candidates
from cortex.extraction.sources import SourceRegistry
from cortex.graph.claims import stamp_graph_provenance
from cortex.graph.graph import CortexGraph, Node, make_node_id
from cortex.graph.minds import adopt_graph_into_mind, init_mind
from cortex.packs import compile_pack, ingest_pack, init_pack


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


def test_top_level_compose_to_codex_suggests_mind_compose(capsys):
    with pytest.raises(SystemExit, match="2"):
        main(["compose", "--to", "codex"])
    stderr = capsys.readouterr().err

    assert "What went wrong:" in stderr
    assert "cortex mind compose <mind> --to codex" in stderr
    assert "cortex migrate" not in stderr


def test_merge_help_includes_guided_examples(capsys):
    with pytest.raises(SystemExit, match="0"):
        main(["merge", "--help"])
    output = capsys.readouterr().out

    assert "cortex merge preview --base main --incoming feature/atlas" in output
    assert "cortex merge --resolve <conflict-id> --choose incoming" in output


def test_sources_list_cli_suggests_safe_retraction_preview(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "ops", owner="tester")
    registry = SourceRegistry.for_store(store_dir)
    payload = registry.register_bytes(b"Project Atlas launched", label="incident-a.md")
    adopt_graph_into_mind(
        store_dir,
        "ops",
        _seed_source_graph(stable_source_id=payload["stable_id"], source_label="incident-a.md"),
    )

    rc = main(["sources", "list", "--mind", "ops", "--store-dir", str(store_dir)])
    output = capsys.readouterr().out

    assert rc == 0
    assert "Preview a retraction safely" in output
    assert payload["stable_id"] in output


def test_audience_preview_cli_suggests_compile_next_step(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "ops", owner="tester")
    graph = CortexGraph()
    graph.add_node(
        Node(
            id=make_node_id("Executive decision"),
            label="Executive decision",
            tags=["decision"],
            confidence=0.95,
            brief="Ship Atlas to beta.",
        )
    )
    adopt_graph_into_mind(store_dir, "ops", graph)
    engine = PolicyEngine(store_dir)
    engine.add_policy(
        "ops",
        AudiencePolicy(
            audience_id="executive",
            display_name="Executive",
            allowed_node_types=["decision"],
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

    rc = main(["audience", "preview", "--mind", "ops", "--audience", "executive", "--store-dir", str(store_dir)])
    output = capsys.readouterr().out

    assert rc == 0
    assert "Compile this audience when ready" in output
    assert "cortex audience compile --mind ops --audience executive" in output


def test_agent_schedule_cli_surfaces_follow_up_steps(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "ops", owner="tester")

    rc = main(
        [
            "agent",
            "schedule",
            "--mind",
            "ops",
            "--audience",
            "team",
            "--cron",
            "0 9 * * 1",
            "--output",
            "brief",
            "--store-dir",
            str(store_dir),
        ]
    )
    output = capsys.readouterr().out

    assert rc == 0
    assert "schedule id:" in output
    assert "cortex agent status" in output


def test_mind_mount_cli_suggests_follow_up_commands(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    init_mind(store_dir, "ops", owner="tester")
    graph = CortexGraph()
    graph.add_node(
        Node(
            id=make_node_id("Project Atlas"),
            label="Project Atlas",
            tags=["project"],
            confidence=0.92,
            brief="Portable runtime demo.",
        )
    )
    adopt_graph_into_mind(store_dir, "ops", graph)

    rc = main(
        [
            "mind",
            "mount",
            "ops",
            "--to",
            "codex",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
        ]
    )
    output = capsys.readouterr().out

    assert rc == 0
    assert "Inspect the persisted mount records" in output
    assert "cortex mind compose ops --to codex" in output


def test_pack_mount_cli_suggests_attach_pack_follow_up(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source = tmp_path / "pack-source.md"
    source.write_text("# Atlas\n\nPortable memory notes.\n", encoding="utf-8")
    init_pack(store_dir, "atlas-pack", description="Atlas", owner="tester")
    ingest_pack(store_dir, "atlas-pack", [str(source)], mode="copy")
    compile_pack(store_dir, "atlas-pack")

    rc = main(
        [
            "pack",
            "mount",
            "atlas-pack",
            "--to",
            "codex",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
        ]
    )
    output = capsys.readouterr().out

    assert rc == 0
    assert "Attach this pack to a Mind" in output
    assert "cortex mind attach-pack <mind> atlas-pack" in output
