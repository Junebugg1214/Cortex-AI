from __future__ import annotations

import pytest

from cortex.extraction import EmbeddingBackend, ExtractedNode


def test_embed_raises_not_implemented():
    backend = EmbeddingBackend()
    with pytest.raises(NotImplementedError) as excinfo:
        backend.embed("hello")
    assert "arXiv:2509.14252" in str(excinfo.value)


def test_extract_statement_raises_not_implemented():
    backend = EmbeddingBackend()
    with pytest.raises(NotImplementedError) as excinfo:
        backend.extract_statement("hello")
    assert "arXiv:2509.14252" in str(excinfo.value)


def test_extract_bulk_raises_not_implemented():
    backend = EmbeddingBackend()
    with pytest.raises(NotImplementedError):
        backend.extract_bulk(["hello"])


def test_canonical_match_raises_not_implemented():
    backend = EmbeddingBackend()
    with pytest.raises(NotImplementedError) as excinfo:
        backend.canonical_match(
            ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.9),
            [],
        )
    assert "arXiv:2509.14252" in str(excinfo.value)


def test_canonical_match_by_similarity_raises_not_implemented():
    backend = EmbeddingBackend()
    with pytest.raises(NotImplementedError):
        backend.canonical_match_by_similarity([0.1], [("n1", [0.1])])


def test_supports_embeddings_true():
    assert EmbeddingBackend().supports_embeddings is True


def test_supports_async_rescoring_true():
    assert EmbeddingBackend().supports_async_rescoring is True
