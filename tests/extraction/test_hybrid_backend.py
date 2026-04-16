from __future__ import annotations

import logging
import time

from cortex.extraction import ExtractedEdge, ExtractedNode, ExtractionResult, HybridBackend
from cortex.graph import CortexGraph, Node, make_node_id_with_tag


class _StaticBackend:
    def __init__(self, result: ExtractionResult, *, delay: float = 0.0, supports_embeddings: bool = False) -> None:
        self.result = result
        self.delay = delay
        self._supports_embeddings = supports_embeddings
        self.called_with: list[tuple[str, dict | None]] = []

    def extract_statement(self, text: str, context: dict | None = None) -> ExtractionResult:
        self.called_with.append((text, context))
        if self.delay:
            time.sleep(self.delay)
        output = ExtractionResult(
            nodes=[ExtractedNode(**vars(node)) for node in self.result.nodes],
            edges=[ExtractedEdge(**vars(edge)) for edge in self.result.edges],
            extraction_method=self.result.extraction_method,
            raw_source=self.result.raw_source,
            warnings=list(self.result.warnings),
            rescore_pending=self.result.rescore_pending,
        )
        output._graph = getattr(self.result, "_graph", None)
        return output

    def extract_bulk(self, texts: list[str], context: dict | None = None):
        self.called_with.append(("bulk", context))
        return [self.result]

    def canonical_match(self, node, existing_nodes):
        return ("n1", 0.9)

    @property
    def supports_async_rescoring(self) -> bool:
        return True

    @property
    def supports_embeddings(self) -> bool:
        return self._supports_embeddings


class _FailingBackend(_StaticBackend):
    def __init__(self) -> None:
        super().__init__(ExtractionResult(extraction_method="model"))

    def extract_statement(self, text: str, context: dict | None = None) -> ExtractionResult:
        raise RuntimeError("boom")


def _make_fast_result() -> ExtractionResult:
    graph = CortexGraph()
    graph.add_node(
        Node(
            id=make_node_id_with_tag("Python", "technical_expertise"),
            label="Python",
            tags=["technical_expertise"],
            confidence=0.55,
            brief="Python",
        )
    )
    result = ExtractionResult(
        nodes=[ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.55)],
        edges=[],
        extraction_method="heuristic",
        raw_source="I use Python.",
    )
    result._graph = graph
    return result


def _wait(result: ExtractionResult, timeout: float = 1.0) -> None:
    try:
        result._rescore_future.result(timeout=timeout)
    except Exception:
        pass
    for _ in range(20):
        if not result.rescore_pending:
            return
        time.sleep(0.01)


def test_extract_statement_returns_immediately_with_rescore_pending(monkeypatch):
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.signal", lambda *args, **kwargs: None)
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.getsignal", lambda *args, **kwargs: None)
    fast = _StaticBackend(_make_fast_result())
    slow = _StaticBackend(
        ExtractionResult(
            nodes=[ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.9)],
            extraction_method="model",
        ),
        delay=0.2,
    )
    backend = HybridBackend(fast_backend=fast, rescore_backend=slow, rescore_workers=1)
    started = time.perf_counter()
    result = backend.extract_statement("I use Python.")
    elapsed = time.perf_counter() - started
    assert elapsed < 0.1
    assert result.rescore_pending is True
    backend.close()


def test_extract_statement_sets_hybrid_method(monkeypatch):
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.signal", lambda *args, **kwargs: None)
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.getsignal", lambda *args, **kwargs: None)
    backend = HybridBackend(
        fast_backend=_StaticBackend(_make_fast_result()), rescore_backend=_StaticBackend(_make_fast_result())
    )
    result = backend.extract_statement("I use Python.")
    assert result.extraction_method == "hybrid"
    backend.close()


def test_async_rescoring_updates_existing_confidence(monkeypatch):
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.signal", lambda *args, **kwargs: None)
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.getsignal", lambda *args, **kwargs: None)
    backend = HybridBackend(
        fast_backend=_StaticBackend(_make_fast_result()),
        rescore_backend=_StaticBackend(
            ExtractionResult(
                nodes=[ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.95)],
                extraction_method="model",
            )
        ),
        rescore_workers=1,
    )
    result = backend.extract_statement("I use Python.")
    _wait(result)
    assert result.nodes[0].confidence == 0.95
    backend.close()


def test_model_only_nodes_are_added_with_review_flag(monkeypatch):
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.signal", lambda *args, **kwargs: None)
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.getsignal", lambda *args, **kwargs: None)
    backend = HybridBackend(
        fast_backend=_StaticBackend(_make_fast_result()),
        rescore_backend=_StaticBackend(
            ExtractionResult(
                nodes=[ExtractedNode(label="Rust", category="technical_expertise", value="Rust", confidence=0.88)],
                extraction_method="model",
            )
        ),
    )
    result = backend.extract_statement("I use Python and Rust.")
    _wait(result)
    rust = next(node for node in result.nodes if node.label == "Rust")
    assert rust.needs_review is True
    backend.close()


