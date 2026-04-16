from __future__ import annotations

import pytest

from cortex.extraction import EmbeddingBackend, ExtractionBackendError, HeuristicBackend, HybridBackend, ModelBackend
from cortex.extraction.registry import get_backend, get_bulk_backend, get_hot_path_backend


def test_get_backend_returns_heuristic():
    assert isinstance(get_backend("heuristic"), HeuristicBackend)


def test_get_backend_returns_model():
    assert isinstance(get_backend("model"), ModelBackend)


def test_get_backend_returns_hybrid():
    assert isinstance(get_backend("hybrid"), HybridBackend)


def test_get_backend_returns_embedding():
    assert isinstance(get_backend("embedding"), EmbeddingBackend)


def test_unknown_backend_raises_with_valid_names():
    with pytest.raises(ExtractionBackendError) as excinfo:
        get_backend("unknown")
    assert "embedding, heuristic, hybrid, model" in str(excinfo.value)


def test_get_hot_path_backend_defaults_to_heuristic(monkeypatch):
    monkeypatch.delenv("CORTEX_HOT_PATH_BACKEND", raising=False)
    monkeypatch.setattr("cortex.extraction.registry.load_extraction_config", lambda: {})
    assert isinstance(get_hot_path_backend(), HeuristicBackend)


def test_get_bulk_backend_defaults_to_model_when_key_present(monkeypatch):
    monkeypatch.delenv("CORTEX_BULK_BACKEND", raising=False)
    monkeypatch.setenv("CORTEX_ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("cortex.extraction.registry.load_extraction_config", lambda: {})
    monkeypatch.setattr("cortex.extraction.registry._model_backend_available", lambda: True)
    assert isinstance(get_bulk_backend(), ModelBackend)


def test_get_bulk_backend_defaults_to_heuristic_without_key(monkeypatch):
    monkeypatch.delenv("CORTEX_BULK_BACKEND", raising=False)
    monkeypatch.delenv("CORTEX_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("cortex.extraction.registry.load_extraction_config", lambda: {})
    assert isinstance(get_bulk_backend(), HeuristicBackend)


def test_get_bulk_backend_defaults_to_heuristic_when_client_missing(monkeypatch):
    monkeypatch.delenv("CORTEX_BULK_BACKEND", raising=False)
    monkeypatch.setenv("CORTEX_ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("cortex.extraction.registry.load_extraction_config", lambda: {})
    monkeypatch.setattr("cortex.extraction.registry._model_backend_available", lambda: False)
    assert isinstance(get_bulk_backend(), HeuristicBackend)


def test_hot_path_env_override_wins(monkeypatch):
    monkeypatch.setenv("CORTEX_HOT_PATH_BACKEND", "model")
    assert isinstance(get_hot_path_backend(), ModelBackend)


def test_bulk_env_override_wins(monkeypatch):
    monkeypatch.setenv("CORTEX_BULK_BACKEND", "heuristic")
    assert isinstance(get_bulk_backend(), HeuristicBackend)


def test_hot_path_config_is_used_when_env_missing(monkeypatch):
    monkeypatch.delenv("CORTEX_HOT_PATH_BACKEND", raising=False)
    monkeypatch.setattr("cortex.extraction.registry.load_extraction_config", lambda: {"hot_path_backend": "model"})
    assert isinstance(get_hot_path_backend(), ModelBackend)


def test_bulk_config_is_used_when_env_missing(monkeypatch):
    monkeypatch.delenv("CORTEX_BULK_BACKEND", raising=False)
    monkeypatch.setattr("cortex.extraction.registry.load_extraction_config", lambda: {"bulk_backend": "heuristic"})
    assert isinstance(get_bulk_backend(), HeuristicBackend)


def test_embedding_hot_backend_raises(monkeypatch):
    monkeypatch.setenv("CORTEX_HOT_PATH_BACKEND", "embedding")
    with pytest.raises(ExtractionBackendError) as excinfo:
        get_hot_path_backend()
    assert "embedding_backend.py" in str(excinfo.value)


def test_embedding_bulk_backend_raises(monkeypatch):
    monkeypatch.setenv("CORTEX_BULK_BACKEND", "embedding")
    with pytest.raises(ExtractionBackendError) as excinfo:
        get_bulk_backend()
    assert "embedding_backend.py" in str(excinfo.value)
