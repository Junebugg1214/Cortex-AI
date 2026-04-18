from __future__ import annotations

import pytest

pytest.importorskip("sentence_transformers")


def test_embedding_backend_retrieves_semantically_similar_nodes() -> None:
    from cortex.extraction.embedding_backend import EmbeddingBackend

    backend = EmbeddingBackend()
    backend.build_index(
        [
            {"id": "semantic-search", "label": "vector embeddings for semantic search and retrieval"},
            {"id": "bread", "label": "sourdough bread starter and baking schedule"},
            {"id": "finance", "label": "quarterly cash flow and invoice reconciliation"},
        ]
    )

    results = backend.search("find related text using embedding similarity", top_k=2, threshold=0.35)

    assert results
    assert results[0]["id"] == "semantic-search"
    assert results[0]["score"] >= 0.35


def test_embedding_backend_canonical_match_uses_cosine_threshold() -> None:
    from cortex.extraction.embedding_backend import EmbeddingBackend

    backend = EmbeddingBackend()
    query = backend.embed("semantic vector search over text")
    candidates = [
        ("bread", backend.embed("sourdough bread starter and baking schedule")),
        ("semantic-search", backend.embed("embedding based semantic retrieval for documents")),
    ]

    match_id, score = backend.canonical_match_by_similarity(query, candidates, threshold=0.35)

    assert match_id == "semantic-search"
    assert score >= 0.35
