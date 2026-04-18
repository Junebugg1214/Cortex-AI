from __future__ import annotations

from cortex.extraction import Document, ExtractedFact, ExtractedRelationship, ExtractionContext, ModelBackend
from cortex.extraction.diagnostics import ExtractionDiagnostics
from cortex.extraction.types import ExtractionResult as BackendExtractionResult


def test_model_backend_runs_all_pipeline_stages(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CORTEX_EXTRACTION_LOG_PATH", str(tmp_path / "extractions.jsonl"))
    backend = ModelBackend()
    calls: list[str] = []

    def _fake_extract_statement(text: str, context: dict | None = None) -> BackendExtractionResult:
        calls.append(text)
        items = [
            ExtractedFact(
                topic="Alice",
                category="identity",
                brief="Alice is a person",
                confidence=0.91,
                extraction_method="model",
                source_quotes=[text],
                source_span=text,
                extraction_confidence=0.91,
                attribute_name="person",
                attribute_value="Alice",
            ),
            ExtractedFact(
                topic="Python",
                category="technical_expertise",
                brief="Python is used",
                confidence=0.92,
                extraction_method="model",
                source_quotes=[text],
                source_span=text,
                extraction_confidence=0.92,
                attribute_name="skill",
                attribute_value="Python",
            ),
            ExtractedRelationship(
                topic="Alice uses Python",
                category="relationships",
                brief="Alice uses Python",
                confidence=0.9,
                extraction_method="model",
                source_quotes=[text],
                source_span=text,
                relationship_type="uses",
                extraction_confidence=0.9,
                source_label="Alice",
                relation="uses",
                target_label="Python",
            ),
        ]
        result = BackendExtractionResult(extraction_method="model", raw_source=text)
        result._typed_items = items
        result._diagnostics = ExtractionDiagnostics(
            tokens_in=17,
            tokens_out=11,
            cost_usd=0.001,
            latency_ms=1.0,
            stage_timings={"request": 1.0},
            model="stub-model",
            prompt_version=(context or {}).get("prompt_version", ""),
        )
        return result

    monkeypatch.setattr(backend, "extract_statement", _fake_extract_statement)

    result = backend.run(
        Document(source_id="stage-doc", source_type="doc", content="Alice uses Python."),
        ExtractionContext(prompt_version="stage-v1"),
    )

    assert calls == ["Alice uses Python."]
    assert len(result.items) == 3
    assert result.diagnostics.model == "stub-model"
    assert result.diagnostics.prompt_version == "stage-v1"
    assert result.diagnostics.stage_timings["request"] == 1.0
    for stage_name in (
        "split_document",
        "generate_candidates",
        "refine_types",
        "link_to_graph",
        "link_relations",
        "calibrate_confidence",
    ):
        assert result.diagnostics.stage_timings[stage_name] >= 0.0
    relationship = next(item for item in result.items if isinstance(item, ExtractedRelationship))
    assert relationship.qualifiers == {"source_id": "Alice", "target_id": "Python"}
