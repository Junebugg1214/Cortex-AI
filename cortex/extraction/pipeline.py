from __future__ import annotations

from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Any, Literal, Protocol, runtime_checkable

from cortex.graph import CortexGraph

from .diagnostics import ExtractionDiagnostics
from .extract_memory_context import ExtractedClaim, ExtractedFact, ExtractedMemoryItem, ExtractedRelationship
from .types import ExtractedEdge, ExtractedNode
from .types import ExtractionResult as BackendExtractionResult

SourceType = Literal["chat", "doc", "code", "transcript"]


@dataclass
class Document:
    """Source document submitted to the extraction pipeline."""

    source_id: str
    source_type: SourceType
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionBudget:
    """Resource budget for one pipeline run."""

    max_tokens: int = 0
    max_latency_ms: int = 0
    max_cost_usd: float = 0.0


class CanonicalResolver(Protocol):
    """Resolver used by extraction pipelines to connect items to existing graph nodes."""

    def resolve(
        self,
        item: ExtractedMemoryItem,
        existing_graph: CortexGraph | None = None,
    ) -> ExtractedMemoryItem:
        """Return the canonicalized item."""


class NoopCanonicalResolver:
    """Default resolver that leaves extracted items unchanged."""

    def resolve(
        self,
        item: ExtractedMemoryItem,
        existing_graph: CortexGraph | None = None,
    ) -> ExtractedMemoryItem:
        return item


@dataclass
class ExtractionContext:
    """Context and constraints for a single extraction pipeline run."""

    existing_graph: CortexGraph | None = None
    budget: ExtractionBudget = field(default_factory=ExtractionBudget)
    prompt_version: str = ""
    canonical_resolver: CanonicalResolver = field(default_factory=NoopCanonicalResolver)


@dataclass
class ExtractionResult:
    """Schema-constrained extraction output returned by the pipeline contract."""

    items: list[ExtractedMemoryItem] = field(default_factory=list)
    diagnostics: ExtractionDiagnostics = field(default_factory=ExtractionDiagnostics)


@runtime_checkable
class ExtractionPipeline(Protocol):
    """Single extraction pipeline contract used by all extraction backends."""

    def run(self, document: Document, context: ExtractionContext) -> ExtractionResult:
        """Extract typed memory items from one document."""


def _estimate_tokens(text: str) -> int:
    """Cheap token estimate used until model providers return exact usage."""

    return len((text or "").split())


def _item_text(item: ExtractedMemoryItem) -> str:
    return " ".join(
        part
        for part in (
            item.topic,
            item.brief,
            item.full_description,
        )
        if part
    )


def _node_flags(node: ExtractedNode) -> list[str]:
    flags: list[str] = []
    if node.needs_review:
        flags.append("needs_review")
    return flags


def _edge_flags(edge: ExtractedEdge) -> list[str]:
    flags: list[str] = []
    if edge.needs_review:
        flags.append("needs_review")
    return flags


def _source_quotes(raw_source: str) -> list[str]:
    source = raw_source.strip()
    return [source] if source else []


def _item_from_node(node: ExtractedNode, backend_result: BackendExtractionResult) -> ExtractedMemoryItem:
    brief = node.value or node.label
    kwargs = {
        "topic": node.label,
        "category": node.category or "mentions",
        "brief": brief,
        "full_description": node.value if node.value != node.label else "",
        "confidence": node.confidence,
        "extraction_method": backend_result.extraction_method,
        "source_quotes": _source_quotes(backend_result.raw_source),
        "source_span": backend_result.raw_source[:240],
        "extraction_confidence": node.match_confidence if node.match_confidence is not None else node.confidence,
        "entity_resolution": node.canonical_match or "",
        "extraction_flags": _node_flags(node),
    }
    if node.category in {"negations", "correction_history"}:
        stance = "denies" if node.category == "negations" else "corrects"
        return ExtractedClaim(assertion=brief, stance=stance, **kwargs)
    return ExtractedFact(attribute_name=node.category or "mentions", attribute_value=node.label, **kwargs)


