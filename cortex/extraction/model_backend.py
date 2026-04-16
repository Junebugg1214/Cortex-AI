from __future__ import annotations

import json
import logging
import os
from typing import Any, Mapping

from cortex.graph import CATEGORY_ORDER

from .backend import ExtractionBackend, ExtractionBackendError, ExtractionParseError, load_extraction_config
from .types import ExtractedEdge, ExtractedNode, ExtractionResult

LOGGER = logging.getLogger(__name__)

MODEL_KEY_ERROR = (
    "ModelBackend requires an API key. Set CORTEX_ANTHROPIC_API_KEY\nor ANTHROPIC_API_KEY. See CONFIG.md for details."
)

EXTRACTION_SYSTEM_PROMPT = """You are a knowledge graph extractor.
Return only a JSON object. No explanation. No markdown fences.

Schema:
{
  "nodes": [
    {
      "label": string,
      "category": string,
      "value": string,
      "confidence": float between 0.0 and 1.0,
      "canonical_match": string or null,
      "match_confidence": float or null
    }
  ],
  "edges": [
    {
      "source": string,
      "target": string,
      "relationship": string,
      "direction_confidence": float between 0.0 and 1.0
    }
  ],
  "warnings": [string]
}

Rules:
- Do not invent facts not present in the input text.
- If relationship direction is ambiguous, return both
  directions as separate edge objects each with
  direction_confidence below 0.6.
- Only return canonical_match if semantic equivalence
  is unambiguous. Do not guess.
- confidence reflects how clearly the fact is stated,
  not how likely it is to be true.
"""

DEFAULT_MODEL = "claude-3-5-sonnet-20241022"
_CATEGORY_ALIASES = {
    "person": "identity",
    "people": "identity",
    "human": "identity",
    "organization": "business_context",
    "company": "business_context",
    "organization_name": "business_context",
    "corporation": "business_context",
    "product": "technical_expertise",
    "technology": "technical_expertise",
    "tech": "technical_expertise",
    "skill": "technical_expertise",
    "language": "technical_expertise",
    "framework": "technical_expertise",
    "tool": "technical_expertise",
    "place": "mentions",
    "location": "mentions",
    "event": "mentions",
    "date": "mentions",
    "number": "mentions",
}


