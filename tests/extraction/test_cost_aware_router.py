from __future__ import annotations

from cortex.extraction import ExtractedFact
from cortex.extraction.diagnostics import ExtractionDiagnostics
from cortex.extraction.hybrid_backend import HybridBackend
from cortex.extraction.model_backend import ModelBackend
from cortex.extraction.pipeline import Document, ExtractionBudget, ExtractionContext
from cortex.extraction.pipeline import ExtractionResult as PipelineExtractionResult


class _HighConfidenceHeuristic:
    def run(self, document: Document, context: ExtractionContext) -> PipelineExtractionResult:
        return PipelineExtractionResult(
            items=[
                ExtractedFact(
                    topic="Python",
                    category="technical_expertise",
                    brief="Python",
                    full_description="I use Python.",
                    confidence=0.92,
                    extraction_method="heuristic",
                    source_quotes=["I use Python."],
                    source_span="I use Python.",
                    extraction_confidence=0.92,
                    attribute_name="skill",
                    attribute_value="Python",
                )
            ],
            diagnostics=ExtractionDiagnostics(tokens_in=3, stage_timings={"extract": 1.0}),
        )


def test_high_confidence_heuristic_skips_model_call(monkeypatch) -> None:
    calls = {"count": 0}

    class _Messages:
        def create(self, *args, **kwargs):
            calls["count"] += 1
            raise AssertionError("Model call should be skipped for high-confidence heuristic items")

    class _Anthropic:
        def __init__(self, *args, **kwargs) -> None:
            self.messages = _Messages()

    monkeypatch.setattr(ModelBackend, "_anthropic_client_cls", lambda self: _Anthropic)
    backend = HybridBackend(
        fast_backend=_HighConfidenceHeuristic(),
        rescore_backend=ModelBackend(api_key="test-key"),
    )

    result = backend.run(
        Document(
            source_id="high-confidence",
            source_type="doc",
            content="I use Python.",
            metadata={},
        ),
        ExtractionContext(
            budget=ExtractionBudget(max_tokens=512, max_latency_ms=1_000, max_cost_usd=0.01),
            prompt_version="router-test",
        ),
    )

    assert calls["count"] == 0
    assert len(result.items) == 1
    assert result.diagnostics.router_decision["heuristic_kept"] == 1
    assert result.diagnostics.router_decision["escalated"] == 0
    assert result.diagnostics.router_decision["cost_saved_usd"] >= 0
    backend.close()
