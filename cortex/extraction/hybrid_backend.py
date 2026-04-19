from __future__ import annotations

import copy
import json
import logging
import signal as signal
from dataclasses import replace
from time import perf_counter
from typing import Any, Mapping

from .diagnostics import ExtractionDiagnostics, write_extraction_record
from .extract_memory_context import ExtractedClaim, ExtractedFact, ExtractedMemoryItem, ExtractedRelationship
from .heuristic_backend import HeuristicBackend
from .model_backend import ModelBackend
from .pipeline import (
    Document,
    ExtractionBudget,
    empty_result,
    items_from_backend_result,
    legacy_context_from_pipeline_context,
    result_from_backend_result,
)
from .pipeline import (
    ExtractionContext as PipelineExtractionContext,
)
from .pipeline import (
    ExtractionResult as PipelineExtractionResult,
)
from .types import ExtractedEdge, ExtractedNode
from .types import ExtractionResult as BackendExtractionResult

LOGGER = logging.getLogger(__name__)
_SIGNAL_COMPAT = signal
_ESCALATION_CONFIDENCE_THRESHOLD = 0.6
_SONNET_INPUT_PRICE_PER_MILLION = 3.0


def _estimate_tokens(text: str) -> int:
    return len((text or "").split())


def _normalize(value: str) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _confidence(item: ExtractedMemoryItem) -> float:
    try:
        return float(item.confidence)
    except (TypeError, ValueError):
        return 0.0


def _item_text(item: ExtractedMemoryItem) -> str:
    parts: list[str] = []
    if item.source_span:
        parts.append(item.source_span)
    parts.extend(quote for quote in item.source_quotes if quote)
    parts.extend(
        part
        for part in (
            item.full_description,
            item.brief,
            item.topic,
        )
        if part
    )
    return " ".join(parts).strip()


def _item_key(item: ExtractedMemoryItem) -> tuple[str, ...]:
    if isinstance(item, ExtractedRelationship):
        return (
            "relationship",
            _normalize(item.source_label),
            _normalize(item.relation or item.relationship_type),
            _normalize(item.target_label),
        )
    if isinstance(item, ExtractedClaim):
        return (
            "claim",
            _normalize(item.category),
            _normalize(item.topic),
            _normalize(item.assertion or item.brief),
            _normalize(item.stance),
        )
    if isinstance(item, ExtractedFact):
        return (
            "fact",
            _normalize(item.category),
            _normalize(item.topic),
            _normalize(item.attribute_name),
            _normalize(item.attribute_value or item.brief),
        )
    return (
        item.__class__.__name__.lower(),
        _normalize(item.category),
        _normalize(item.topic),
        _normalize(item.brief),
    )


def _clone_item(item: ExtractedMemoryItem, *, method: str = "hybrid") -> ExtractedMemoryItem:
    cloned = copy.deepcopy(item)
    cloned.extraction_method = method
    return cloned


def _merge_items(
    heuristic_items: list[ExtractedMemoryItem],
    model_items: list[ExtractedMemoryItem],
) -> list[ExtractedMemoryItem]:
    merged: dict[tuple[str, ...], ExtractedMemoryItem] = {}
    order: list[tuple[str, ...]] = []
    for item in [*heuristic_items, *model_items]:
        key = _item_key(item)
        candidate = _clone_item(item)
        if key not in merged:
            merged[key] = candidate
            order.append(key)
            continue

        existing = merged[key]
        if type(existing) is type(candidate):
            existing.merge_with(candidate)
            existing.extraction_method = "hybrid"
            continue
        if _confidence(candidate) > _confidence(existing):
            merged[key] = candidate
    return [merged[key] for key in order]


def _legacy_node_from_item(item: ExtractedMemoryItem) -> ExtractedNode | None:
    if isinstance(item, ExtractedRelationship):
        return None
    confidence = _confidence(item)
    extraction_confidence = float(item.extraction_confidence or confidence)
    needs_review = "needs_review" in item.extraction_flags or extraction_confidence < _ESCALATION_CONFIDENCE_THRESHOLD
    value = item.full_description or item.brief or item.topic
    if isinstance(item, ExtractedFact):
        value = item.attribute_value or value
    if isinstance(item, ExtractedClaim):
        value = item.assertion or value
    return ExtractedNode(
        label=item.topic,
        category=item.category or "mentions",
        value=value,
        confidence=confidence,
        canonical_match=item.entity_resolution or None,
        match_confidence=extraction_confidence,
        needs_review=needs_review,
    )


