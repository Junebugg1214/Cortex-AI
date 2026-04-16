from __future__ import annotations

import copy
import logging
import os
import signal
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from cortex.contradictions import ContradictionEngine
from cortex.graph import Node, make_node_id_with_tag

from .backend import ExtractionBackend, load_extraction_config
from .heuristic_backend import HeuristicBackend
from .model_backend import ModelBackend
from .types import ExtractedEdge, ExtractedNode, ExtractionResult

LOGGER = logging.getLogger(__name__)


def _default_rescore_workers() -> int:
    raw = os.environ.get("CORTEX_HYBRID_RESCORE_WORKERS", "").strip()
    if raw:
        try:
            return max(int(raw), 1)
        except ValueError:
            return 4
    config = load_extraction_config()
    try:
        return max(int(config.get("hybrid_rescore_workers", 4)), 1)
    except (TypeError, ValueError):
        return 4


class HybridBackend(ExtractionBackend):
    """Fast heuristic extraction with background rescoring."""

    def __init__(
        self,
        *,
        fast_backend: ExtractionBackend | None = None,
        rescore_backend: ExtractionBackend | None = None,
        rescore_workers: int | None = None,
    ) -> None:
        self.fast_backend = fast_backend or HeuristicBackend()
        self.rescore_backend = rescore_backend or ModelBackend()
        self.rescore_workers = rescore_workers or _default_rescore_workers()
        self._executor = ThreadPoolExecutor(max_workers=self.rescore_workers, thread_name_prefix="cortex-hybrid")
        self._shutdown_lock = threading.Lock()
        self._closed = False
        self._previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, self._handle_sigterm)

    def extract_statement(
        self,
        text: str,
        context: dict | None = None,
    ) -> ExtractionResult:
        """Return fast heuristic extraction immediately and rescore in the background."""

        fast_result = self.fast_backend.extract_statement(text, context=context)
        result = ExtractionResult(
            nodes=[copy.deepcopy(item) for item in fast_result.nodes],
            edges=[copy.deepcopy(item) for item in fast_result.edges],
            extraction_method="hybrid",
            raw_source=fast_result.raw_source,
            warnings=list(fast_result.warnings),
            rescore_pending=True,
        )
        result._graph = getattr(fast_result, "_graph", None)
        future = self._executor.submit(self.rescore_backend.extract_statement, text, context)
        result._rescore_future = future
        future.add_done_callback(lambda done: self._apply_rescore(done, result, context or {}))
        return result

    def extract_bulk(
        self,
        texts: list[str],
        context: dict | None = None,
    ) -> list[ExtractionResult]:
        """Use the rescore backend directly for bulk extraction."""

        return self.rescore_backend.extract_bulk(texts, context=context)

    def canonical_match(
        self,
        node: ExtractedNode,
        existing_nodes: list[dict],
    ) -> tuple[str | None, float]:
        """Delegate canonical matching to the rescore backend."""

        return self.rescore_backend.canonical_match(node, existing_nodes)

    @property
    def supports_async_rescoring(self) -> bool:
        """Return true because HybridBackend always schedules rescoring."""

        return True

    @property
    def supports_embeddings(self) -> bool:
        """Return true when the rescore backend emits embeddings."""

        return self.rescore_backend.supports_embeddings

    def close(self) -> None:
        """Shut down the background worker pool."""

        self._shutdown(discard_queued=False)

    def _apply_rescore(self, future: Future, result: ExtractionResult, context: dict[str, Any]) -> None:
        try:
            rescored = future.result()
        except Exception as exc:  # pragma: no cover - exercised in tests
            LOGGER.warning("HybridBackend rescoring failed: %s", exc)
            result.rescore_pending = False
            return

        existing_by_key = {(node.label, node.category): node for node in result.nodes}
        for new_node in rescored.nodes:
            key = (new_node.label, new_node.category)
            existing = existing_by_key.get(key)
            if existing is not None:
                existing.confidence = max(existing.confidence, new_node.confidence)
                if new_node.canonical_match:
                    existing.canonical_match = new_node.canonical_match
                    existing.match_confidence = new_node.match_confidence
                existing.needs_review = existing.needs_review or new_node.needs_review
                if self.rescore_backend.supports_embeddings and new_node.embedding is not None:
                    existing.embedding = list(new_node.embedding)
            else:
                promoted = copy.deepcopy(new_node)
                promoted.needs_review = True
                result.nodes.append(promoted)
                existing_by_key[key] = promoted

        edge_keys = {(edge.source, edge.target, edge.relationship): edge for edge in result.edges}
        for new_edge in rescored.edges:
            key = (new_edge.source, new_edge.target, new_edge.relationship)
            existing_edge = edge_keys.get(key)
            if existing_edge is not None:
                existing_edge.direction_confidence = max(existing_edge.direction_confidence, new_edge.direction_confidence)
                existing_edge.needs_review = existing_edge.needs_review or new_edge.needs_review
            else:
                promoted_edge = copy.deepcopy(new_edge)
                promoted_edge.needs_review = True
                result.edges.append(promoted_edge)
                edge_keys[key] = promoted_edge

        graph = context.get("graph")
        if graph is None:
            graph = getattr(result, "_graph", None)
        if graph is not None:
            self._apply_rescore_to_graph(graph, rescored)

        result.rescore_pending = False

    def _apply_rescore_to_graph(self, graph, rescored: ExtractionResult) -> None:
        existing_by_label = {node.label: node for node in graph.nodes.values()}
        for new_node in rescored.nodes:
            existing = existing_by_label.get(new_node.label)
            if existing is None:
                graph.add_node(
                    Node(
                        id=make_node_id_with_tag(new_node.label, new_node.category),
                        label=new_node.label,
                        tags=[new_node.category],
                        confidence=new_node.confidence,
                        brief=new_node.value or new_node.label,
                        full_description=new_node.value if new_node.value != new_node.label else "",
                        properties={
                            "needs_review": True,
                            "embedding": list(new_node.embedding) if new_node.embedding is not None else [],
                        },
                    )
                )
                existing = graph.nodes[make_node_id_with_tag(new_node.label, new_node.category)]
                existing_by_label[new_node.label] = existing
            else:
                existing.confidence = max(existing.confidence, new_node.confidence)
                if new_node.category not in existing.tags:
                    existing.tags.append(new_node.category)
                existing.properties["needs_review"] = bool(existing.properties.get("needs_review") or new_node.needs_review)
                if self.rescore_backend.supports_embeddings and new_node.embedding is not None:
                    existing.properties["embedding"] = list(new_node.embedding)

        if any(node.confidence > 0.85 for node in rescored.nodes):
            contradictions = ContradictionEngine().detect_all(graph)
            if contradictions:
                graph.meta["contradictions"] = [item.to_dict() for item in contradictions]

    def _shutdown(self, *, discard_queued: bool) -> None:
        with self._shutdown_lock:
            if self._closed:
                return
            self._executor.shutdown(wait=True, cancel_futures=discard_queued)
            self._closed = True

    def _handle_sigterm(self, signum: int, frame: object | None) -> None:
        """Finish in-flight work, discard queued tasks, and log the discard count."""

        queued = 0
        work_queue = getattr(self._executor, "_work_queue", None)
        if work_queue is not None:
            try:
                queued = int(work_queue.qsize())
            except Exception:  # pragma: no cover - platform dependent
                queued = 0
        with self._shutdown_lock:
            if not self._closed:
                self._executor.shutdown(wait=True, cancel_futures=True)
                self._closed = True
        LOGGER.info("HybridBackend discarded %s queued rescore task(s) during shutdown.", queued)
        previous = self._previous_sigterm_handler
        if callable(previous) and previous is not self._handle_sigterm:
            previous(signum, frame)
