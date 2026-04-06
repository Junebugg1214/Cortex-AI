from __future__ import annotations

import json
from pathlib import Path

from cortex.cli import main
from cortex.packs import (
    compile_pack,
    ingest_pack,
    init_pack,
    list_packs,
    load_manifest,
    pack_status,
    render_pack_context,
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


def test_cli_pack_round_trip(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "brain-state.md"
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
