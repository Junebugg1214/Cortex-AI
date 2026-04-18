from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from time import perf_counter
from typing import Any, Mapping

from cortex.graph import CATEGORY_ORDER

from .backend import ExtractionBackend, ExtractionBackendError, ExtractionParseError, load_extraction_config
from .diagnostics import ExtractionDiagnostics, write_extraction_record
from .pipeline import (
    Document,
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
_ANTHROPIC_PRICING_PER_MILLION = (
    ("claude-3-opus", 15.0, 75.0),
    ("claude-opus", 15.0, 75.0),
    ("claude-3-5-haiku", 0.80, 4.0),
    ("claude-3-haiku", 0.25, 1.25),
    ("claude-3-7-sonnet", 3.0, 15.0),
    ("claude-3-5-sonnet", 3.0, 15.0),
    ("claude-sonnet", 3.0, 15.0),
)
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
        self._last_request_diagnostics: ExtractionDiagnostics | None = None

    def run(self, document: Document, context: PipelineExtractionContext) -> PipelineExtractionResult:
        """Run model extraction through the unified pipeline contract."""

        started = perf_counter()
        if not document.content.strip():
            result = empty_result(document, started_at=started)
            result.diagnostics = replace(result.diagnostics, prompt_version=context.prompt_version)
            write_extraction_record(
                result.diagnostics,
                backend="model",
                operation="run",
                source_id=document.source_id,
                source_type=document.source_type,
                item_count=0,
            )
            return result
        legacy_context = legacy_context_from_pipeline_context(context)
        legacy_context["_skip_diagnostics_log"] = True
        result = self.extract_statement(
            document.content,
            context=legacy_context,
        )
        pipeline_result = result_from_backend_result(result, document=document, context=context, started_at=started)
        write_extraction_record(
            pipeline_result.diagnostics,
            backend="model",
            operation="run",
            source_id=document.source_id,
            source_type=document.source_type,
            item_count=len(pipeline_result.items),
        )
        return pipeline_result

    def extract_statement(
        self,
        text: str,
        context: dict | None = None,
    ) -> ExtractionResult:
        """Extract graph facts from one statement with Claude."""

        started = perf_counter()
        context = dict(context or {})
        raw = self._request_json(
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
            user_prompt=json.dumps({"text": text}, ensure_ascii=False),
        )
        diagnostics = self._consume_request_diagnostics(
            started_at=started,
            prompt_version=str(context.get("prompt_version") or ""),
        )
        payload = self._parse_json_payload(raw)
        result = self._result_from_payload(payload, raw_source=text)
        diagnostics = replace(diagnostics, warnings=list(result.warnings))
        result._diagnostics = diagnostics
        if not self._skip_diagnostics_log(context):
            write_extraction_record(
                diagnostics,
                backend="model",
                operation="extract_statement",
                item_count=len(result.nodes) + len(result.edges),
            )
        return result

    def extract_bulk(
        self,
        texts: list[str],
        context: dict | None = None,
    ) -> list[ExtractionResult]:
        """Extract graph facts from a batch of statements in batches of 10 API calls."""

        started = perf_counter()
        context = dict(context or {})
        prompt_version = str(context.get("prompt_version") or "")
        results: list[ExtractionResult] = []
        request_diagnostics: list[ExtractionDiagnostics] = []
        for batch_start in range(0, len(texts), 10):
            batch = texts[batch_start : batch_start + 10]
            raw = self._request_json(
                system_prompt=(
                    EXTRACTION_SYSTEM_PROMPT
                    + '\nWhen given multiple texts, return {"results": [schema, ...]} in the same order.'
                ),
                user_prompt=json.dumps({"texts": batch}, ensure_ascii=False),
            )
            request_diagnostics.append(
                self._consume_request_diagnostics(started_at=started, prompt_version=prompt_version)
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
        diagnostics = self._combine_diagnostics(
            request_diagnostics,
            started_at=started,
            prompt_version=prompt_version,
            warnings=[warning for result in results for warning in result.warnings],
        )
        for result in results:
            result._diagnostics = diagnostics
        if not self._skip_diagnostics_log(context):
            write_extraction_record(
                diagnostics,
                backend="model",
                operation="extract_bulk",
                item_count=sum(len(result.nodes) + len(result.edges) for result in results),
            )
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
        self._last_request_diagnostics = None
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
        model_name = self._model_name()
        started = perf_counter()
        response = client.messages.create(
            model=model_name,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        latency_ms = (perf_counter() - started) * 1000.0
        content = getattr(response, "content", [])
        parts: list[str] = []
        for block in content:
            text = block.get("text") if isinstance(block, Mapping) else getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        self._last_request_diagnostics = self._diagnostics_from_response(
            response,
            fallback_model=model_name,
            latency_ms=latency_ms,
        )
        return "".join(parts).strip()

    @staticmethod
    def _skip_diagnostics_log(context: dict[str, Any]) -> bool:
        return bool(context.get("_skip_diagnostics_log", False))

    @staticmethod
    def _object_value(source: Any, key: str) -> Any:
        if isinstance(source, Mapping):
            return source.get(key)
        return getattr(source, key, None)

    @classmethod
    def _int_value(cls, source: Any, key: str) -> int:
        value = cls._object_value(source, key)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _float_value(cls, source: Any, key: str) -> float | None:
        value = cls._object_value(source, key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _cost_from_usage(*, model: str, tokens_in: int, tokens_out: int) -> float:
        normalized_model = model.lower()
        for marker, input_price, output_price in _ANTHROPIC_PRICING_PER_MILLION:
            if marker in normalized_model:
                return (tokens_in * input_price + tokens_out * output_price) / 1_000_000.0
        return 0.0

    def _diagnostics_from_response(
        self,
        response: Any,
        *,
        fallback_model: str,
        latency_ms: float,
    ) -> ExtractionDiagnostics:
        usage = self._object_value(response, "usage") or {}
        cache_creation_tokens = self._int_value(usage, "cache_creation_input_tokens")
        cache_read_tokens = self._int_value(usage, "cache_read_input_tokens")
        tokens_in = self._int_value(usage, "input_tokens") + cache_creation_tokens + cache_read_tokens
        tokens_out = self._int_value(usage, "output_tokens")
        model_name = str(self._object_value(response, "model") or fallback_model)
        cost_usd = self._float_value(response, "cost_usd")
        if cost_usd is None:
            cost_usd = self._float_value(usage, "cost_usd")
        if cost_usd is None:
            cost_usd = self._cost_from_usage(model=model_name, tokens_in=tokens_in, tokens_out=tokens_out)
        return ExtractionDiagnostics(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            stage_timings={"request": latency_ms},
            model=model_name,
            cache_hit=cache_read_tokens > 0,
        )

    def _consume_request_diagnostics(
        self,
        *,
        started_at: float,
        prompt_version: str,
    ) -> ExtractionDiagnostics:
        latency_ms = (perf_counter() - started_at) * 1000.0
        diagnostics = self._last_request_diagnostics
        self._last_request_diagnostics = None
        if diagnostics is None:
            diagnostics = ExtractionDiagnostics(model=self._model_name())
        stage_timings = dict(diagnostics.stage_timings)
        stage_timings["extract"] = latency_ms
        return replace(
            diagnostics,
            latency_ms=latency_ms,
            stage_timings=stage_timings,
            prompt_version=prompt_version,
        )

    @staticmethod
    def _combine_diagnostics(
        diagnostics: list[ExtractionDiagnostics],
        *,
        started_at: float,
        prompt_version: str,
        warnings: list[str],
    ) -> ExtractionDiagnostics:
        latency_ms = (perf_counter() - started_at) * 1000.0
        request_ms = sum(item.stage_timings.get("request", 0.0) for item in diagnostics)
        model = next((item.model for item in diagnostics if item.model), "")
        return ExtractionDiagnostics(
            tokens_in=sum(item.tokens_in for item in diagnostics),
            tokens_out=sum(item.tokens_out for item in diagnostics),
            cost_usd=sum(item.cost_usd for item in diagnostics),
            latency_ms=latency_ms,
            stage_timings={"request": request_ms, "extract": latency_ms},
            model=model,
            prompt_version=prompt_version,
            warnings=list(warnings),
            cache_hit=any(item.cache_hit for item in diagnostics),
        )

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
