from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from time import perf_counter

from cortex.extraction.diagnostics import ExtractionDiagnostics
from cortex.extraction.extract_memory_context import ExtractedClaim, ExtractedFact, ExtractedMemoryItem

from .state import PipelineState


@dataclass(frozen=True)
class Refinement:
    """A refined item and optional diagnostics from a second-pass model call."""

    item: ExtractedMemoryItem
    diagnostics: ExtractionDiagnostics = field(default_factory=ExtractionDiagnostics)
    warnings: tuple[str, ...] = ()


TypeRefiner = Callable[[ExtractedMemoryItem], Refinement]


def _needs_type_refinement(item: ExtractedMemoryItem, *, threshold: float) -> bool:
    if not isinstance(item, (ExtractedFact, ExtractedClaim)):
        return False
    confidence = float(item.extraction_confidence or item.confidence)
    return confidence < threshold


def refine_types(
    state: PipelineState,
    *,
    refiner: TypeRefiner | None = None,
    threshold: float = 0.6,
) -> PipelineState:
    """Refine low-confidence fact/claim typing through an optional second pass."""

    started = perf_counter()
    if refiner is None:
        return state.with_timing("refine_types", (perf_counter() - started) * 1000.0)

    items: list[ExtractedMemoryItem] = []
    warnings = list(state.warnings)
    tokens_in = state.diagnostics.tokens_in
    tokens_out = state.diagnostics.tokens_out
    cost_usd = state.diagnostics.cost_usd
    cache_hit = state.diagnostics.cache_hit
    model = state.diagnostics.model
    request_ms = state.diagnostics.stage_timings.get("request", 0.0)

    for item in state.items:
        if not _needs_type_refinement(item, threshold=threshold):
            items.append(item)
            continue
        refinement = refiner(item)
        items.append(refinement.item)
        tokens_in += refinement.diagnostics.tokens_in
        tokens_out += refinement.diagnostics.tokens_out
        cost_usd += refinement.diagnostics.cost_usd
        cache_hit = cache_hit or refinement.diagnostics.cache_hit
        model = model or refinement.diagnostics.model
        request_ms += refinement.diagnostics.stage_timings.get("request", 0.0)
        for warning in (*refinement.warnings, *refinement.diagnostics.warnings):
            if warning and warning not in warnings:
                warnings.append(warning)

    stage_timings = dict(state.diagnostics.stage_timings)
    stage_timings["request"] = request_ms
    diagnostics = replace(
        state.diagnostics,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        model=model,
        warnings=warnings,
        cache_hit=cache_hit,
        stage_timings=stage_timings,
    )
    next_state = replace(state, items=tuple(items), diagnostics=diagnostics, warnings=tuple(warnings))
    return next_state.with_timing("refine_types", (perf_counter() - started) * 1000.0)