def _item_from_edge(edge: ExtractedEdge, backend_result: BackendExtractionResult) -> ExtractedRelationship:
    topic = f"{edge.source} {edge.relationship or 'related_to'} {edge.target}".strip()
    return ExtractedRelationship(
        topic=topic,
        category="relationships",
        brief=topic,
        full_description=topic,
        confidence=edge.direction_confidence,
        extraction_method=backend_result.extraction_method,
        source_quotes=_source_quotes(backend_result.raw_source),
        source_span=backend_result.raw_source[:240],
        relationship_type=edge.relationship or "related_to",
        extraction_confidence=edge.direction_confidence,
        extraction_flags=_edge_flags(edge),
        source_label=edge.source,
        relation=edge.relationship or "related_to",
        target_label=edge.target,
        qualifiers={"direction_confidence": f"{edge.direction_confidence:.3f}"},
    )


def items_from_backend_result(backend_result: BackendExtractionResult) -> list[ExtractedMemoryItem]:
    """Translate legacy backend node/edge output into typed memory items."""

    typed_items = getattr(backend_result, "_typed_items", None)
    if typed_items is not None:
        return [item for item in typed_items if isinstance(item, ExtractedMemoryItem)]

    items: list[ExtractedMemoryItem] = []
    items.extend(_item_from_node(node, backend_result) for node in backend_result.nodes)
    items.extend(_item_from_edge(edge, backend_result) for edge in backend_result.edges)
    return items


def empty_result(document: Document, *, started_at: float | None = None) -> ExtractionResult:
    """Return an empty pipeline result with diagnostics for the given document."""

    latency_ms = ((perf_counter() - started_at) * 1000.0) if started_at is not None else 0.0
    return ExtractionResult(
        diagnostics=ExtractionDiagnostics(
            tokens_in=_estimate_tokens(document.content),
            latency_ms=latency_ms,
            stage_timings={"extract": latency_ms},
        )
    )


def result_from_backend_result(
    backend_result: BackendExtractionResult,
    *,
    document: Document,
    context: ExtractionContext,
    started_at: float,
) -> ExtractionResult:
    """Build a pipeline result and diagnostics from a legacy backend result."""

    items = [
        context.canonical_resolver.resolve(item, context.existing_graph)
        for item in items_from_backend_result(backend_result)
    ]
    latency_ms = (perf_counter() - started_at) * 1000.0
    backend_diagnostics = getattr(backend_result, "_diagnostics", None)
    if isinstance(backend_diagnostics, ExtractionDiagnostics):
        stage_timings = dict(backend_diagnostics.stage_timings)
        stage_timings["extract"] = latency_ms
        diagnostics = replace(
            backend_diagnostics,
            latency_ms=latency_ms,
            stage_timings=stage_timings,
            warnings=list(backend_result.warnings),
            prompt_version=backend_diagnostics.prompt_version or context.prompt_version,
        )
        return ExtractionResult(items=items, diagnostics=diagnostics)
    return ExtractionResult(
        items=items,
        diagnostics=ExtractionDiagnostics(
            tokens_in=_estimate_tokens(document.content),
            tokens_out=sum(_estimate_tokens(_item_text(item)) for item in items),
            latency_ms=latency_ms,
            cost_usd=0.0,
            stage_timings={"extract": latency_ms},
            prompt_version=context.prompt_version,
            warnings=list(backend_result.warnings),
        ),
    )


def legacy_context_from_pipeline_context(context: ExtractionContext) -> dict[str, Any]:
    """Expose the new context to compatibility extraction methods."""

    legacy_context: dict[str, Any] = {
        "budget": context.budget,
        "prompt_version": context.prompt_version,
        "canonical_resolver": context.canonical_resolver,
    }
    if context.existing_graph is not None:
        legacy_context["graph"] = context.existing_graph
    return legacy_context
