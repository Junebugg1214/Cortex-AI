from __future__ import annotations

import os
from time import perf_counter
from typing import Any

from .pipeline import (
    Document,
    ExtractionPipeline,
    empty_result,
    legacy_context_from_pipeline_context,
    result_from_backend_result,
)
from .pipeline import (
    ExtractionContext as PipelineExtractionContext,
)
from .pipeline import (
    ExtractionResult as PipelineExtractionResult,
)
from .types import ExtractedNode, ExtractionResult

EMBEDDING_BACKEND_DISABLED_MESSAGE = (
    "EmbeddingBackend requires optional embedding dependencies. Install with "
    "`pip install cortex-identity[fast,embeddings]` or set "
    "CORTEX_HOT_PATH_BACKEND=heuristic or model."
)


class EmbeddingBackend(ExtractionPipeline):
    """SentenceTransformer-backed embedding backend with a flat NumPy index."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise NotImplementedError(EMBEDDING_BACKEND_DISABLED_MESSAGE) from exc

        self._np = np
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.match_threshold = self._load_match_threshold()
        self._index_ids: list[str] = []
        self._index_labels: list[str] = []
        self._index_records: list[Any] = []
        self._index_embeddings = None

    @staticmethod
    def _load_match_threshold() -> float:
        raw = os.environ.get("CORTEX_EMBEDDING_MATCH_THRESHOLD", "").strip()
        if not raw:
            return 0.92
        try:
            return float(raw)
        except ValueError:
            return 0.92

    def _encode_many(self, texts: list[str]):
        vectors = self.model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        matrix = self._np.asarray(vectors, dtype="float32")
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        return matrix

    def _normalize(self, matrix):
        normalized = self._np.asarray(matrix, dtype="float32")
        if normalized.ndim == 1:
            normalized = normalized.reshape(1, -1)
        norms = self._np.linalg.norm(normalized, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return normalized / norms

    @staticmethod
    def _record_id(record: Any, fallback: int) -> str:
        if isinstance(record, ExtractedNode):
            return record.canonical_match or record.label or str(fallback)
        if isinstance(record, dict):
            return str(record.get("id") or record.get("node_id") or record.get("label") or fallback)
        return str(fallback)

    @staticmethod
    def _record_label(record: Any) -> str:
        if isinstance(record, ExtractedNode):
            return record.label
        if isinstance(record, dict):
            return str(record.get("label") or record.get("topic") or record.get("text") or record.get("value") or "")
        return str(record)

    def embed(self, text: str) -> list[float]:
        """Encode text into a normalized SentenceTransformer representation."""

        return [float(value) for value in self._encode_many([text or ""])[0].tolist()]

    def build_index(self, nodes: list[Any]) -> None:
        """Build a flat in-memory NumPy index over node labels."""

        self._index_records = list(nodes)
        self._index_ids = [self._record_id(node, index) for index, node in enumerate(nodes)]
        self._index_labels = [self._record_label(node) for node in nodes]
        self._index_embeddings = self._encode_many(self._index_labels) if self._index_labels else None

    def search(self, query: str, top_k: int = 5, threshold: float = 0.0) -> list[dict[str, Any]]:
        """Return top indexed nodes by cosine similarity to the query."""

        if self._index_embeddings is None or not self._index_ids:
            raise ValueError("Embedding index is empty; call build_index(nodes) before search().")

        query_vector = self._encode_many([query or ""])[0]
        scores = self._index_embeddings @ query_vector
        order = self._np.argsort(-scores)
        results: list[dict[str, Any]] = []
        for raw_index in order[: max(top_k, 0)]:
            index = int(raw_index)
            score = float(scores[index])
            if score < threshold:
                continue
            results.append(
                {
                    "id": self._index_ids[index],
                    "label": self._index_labels[index],
                    "score": score,
                    "node": self._index_records[index],
                }
            )
        return results

    def search_nodes(
        self,
        query: str,
        nodes: list[Any],
        top_k: int = 5,
        threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Build a temporary flat index and search it."""

        self.build_index(nodes)
        return self.search(query, top_k=top_k, threshold=threshold)

    def canonical_match_by_similarity(
        self,
        embedding: list[float],
        existing_embeddings: list[tuple[str, list[float]]],
        threshold: float = 0.92,
    ) -> tuple[str | None, float]:
        """Resolve canonical matches via cosine similarity."""

        if not embedding or not existing_embeddings:
            return None, 0.0

        query = self._normalize(self._np.asarray(embedding, dtype="float32"))
        ids: list[str] = []
        vectors: list[list[float]] = []
        for existing_id, vector in existing_embeddings:
            if len(vector) != len(embedding):
                continue
            ids.append(existing_id)
            vectors.append(vector)
        if not vectors:
            return None, 0.0

        matrix = self._normalize(self._np.asarray(vectors, dtype="float32"))
        scores = matrix @ query[0]
        best_index = int(self._np.argmax(scores))
        score = float(scores[best_index])
        return (ids[best_index], score) if score >= threshold else (None, score)

    def extract_statement(self, text: str, context: dict | None = None) -> ExtractionResult:
        """Emit one embedding-bearing node for a statement."""

        label = (text or "").strip()
        if not label:
            return ExtractionResult(extraction_method="embedding", raw_source=text or "")

        return ExtractionResult(
            nodes=[
                ExtractedNode(
                    label=label,
                    category="mentions",
                    value=label,
                    confidence=0.65,
                    embedding=self.embed(label),
                )
            ],
            extraction_method="embedding",
            raw_source=text,
        )

    def run(self, document: Document, context: PipelineExtractionContext) -> PipelineExtractionResult:
        """Run embedding extraction through the unified pipeline contract."""

        started = perf_counter()
        if not document.content.strip():
            return empty_result(document, started_at=started)
        result = self.extract_statement(
            document.content,
            context=legacy_context_from_pipeline_context(context),
        )
        return result_from_backend_result(result, document=document, context=context, started_at=started)

    def extract_bulk(self, texts: list[str], context: dict | None = None) -> list[ExtractionResult]:
        """Extract embedding-bearing nodes from many statements."""

        return [self.extract_statement(text, context=context) for text in texts]

    def canonical_match(
        self,
        node: ExtractedNode,
        existing_nodes: list[dict],
    ) -> tuple[str | None, float]:
        """Resolve a candidate node to an existing canonical node id."""

        candidate = node.embedding or self.embed(node.label)
        existing_embeddings: list[tuple[str, list[float]]] = []
        pending_ids: list[str] = []
        pending_labels: list[str] = []

        for index, existing in enumerate(existing_nodes):
            node_id = self._record_id(existing, index)
            embedding = existing.get("embedding") if isinstance(existing, dict) else None
            if embedding:
                existing_embeddings.append((node_id, [float(value) for value in embedding]))
                continue
            pending_ids.append(node_id)
            pending_labels.append(self._record_label(existing))

        if pending_labels:
            for node_id, vector in zip(pending_ids, self._encode_many(pending_labels), strict=True):
                existing_embeddings.append((node_id, [float(value) for value in vector.tolist()]))

        return self.canonical_match_by_similarity(candidate, existing_embeddings, threshold=self.match_threshold)

    @property
    def supports_async_rescoring(self) -> bool:
        """Return true because embedding search is suitable for async rescoring."""

        return True

    @property
    def supports_embeddings(self) -> bool:
        """Return true because this backend emits embeddings."""

        return True
