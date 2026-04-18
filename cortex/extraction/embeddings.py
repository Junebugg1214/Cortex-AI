from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from typing import Any, Protocol

from cortex.search import semantic_search_documents

DEFAULT_EMBEDDING_PROVIDER = "disabled"


def _normalize_text(text: str) -> str:
    return " ".join(str(text).lower().strip().split())


def document_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    if payload.get("label"):
        parts.extend([str(payload["label"])] * 3)
    for alias in payload.get("aliases", []):
        if alias:
            parts.extend([str(alias)] * 2)
    if payload.get("brief"):
        parts.append(str(payload["brief"]))
    if payload.get("full_description"):
        parts.append(str(payload["full_description"]))
    for value in (payload.get("properties") or {}).values():
        if isinstance(value, str):
            parts.append(value)
    for tag in payload.get("tags", []):
        if tag:
            parts.append(str(tag))
    return " ".join(parts)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class EmbeddingProvider(Protocol):
    name: str
    enabled: bool

    def embed_text(self, text: str) -> list[float]: ...


@dataclass(slots=True)
class DisabledEmbeddingProvider:
    name: str = DEFAULT_EMBEDDING_PROVIDER
    enabled: bool = False

    def embed_text(self, text: str) -> list[float]:
        return []


@dataclass(slots=True)
class HashedEmbeddingProvider:
    dimensions: int = 96
    ngram_size: int = 3
    name: str = "hashed"
    enabled: bool = True

    def _ngrams(self, text: str) -> list[str]:
        normalized = _normalize_text(text)
        if not normalized:
            return []
        if len(normalized) <= self.ngram_size:
            return [normalized]
        return [normalized[idx : idx + self.ngram_size] for idx in range(len(normalized) - self.ngram_size + 1)]

    def _hash_value(self, raw: str) -> int:
        return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16], 16)

    def embed_text(self, text: str) -> list[float]:
        ngrams = self._ngrams(text)
        if not ngrams:
            return [0.0] * self.dimensions
        values = [0.0] * self.dimensions
        for ngram in ngrams:
            bucket = self._hash_value(ngram) % self.dimensions
            sign = -1.0 if self._hash_value(f"sign:{ngram}") % 2 else 1.0
            values[bucket] += sign
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0.0:
            return values
        return [round(value / norm, 6) for value in values]


def get_embedding_provider(provider_name: str | None = None) -> EmbeddingProvider:
    raw = (provider_name or os.getenv("CORTEX_EMBEDDING_PROVIDER") or DEFAULT_EMBEDDING_PROVIDER).strip().lower()
    if raw in {"", "disabled", "off", "none"}:
        return DisabledEmbeddingProvider()
    if raw in {"hashed", "local"}:
        return HashedEmbeddingProvider()
    raise ValueError(f"Unknown embedding provider: {provider_name or raw}")


def build_document_embeddings(
    documents: list[dict[str, Any]],
    provider: EmbeddingProvider,
) -> dict[str, list[float]]:
    if not provider.enabled:
        return {}
    embeddings: dict[str, list[float]] = {}
    for payload in documents:
        doc_id = str(payload.get("id", "")).strip()
        if not doc_id:
            continue
        embeddings[doc_id] = provider.embed_text(document_text(payload))
    return embeddings


def vector_search_documents(
    documents: list[dict[str, Any]],
    query: str,
    *,
    provider: EmbeddingProvider,
    limit: int = 10,
    min_score: float = 0.0,
    document_embeddings: dict[str, list[float]] | None = None,
) -> list[dict[str, Any]]:
    if not provider.enabled or not query:
        return []
    query_vector = provider.embed_text(query)
    if not any(query_vector):
        return []
    embeddings = document_embeddings or build_document_embeddings(documents, provider)
    payload_by_id = {str(item.get("id", "")): item for item in documents}
    scored: list[tuple[str, float]] = []
    for doc_id, vector in embeddings.items():
        score = round(_cosine_similarity(query_vector, vector), 4)
        if score >= min_score:
            scored.append((doc_id, score))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return [
        {"node": payload_by_id[doc_id], "score": score} for doc_id, score in scored[:limit] if doc_id in payload_by_id
    ]


def hybrid_search_documents(
    documents: list[dict[str, Any]],
    query: str,
    *,
    limit: int = 10,
    min_score: float = 0.0,
    lexical_index: Any | None = None,
    provider: EmbeddingProvider | None = None,
    document_embeddings: dict[str, list[float]] | None = None,
    lexical_weight: float = 0.8,
    embedding_weight: float = 0.2,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lexical_results = semantic_search_documents(
        documents,
        query,
        limit=max(limit * 3, 10),
        min_score=min_score,
        index=lexical_index,
    )
    embedding_provider = provider or DisabledEmbeddingProvider()
    embedding_results = vector_search_documents(
        documents,
        query,
        provider=embedding_provider,
        limit=max(limit * 3, 10),
        min_score=min_score,
        document_embeddings=document_embeddings,
    )

    payload_by_id = {str(item.get("id", "")): item for item in documents}
    combined: dict[str, float] = {}
    sources: dict[str, set[str]] = {}

    for item in lexical_results:
        payload = item["node"]
        doc_id = str(payload.get("id", "")).strip()
        if not doc_id:
            continue
        combined[doc_id] = combined.get(doc_id, 0.0) + float(item["score"]) * lexical_weight
        sources.setdefault(doc_id, set()).add("lexical")

    for item in embedding_results:
        payload = item["node"]
        doc_id = str(payload.get("id", "")).strip()
        if not doc_id:
            continue
        combined[doc_id] = max(combined.get(doc_id, 0.0), float(item["score"]) * embedding_weight)
        sources.setdefault(doc_id, set()).add("embedding")

    ranked = sorted(combined.items(), key=lambda item: (-item[1], item[0]))
    results = [
        {
            "node": payload_by_id[doc_id],
            "score": round(score, 4),
            "sources": sorted(sources.get(doc_id, set())),
        }
        for doc_id, score in ranked[:limit]
        if doc_id in payload_by_id
    ]
    return results, {
        "embedding_enabled": embedding_provider.enabled,
        "embedding_provider": embedding_provider.name,
        "lexical_results": len(lexical_results),
        "embedding_results": len(embedding_results),
        "hybrid": embedding_provider.enabled,
    }


__all__ = [
    "DEFAULT_EMBEDDING_PROVIDER",
    "DisabledEmbeddingProvider",
    "EmbeddingProvider",
    "HashedEmbeddingProvider",
    "build_document_embeddings",
    "document_text",
    "get_embedding_provider",
    "hybrid_search_documents",
    "vector_search_documents",
]
