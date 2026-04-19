from __future__ import annotations

from cortex.extraction import ExtractedEdge, ExtractedNode, ExtractionResult, HybridBackend


class _StaticBackend:
    def __init__(self, result: ExtractionResult, *, supports_embeddings: bool = False) -> None:
        self.result = result
        self._supports_embeddings = supports_embeddings
        self.called_with: list[tuple[str, dict | None]] = []

    def extract_statement(self, text: str, context: dict | None = None) -> ExtractionResult:
        self.called_with.append((text, context))
        output = ExtractionResult(
            nodes=[ExtractedNode(**vars(node)) for node in self.result.nodes],
            edges=[ExtractedEdge(**vars(edge)) for edge in self.result.edges],
            extraction_method=self.result.extraction_method,
            raw_source=text,
            warnings=list(self.result.warnings),
            rescore_pending=False,
        )
        typed_items = getattr(self.result, "_typed_items", None)
        if typed_items is not None:
            output._typed_items = list(typed_items)
        return output

    def canonical_match(self, node, existing_nodes):
        return ("n1", 0.9)

    @property
    def supports_async_rescoring(self) -> bool:
        return False

    @property
    def supports_embeddings(self) -> bool:
        return self._supports_embeddings


def _make_result(
    *,
    label: str = "Python",
    category: str = "technical_expertise",
    value: str = "Python",
    confidence: float = 0.9,
    method: str = "heuristic",
) -> ExtractionResult:
    return ExtractionResult(
        nodes=[
            ExtractedNode(
                label=label,
                category=category,
                value=value,
                confidence=confidence,
            )
        ],
        edges=[],
        extraction_method=method,
        raw_source="I use Python.",
    )


def test_extract_statement_sets_hybrid_method() -> None:
    model = _StaticBackend(ExtractionResult(extraction_method="model"))
    backend = HybridBackend(
        fast_backend=_StaticBackend(_make_result(confidence=0.92)),
        rescore_backend=model,
    )

    result = backend.extract_statement("I use Python.")

    assert result.extraction_method == "hybrid"
    assert result.rescore_pending is False
    assert model.called_with == []
    backend.close()


def test_low_confidence_item_escalates_once_and_merges_confidence() -> None:
    model = _StaticBackend(_make_result(confidence=0.95, method="model"))
    backend = HybridBackend(
        fast_backend=_StaticBackend(_make_result(confidence=0.55)),
        rescore_backend=model,
    )

    result = backend.extract_statement("I use Python.")

    assert len(model.called_with) == 1
    assert result.nodes[0].confidence == 0.95
    assert result.extraction_method == "hybrid"
    backend.close()


def test_claim_escalates_even_with_high_confidence() -> None:
    model = _StaticBackend(ExtractionResult(extraction_method="model"))
    backend = HybridBackend(
        fast_backend=_StaticBackend(
            _make_result(category="negations", value="Avoid Python", confidence=0.91),
        ),
        rescore_backend=model,
    )

    result = backend.extract_statement("I avoid Python now.")

    assert len(model.called_with) == 1
    assert result.nodes[0].category == "negations"
    assert result.nodes[0].value == "Avoid Python"
    backend.close()


def test_extract_bulk_routes_each_text() -> None:
    model = _StaticBackend(ExtractionResult(extraction_method="model"))
    backend = HybridBackend(
        fast_backend=_StaticBackend(_make_result(confidence=0.92)),
        rescore_backend=model,
    )

    results = backend.extract_bulk(["I use Python.", "I use Rust."])

    assert len(results) == 2
    assert [result.extraction_method for result in results] == ["hybrid", "hybrid"]
    assert model.called_with == []
    backend.close()


def test_canonical_match_delegates_to_rescore_backend() -> None:
    rescore = _StaticBackend(ExtractionResult(nodes=[], extraction_method="model"))
    backend = HybridBackend(fast_backend=_StaticBackend(_make_result()), rescore_backend=rescore)
    match = backend.canonical_match(
        ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.9), []
    )
    assert match == ("n1", 0.9)
    backend.close()


def test_supports_embeddings_delegates_to_rescore_backend() -> None:
    backend = HybridBackend(
        fast_backend=_StaticBackend(_make_result()),
        rescore_backend=_StaticBackend(
            ExtractionResult(nodes=[], extraction_method="embedding"),
            supports_embeddings=True,
        ),
    )
    assert backend.supports_embeddings is True
    backend.close()