def test_model_only_edges_are_added_with_review_flag(monkeypatch):
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.signal", lambda *args, **kwargs: None)
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.getsignal", lambda *args, **kwargs: None)
    backend = HybridBackend(
        fast_backend=_StaticBackend(_make_fast_result()),
        rescore_backend=_StaticBackend(
            ExtractionResult(
                edges=[
                    ExtractedEdge(
                        source="Python", target="Data Science", relationship="used_in", direction_confidence=0.58
                    )
                ],
                extraction_method="model",
            )
        ),
    )
    result = backend.extract_statement("I use Python for data science.")
    _wait(result)
    assert result.edges[0].needs_review is True
    backend.close()


def test_embedding_from_rescore_is_stored(monkeypatch):
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.signal", lambda *args, **kwargs: None)
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.getsignal", lambda *args, **kwargs: None)
    fast = _make_fast_result()
    graph = fast._graph
    backend = HybridBackend(
        fast_backend=_StaticBackend(fast),
        rescore_backend=_StaticBackend(
            ExtractionResult(
                nodes=[
                    ExtractedNode(
                        label="Python",
                        category="technical_expertise",
                        value="Python",
                        confidence=0.9,
                        embedding=[0.1, 0.2],
                    )
                ],
                extraction_method="embedding",
            ),
            supports_embeddings=True,
        ),
    )
    result = backend.extract_statement("I use Python.", context={"graph": graph})
    _wait(result)
    assert result.nodes[0].embedding == [0.1, 0.2]
    assert graph.nodes[next(iter(graph.nodes))].properties["embedding"] == [0.1, 0.2]
    backend.close()


def test_high_confidence_contradiction_is_recorded(monkeypatch):
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.signal", lambda *args, **kwargs: None)
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.getsignal", lambda *args, **kwargs: None)
    fast = _make_fast_result()
    graph = fast._graph
    backend = HybridBackend(
        fast_backend=_StaticBackend(fast),
        rescore_backend=_StaticBackend(
            ExtractionResult(
                nodes=[ExtractedNode(label="Python", category="negations", value="Avoid Python", confidence=0.91)],
                extraction_method="model",
            )
        ),
    )
    result = backend.extract_statement("I avoid Python now.", context={"graph": graph})
    _wait(result)
    assert graph.meta["contradictions"]
    backend.close()


def test_rescore_failure_is_logged_and_does_not_crash(monkeypatch, caplog):
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.signal", lambda *args, **kwargs: None)
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.getsignal", lambda *args, **kwargs: None)
    backend = HybridBackend(fast_backend=_StaticBackend(_make_fast_result()), rescore_backend=_FailingBackend())
    with caplog.at_level(logging.WARNING):
        result = backend.extract_statement("I use Python.")
        _wait(result)
    assert "rescoring failed" in caplog.text
    assert result.rescore_pending is False
    backend.close()


def test_extract_bulk_delegates_to_rescore_backend(monkeypatch):
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.signal", lambda *args, **kwargs: None)
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.getsignal", lambda *args, **kwargs: None)
    rescore = _StaticBackend(ExtractionResult(nodes=[], extraction_method="model"))
    backend = HybridBackend(fast_backend=_StaticBackend(_make_fast_result()), rescore_backend=rescore)
    backend.extract_bulk(["a", "b"])
    assert rescore.called_with[0][0] == "bulk"
    backend.close()


def test_canonical_match_delegates_to_rescore_backend(monkeypatch):
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.signal", lambda *args, **kwargs: None)
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.getsignal", lambda *args, **kwargs: None)
    rescore = _StaticBackend(ExtractionResult(nodes=[], extraction_method="model"))
    backend = HybridBackend(fast_backend=_StaticBackend(_make_fast_result()), rescore_backend=rescore)
    match = backend.canonical_match(
        ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.9), []
    )
    assert match == ("n1", 0.9)
    backend.close()


def test_supports_embeddings_delegates_to_rescore_backend(monkeypatch):
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.signal", lambda *args, **kwargs: None)
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.getsignal", lambda *args, **kwargs: None)
    backend = HybridBackend(
        fast_backend=_StaticBackend(_make_fast_result()),
        rescore_backend=_StaticBackend(
            ExtractionResult(nodes=[], extraction_method="embedding"), supports_embeddings=True
        ),
    )
    assert backend.supports_embeddings is True
    backend.close()


def test_sigterm_shutdown_logs_discarded_tasks(monkeypatch, caplog):
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.signal", lambda *args, **kwargs: None)
    monkeypatch.setattr("cortex.extraction.hybrid_backend.signal.getsignal", lambda *args, **kwargs: None)
    backend = HybridBackend(
        fast_backend=_StaticBackend(_make_fast_result()),
        rescore_backend=_StaticBackend(ExtractionResult(nodes=[], extraction_method="model"), delay=0.05),
        rescore_workers=1,
    )
    backend.extract_statement("one")
    backend.extract_statement("two")
    with caplog.at_level(logging.INFO):
        backend._handle_sigterm(15, None)
    assert backend._closed is True
    assert "discarded" in caplog.text
