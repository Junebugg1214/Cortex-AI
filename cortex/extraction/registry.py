from __future__ import annotations

import importlib.util
import os

from .backend import ExtractionBackend, ExtractionBackendError, load_extraction_config
from .embedding_backend import EmbeddingBackend
from .heuristic_backend import HeuristicBackend
from .hybrid_backend import HybridBackend
from .model_backend import ModelBackend

BACKENDS = {
    "heuristic": HeuristicBackend,
    "model": ModelBackend,
    "hybrid": HybridBackend,
    "embedding": EmbeddingBackend,
}


def _api_key_present() -> bool:
    if os.environ.get("CORTEX_ANTHROPIC_API_KEY", "").strip():
        return True
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return True
    config = load_extraction_config()
    return bool(str(config.get("anthropic_api_key", "")).strip())


def _model_backend_available() -> bool:
    """Return true when the Anthropic client dependency is installed."""

    return importlib.util.find_spec("anthropic") is not None


def _guard_embedding(name: str) -> None:
    if name == "embedding":
        raise ExtractionBackendError(
            "EmbeddingBackend is not yet implemented. See\n"
            "cortex/extraction/embedding_backend.py."
        )


def get_backend(name: str) -> ExtractionBackend:
    """Instantiate one named extraction backend."""

    normalized = str(name or "").strip().lower()
    backend_cls = BACKENDS.get(normalized)
    if backend_cls is None:
        valid = ", ".join(sorted(BACKENDS))
        raise ExtractionBackendError(
            f"Unknown extraction backend '{name}'. Valid backends: {valid}."
        )
    return backend_cls()


def get_hot_path_backend() -> ExtractionBackend:
    """Return the configured backend for interactive remember flows."""

    name = os.environ.get("CORTEX_HOT_PATH_BACKEND", "").strip().lower()
    if not name:
        config = load_extraction_config()
        name = str(config.get("hot_path_backend", "")).strip().lower() or "heuristic"
    _guard_embedding(name)
    return get_backend(name)


def get_bulk_backend() -> ExtractionBackend:
    """Return the configured backend for bulk extraction flows."""

    name = os.environ.get("CORTEX_BULK_BACKEND", "").strip().lower()
    if not name:
        config = load_extraction_config()
        name = str(config.get("bulk_backend", "")).strip().lower()
    if not name:
        name = "model" if _api_key_present() and _model_backend_available() else "heuristic"
    _guard_embedding(name)
    return get_backend(name)
