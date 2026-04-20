from __future__ import annotations

import logging
from pathlib import Path

from cortex.graph.graph import CortexGraph, Node
from cortex.packs import compile_pack, ingest_pack, init_pack, pack_status
from cortex.security.secrets import CortexIgnore, SecretsScanner
from cortex.service.service import MemoryService
from cortex.storage import build_sqlite_backend


def test_secret_scanner_detects_openai_key_pattern():
    scanner = SecretsScanner()

    matches = scanner.scan_text("token=sk-abcdefghijklmnopqrstuvwx", field_name="body")

    assert any(match.rule_id == "openai_api_key" for match in matches)


def test_secret_scanner_detects_secret_in_node_properties():
    scanner = SecretsScanner()
    node = Node(
        id="n1",
        label="Deployment",
        tags=["project"],
        properties={"api_key": "sk-abcdefghijklmnopqrstuvwx"},
    )

    matches = scanner.scan_node(node)

    assert matches


def test_cortexignore_discovers_and_matches_patterns(tmp_path: Path, monkeypatch):
    (tmp_path / ".cortexignore").write_text("*.pem\nsecrets/*\n", encoding="utf-8")
    cert = tmp_path / "prod.pem"
    secret = tmp_path / "secrets" / "token.txt"
    secret.parent.mkdir()
    cert.write_text("pem", encoding="utf-8")
    secret.write_text("token", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    ignore = CortexIgnore.discover()

    assert ignore.matches(cert)
    assert ignore.matches(secret)
    assert not ignore.matches(tmp_path / "notes.md")


def test_ingest_pack_skips_cortexignore_matches(tmp_path: Path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (tmp_path / ".cortexignore").write_text(".env\n", encoding="utf-8")
    (source_dir / ".env").write_text("SECRET=1", encoding="utf-8")
    (source_dir / "notes.md").write_text("Project Atlas", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    init_pack(store_dir, "ai-memory")
    payload = ingest_pack(store_dir, "ai-memory", [str(source_dir)], recurse=True)

    assert payload["ingested_count"] == 1
    assert payload["ignored"] == [str((source_dir / ".env").resolve())]


def test_compile_pack_strips_secret_nodes_by_default(tmp_path: Path):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "brainpack.md"
    source.write_text(
        "# Secrets\n\nProduction key sk-abcdefghijklmnopqrstuvwx must never ship.\nProject Atlas launched.",
        encoding="utf-8",
    )

    init_pack(store_dir, "ai-memory")
    ingest_pack(store_dir, "ai-memory", [str(source)])
    payload = compile_pack(store_dir, "ai-memory", mode="full")
    status = pack_status(store_dir, "ai-memory")

    assert payload["secret_finding_count"] >= 1
    assert payload["secrets_removed"] >= 1
    assert status["graph_nodes"] == payload["graph_nodes"]


def test_compile_pack_can_include_secrets_when_requested(tmp_path: Path):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "brainpack.md"
    source.write_text(
        "# Secrets\n\nProduction key sk-abcdefghijklmnopqrstuvwx must never ship.\nProject Atlas launched.",
        encoding="utf-8",
    )

    init_pack(store_dir, "ai-memory")
    ingest_pack(store_dir, "ai-memory", [str(source)])
    payload = compile_pack(store_dir, "ai-memory", mode="full", include_secrets=True)

    assert payload["secret_finding_count"] >= 1
    assert payload["secrets_removed"] == 0


def test_memory_service_logs_secret_warning_on_startup(tmp_path: Path, caplog):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    graph = CortexGraph()
    graph.add_node(
        Node(
            id="n1",
            label="Deployment key",
            tags=["security"],
            properties={"api_key": "sk-abcdefghijklmnopqrstuvwx"},
        )
    )
    backend.versions.commit(graph, "seed secret")

    with caplog.at_level(logging.WARNING):
        MemoryService(store_dir=store_dir, backend=backend)

    assert any("secret-like" in record.message for record in caplog.records)
