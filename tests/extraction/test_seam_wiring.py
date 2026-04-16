from __future__ import annotations

import json
from types import SimpleNamespace

from cortex.extraction import ExtractedNode, ExtractionResult
from cortex.graph import CortexGraph, Node, make_node_id_with_tag
from cortex.session import MemorySession
from cortex.webapp_backend import MemoryUIBackend


class _BackendStub:
    def __init__(self, result: ExtractionResult) -> None:
        self.result = result
        self.statement_calls: list[tuple[str, dict | None]] = []
        self.bulk_calls: list[tuple[list[str], dict | None]] = []

    def extract_statement(self, text: str, context: dict | None = None) -> ExtractionResult:
        self.statement_calls.append((text, context))
        return self.result

    def extract_bulk(self, texts: list[str], context: dict | None = None) -> list[ExtractionResult]:
        self.bulk_calls.append((texts, context))
        return [self.result]

    def canonical_match(self, node, existing_nodes):
        return None, 0.0

    @property
    def supports_async_rescoring(self) -> bool:
        return False

    @property
    def supports_embeddings(self) -> bool:
        return False


def _graph_result() -> ExtractionResult:
    graph = CortexGraph()
    graph.add_node(
        Node(
            id=make_node_id_with_tag("Python", "technical_expertise"),
            label="Python",
            tags=["technical_expertise"],
            confidence=0.9,
            brief="Python",
        )
    )
    result = ExtractionResult(
        nodes=[ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.9)],
        extraction_method="heuristic",
        raw_source="I use Python.",
    )
    result._graph = graph
    return result


def test_extract_graph_from_statement_uses_hot_path_backend(monkeypatch):
    from cortex import portable_graphs

    backend = _BackendStub(_graph_result())
    monkeypatch.setattr(portable_graphs, "get_hot_path_backend", lambda: backend)
    graph = portable_graphs.extract_graph_from_statement("I use Python.")
    assert backend.statement_calls[0][0] == "I use Python."
    assert any(node.label == "Python" for node in graph.nodes.values())


def test_extract_graph_from_statement_uses_backend_result_graph(monkeypatch):
    from cortex import portable_graphs

    backend = _BackendStub(_graph_result())
    monkeypatch.setattr(portable_graphs, "get_hot_path_backend", lambda: backend)
    graph = portable_graphs.extract_graph_from_statement("I use Python.")
    assert graph.export_v5()["graph"]["nodes"] == _graph_result()._graph.export_v5()["graph"]["nodes"]


def test_cli_run_extraction_uses_bulk_backend(monkeypatch):
    from cortex import cli_extract_commands

    backend = _BackendStub(
        ExtractionResult(
            nodes=[ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.9)]
        )
    )
    monkeypatch.setattr(cli_extract_commands, "get_bulk_backend", lambda: backend)
    result = cli_extract_commands.run_extraction(object(), "I use Python and Rust.", "text")
    assert backend.bulk_calls
    assert "categories" in result


def test_portable_sources_run_extraction_data_uses_bulk_backend(monkeypatch):
    from cortex import portable_sources

    backend = _BackendStub(
        ExtractionResult(
            nodes=[ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.9)]
        )
    )
    monkeypatch.setattr(portable_sources, "get_bulk_backend", lambda: backend)
    result = portable_sources.run_extraction_data(object(), "I use Python and Rust.", "text")
    assert backend.bulk_calls
    assert "categories" in result


def test_memory_session_remember_bypass_is_unaffected(monkeypatch):
    calls: list[dict] = []

    class _Client:
        def upsert_node(self, **kwargs):
            calls.append(kwargs)
            return {"status": "ok"}

    session = MemorySession(client=_Client())
    payload = session.remember(label="Python")
    assert payload == {"status": "ok"}
    assert calls[0]["node"]["label"] == "Python"


