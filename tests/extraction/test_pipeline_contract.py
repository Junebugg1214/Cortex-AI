from __future__ import annotations

from cortex.extraction import HeuristicBackend, HybridBackend, ModelBackend
from cortex.extraction.backend import ExtractionBackend
from cortex.extraction.pipeline import (
    Document,
    ExtractionBudget,
    ExtractionContext,
    ExtractionDiagnostics,
    ExtractionPipeline,
    ExtractionResult,
)


def _empty_document() -> Document:
    return Document(
        source_id="empty-chat",
        source_type="chat",
        content="",
        metadata={"fixture": "pipeline-contract"},
    )


def _context() -> ExtractionContext:
    return ExtractionContext(
        budget=ExtractionBudget(max_tokens=512, max_latency_ms=1_000, max_cost_usd=0.01),
        prompt_version="contract-test",
    )


def test_extraction_backend_is_deprecated_alias_for_pipeline() -> None:
    assert ExtractionBackend is ExtractionPipeline


def test_heuristic_backend_satisfies_pipeline_contract_on_empty_document() -> None:
    backend = HeuristicBackend()
    assert isinstance(backend, ExtractionPipeline)

    result = backend.run(_empty_document(), _context())

    assert isinstance(result, ExtractionResult)
    assert result.items == []
    assert isinstance(result.diagnostics, ExtractionDiagnostics)


def test_model_backend_satisfies_pipeline_contract_on_empty_document() -> None:
    backend = ModelBackend()
    assert isinstance(backend, ExtractionPipeline)

    result = backend.run(_empty_document(), _context())

    assert isinstance(result, ExtractionResult)
    assert result.items == []
    assert isinstance(result.diagnostics, ExtractionDiagnostics)


def test_hybrid_backend_satisfies_pipeline_contract_on_empty_document(monkeypatch) -> None:
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.signal", lambda *args, **kwargs: None)
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.getsignal", lambda *args, **kwargs: None)
    backend = HybridBackend()
    try:
        assert isinstance(backend, ExtractionPipeline)

        result = backend.run(_empty_document(), _context())

        assert isinstance(result, ExtractionResult)
        assert result.items == []
        assert isinstance(result.diagnostics, ExtractionDiagnostics)
    finally:
        backend.close()