def _legacy_edge_from_item(item: ExtractedMemoryItem) -> ExtractedEdge | None:
    if not isinstance(item, ExtractedRelationship):
        return None
    confidence = float(item.extraction_confidence or item.confidence)
    return ExtractedEdge(
        source=item.source_label,
        target=item.target_label,
        relationship=item.relation or item.relationship_type or "related_to",
        direction_confidence=confidence,
        needs_review="needs_review" in item.extraction_flags or confidence < _ESCALATION_CONFIDENCE_THRESHOLD,
    )


def _legacy_result_from_items(
    items: list[ExtractedMemoryItem],
    *,
    raw_source: str,
    diagnostics: ExtractionDiagnostics,
) -> BackendExtractionResult:
    nodes = [node for item in items if (node := _legacy_node_from_item(item)) is not None]
    edges = [edge for item in items if (edge := _legacy_edge_from_item(item)) is not None]
    result = BackendExtractionResult(
        nodes=nodes,
        edges=edges,
        extraction_method="hybrid",
        raw_source=raw_source,
        warnings=list(diagnostics.warnings),
        rescore_pending=False,
    )
    result._typed_items = list(items)
    result._diagnostics = diagnostics
    return result


def _diagnostics_from_result(result: PipelineExtractionResult | BackendExtractionResult) -> ExtractionDiagnostics:
    diagnostics = getattr(result, "diagnostics", None)
    if isinstance(diagnostics, ExtractionDiagnostics):
        return diagnostics
    diagnostics = getattr(result, "_diagnostics", None)
    if isinstance(diagnostics, ExtractionDiagnostics):
        return diagnostics
    return ExtractionDiagnostics()


def _warning_list(
    *diagnostics: ExtractionDiagnostics, backend_result: BackendExtractionResult | None = None
) -> list[str]:
    warnings: list[str] = []
    for diagnostic in diagnostics:
        warnings.extend(diagnostic.warnings)
    if backend_result is not None:
        warnings.extend(backend_result.warnings)
    return list(dict.fromkeys(warning for warning in warnings if warning))


def _stage_timings(
    *,
    heuristic: ExtractionDiagnostics,
    model: ExtractionDiagnostics | None,
    router_ms: float,
    latency_ms: float,
) -> dict[str, float]:
    timings: dict[str, float] = {}
    for name, duration in heuristic.stage_timings.items():
        timings[f"heuristic.{name}"] = float(duration)
    if model is not None:
        for name, duration in model.stage_timings.items():
            timings[f"model.{name}"] = float(duration)
    timings["router"] = router_ms
    timings["extract"] = latency_ms
    return timings


def _cost_saved_usd(document_text: str, escalated_spans: list[str]) -> float:
    full_tokens = _estimate_tokens(document_text)
    escalated_tokens = _estimate_tokens("\n".join(escalated_spans))
    saved_tokens = max(0, full_tokens - escalated_tokens)
    return round((saved_tokens * _SONNET_INPUT_PRICE_PER_MILLION) / 1_000_000.0, 6)


def _document_from_legacy_text(text: str, context: Mapping[str, Any] | None) -> Document:
    source_type = str((context or {}).get("source_type") or "doc")
    if source_type not in {"chat", "doc", "code", "transcript"}:
        source_type = "doc"
    return Document(
        source_id=str((context or {}).get("source_id") or "statement"),
        source_type=source_type,  # type: ignore[arg-type]
        content=text,
        metadata=dict((context or {}).get("metadata") or {}),
    )


def _pipeline_context_from_legacy(context: Mapping[str, Any] | None) -> PipelineExtractionContext:
    raw_budget = (context or {}).get("budget")
    budget = raw_budget if isinstance(raw_budget, ExtractionBudget) else ExtractionBudget()
    prompt_overrides = (context or {}).get("prompt_overrides")
    graph = (context or {}).get("graph")
    return PipelineExtractionContext(
        existing_graph=graph if graph is not None else None,
        budget=budget,
        prompt_version=str((context or {}).get("prompt_version") or ""),
        prompt_overrides=dict(prompt_overrides) if isinstance(prompt_overrides, Mapping) else {},
    )


