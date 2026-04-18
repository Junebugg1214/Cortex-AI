from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from cortex.extraction.diagnostics import ExtractionDiagnostics
from cortex.extraction.extract_memory_context import ExtractedMemoryItem
from cortex.extraction.pipeline import Document, ExtractionContext
from cortex.extraction.retrieval import NodeHint


@dataclass(frozen=True)
class DocumentChunk:
    """A source-aware unit of text submitted to model extraction."""

    chunk_id: str
    text: str
    source_type: str
    source_span: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineState:
    """Immutable state passed between extraction stages."""

    document: Document
    context: ExtractionContext
    chunks: tuple[DocumentChunk, ...] = ()
    items: tuple[ExtractedMemoryItem, ...] = ()
    diagnostics: ExtractionDiagnostics = field(default_factory=ExtractionDiagnostics)
    retrieval_hints: dict[str, tuple[NodeHint, ...]] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_timing(self, stage_name: str, duration_ms: float) -> PipelineState:
        """Return a state with stage timing accumulated."""

        stage_timings = dict(self.diagnostics.stage_timings)
        stage_timings[stage_name] = stage_timings.get(stage_name, 0.0) + duration_ms
        return replace(self, diagnostics=replace(self.diagnostics, stage_timings=stage_timings))

    def with_warnings(self, warnings: list[str] | tuple[str, ...]) -> PipelineState:
        """Return a state with de-duplicated warnings appended in order."""

        merged = list(self.warnings)
        for warning in warnings:
            if warning and warning not in merged:
                merged.append(warning)
        return replace(
            self,
            warnings=tuple(merged),
            diagnostics=replace(self.diagnostics, warnings=merged),
        )
