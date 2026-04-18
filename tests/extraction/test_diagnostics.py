from __future__ import annotations

import json

import pytest

from cortex.cli import main
from cortex.extraction.diagnostics import ExtractionDiagnostics, write_extraction_record
from cortex.extraction.model_backend import DEFAULT_MODEL, ModelBackend
from cortex.extraction.pipeline import Document, ExtractionContext


def test_model_backend_records_cost_and_tokens(monkeypatch, tmp_path) -> None:
    log_path = tmp_path / "extractions.jsonl"
    monkeypatch.setenv("CORTEX_EXTRACTION_LOG_PATH", str(log_path))

    response_payload = {
        "nodes": [
            {
                "label": "Python",
                "category": "technical_expertise",
                "value": "Python",
                "confidence": 0.91,
            }
        ],
        "edges": [],
        "warnings": ["stubbed warning"],
    }

    class _Usage:
        input_tokens = 123
        output_tokens = 45

    class _Block:
        text = json.dumps(response_payload)

    class _Response:
        content = [_Block()]
        usage = _Usage()
        model = DEFAULT_MODEL

    class _Messages:
        def create(self, **_kwargs):
            return _Response()

    class _Client:
        def __init__(self, *, api_key: str) -> None:
            self.api_key = api_key
            self.messages = _Messages()

    backend = ModelBackend(api_key="test-key")
    monkeypatch.setattr(backend, "_anthropic_client_cls", lambda: _Client)

    result = backend.run(
        Document(source_id="diag-doc", source_type="chat", content="I use Python."),
        ExtractionContext(prompt_version="diag-v1"),
    )

    expected_cost = (123 * 3.0 + 45 * 15.0) / 1_000_000.0
    assert result.diagnostics.tokens_in == 123
    assert result.diagnostics.tokens_out == 45
    assert result.diagnostics.cost_usd == pytest.approx(expected_cost)
    assert result.diagnostics.model == DEFAULT_MODEL
    assert result.diagnostics.prompt_version == "diag-v1"
    assert result.diagnostics.warnings == ["stubbed warning"]
    assert result.diagnostics.cache_hit is False
    assert result.diagnostics.stage_timings["request"] >= 0.0
    assert result.diagnostics.stage_timings["extract"] >= result.diagnostics.stage_timings["request"]

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    record = records[0]
    assert record["backend"] == "model"
    assert record["operation"] == "run"
    assert record["source_id"] == "diag-doc"
    assert record["source_type"] == "chat"
    assert record["item_count"] == 1
    assert record["tokens_in"] == 123
    assert record["tokens_out"] == 45
    assert record["cost_usd"] == pytest.approx(expected_cost)


def test_debug_extractions_tail_prints_recent_records(monkeypatch, tmp_path, capsys) -> None:
    log_path = tmp_path / "extractions.jsonl"
    monkeypatch.setenv("CORTEX_EXTRACTION_LOG_PATH", str(log_path))
    write_extraction_record(
        ExtractionDiagnostics(latency_ms=2.5, stage_timings={"extract": 2.5}),
        backend="heuristic",
        operation="run",
        source_id="doc-1",
        source_type="chat",
        item_count=2,
    )

    assert main(["debug", "extractions", "tail", "--limit", "1"]) == 0

    out = capsys.readouterr().out
    assert "heuristic.run" in out
    assert "items=2" in out
    assert "latency=2.5ms" in out
