from __future__ import annotations

from .backend import ExtractionBackend
from .types import ExtractedNode, ExtractionResult

EMBEDDING_BACKEND_DISABLED_MESSAGE = (
    "EmbeddingBackend is a roadmap stub; set CORTEX_HOT_PATH_BACKEND=heuristic or model"
)


class EmbeddingBackend(ExtractionBackend):
    """EmbeddingBackend: JEPA-ready extraction backend stub.

    This backend is the architectural target for replacing both
    the heuristic AggressiveExtractor and the ModelBackend LLM
    calls with a representation-space model.

    Intended backbone: LLM-JEPA (arXiv:2509.14252) or a
    fine-tuned text encoder trained on Cortex graph data.

    Two capabilities this backend will provide when implemented:

    1. Semantic extraction in embedding space
       Instead of pattern-matching surface syntax or calling a
       generative LLM, extract_statement() will encode the input
       into a high-dimensional representation and decode graph
       structure from that space. Semantically equivalent inputs
       will produce similar representations regardless of surface
       wording — solving the deduplication and entity resolution
       failures in the current heuristic pipeline.

    2. Vector-similarity canonical matching
       canonical_match() will replace ModelBackend's LLM judgment
       call with cosine similarity between node.embedding and
       embeddings of existing graph nodes. Threshold configurable
       via CORTEX_EMBEDDING_MATCH_THRESHOLD (default: 0.92).
       This eliminates per-match API calls and makes deduplication
       consistent and fast.

    Current state: all methods raise NotImplementedError.
    The interface is complete and stable. Implement by replacing
    the NotImplementedError bodies — no interface changes needed.

    To activate once implemented:
      CORTEX_HOT_PATH_BACKEND=embedding
      CORTEX_BULK_BACKEND=embedding
    """

    def __init__(self) -> None:
        raise NotImplementedError(EMBEDDING_BACKEND_DISABLED_MESSAGE)

    def embed(self, text: str) -> list[float]:
        """Encode text into the model's representation space."""

        raise NotImplementedError(
            "EmbeddingBackend.embed() is not yet implemented. "
            "Intended backbone: LLM-JEPA (arXiv:2509.14252). "
            "See cortex/extraction/embedding_backend.py for design notes."
        )

    def canonical_match_by_similarity(
        self,
        embedding: list[float],
        existing_embeddings: list[tuple[str, list[float]]],
        threshold: float = 0.92,
    ) -> tuple[str | None, float]:
        """Resolve canonical matches via vector similarity once implemented."""

        raise NotImplementedError("EmbeddingBackend.canonical_match_by_similarity() is not yet implemented.")

    def extract_statement(self, text: str, context: dict | None = None) -> ExtractionResult:
        """Extract graph facts from one statement once the embedding model exists."""

        raise NotImplementedError(
            "EmbeddingBackend.extract_statement() is not yet implemented. "
            "Intended backbone: LLM-JEPA (arXiv:2509.14252). "
            "See cortex/extraction/embedding_backend.py for design notes."
        )

    def extract_bulk(self, texts: list[str], context: dict | None = None) -> list[ExtractionResult]:
        """Extract graph facts from many statements once the embedding model exists."""

        raise NotImplementedError(
            "EmbeddingBackend.extract_bulk() is not yet implemented. "
            "Intended backbone: LLM-JEPA (arXiv:2509.14252). "
            "See cortex/extraction/embedding_backend.py for design notes."
        )

    def canonical_match(
        self,
        node: ExtractedNode,
        existing_nodes: list[dict],
    ) -> tuple[str | None, float]:
        """Resolve canonical matches once vector similarity is implemented."""

        raise NotImplementedError(
            "EmbeddingBackend.canonical_match() is not yet implemented. "
            "Intended backbone: LLM-JEPA (arXiv:2509.14252). "
            "See cortex/extraction/embedding_backend.py for design notes."
        )

    @property
    def supports_async_rescoring(self) -> bool:
        """Return true because embedding backends are intended for async rescoring."""

        return True

    @property
    def supports_embeddings(self) -> bool:
        """Return true because this backend is responsible for embeddings."""

        return True