def test_memory_session_remember_does_not_touch_hot_path_backend(monkeypatch):
    monkeypatch.setattr(
        "cortex.portable_graphs.get_hot_path_backend", lambda: (_ for _ in ()).throw(AssertionError("should not run"))
    )

    class _Client:
        def upsert_node(self, **kwargs):
            return {"status": "ok"}

    session = MemorySession(client=_Client())
    assert session.remember(label="Python") == {"status": "ok"}


def test_webapp_remember_endpoint_default_mind_path_unaffected(monkeypatch, tmp_path):
    backend = MemoryUIBackend(store_dir=tmp_path)
    monkeypatch.setattr("cortex.minds.resolve_default_mind", lambda store_dir: "self")
    monkeypatch.setattr(
        "cortex.minds.remember_and_sync_default_mind",
        lambda *args, **kwargs: {"statement": kwargs["statement"], "targets": [], "fact_count": 1},
    )
    payload = backend.portability_remember(statement="I use Python.")
    assert payload["status"] == "ok"
    assert payload["statement"] == "I use Python."


def test_webapp_remember_endpoint_standalone_path_unaffected(monkeypatch, tmp_path):
    backend = MemoryUIBackend(store_dir=tmp_path)
    monkeypatch.setattr("cortex.minds.resolve_default_mind", lambda store_dir: "")
    monkeypatch.setattr(
        "cortex.portable_runtime.remember_and_sync",
        lambda *args, **kwargs: {"statement": args[0], "targets": [], "fact_count": 1},
    )
    payload = backend.portability_remember(statement="I use Python.")
    assert payload["status"] == "ok"
    assert payload["statement"] == "I use Python."


def test_webapp_remember_endpoint_requires_non_empty_statement(tmp_path):
    backend = MemoryUIBackend(store_dir=tmp_path)
    try:
        backend.portability_remember(statement="  ")
    except ValueError as exc:
        assert "statement is required" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError")


def test_bulk_seam_preserves_multiple_collected_texts(monkeypatch):
    from cortex import cli_extract_commands

    backend = _BackendStub(ExtractionResult(nodes=[]))
    monkeypatch.setattr(cli_extract_commands, "get_bulk_backend", lambda: backend)
    cli_extract_commands.run_extraction(
        object(),
        "I use Python for backend development.\n\nI use Rust for systems programming.",
        "text",
    )
    assert backend.bulk_calls[0][0] == [
        "I use Python for backend development.",
        "I use Rust for systems programming.",
    ]


def test_run_extract_uses_result_categories_for_stats(monkeypatch, tmp_path):
    from cortex import cli_extract_commands

    input_path = tmp_path / "input.txt"
    input_path.write_text("I use Python and React.", encoding="utf-8")
    output_path = tmp_path / "context.json"
    output_lines: list[str] = []

    context = SimpleNamespace(
        echo=lambda *args, **kwargs: output_lines.append(str(args[0])),
        error=lambda *args, **kwargs: 1,
        is_quiet=lambda: False,
        load_graph=lambda _: None,
        missing_path_error=lambda *_a, **_k: 1,
        permission_error=lambda *_a, **_k: 1,
    )

    backend = _BackendStub(
        ExtractionResult(
            nodes=[
                ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.9),
                ExtractedNode(label="React", category="technical_expertise", value="React", confidence=0.87),
            ],
            extraction_method="model",
            raw_source="I use Python and React.",
        )
    )
    monkeypatch.setattr(cli_extract_commands, "get_bulk_backend", lambda: backend)

    args = SimpleNamespace(
        from_detected=[],
        input_file=str(input_path),
        project=str(tmp_path),
        format="auto",
        merge=None,
        output=str(output_path),
        no_claims=True,
        store_dir=str(tmp_path),
        json_output=False,
        include_config_metadata=False,
        stats=False,
        verbose=False,
        redact=False,
        redact_patterns=None,
        no_redact_detected=False,
    )

    rc = cli_extract_commands.run_extract(args, ctx=context)  # type: ignore[arg-type]
    assert rc == 0
    assert any("Extracted 2 topics across" in line for line in output_lines)
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "6.0"
    assert payload["meta"]["node_count"] == 2
