from __future__ import annotations

import json
from pathlib import Path

from cortex.cli import main
from cortex.graph import CortexGraph, Node, make_node_id
from cortex.packs import (
    ask_pack,
    compile_pack,
    export_pack_bundle,
    import_pack_bundle,
    ingest_pack,
    init_pack,
    lint_pack,
    list_packs,
    load_manifest,
    mount_pack,
    openclaw_mount_registry_path,
    pack_status,
    query_pack,
    render_pack_context,
    verify_pack_bundle,
)


def _seed_source(path: Path) -> None:
    path.write_text(
        (
            "# Portable AI Memory\n\n"
            "I am Marc Saint-Jour.\n"
            "I use Python, FastAPI, and Cortex.\n"
            "I am building portable brain-state infrastructure for agents.\n"
            "I prefer concise, implementation-first responses.\n"
        ),
        encoding="utf-8",
    )


def test_pack_init_creates_manifest_and_layout(tmp_path):
    store_dir = tmp_path / ".cortex"

    payload = init_pack(store_dir, "ai-memory", description="Portable AI memory research", owner="marc")
    manifest = load_manifest(store_dir, "ai-memory")

    assert payload["created"] is True
    assert (store_dir / "packs" / "ai-memory" / "raw").exists()
    assert (store_dir / "packs" / "ai-memory" / "wiki").exists()
    assert manifest.name == "ai-memory"
    assert manifest.description == "Portable AI memory research"
    assert manifest.owner == "marc"


def test_pack_ingest_compile_status_and_context(tmp_path):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "memory.md"
    _seed_source(source)

    init_pack(store_dir, "ai-memory", description="Portable AI memory research", owner="marc")
    ingest = ingest_pack(store_dir, "ai-memory", [str(source)], mode="copy")
    compiled = compile_pack(store_dir, "ai-memory", suggest_questions=True, max_summary_chars=240)
    status = pack_status(store_dir, "ai-memory")
    packs = list_packs(store_dir)
    context = render_pack_context(store_dir, "ai-memory", target="chatgpt", smart=True, max_chars=900)

    assert ingest["ingested_count"] == 1
    assert compiled["graph_nodes"] >= 3
    assert compiled["article_count"] >= 2
    assert compiled["claim_count"] >= 1
    assert (store_dir / "packs" / "ai-memory" / "wiki" / "index.md").exists()
    assert (store_dir / "packs" / "ai-memory" / "claims" / "claims.json").exists()
    assert status["compile_status"] == "compiled"
    assert status["source_count"] == 1
    assert packs["count"] == 1
    assert context["target"] == "chatgpt"
    assert context["consume_as"] == "custom_instructions"
    assert context["fact_count"] >= 1
    assert "Identity" in context["context_markdown"] or "Role" in context["context_markdown"]


def test_pack_query_and_ask_write_back_artifact(tmp_path):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "memory.md"
    _seed_source(source)

    init_pack(store_dir, "ai-memory", description="Portable AI memory research", owner="marc")
    ingest_pack(store_dir, "ai-memory", [str(source)], mode="copy")
    compile_pack(store_dir, "ai-memory", suggest_questions=True, max_summary_chars=240)

    query_payload = query_pack(store_dir, "ai-memory", "portable brain-state infrastructure", limit=5)
    ask_payload = ask_pack(
        store_dir,
        "ai-memory",
        "What does this Brainpack say about portable brain-state infrastructure?",
        output="report",
        limit=6,
        write_back=True,
    )
    refreshed = pack_status(store_dir, "ai-memory")

    assert query_payload["total_matches"] >= 1
    assert any(item["kind"] in {"concept", "claim", "wiki"} for item in query_payload["results"])
    assert ask_payload["artifact_written"] is True
    assert ask_payload["artifact_path"]
    assert Path(ask_payload["artifact_path"]).exists()
    assert "Executive Summary" in ask_payload["answer_markdown"]
    assert refreshed["artifact_count"] >= 1

    artifact_query = query_pack(
        store_dir, "ai-memory", "portable brain-state infrastructure", mode="artifacts", limit=5
    )
    assert artifact_query["counts"]["artifacts"] >= 1
    assert artifact_query["artifacts"][0]["path"].startswith("artifacts/reports/")

    slides_payload = ask_pack(
        store_dir,
        "ai-memory",
        "Summarize this pack as slides",
        output="slides",
        limit=4,
        write_back=True,
    )
    assert slides_payload["artifact_path"]
    assert "/artifacts/slides/" in slides_payload["artifact_path"]


