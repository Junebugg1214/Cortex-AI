from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from time import perf_counter
from typing import Annotated, Any, Literal, Mapping

from cortex.graph.graph import CATEGORY_ORDER

from .backend import ExtractionBackendError, ExtractionParseError, load_extraction_config
from .diagnostics import ExtractionDiagnostics, write_extraction_record
from .eval.replay_cache import ReplayCache
from .extract_memory_context import ExtractedClaim, ExtractedFact, ExtractedMemoryItem, ExtractedRelationship
from .llm_provider import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_PROVIDER_NAME,
    AnthropicLLMProvider,
    LLMProviderError,
    StructuredLLMProvider,
    create_registered_llm_provider,
)
from .pipeline import (
    Document,
    ExtractionPipeline,
    empty_result,
    items_from_backend_result,
    legacy_context_from_pipeline_context,
)
from .pipeline import (
    ExtractionContext as PipelineExtractionContext,
)
from .pipeline import (
    ExtractionResult as PipelineExtractionResult,
)
from .prompts import load_prompt
from .retrieval import NodeHint, retrieve_similar_nodes
from .stages import (
    CandidateBatch,
    PipelineState,
    Refinement,
    calibrate_confidence,
    generate_candidates,
    link_relations,
    link_to_graph,
    refine_types,
    split_document,
)
from .stages.state import DocumentChunk
from .types import ExtractedEdge, ExtractedNode, ExtractionResult

try:  # pragma: no cover - missing dependency path is exercised by install profiles.
    from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
except ImportError as exc:  # pragma: no cover
    BaseModel = object  # type: ignore[misc,assignment]
    ConfigDict = None  # type: ignore[assignment]
    Field = None  # type: ignore[assignment]
    TypeAdapter = None  # type: ignore[assignment]
    ValidationError = ValueError  # type: ignore[assignment]
    _PYDANTIC_IMPORT_ERROR: ImportError | None = exc
else:
    _PYDANTIC_IMPORT_ERROR = None

LOGGER = logging.getLogger(__name__)

MODEL_KEY_ERROR = (
    "ModelBackend requires an API key. Set CORTEX_ANTHROPIC_API_KEY\nor ANTHROPIC_API_KEY. See CONFIG.md for details."
)

CANDIDATES_PROMPT = load_prompt("candidates", "v1")
TYPING_PROMPT = load_prompt("typing", "v1")
CANONICALIZE_PROMPT = load_prompt("canonicalize", "v1")
PROMPT_REFERENCES = (
    CANDIDATES_PROMPT.reference,
    TYPING_PROMPT.reference,
    CANONICALIZE_PROMPT.reference,
)
EXTRACTION_SYSTEM_PROMPT = CANDIDATES_PROMPT.content

DEFAULT_MODEL = DEFAULT_ANTHROPIC_MODEL
_TYPED_EXTRACTION_TOOL_NAME = "emit_extracted_memory_items"
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


if _PYDANTIC_IMPORT_ERROR is None:

    class _BaseTypedToolItem(BaseModel):
        model_config = ConfigDict(extra="forbid")

        topic: str
        category: str
        brief: str = ""
        full_description: str = ""
        confidence: float = Field(0.5, ge=0.0, le=1.0)
        extraction_method: str = "model"
        source_quotes: list[str] = Field(default_factory=list)
        source_span: str = ""
        extraction_confidence: float = Field(0.0, ge=0.0, le=1.0)
        entity_resolution: str = Field(
            "",
            description="Existing Cortex node_id to attach this item to when retrieval hints identify a known entity.",
        )
        node_id: str = Field(
            "",
            description="Optional alias for entity_resolution; use only IDs provided in retrieval hints.",
        )
        extraction_flags: list[str] = Field(default_factory=list)

    class _FactToolItem(_BaseTypedToolItem):
        extraction_type: Literal["fact"]
        attribute_name: str
        attribute_value: str

    class _ClaimToolItem(_BaseTypedToolItem):
        extraction_type: Literal["claim"]
        assertion: str
        stance: Literal["asserts", "denies", "corrects"] = "asserts"

    class _RelationshipToolItem(_BaseTypedToolItem):
        extraction_type: Literal["relationship"]
        source_label: str = "self"
        relation: str
        target_label: str
        qualifiers: dict[str, str] = Field(default_factory=dict)

    _TypedToolItem = Annotated[
        _FactToolItem | _ClaimToolItem | _RelationshipToolItem,
        Field(discriminator="extraction_type"),
    ]

    class _TypedExtractionPayload(BaseModel):
        model_config = ConfigDict(extra="forbid")

        items: list[_TypedToolItem] = Field(default_factory=list)
        warnings: list[str] = Field(default_factory=list)

    _TYPED_EXTRACTION_ADAPTER = TypeAdapter(_TypedExtractionPayload)
