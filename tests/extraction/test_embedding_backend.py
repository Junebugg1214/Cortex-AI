from __future__ import annotations

import sys
from types import ModuleType

import pytest

np = pytest.importorskip("numpy")


@pytest.fixture(autouse=True)
def stub_sentence_transformer(monkeypatch) -> None:
    class OfflineSentenceTransformer:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name

        def encode(
            self,
            texts: list[str],
            *,
            convert_to_numpy: bool = True,
            normalize_embeddings: bool = True,
            show_progress_bar: bool = False,
        ):
            vectors = np.asarray([_offline_embedding(text) for text in texts], dtype="float32")
            if normalize_embeddings:
                norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                norms[norms == 0.0] = 1.0
                vectors = vectors / norms
            return vectors if convert_to_numpy else vectors.tolist()

    module = ModuleType("sentence_transformers")
    module.SentenceTransformer = OfflineSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)


def _offline_embedding(text: str) -> list[float]:
    normalized = text.lower()
    return [
        float(any(term in normalized for term in ("semantic", "vector", "embedding", "retrieval", "search", "text"))),
        float(any(term in normalized for term in ("bread", "sourdough", "starter", "baking"))),
        float(any(term in normalized for term in ("cash", "invoice", "finance", "reconciliation"))),
    ]


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