def test_pack_lint_reports_integrity_findings_and_persists_report(tmp_path):
    store_dir = tmp_path / ".cortex"
    readable = tmp_path / "memory.md"
    unreadable = tmp_path / "figure.png"
    short_note = tmp_path / "tiny.txt"
    _seed_source(readable)
    unreadable.write_bytes(b"\x89PNG\r\n\x1a\nbinary")
    short_note.write_text("Tiny note about memory.", encoding="utf-8")

    init_pack(store_dir, "ai-memory", description="Portable AI memory research", owner="marc")
    ingest_pack(store_dir, "ai-memory", [str(readable), str(unreadable), str(short_note)], mode="copy")
    compile_pack(store_dir, "ai-memory", suggest_questions=True, max_summary_chars=240)

    compiled_graph_path = store_dir / "packs" / "ai-memory" / "graph" / "brainpack.graph.json"
    graph = CortexGraph.from_v5_json(json.loads(compiled_graph_path.read_text(encoding="utf-8")))
    graph.add_node(
        Node(
            id=make_node_id("python-negated"),
            label="Python",
            tags=["technical_expertise", "negations"],
            confidence=0.91,
            brief="Conflicting statement about Python usage.",
        )
    )
    graph.add_node(
        Node(
            id=make_node_id("python-2"),
            label="Python 2",
            tags=["technical_expertise"],
            confidence=0.87,
            brief="Duplicate-ish Python concept.",
        )
    )
    compiled_graph_path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")

    claims_file = store_dir / "packs" / "ai-memory" / "claims" / "claims.json"
    claims_payload = json.loads(claims_file.read_text(encoding="utf-8"))
    claims_payload["claims"].append(
        {
            "id": "weak-claim",
            "label": "Uncertain preference",
            "tags": ["user_preferences"],
            "confidence": 0.22,
            "brief": "A deliberately weak claim for lint coverage.",
            "source_quotes": [],
            "provenance": [],
        }
    )
    claims_file.write_text(json.dumps(claims_payload, indent=2), encoding="utf-8")

    payload = lint_pack(store_dir, "ai-memory")
    report_path = Path(payload["report_path"])

    assert payload["lint_status"] in {"warn", "fail"}
    assert payload["summary"]["contradictions"] >= 1
    assert payload["summary"]["duplicates"] >= 1
    assert payload["summary"]["weak_claims"] >= 1
    assert payload["summary"]["unreadable_sources"] >= 1
    assert any(item["type"] == "thin_article" for item in payload["findings"])
    assert report_path.exists()
    assert (
        json.loads(report_path.read_text(encoding="utf-8"))["summary"]["total_findings"]
        == payload["summary"]["total_findings"]
    )


