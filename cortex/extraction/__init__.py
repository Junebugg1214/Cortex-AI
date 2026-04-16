from __future__ import annotations

from .backend import (
    BulkTextCollector,
    ExtractionBackend,
    ExtractionBackendError,
    ExtractionParseError,
    collect_bulk_texts,
    load_extraction_config,
)
from .embedding_backend import EmbeddingBackend
from .heuristic_backend import (
    HeuristicBackend,
    graph_from_result,
    merged_graph_from_results,
    merged_v4_from_results,
    result_from_graph,
    v4_from_result,
)
from .hybrid_backend import HybridBackend
from .model_backend import ModelBackend
from .registry import BACKENDS, get_backend, get_bulk_backend, get_hot_path_backend
from .types import ExtractedEdge, ExtractedNode, ExtractionResult

__all__ = [
    "BACKENDS",
    "BulkTextCollector",
    "EmbeddingBackend",
    "ExtractedEdge",
    "ExtractedNode",
    "ExtractionBackend",
    "ExtractionBackendError",
    "ExtractionParseError",
    "ExtractionResult",
    "HeuristicBackend",
    "HybridBackend",
    "ModelBackend",
    "collect_bulk_texts",
    "get_backend",
    "get_bulk_backend",
    "get_hot_path_backend",
    "graph_from_result",
    "load_extraction_config",
    "merged_graph_from_results",
    "merged_v4_from_results",
    "result_from_graph",
    "v4_from_result",
]