else:
    _BaseTypedToolItem = object
    _FactToolItem = object
    _ClaimToolItem = object
    _RelationshipToolItem = object
    _TypedExtractionPayload = object
    _TYPED_EXTRACTION_ADAPTER = None


def typed_extraction_input_schema() -> dict[str, Any]:
    """Return the JSON Schema for typed ExtractedFact/Claim/Relationship output."""

    return _typed_extraction_adapter().json_schema()


def _typed_extraction_adapter() -> Any:
    """Return the Pydantic adapter or raise the model-extra install hint."""

    if _TYPED_EXTRACTION_ADAPTER is None:
        raise ExtractionBackendError(
            "Pydantic >= 2.6 is required for ModelBackend schema validation. Install cortex-identity[model]."
        ) from _PYDANTIC_IMPORT_ERROR
    return _TYPED_EXTRACTION_ADAPTER


class ModelBackend(ExtractionPipeline):
    """Schema-constrained model extraction backend."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        embedding_backend: Any | None = None,
        llm_provider: StructuredLLMProvider | None = None,
        provider_name: str | None = None,
        model_id: str | None = None,
        replay_cache: ReplayCache | None = None,
        retrieval_top_k: int = 8,
        retrieval_threshold: float = 0.72,
    ) -> None:
        self._configured_api_key = api_key
        self._embedding_backend = embedding_backend
        self._llm_provider_override = llm_provider
        self._configured_provider_name = (provider_name or "").strip()
        self._configured_model_id = (model_id or "").strip()
        self._replay_cache = replay_cache if replay_cache is not None else ReplayCache.from_env()
        self._retrieval_top_k = retrieval_top_k
        self._retrieval_threshold = retrieval_threshold
        self._last_request_diagnostics: ExtractionDiagnostics | None = None
        self._resolved_llm_provider: StructuredLLMProvider | None = llm_provider

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

        state = PipelineState(
            document=document,
            context=context,
            diagnostics=ExtractionDiagnostics(prompt_version=context.prompt_version),
        )
        state = split_document(state)
        state = generate_candidates(
            state,
            extractor=lambda chunk, hints: self._candidate_batch_from_chunk(chunk, hints, context=context),
            hint_provider=lambda chunk: self._retrieve_hints(chunk.text, graph=context.existing_graph),
        )
        state = refine_types(
            state,
            refiner=lambda item: self._refine_low_confidence_item(item, context=context),
        )
        state = link_to_graph(
            state,
            embedding_backend=self._embedding_backend,
            retrieval_top_k=self._retrieval_top_k,
            retrieval_threshold=self._retrieval_threshold,
        )
        state = link_relations(state)
        state = calibrate_confidence(state)
        state = self._detect_contradictions(state)

        latency_ms = (perf_counter() - started) * 1000.0
        stage_timings = dict(state.diagnostics.stage_timings)
        stage_timings["extract"] = latency_ms
        diagnostics = replace(
            state.diagnostics,
            latency_ms=latency_ms,
            stage_timings=stage_timings,
            prompt_version=state.diagnostics.prompt_version or context.prompt_version,
            warnings=list(state.warnings),
        )
        pipeline_result = PipelineExtractionResult(items=list(state.items), diagnostics=diagnostics)
        write_extraction_record(
            pipeline_result.diagnostics,
            backend="model",
            operation="run",
            source_id=document.source_id,
            source_type=document.source_type,
            item_count=len(pipeline_result.items),
        )
        return pipeline_result

    def _candidate_batch_from_chunk(
        self,
        chunk: DocumentChunk,
        hints: Any,
        *,
        context: PipelineExtractionContext,
    ) -> CandidateBatch:
        legacy_context = legacy_context_from_pipeline_context(context)
        legacy_context["_skip_diagnostics_log"] = True
        legacy_context["retrieval_hints"] = list(hints)
        result = self.extract_statement(chunk.text, context=legacy_context)
        diagnostics = getattr(result, "_diagnostics", None)
        if not isinstance(diagnostics, ExtractionDiagnostics):
            diagnostics = ExtractionDiagnostics(prompt_version=context.prompt_version)
        return CandidateBatch(
            items=tuple(items_from_backend_result(result)),
            diagnostics=diagnostics,
            warnings=tuple(result.warnings),
        )

    def _refine_low_confidence_item(
        self,
        item: ExtractedMemoryItem,
        *,
        context: PipelineExtractionContext,
    ) -> Refinement:
        raw_source = item.source_span or "\n".join(item.source_quotes) or item.brief or item.topic
        user_prompt = TYPING_PROMPT.render(
            source_text=raw_source,
            current_item=json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True),
        )
        legacy_context = legacy_context_from_pipeline_context(context)
        legacy_context["_skip_diagnostics_log"] = True
        result = self.extract_statement(user_prompt, context=legacy_context)
        diagnostics = getattr(result, "_diagnostics", None)
        if not isinstance(diagnostics, ExtractionDiagnostics):
            diagnostics = ExtractionDiagnostics(prompt_version=context.prompt_version)
        refined = next(
            (
                candidate
                for candidate in items_from_backend_result(result)
                if isinstance(candidate, ExtractedFact | ExtractedClaim)
            ),
            item,
        )
        return Refinement(item=refined, diagnostics=diagnostics, warnings=tuple(result.warnings))

    @staticmethod
    def _detect_contradictions(state: PipelineState) -> PipelineState:
        started = perf_counter()
        graph = state.context.existing_graph
        metadata = dict(state.metadata)
        warnings = list(state.warnings)
        if graph is not None:
            try:
                from cortex.graph.contradictions import ContradictionEngine

                contradictions = ContradictionEngine().detect_all(graph)
                if contradictions:
                    graph.meta["contradictions"] = [item.to_dict() for item in contradictions]
                    metadata["contradictions_detected"] = len(contradictions)
            except Exception:  # pragma: no cover - contradiction scan should not break extraction
                if "contradiction_detection_failed" not in warnings:
                    warnings.append("contradiction_detection_failed")
        next_state = replace(state, metadata=metadata, warnings=tuple(warnings))
        if warnings != list(state.warnings):
            next_state = next_state.with_warnings(tuple(warnings))
        return next_state.with_timing("contradictions.detect", (perf_counter() - started) * 1000.0)

    def extract_statement(
        self,
        text: str,
        context: dict | None = None,
    ) -> ExtractionResult:
        """Extract graph facts from one statement with Claude."""

        started = perf_counter()
        context = dict(context or {})
        prompt_version = str(context.get("prompt_version") or "")
        system_prompt = self._system_prompt_from_context(context)
        retrieval_hints = self._coerce_retrieval_hints(context.get("retrieval_hints"))
        if self._uses_legacy_request_json_override():
            result, diagnostics = self._extract_statement_legacy_json(
                text,
                started_at=started,
                prompt_version=prompt_version,
                system_prompt=system_prompt,
                retrieval_hints=retrieval_hints,
            )
        else:
            result, diagnostics = self._extract_statement_with_tool_schema(
                text,
                started_at=started,
                prompt_version=prompt_version,
                system_prompt=system_prompt,
                retrieval_hints=retrieval_hints,
            )
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
        system_prompt = self._system_prompt_from_context(context)
        results: list[ExtractionResult] = []
        request_diagnostics: list[ExtractionDiagnostics] = []
        for batch_start in range(0, len(texts), 10):
            batch = texts[batch_start : batch_start + 10]
            raw = self._request_json(
                system_prompt=(
                    system_prompt + '\nWhen given multiple texts, return {"results": [schema, ...]} in the same order.'
                ),
                user_prompt=json.dumps({"texts": batch}, ensure_ascii=False),
                prompt_version=prompt_version,
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

    def _extract_statement_legacy_json(
        self,
        text: str,
        *,
        started_at: float,
        prompt_version: str,
        system_prompt: str,
        retrieval_hints: list[NodeHint],
    ) -> tuple[ExtractionResult, ExtractionDiagnostics]:
        """Compatibility path for tests and callers that override _request_json."""

        user_prompt = self._statement_user_prompt(text, retrieval_hints=retrieval_hints)
        request_diagnostics: list[ExtractionDiagnostics] = []
        for _attempt in range(3):
            raw = self._request_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                prompt_version=prompt_version,
            )
            request_diagnostics.append(
                self._consume_request_diagnostics(started_at=started_at, prompt_version=prompt_version)
            )
            try:
                payload = self._parse_json_payload(raw)
            except ExtractionParseError:
                continue
            if not isinstance(payload, Mapping):
                continue
            result = self._result_from_payload(payload, raw_source=text)
            diagnostics = self._combine_diagnostics(
                request_diagnostics,
                started_at=started_at,
                prompt_version=prompt_version,
                warnings=list(result.warnings),
            )
            return result, diagnostics

        warnings = ["schema_violation"]
        diagnostics = self._combine_diagnostics(
            request_diagnostics,
            started_at=started_at,
            prompt_version=prompt_version,
            warnings=warnings,
        )
        return (
            ExtractionResult(extraction_method="model", raw_source=text, warnings=warnings),
            diagnostics,
        )

    def _extract_statement_with_tool_schema(
        self,
        text: str,
        *,
        started_at: float,
        prompt_version: str,
        system_prompt: str,
        retrieval_hints: list[NodeHint],
    ) -> tuple[ExtractionResult, ExtractionDiagnostics]:
        """Extract one statement through the schema-constrained provider tool path."""

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": self._statement_user_prompt(text, retrieval_hints=retrieval_hints)}
        ]
        request_diagnostics: list[ExtractionDiagnostics] = []
        for attempt in range(3):
            response, diagnostics = self._request_typed_tool_response(
                system_prompt=system_prompt,
                messages=messages,
                prompt_version=prompt_version,
            )
            request_diagnostics.append(diagnostics)
            try:
                tool_input = self._tool_input_from_response(response)
                result = self._result_from_typed_payload(tool_input, raw_source=text)
                diagnostics = self._combine_diagnostics(
                    request_diagnostics,
                    started_at=started_at,
                    prompt_version=prompt_version,
                    warnings=list(result.warnings),
                )
                return result, diagnostics
            except (ExtractionParseError, TypeError, ValueError, ValidationError) as exc:
                if attempt < 2:
                    messages.extend(self._schema_feedback_messages(str(exc)))

        warnings = ["schema_violation"]
        diagnostics = self._combine_diagnostics(
            request_diagnostics,
            started_at=started_at,
            prompt_version=prompt_version,
            warnings=warnings,
        )
        return (
            ExtractionResult(extraction_method="model", raw_source=text, warnings=warnings),
            diagnostics,
        )

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

    def _retrieve_hints(self, chunk_text: str, *, graph: Any) -> list[NodeHint]:
        if self._embedding_backend is None:
            return []
        try:
            return retrieve_similar_nodes(
                self._embedding_backend,
                graph,
                chunk_text,
                top_k=self._retrieval_top_k,
                threshold=self._retrieval_threshold,
            )
        except Exception as exc:  # pragma: no cover - optional retrieval should not break extraction
            LOGGER.warning("ModelBackend retrieval hints failed: %s", exc)
            return []

    @staticmethod
    def _coerce_retrieval_hints(raw_hints: Any) -> list[NodeHint]:
        hints: list[NodeHint] = []
        if not raw_hints:
            return hints
        for raw_hint in raw_hints:
            if isinstance(raw_hint, NodeHint):
                hints.append(raw_hint)
                continue
            if not isinstance(raw_hint, Mapping):
                continue
            try:
                hints.append(
                    NodeHint(
                        node_id=str(raw_hint.get("node_id", "")).strip(),
                        label=str(raw_hint.get("label", "")).strip(),
                        type=str(raw_hint.get("type", "") or "mentions"),
                        confidence=float(raw_hint.get("confidence", 0.0) or 0.0),
                        similarity=float(raw_hint.get("similarity", 0.0) or 0.0),
                    )
                )
            except (TypeError, ValueError):
                continue
        return [hint for hint in hints if hint.node_id and hint.label]

    @staticmethod
    def _system_prompt_from_context(context: Mapping[str, Any]) -> str:
        prompt = context.get("system_prompt")
        if isinstance(prompt, str) and prompt.strip():
            return prompt.strip()
        overrides = context.get("prompt_overrides")
        if isinstance(overrides, Mapping):
            candidate_prompt = overrides.get("candidates") or overrides.get("system")
            if isinstance(candidate_prompt, str) and candidate_prompt.strip():
                return candidate_prompt.strip()
        return EXTRACTION_SYSTEM_PROMPT

    @staticmethod
    def _statement_user_prompt(text: str, *, retrieval_hints: list[NodeHint]) -> str:
        if not retrieval_hints:
            return json.dumps({"text": text}, ensure_ascii=False)
        hint_lines = CANONICALIZE_PROMPT.content.splitlines()
        for hint in retrieval_hints:
            hint_lines.extend(
                [
                    f"- node_id: {hint.node_id}",
                    f"  label: {hint.label}",
                    f"  type: {hint.type}",
                    f"  confidence: {hint.confidence:.3f}",
                    f"  similarity: {hint.similarity:.3f}",
                ]
            )
        return "\n".join([*hint_lines, "", "## Chunk", text])

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

    def _request_json(self, *, system_prompt: str, user_prompt: str, prompt_version: str = "") -> str:
        """Call the configured provider and return the raw text response."""

        model_name = self._model_name()
        input_content = self._replay_input_content(system_prompt=system_prompt, user_prompt=user_prompt)
        cached = self._read_replay_response(
            prompt_version=prompt_version,
            input_content=input_content,
            model_id=model_name,
        )
        if cached is not None:
            payload = cached.get("payload")
            if isinstance(payload, Mapping) and isinstance(payload.get("raw_text"), str):
                self._last_request_diagnostics = self._diagnostics_from_replay_payload(
                    payload,
                    fallback_model=model_name,
                    prompt_version=prompt_version,
                )
                return str(payload["raw_text"]).strip()

        self._raise_replay_miss_if_read(
            prompt_version=prompt_version,
            input_content=input_content,
            model_id=model_name,
            payload_kind="text",
        )

        provider_response = self._llm_provider().create_message(
            model=model_name,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        response = provider_response.response
        content = getattr(response, "content", [])
        parts: list[str] = []
        for block in content:
            text = block.get("text") if isinstance(block, Mapping) else getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        self._last_request_diagnostics = self._diagnostics_from_response(
            response,
            fallback_model=model_name,
            latency_ms=provider_response.latency_ms,
        )
        raw_text = "".join(parts).strip()
        self._write_replay_response(
            prompt_version=prompt_version,
            input_content=input_content,
            model_id=model_name,
            payload={
                "kind": "text",
                "raw_text": raw_text,
                "response": self._serializable_response(response),
                "diagnostics": self._last_request_diagnostics.as_dict(),
            },
        )
        return raw_text

    def _request_typed_tool_response(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        prompt_version: str = "",
    ) -> tuple[Any, ExtractionDiagnostics]:
        """Call the configured provider and require a typed extraction tool_use response."""

        model_name = self._model_name()
        input_content = self._replay_input_content(system_prompt=system_prompt, messages=messages)
        cached = self._read_replay_response(
            prompt_version=prompt_version,
            input_content=input_content,
            model_id=model_name,
        )
        if cached is not None:
            payload = cached.get("payload")
            if isinstance(payload, Mapping) and isinstance(payload.get("response"), Mapping):
                return (
                    dict(payload["response"]),
                    self._diagnostics_from_replay_payload(
                        payload,
                        fallback_model=model_name,
                        prompt_version=prompt_version,
                    ),
                )

        self._raise_replay_miss_if_read(
            prompt_version=prompt_version,
            input_content=input_content,
            model_id=model_name,
            payload_kind="typed_tool",
        )

        provider_response = self._llm_provider().create_tool_message(
            model=model_name,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=[
                {
                    "name": _TYPED_EXTRACTION_TOOL_NAME,
                    "description": "Emit typed Cortex memory items extracted from the input text.",
                    "input_schema": typed_extraction_input_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": _TYPED_EXTRACTION_TOOL_NAME},
        )
        response = provider_response.response
        diagnostics = self._diagnostics_from_response(
            response,
            fallback_model=model_name,
            latency_ms=provider_response.latency_ms,
        )
        self._write_replay_response(
            prompt_version=prompt_version,
            input_content=input_content,
            model_id=model_name,
            payload={
                "kind": "typed_tool",
                "response": self._serializable_response(response),
                "diagnostics": diagnostics.as_dict(),
            },
        )
        return (
            response,
            diagnostics,
        )

    def _llm_provider(self) -> StructuredLLMProvider:
        if self._resolved_llm_provider is not None:
            return self._resolved_llm_provider
        provider_name = self._provider_name()
        if provider_name == DEFAULT_PROVIDER_NAME:
            self._resolved_llm_provider = AnthropicLLMProvider(
                api_key=self._api_key(), client_cls=self._anthropic_client_cls
            )
            return self._resolved_llm_provider
        try:
            self._resolved_llm_provider = create_registered_llm_provider(provider_name)
        except LLMProviderError as exc:
            raise ExtractionBackendError(str(exc)) from exc
        return self._resolved_llm_provider

    def _tool_input_from_response(self, response: Any) -> Any:
        """Return the tool_use input emitted by the provider."""

        raw_text: list[str] = []
        content = self._object_value(response, "content") or []
        for block in content:
            block_type = self._object_value(block, "type")
            block_name = self._object_value(block, "name")
            if block_type == "tool_use" and block_name == _TYPED_EXTRACTION_TOOL_NAME:
                tool_input = self._object_value(block, "input")
                if isinstance(tool_input, str):
                    return self._parse_json_payload(tool_input)
                return tool_input
            text = self._object_value(block, "text")
            if isinstance(text, str):
                raw_text.append(text)
        if raw_text:
            return self._parse_json_payload("".join(raw_text).strip())
        raise ExtractionParseError(
            "ModelBackend did not return the required typed extraction tool_use.",
            raw_response=str(getattr(response, "content", "")),
        )

    @staticmethod
    def _schema_feedback_messages(validation_error: str) -> list[dict[str, str]]:
        return [
            {
                "role": "assistant",
                "content": "I attempted the extraction tool call, but the input failed schema validation.",
            },
            {
                "role": "user",
                "content": (
                    "The previous tool input did not match the required JSON Schema. "
                    f"Validation error:\n{validation_error}\n"
                    f"Call {_TYPED_EXTRACTION_TOOL_NAME} again with corrected input only."
                ),
            },
        ]

    @staticmethod
    def _skip_diagnostics_log(context: dict[str, Any]) -> bool:
        return bool(context.get("_skip_diagnostics_log", False))

    @staticmethod
    def _replay_input_content(**parts: Any) -> str:
        return json.dumps(parts, ensure_ascii=False, sort_keys=True)

    def _read_replay_response(
        self,
        *,
        prompt_version: str,
        input_content: str,
        model_id: str,
    ) -> dict[str, Any] | None:
        try:
            return self._replay_cache.read(
                prompt_version=prompt_version,
                input_content=input_content,
                model_id=model_id,
            )
        except OSError as exc:  # pragma: no cover - cache should never break extraction
            LOGGER.warning("Unable to read extraction replay cache: %s", exc)
            return None

    def _raise_replay_miss_if_read(
        self,
        *,
        prompt_version: str,
        input_content: str,
        model_id: str,
        payload_kind: str,
    ) -> None:
        if self._replay_cache.mode != "read":
            return
        key = self._replay_cache.key(
            prompt_version=prompt_version,
            input_content=input_content,
            model_id=model_id,
        )
        path = self._replay_cache.path_for_key(key)
        raise ExtractionBackendError(
            "Extraction replay cache miss in read mode "
            f"for {payload_kind} request (model={model_id}, prompt_version={prompt_version or '-'}, "
            f"key={key}, path={path}). "
            "Refresh the replay cache with `cortex extract refresh-cache` or set "
            "CORTEX_EXTRACTION_REPLAY=off/write to allow live model calls."
        )

    def _write_replay_response(
        self,
        *,
        prompt_version: str,
        input_content: str,
        model_id: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            self._replay_cache.write(
                prompt_version=prompt_version,
                input_content=input_content,
                model_id=model_id,
                payload=payload,
            )
        except OSError as exc:  # pragma: no cover - cache should never break extraction
            LOGGER.warning("Unable to write extraction replay cache: %s", exc)

    def _diagnostics_from_replay_payload(
        self,
        payload: Mapping[str, Any],
        *,
        fallback_model: str,
        prompt_version: str,
    ) -> ExtractionDiagnostics:
        raw = payload.get("diagnostics")
        diagnostics = raw if isinstance(raw, Mapping) else {}
        stage_timings = diagnostics.get("stage_timings")
        return ExtractionDiagnostics(
            tokens_in=int(diagnostics.get("tokens_in") or 0),
            tokens_out=int(diagnostics.get("tokens_out") or 0),
            cost_usd=0.0,
            latency_ms=0.0,
            stage_timings={**(dict(stage_timings) if isinstance(stage_timings, Mapping) else {}), "request": 0.0},
            model=str(diagnostics.get("model") or fallback_model),
            prompt_version=str(diagnostics.get("prompt_version") or prompt_version),
            warnings=list(diagnostics.get("warnings") or []),
            cache_hit=True,
        )

    @classmethod
    def _serializable_response(cls, response: Any) -> dict[str, Any]:
        return {
            "content": [cls._json_safe(block) for block in (cls._object_value(response, "content") or [])],
            "usage": cls._json_safe(cls._object_value(response, "usage") or {}),
            "model": str(cls._object_value(response, "model") or ""),
        }

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, Mapping):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, list | tuple | set):
            return [cls._json_safe(item) for item in value]
        if hasattr(value, "model_dump"):
            return cls._json_safe(value.model_dump())

        payload: dict[str, Any] = {}
        try:
            payload.update(vars(value))
        except TypeError:
            pass
        for key in (
            "id",
            "type",
            "name",
            "input",
            "text",
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "cost_usd",
        ):
            if hasattr(value, key):
                payload[key] = getattr(value, key)
        if payload:
            return cls._json_safe(payload)
        return str(value)

    def _uses_legacy_request_json_override(self) -> bool:
        return "_request_json" in self.__dict__

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
        """Resolve the model id from config or environment."""

        if self._configured_model_id:
            return self._configured_model_id
        env_model = os.environ.get("CORTEX_MODEL_ID", "").strip()
        if env_model:
            return env_model
        config = load_extraction_config()
        config_model = str(config.get("model_id", "")).strip()
        if config_model:
            return config_model
        provider_name = self._provider_name(config=config)
        if provider_name == DEFAULT_PROVIDER_NAME:
            env_model = os.environ.get("CORTEX_ANTHROPIC_MODEL", "").strip()
            if env_model:
                return env_model
            config_model = str(config.get("anthropic_model", "")).strip()
            if config_model:
                return config_model
            return DEFAULT_MODEL
        provider_default = self._provider_default_model_id()
        if provider_default:
            return provider_default
        raise ExtractionBackendError(
            f"ModelBackend requires a model_id for LLM provider '{provider_name}'. "
            "Pass model_id=..., set CORTEX_MODEL_ID, configure model_id, or expose "
            "default_model_id on the provider."
        )

    def _provider_name(self, *, config: Mapping[str, Any] | None = None) -> str:
        """Resolve the configured LLM provider name."""

        if self._llm_provider_override is not None:
            provider_name = str(getattr(self._llm_provider_override, "provider_name", "")).strip()
            return provider_name or "injected"
        if self._configured_provider_name:
            return self._configured_provider_name
        env_provider = os.environ.get("CORTEX_LLM_PROVIDER", "").strip()
        if env_provider:
            return env_provider
        config = load_extraction_config() if config is None else config
        config_provider = str(config.get("llm_provider", "")).strip()
        if config_provider:
            return config_provider
        return DEFAULT_PROVIDER_NAME

    def _provider_default_model_id(self) -> str:
        """Return an injected or registered provider's default model id, when available."""

        provider = self._llm_provider()
        default = getattr(provider, "default_model_id", None)
        if callable(default):
            default = default()
        return str(default or "").strip()

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

    def _result_from_typed_payload(self, payload: Any, *, raw_source: str) -> ExtractionResult:
        """Validate typed tool output and convert it into legacy-compatible output."""

        typed_payload = _typed_extraction_adapter().validate_python(payload)
        typed_items = [
            self._memory_item_from_tool_item(tool_item, raw_source=raw_source) for tool_item in typed_payload.items
        ]
        warnings = [warning for warning in typed_payload.warnings if warning.strip()]
        return self._result_from_typed_items(typed_items, warnings=warnings, raw_source=raw_source)

    def _memory_item_from_tool_item(
        self,
        item: _FactToolItem | _ClaimToolItem | _RelationshipToolItem,
        *,
        raw_source: str,
    ) -> ExtractedMemoryItem:
        source_quotes = [quote.strip() for quote in item.source_quotes if quote.strip()]
        source_span = (item.source_span or raw_source[:240]).strip()
        common = {
            "topic": item.topic.strip(),
            "category": self._normalize_category(item.category),
            "brief": item.brief.strip() or item.topic.strip(),
            "full_description": item.full_description.strip(),
            "confidence": float(item.confidence),
            "extraction_method": "model",
            "source_quotes": source_quotes or ([raw_source.strip()] if raw_source.strip() else []),
            "source_span": source_span[:240],
            "extraction_confidence": float(item.extraction_confidence or item.confidence),
            "entity_resolution": (item.entity_resolution or item.node_id).strip(),
            "extraction_flags": [flag.strip() for flag in item.extraction_flags if flag.strip()],
        }
        if isinstance(item, _FactToolItem):
            return ExtractedFact(
                attribute_name=item.attribute_name.strip(),
                attribute_value=item.attribute_value.strip(),
                **common,
            )
        if isinstance(item, _ClaimToolItem):
            return ExtractedClaim(
                assertion=item.assertion.strip(),
                stance=item.stance,
                **common,
            )
        return ExtractedRelationship(
            source_label=item.source_label.strip() or "self",
            relation=item.relation.strip() or "related_to",
            target_label=item.target_label.strip(),
            qualifiers={str(key): str(value) for key, value in item.qualifiers.items()},
            relationship_type=item.relation.strip() or "related_to",
            **common,
        )

    def _result_from_typed_items(
        self,
        typed_items: list[ExtractedMemoryItem],
        *,
        warnings: list[str],
        raw_source: str,
    ) -> ExtractionResult:
        nodes: list[ExtractedNode] = []
        edges: list[ExtractedEdge] = []
        for item in typed_items:
            confidence = float(item.extraction_confidence or item.confidence)
            needs_review = "needs_review" in item.extraction_flags or confidence < 0.6
            if isinstance(item, ExtractedRelationship):
                edges.append(
                    ExtractedEdge(
                        source=item.source_label,
                        target=item.target_label,
                        relationship=item.relation or "related_to",
                        direction_confidence=confidence,
                        needs_review=needs_review,
                    )
                )
                continue
            value = item.full_description or item.brief or item.topic
            if isinstance(item, ExtractedFact):
                value = item.attribute_value or value
            if isinstance(item, ExtractedClaim):
                value = item.assertion or value
            nodes.append(
                ExtractedNode(
                    label=item.topic,
                    category=self._normalize_category(item.category),
                    value=value,
                    confidence=item.confidence,
                    canonical_match=item.entity_resolution or None,
                    match_confidence=confidence,
                    needs_review=needs_review,
                )
            )
        result = ExtractionResult(
            nodes=nodes,
            edges=edges,
            extraction_method="model",
            raw_source=raw_source,
            warnings=warnings,
        )
        result._typed_items = list(typed_items)
        return result

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