def test_pack_mount_writes_direct_targets_and_openclaw_registry(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    openclaw_store_dir = tmp_path / "openclaw-store"
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "memory.md"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_source(source)

    init_pack(store_dir, "ai-memory", description="Portable AI memory research", owner="marc")
    ingest_pack(store_dir, "ai-memory", [str(source)], mode="copy")
    compile_pack(store_dir, "ai-memory", suggest_questions=True, max_summary_chars=240)

    payload = mount_pack(
        store_dir,
        "ai-memory",
        targets=["hermes", "claude-code", "codex", "cursor", "openclaw"],
        project_dir=str(project_dir),
        smart=True,
        max_chars=900,
        openclaw_store_dir=str(openclaw_store_dir),
    )
    status = pack_status(store_dir, "ai-memory")
    registry = json.loads(openclaw_mount_registry_path(openclaw_store_dir).read_text(encoding="utf-8"))

    assert payload["mount_count"] == 5
    assert (home_dir / ".hermes" / "memories" / "USER.md").exists()
    assert (home_dir / ".hermes" / "memories" / "MEMORY.md").exists()
    assert (home_dir / ".hermes" / "config.yaml").exists()
    assert (home_dir / ".claude" / "CLAUDE.md").exists()
    assert (project_dir / "CLAUDE.md").exists()
    assert (project_dir / "AGENTS.md").exists()
    assert (project_dir / ".cursor" / "rules" / "cortex.mdc").exists()
    assert status["mount_count"] == 5
    assert set(status["mounted_targets"]) == {"hermes", "claude-code", "codex", "cursor", "openclaw"}
    assert registry["mount_count"] == 1
    assert registry["mounts"][0]["name"] == "ai-memory"
    assert registry["mounts"][0]["smart"] is True


def test_pack_export_import_bundle_round_trip_materializes_reference_sources(tmp_path):
    source_store = tmp_path / "source-store"
    imported_store = tmp_path / "imported-store"
    source = tmp_path / "portable-memory.md"
    bundle = tmp_path / "ai-memory.brainpack.zip"
    _seed_source(source)

    init_pack(source_store, "ai-memory", description="Portable AI memory research", owner="marc")
    ingest_pack(source_store, "ai-memory", [str(source)], mode="reference")
    compile_pack(source_store, "ai-memory", suggest_questions=True, max_summary_chars=240)
    ask_pack(
        source_store,
        "ai-memory",
        "What does this pack say about portable brain-state infrastructure?",
        output="note",
        limit=5,
        write_back=True,
    )
    lint_pack(source_store, "ai-memory")

    export_payload = export_pack_bundle(source_store, "ai-memory", bundle)
    verify_payload = verify_pack_bundle(bundle)
    import_payload = import_pack_bundle(bundle, imported_store, as_name="ai-memory-copy")

    assert export_payload["materialized_reference_sources"] == 1
    assert export_payload["archive"] == str(bundle)
    assert verify_payload["valid"] is True
    assert import_payload["pack"] == "ai-memory-copy"
    assert import_payload["original_pack"] == "ai-memory"

    status = pack_status(imported_store, "ai-memory-copy")
    assert status["compile_status"] == "compiled"
    assert status["artifact_count"] >= 1
    imported_manifest = load_manifest(imported_store, "ai-memory-copy")
    assert imported_manifest.name == "ai-memory-copy"

    imported_sources = json.loads(
        (imported_store / "packs" / "ai-memory-copy" / "indexes" / "sources.json").read_text(encoding="utf-8")
    )
    assert imported_sources["sources"][0]["stored_path"].startswith("raw/bundled-references/")
    assert imported_sources["sources"][0]["mode"] == "copy"

    recompiled = compile_pack(imported_store, "ai-memory-copy", suggest_questions=True, max_summary_chars=240)
    assert recompiled["text_source_count"] == 1


def test_pack_import_rejects_path_traversal_bundle(tmp_path):
    from zipfile import ZIP_DEFLATED, ZipFile

    archive = tmp_path / "unsafe.brainpack.zip"
    manifest = {
        "format_version": "1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "pack_name": "unsafe-pack",
        "manifest": {"name": "unsafe-pack"},
        "file_count": 1,
        "files": [{"path": "manifest.toml", "size": 4, "sha256": "e3b0c44298fc1c149afbf4c8996fb924"}],
    }
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as handle:
        handle.writestr("bundle_manifest.json", json.dumps(manifest))
        handle.writestr("pack/../../escape.txt", "nope")

    try:
        import_pack_bundle(archive, tmp_path / "store")
    except ValueError as exc:
        assert "unsafe path traversal" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected import_pack_bundle to reject traversal entries")


def test_cli_pack_round_trip(tmp_path, capsys, monkeypatch):
    store_dir = tmp_path / ".cortex"
    imported_store_dir = tmp_path / ".imported"
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    openclaw_store_dir = tmp_path / "openclaw-store"
    source = tmp_path / "brain-state.md"
    bundle = tmp_path / "brain-layer.brainpack.zip"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_source(source)

    assert main(["pack", "init", "brain-layer", "--store-dir", str(store_dir), "--format", "json"]) == 0
    init_payload = json.loads(capsys.readouterr().out)
    assert init_payload["pack"] == "brain-layer"

    assert (
        main(
            [
                "pack",
                "ingest",
                "brain-layer",
                str(source),
                "--store-dir",
                str(store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )
    ingest_payload = json.loads(capsys.readouterr().out)
    assert ingest_payload["ingested_count"] == 1

    assert (
        main(
            [
                "pack",
                "compile",
                "brain-layer",
                "--store-dir",
                str(store_dir),
                "--suggest-questions",
                "--format",
                "json",
            ]
        )
        == 0
    )
    compile_payload = json.loads(capsys.readouterr().out)
    assert compile_payload["status"] == "ok"
    assert compile_payload["graph_nodes"] >= 3

    assert (
        main(
            [
                "pack",
                "context",
                "brain-layer",
                "--target",
                "hermes",
                "--store-dir",
                str(store_dir),
                "--smart",
                "--format",
                "json",
            ]
        )
        == 0
    )
    context_payload = json.loads(capsys.readouterr().out)
    assert context_payload["target"] == "hermes"
    assert context_payload["consume_as"] == "hermes_memory"

    assert (
        main(
            [
                "pack",
                "query",
                "brain-layer",
                "portable brain-state",
                "--store-dir",
                str(store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )
    query_payload = json.loads(capsys.readouterr().out)
    assert query_payload["total_matches"] >= 1

    assert (
        main(
            [
                "pack",
                "ask",
                "brain-layer",
                "What does this pack say about portable brain-state infrastructure?",
                "--store-dir",
                str(store_dir),
                "--output",
                "note",
                "--format",
                "json",
            ]
        )
        == 0
    )
    ask_payload = json.loads(capsys.readouterr().out)
    assert ask_payload["artifact_written"] is True
    assert ask_payload["artifact_path"]

    assert (
        main(
            [
                "pack",
                "lint",
                "brain-layer",
                "--store-dir",
                str(store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )
    lint_payload = json.loads(capsys.readouterr().out)
    assert lint_payload["status"] == "ok"
    assert "summary" in lint_payload

    assert (
        main(
            [
                "pack",
                "mount",
                "brain-layer",
                "--to",
                "hermes",
                "claude-code",
                "codex",
                "cursor",
                "openclaw",
                "--project",
                str(project_dir),
                "--store-dir",
                str(store_dir),
                "--openclaw-store-dir",
                str(openclaw_store_dir),
                "--smart",
                "--format",
                "json",
            ]
        )
        == 0
    )
    mount_payload = json.loads(capsys.readouterr().out)
    assert {item["target"] for item in mount_payload["targets"]} == {
        "hermes",
        "claude-code",
        "codex",
        "cursor",
        "openclaw",
    }
    assert (home_dir / ".hermes" / "memories" / "USER.md").exists()
    assert (project_dir / "AGENTS.md").exists()
    assert (project_dir / ".cursor" / "rules" / "cortex.mdc").exists()
    assert openclaw_mount_registry_path(openclaw_store_dir).exists()

    assert (
        main(
            [
                "pack",
                "export",
                "brain-layer",
                "--store-dir",
                str(store_dir),
                "--output",
                str(bundle),
                "--format",
                "json",
            ]
        )
        == 0
    )
    export_payload = json.loads(capsys.readouterr().out)
    assert export_payload["archive"] == str(bundle)
    assert export_payload["verified"] is True

    assert (
        main(
            [
                "pack",
                "import",
                str(bundle),
                "--store-dir",
                str(imported_store_dir),
                "--as",
                "brain-layer-copy",
                "--format",
                "json",
            ]
        )
        == 0
    )
    import_payload = json.loads(capsys.readouterr().out)
    assert import_payload["pack"] == "brain-layer-copy"
    assert import_payload["compile_status"] == "compiled"