class ModelBackend(ExtractionBackend):
    """Anthropic-backed extraction backend."""

    def __init__(self, *, api_key: str | None = None) -> None:
        self._configured_api_key = api_key

    def extract_statement(
        self,
        text: str,
        context: dict | None = None,
    ) -> ExtractionResult:
        """Extract graph facts from one statement with Claude."""

        raw = self._request_json(
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
            user_prompt=json.dumps({"text": text}, ensure_ascii=False),
        )
        payload = self._parse_json_payload(raw)
        return self._result_from_payload(payload, raw_source=text)

    def extract_bulk(
        self,
        texts: list[str],
        context: dict | None = None,
    ) -> list[ExtractionResult]:
        """Extract graph facts from a batch of statements in batches of 10 API calls."""

        results: list[ExtractionResult] = []
        for batch_start in range(0, len(texts), 10):
            batch = texts[batch_start : batch_start + 10]
            raw = self._request_json(
                system_prompt=(
                    EXTRACTION_SYSTEM_PROMPT
                    + '\nWhen given multiple texts, return {"results": [schema, ...]} in the same order.'
                ),
                user_prompt=json.dumps({"texts": batch}, ensure_ascii=False),
            )
            payload = self._parse_json_payload(raw)
            if isinstance(payload, dict) and isinstance(payload.get("results"), list):
                batch_payloads = payload["results"]
            elif isinstance(payload, list):
                batch_payloads = payload
            elif len(batch) == 1 and isinstance(payload, dict):
                batch_payloads = [payload]
            else:
                raise ExtractionParseError(
                    "ModelBackend returned an unexpected bulk payload shape.",
                    raw_response=raw,
                )
            if len(batch_payloads) != len(batch):
                raise ExtractionParseError(
                    "ModelBackend returned a different number of bulk extraction results than requested.",
                    raw_response=raw,
                )
            for text, item in zip(batch, batch_payloads):
                if not isinstance(item, dict):
                    raise ExtractionParseError(
                        "ModelBackend returned a non-object bulk extraction item.",
                        raw_response=raw,
                    )
                results.append(self._result_from_payload(item, raw_source=text))
        return results

    def canonical_match(
        self,
        node: ExtractedNode,
        existing_nodes: list[dict],
    ) -> tuple[str | None, float]:
        """Resolve semantic equivalence through LLM judgment.

        Canonical match via LLM judgment. This method is the intended replacement
        target for EmbeddingBackend.canonical_match(), which will use JEPA/LLM-JEPA
        vector similarity instead of generative API calls. See
        cortex/extraction/embedding_backend.py.
        """

        candidates = []
        for item in existing_nodes[:20]:
            if not isinstance(item, dict):
                continue
            candidates.append(
                {
                    "id": item.get("id"),
                    "label": item.get("label"),
                    "value": item.get("value") or item.get("full_description") or item.get("brief") or "",
                }
            )
        raw = self._request_json(
            system_prompt=(
                "Return only JSON. Decide whether the candidate node is semantically equivalent to one of the "
                'existing nodes. Return {"canonical_match": string|null, "confidence": float}.'
            ),
            user_prompt=json.dumps(
                {
                    "candidate": {"label": node.label, "value": node.value, "category": node.category},
                    "existing_nodes": candidates,
                },
                ensure_ascii=False,
            ),
        )
        payload = self._parse_json_payload(raw)
        if not isinstance(payload, dict):
            raise ExtractionParseError("ModelBackend canonical_match returned a non-object payload.", raw_response=raw)
        match = payload.get("canonical_match")
        confidence = float(payload.get("confidence", 0.0) or 0.0)
        if not match:
            return None, 0.0
        valid_ids = {item.get("id") for item in candidates}
        if match not in valid_ids:
            return None, 0.0
        return str(match), confidence

    @property
    def supports_async_rescoring(self) -> bool:
        """Return true because model-backed extraction can be used for rescoring."""

        return True

    @property
    def supports_embeddings(self) -> bool:
        """Return false because the model backend does not emit embeddings."""

        return False

    def _api_key(self) -> str:
        key = (self._configured_api_key or "").strip()
        if key:
            return key
        env_key = os.environ.get("CORTEX_ANTHROPIC_API_KEY", "").strip()
        if env_key:
            return env_key
        env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if env_key:
            return env_key
        config = load_extraction_config()
        config_key = str(config.get("anthropic_api_key", "")).strip()
        if config_key:
            return config_key
        raise ExtractionBackendError(MODEL_KEY_ERROR)

    def _anthropic_client_cls(self):
        """Return the Anthropic client class lazily."""

        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover - exercised via mocks in tests
            raise ExtractionBackendError(
                "Anthropic client is unavailable. Install the anthropic package or use HeuristicBackend."
            ) from exc
        return Anthropic

    def _request_json(self, *, system_prompt: str, user_prompt: str) -> str:
        """Call Anthropic and return the raw text response."""

        api_key = self._api_key()
        client = self._anthropic_client_cls()(api_key=api_key)
        response = client.messages.create(
            model=self._model_name(),
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = getattr(response, "content", [])
        parts: list[str] = []
        for block in content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts).strip()

    def _model_name(self) -> str:
        """Resolve the Anthropic model name from config or environment."""

        env_model = os.environ.get("CORTEX_ANTHROPIC_MODEL", "").strip()
        if env_model:
            return env_model
        config = load_extraction_config()
        config_model = str(config.get("anthropic_model", "")).strip()
        if config_model:
            return config_model
        return DEFAULT_MODEL

    @staticmethod
    def _normalize_category(raw_category: str) -> str:
        """Normalize model-returned categories to local canonical tags."""

        category = " ".join(raw_category.strip().lower().replace("_", " ").replace("-", " ").split())
        if not category:
            return "mentions"
        if category in CATEGORY_ORDER:
            return category
        if category in _CATEGORY_ALIASES:
            return _CATEGORY_ALIASES[category]
        return "mentions"

    def _parse_json_payload(self, raw: str) -> Any:
        """Parse structured JSON from the model response."""

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            LOGGER.debug("ModelBackend raw response: %s", raw)
            raise ExtractionParseError(
                f"ModelBackend returned invalid JSON: {exc.msg}",
                raw_response=raw,
            ) from exc

    def _result_from_payload(self, payload: Mapping[str, Any], *, raw_source: str) -> ExtractionResult:
        """Normalize a parsed model payload into an ExtractionResult."""

        nodes: list[ExtractedNode] = []
        for item in payload.get("nodes", []):
            if not isinstance(item, Mapping):
                continue
            match_confidence = item.get("match_confidence")
            nodes.append(
                ExtractedNode(
                    label=str(item.get("label", "")).strip(),
                    category=self._normalize_category(str(item.get("category", ""))),
                    value=str(item.get("value", "")).strip(),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                    canonical_match=(str(item.get("canonical_match")).strip() if item.get("canonical_match") else None),
                    match_confidence=float(match_confidence) if match_confidence is not None else None,
                    needs_review=bool(item.get("needs_review", False)),
                )
            )
        edges: list[ExtractedEdge] = []
        for item in payload.get("edges", []):
            if not isinstance(item, Mapping):
                continue
            direction_confidence = float(item.get("direction_confidence", 0.0) or 0.0)
            edges.append(
                ExtractedEdge(
                    source=str(item.get("source", "")).strip(),
                    target=str(item.get("target", "")).strip(),
                    relationship=str(item.get("relationship", "")).strip() or "related_to",
                    direction_confidence=direction_confidence,
                    needs_review=bool(item.get("needs_review", False) or direction_confidence < 0.6),
                )
            )
        warnings = [str(item) for item in payload.get("warnings", []) if str(item).strip()]
        return ExtractionResult(
            nodes=nodes,
            edges=edges,
            extraction_method="model",
            raw_source=raw_source,
            warnings=warnings,
        )
