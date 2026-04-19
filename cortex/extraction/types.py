from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ExtractedNode:
    """Structured node emitted by an extraction backend."""

    label: str
    category: str
    value: str
    confidence: float
    canonical_match: str | None = None
    match_confidence: float | None = None
    needs_review: bool = False
    embedding: list[float] | None = None


@dataclass
class ExtractedEdge:
    """Structured edge emitted by an extraction backend."""

    source: str
    target: str
    relationship: str
    direction_confidence: float
    needs_review: bool = False


@dataclass
class ExtractionResult:
    """Normalized extraction payload returned by any backend."""

    nodes: list[ExtractedNode] = field(default_factory=list)
    edges: list[ExtractedEdge] = field(default_factory=list)
    extraction_method: Literal["heuristic", "model", "hybrid", "embedding"] = "heuristic"
    raw_source: str = ""
    warnings: list[str] = field(default_factory=list)
    rescore_pending: bool = False


BackendExtractionResult = ExtractionResult
LegacyExtractionResult = ExtractionResult
