from __future__ import annotations

import importlib.util

import pytest

from cortex.extraction import EMBEDDING_BACKEND_DISABLED_MESSAGE
from cortex.extraction.registry import get_backend, get_bulk_backend, get_hot_path_backend

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("sentence_transformers") is not None,
    reason="disabled-backend assertions only apply when the optional embeddings extra is absent",
)


def _assert_disabled(excinfo) -> None:
    assert isinstance(excinfo.value, NotImplementedError)
    assert str(excinfo.value) == EMBEDDING_BACKEND_DISABLED_MESSAGE
    assert "cortex-identity[fast,embeddings]" in str(excinfo.value)


def test_get_backend_embedding_fails_at_construction():
    with pytest.raises(NotImplementedError) as excinfo:
        get_backend("embedding")
    _assert_disabled(excinfo)


def test_hot_path_embedding_env_fails_at_startup(monkeypatch):
    monkeypatch.setenv("CORTEX_HOT_PATH_BACKEND", "embedding")

    with pytest.raises(NotImplementedError) as excinfo:
        get_hot_path_backend()

    _assert_disabled(excinfo)


def test_hot_path_embedding_config_fails_at_startup(monkeypatch):
    monkeypatch.delenv("CORTEX_HOT_PATH_BACKEND", raising=False)
    monkeypatch.setattr("cortex.extraction.registry.load_extraction_config", lambda: {"hot_path_backend": "embedding"})

    with pytest.raises(NotImplementedError) as excinfo:
        get_hot_path_backend()

    _assert_disabled(excinfo)


def test_bulk_embedding_env_fails_at_startup(monkeypatch):
    monkeypatch.setenv("CORTEX_BULK_BACKEND", "embedding")

    with pytest.raises(NotImplementedError) as excinfo:
        get_bulk_backend()

    _assert_disabled(excinfo)


def test_bulk_embedding_config_fails_at_startup(monkeypatch):
    monkeypatch.delenv("CORTEX_BULK_BACKEND", raising=False)
    monkeypatch.setattr("cortex.extraction.registry.load_extraction_config", lambda: {"bulk_backend": "embedding"})

    with pytest.raises(NotImplementedError) as excinfo:
        get_bulk_backend()

    _assert_disabled(excinfo)