class CostAwareRouter:
    """Route extraction through heuristics first and escalate only uncertain spans."""

    def __init__(
        self,
        *,
        heuristic_backend: Any | None = None,
        model_backend: Any | None = None,
        confidence_threshold: float = _ESCALATION_CONFIDENCE_THRESHOLD,
    ) -> None:
        self.heuristic_backend = heuristic_backend or HeuristicBackend()
        self.model_backend = model_backend or ModelBackend()
        self.confidence_threshold = confidence_threshold

    def run(self, document: Document, context: PipelineExtractionContext) -> PipelineExtractionResult:
        started = perf_counter()
        if not document.content.strip():
            result = empty_result(document, started_at=started)
            result.diagnostics = replace(
                result.diagnostics,
                prompt_version=context.prompt_version,
                router_decision={"heuristic_kept": 0, "escalated": 0, "cost_saved_usd": 0.0},
            )
            write_extraction_record(
                result.diagnostics,
                backend="hybrid",
                operation="run",
                source_id=document.source_id,
                source_type=document.source_type,
                item_count=0,
            )
            return result

        router_started = perf_counter()
        heuristic_result = self._run_heuristic(document, context)
        heuristic_items = list(heuristic_result.items)
        heuristic_diagnostics = _diagnostics_from_result(heuristic_result)
        kept, escalated = self._partition_items(heuristic_items)
        escalated_spans = self._spans_for_items(escalated)

        model_items: list[ExtractedMemoryItem] = []
        model_diagnostics: ExtractionDiagnostics | None = None
        model_backend_result: BackendExtractionResult | None = None
        if escalated_spans:
            model_backend_result = self._run_model(document, context, escalated, escalated_spans)
            model_items = list(items_from_backend_result(model_backend_result))
            model_diagnostics = _diagnostics_from_result(model_backend_result)

        items = _merge_items(heuristic_items, model_items)
        router_ms = (perf_counter() - router_started) * 1000.0
        latency_ms = (perf_counter() - started) * 1000.0
        router_decision = {
            "heuristic_kept": len(kept),
            "escalated": len(escalated),
            "cost_saved_usd": _cost_saved_usd(document.content, escalated_spans),
        }
        diagnostics = ExtractionDiagnostics(
            tokens_in=heuristic_diagnostics.tokens_in + (model_diagnostics.tokens_in if model_diagnostics else 0),
            tokens_out=heuristic_diagnostics.tokens_out + (model_diagnostics.tokens_out if model_diagnostics else 0),
            cost_usd=(model_diagnostics.cost_usd if model_diagnostics else 0.0),
            latency_ms=latency_ms,
            stage_timings=_stage_timings(
                heuristic=heuristic_diagnostics,
                model=model_diagnostics,
                router_ms=router_ms,
                latency_ms=latency_ms,
            ),
            model=model_diagnostics.model if model_diagnostics else "",
            prompt_version=context.prompt_version,
            warnings=_warning_list(
                heuristic_diagnostics,
                model_diagnostics or ExtractionDiagnostics(),
                backend_result=model_backend_result,
            ),
            cache_hit=bool(model_diagnostics.cache_hit) if model_diagnostics else False,
            router_decision=router_decision,
        )
        result = PipelineExtractionResult(items=items, diagnostics=diagnostics)
        write_extraction_record(
            diagnostics,
            backend="hybrid",
            operation="run",
            source_id=document.source_id,
            source_type=document.source_type,
            item_count=len(items),
        )
        return result

    def _run_heuristic(
        self,
        document: Document,
        context: PipelineExtractionContext,
    ) -> PipelineExtractionResult:
        if hasattr(self.heuristic_backend, "run"):
            return self.heuristic_backend.run(document, context)
        backend_result = self.heuristic_backend.extract_statement(
            document.content,
            context={**legacy_context_from_pipeline_context(context), "_skip_diagnostics_log": True},
        )
        return result_from_backend_result(backend_result, document=document, context=context, started_at=perf_counter())

    def _run_model(
        self,
        document: Document,
        context: PipelineExtractionContext,
        escalated_items: list[ExtractedMemoryItem],
        spans: list[str],
    ) -> BackendExtractionResult:
        legacy_context = legacy_context_from_pipeline_context(context)
        legacy_context["_skip_diagnostics_log"] = True
        legacy_context["known_heuristic_items"] = [item.to_dict() for item in escalated_items]
        legacy_context["router_escalated_spans"] = list(spans)
        prompt = self._escalation_prompt(
            document=document,
            escalated_items=escalated_items,
            spans=spans,
        )
        try:
            return self.model_backend.extract_statement(prompt, context=legacy_context)
        except Exception as exc:  # pragma: no cover - defensive, exercised by compatibility tests
            LOGGER.warning("cost-aware model escalation failed: %s", exc)
            diagnostics = ExtractionDiagnostics(
                prompt_version=context.prompt_version,
                warnings=["model_escalation_failed"],
            )
            result = BackendExtractionResult(
                extraction_method="model",
                raw_source=prompt,
                warnings=list(diagnostics.warnings),
            )
            result._diagnostics = diagnostics
            return result

    def _partition_items(
        self,
        items: list[ExtractedMemoryItem],
    ) -> tuple[list[ExtractedMemoryItem], list[ExtractedMemoryItem]]:
        kept: list[ExtractedMemoryItem] = []
        escalated: list[ExtractedMemoryItem] = []
        for item in items:
            if isinstance(item, ExtractedClaim) or _confidence(item) < self.confidence_threshold:
                escalated.append(item)
            else:
                kept.append(item)
        return kept, escalated

    @staticmethod
    def _spans_for_items(items: list[ExtractedMemoryItem]) -> list[str]:
        spans: list[str] = []
        seen: set[str] = set()
        for item in items:
            span = _item_text(item)
            if not span:
                continue
            normalized = _normalize(span)
            if normalized in seen:
                continue
            seen.add(normalized)
            spans.append(span)
        return spans

    @staticmethod
    def _escalation_prompt(
        *,
        document: Document,
        escalated_items: list[ExtractedMemoryItem],
        spans: list[str],
    ) -> str:
        return json.dumps(
            {
                "task": (
                    "Review only the provided spans. Emit typed Cortex memory items for low-confidence "
                    "heuristic outputs and claims. Use the known heuristic items as context, and do not "
                    "re-extract unrelated document content."
                ),
                "source_id": document.source_id,
                "source_type": document.source_type,
                "known_heuristic_items": [item.to_dict() for item in escalated_items],
                "spans": spans,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


class HybridBackend:
    """Hybrid backend implemented as a cost-aware router."""

    def __init__(
        self,
        *,
        fast_backend: Any | None = None,
        rescore_backend: Any | None = None,
        rescore_workers: int | None = None,
    ) -> None:
        self.fast_backend = fast_backend or HeuristicBackend()
        self.rescore_backend = rescore_backend or ModelBackend()
        self.rescore_workers = rescore_workers
        self.router = CostAwareRouter(
            heuristic_backend=self.fast_backend,
            model_backend=self.rescore_backend,
        )
        self._closed = False

    def run(self, document: Document, context: PipelineExtractionContext) -> PipelineExtractionResult:
        return self.router.run(document, context)

    def extract_statement(
        self,
        text: str,
        context: dict | None = None,
    ) -> BackendExtractionResult:
        document = _document_from_legacy_text(text, context)
        pipeline_context = _pipeline_context_from_legacy(context)
        result = self.run(document, pipeline_context)
        return _legacy_result_from_items(
            list(result.items),
            raw_source=text,
            diagnostics=result.diagnostics,
        )

    def extract_bulk(
        self,
        texts: list[str],
        context: dict | None = None,
    ) -> list[BackendExtractionResult]:
        return [self.extract_statement(text, context=context) for text in texts]

    def canonical_match(
        self,
        node: ExtractedNode,
        existing_nodes: list[dict],
    ) -> tuple[str | None, float]:
        if hasattr(self.rescore_backend, "canonical_match"):
            return self.rescore_backend.canonical_match(node, existing_nodes)
        return None, 0.0

    @property
    def supports_async_rescoring(self) -> bool:
        return False

    @property
    def supports_embeddings(self) -> bool:
        return bool(getattr(self.rescore_backend, "supports_embeddings", False))

    def close(self) -> None:
        self._closed = True
        close = getattr(self.rescore_backend, "close", None)
        if callable(close):
            close()

    def _handle_sigterm(self, signum: int, frame: Any) -> None:
        LOGGER.info("cost-aware hybrid backend received signal %s; closing", signum)
        self.close()


__all__ = ["CostAwareRouter", "HybridBackend"]
