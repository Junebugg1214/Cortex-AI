"""Extraction backends and typed extraction results."""

from __future__ import annotations

from importlib import import_module as _import_module
from typing import Any

_LAZY_ATTRS = {
    "BACKENDS": "cortex.extraction.registry",
    "BulkTextCollector": "cortex.extraction.backend",
    "EMBEDDING_BACKEND_DISABLED_MESSAGE": "cortex.extraction.embedding_backend",
    "EmbeddingBackend": "cortex.extraction.embedding_backend",
    "CanonicalResolver": "cortex.extraction.pipeline",
    "Document": "cortex.extraction.pipeline",
    "ExtractedEdge": "cortex.extraction.types",
    "ExtractedMemoryItem": "cortex.extraction.extract_memory_context",
    "ExtractedTopic": "cortex.extraction.extract_memory_context",
    "ExtractedFact": "cortex.extraction.extract_memory_context",
    "ExtractedClaim": "cortex.extraction.extract_memory_context",
    "ExtractedRelationship": "cortex.extraction.extract_memory_context",
    "ExtractedNode": "cortex.extraction.types",
    "ExtractionBackend": "cortex.extraction.backend",
    "ExtractionBackendError": "cortex.extraction.backend",
    "ExtractionBudget": "cortex.extraction.pipeline",
    "ExtractionContext": "cortex.extraction.pipeline",
    "ExtractionDiagnostics": "cortex.extraction.pipeline",
    "ExtractionParseError": "cortex.extraction.backend",
    "ExtractionPipeline": "cortex.extraction.pipeline",
    "ExtractionResult": "cortex.extraction.types",
    "HeuristicBackend": "cortex.extraction.heuristic_backend",
    "HeuristicRuleExtractor": "cortex.extraction.heuristic_rules",
    "HybridBackend": "cortex.extraction.hybrid_backend",
    "ModelBackend": "cortex.extraction.model_backend",
    "collect_bulk_texts": "cortex.extraction.backend",
    "get_backend": "cortex.extraction.registry",
    "get_bulk_backend": "cortex.extraction.registry",
    "get_hot_path_backend": "cortex.extraction.registry",
    "graph_from_result": "cortex.extraction.heuristic_backend",
    "load_extraction_config": "cortex.extraction.backend",
    "merged_graph_from_results": "cortex.extraction.heuristic_backend",
    "merged_v4_from_results": "cortex.extraction.heuristic_backend",
    "result_from_graph": "cortex.extraction.heuristic_backend",
    "v4_from_result": "cortex.extraction.heuristic_backend",
}

__all__ = sorted(_LAZY_ATTRS)


def __getattr__(name: str) -> Any:
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'cortex.extraction' has no attribute {name!r}")
    module = _import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
