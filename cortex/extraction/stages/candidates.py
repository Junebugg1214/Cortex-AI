from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from time import perf_counter

from cortex.extraction.diagnostics import ExtractionDiagnostics
from cortex.extraction.extract_memory_context import ExtractedMemoryItem
from cortex.extraction.prompts import load_prompt
from cortex.extraction.retrieval import NodeHint

from .state import DocumentChunk, PipelineState

CANDIDATES_PROMPT = load_prompt("candidates", "v1")
PROMPT_REFERENCES = (CANDIDATES_PROMPT.reference,)


@dataclass(frozen=True)
class CandidateBatch:
    """Typed candidate items and observability from one model chunk call."""

    items: tuple[ExtractedMemoryItem, ...] = ()
    diagnostics: ExtractionDiagnostics = field(default_factory=ExtractionDiagnostics)
    warnings: tuple[str, ...] = ()


CandidateExtractor = Callable[[DocumentChunk, Sequence[NodeHint]], CandidateBatch]
HintProvider = Callable[[DocumentChunk], Sequence[NodeHint]]


def _merge_diagnostics(
    current: ExtractionDiagnostics,
    batches: list[ExtractionDiagnostics],
    *,
    warnings: list[str],
) -> ExtractionDiagnostics:
    stage_timings = dict(current.stage_timings)
    stage_timings["request"] = stage_timings.get("request", 0.0) + sum(
        batch.stage_timings.get("request", 0.0) for batch in batches
    )
    model = current.model or next((batch.model for batch in batches if batch.model), "")
    prompt_version = current.prompt_version or next(
        (batch.prompt_version for batch in batches if batch.prompt_version), ""
    )
    return replace(
        current,
        tokens_in=sum(batch.tokens_in for batch in batches) or current.tokens_in,
        tokens_out=sum(batch.tokens_out for batch in batches),
        cost_usd=sum(batch.cost_usd for batch in batches),
        model=model,
        prompt_version=prompt_version,
        warnings=warnings,
        cache_hit=any(batch.cache_hit for batch in batches),
        stage_timings=stage_timings,
    )


def generate_candidates(
    state: PipelineState,
    *,
    extractor: CandidateExtractor,
    hint_provider: HintProvider | None = None,
) -> PipelineState:
    """Call the candidate extractor for each chunk and collect raw typed items."""

    started = perf_counter()
    items: list[ExtractedMemoryItem] = []
    warnings = list(state.warnings)
    diagnostics: list[ExtractionDiagnostics] = []
    retrieval_hints = dict(state.retrieval_hints)

    for chunk in state.chunks:
        hints = (
            tuple(hint_provider(chunk)) if hint_provider is not None else tuple(retrieval_hints.get(chunk.chunk_id, ()))
        )
        retrieval_hints[chunk.chunk_id] = hints
        batch = extractor(chunk, hints)
        items.extend(batch.items)
        diagnostics.append(batch.diagnostics)
        for warning in (*batch.warnings, *batch.diagnostics.warnings):
            if warning and warning not in warnings:
                warnings.append(warning)

    merged_diagnostics = _merge_diagnostics(state.diagnostics, diagnostics, warnings=warnings)
    next_state = replace(
        state,
        items=tuple(items),
        diagnostics=merged_diagnostics,
        retrieval_hints=retrieval_hints,
        warnings=tuple(warnings),
    )
    return next_state.with_timing("generate_candidates", (perf_counter() - started) * 1000.0)
