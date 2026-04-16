from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Mapping

try:  # pragma: no cover - Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib

from cortex.extract_memory_processing import AggressiveExtractionProcessingMixin

from .types import ExtractedNode, ExtractionResult


class ExtractionBackendError(RuntimeError):
    """Raised when a configured extraction backend cannot run."""


class ExtractionParseError(ExtractionBackendError):
    """Raised when a backend returns malformed structured output."""

    def __init__(self, message: str, *, raw_response: str = "") -> None:
        super().__init__(message)
        self.raw_response = raw_response


class ExtractionBackend(ABC):
    """Abstract extraction backend interface."""

    @abstractmethod
    def extract_statement(
        self,
        text: str,
        context: dict | None = None,
    ) -> ExtractionResult:
        """Extract graph facts from one statement."""

    @abstractmethod
    def extract_bulk(
        self,
        texts: list[str],
        context: dict | None = None,
    ) -> list[ExtractionResult]:
        """Extract graph facts from a batch of statements."""

    @abstractmethod
    def canonical_match(
        self,
        node: ExtractedNode,
        existing_nodes: list[dict],
    ) -> tuple[str | None, float]:
        """Resolve a candidate node to an existing canonical node id."""

    @property
    @abstractmethod
    def supports_async_rescoring(self) -> bool:
        """Return true when the backend supports asynchronous rescoring."""

    @property
    @abstractmethod
    def supports_embeddings(self) -> bool:
        """Return true when the backend emits embeddings."""


def _safe_load_toml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_extraction_config(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Load the optional `[extraction]` config table from Cortex config.toml."""

    env_map = env or os.environ
    explicit_path = env_map.get("CORTEX_CONFIG", "").strip()
    if explicit_path:
        extraction = _safe_load_toml(Path(explicit_path)).get("extraction", {})
        return extraction if isinstance(extraction, dict) else {}

    explicit_store = env_map.get("CORTEX_STORE_DIR", "").strip()
    if explicit_store:
        extraction = _safe_load_toml(Path(explicit_store) / "config.toml").get("extraction", {})
        return extraction if isinstance(extraction, dict) else {}

    for candidate in (Path.cwd() / ".cortex" / "config.toml", Path.cwd() / "config.toml"):
        extraction = _safe_load_toml(candidate).get("extraction", {})
        if isinstance(extraction, dict) and extraction:
            return extraction
        if candidate.exists():
            return {}

    try:
        from cortex.config import load_selfhost_config

        config = load_selfhost_config(env=env_map)
    except Exception:
        return {}

    payload = _safe_load_toml(config.config_path)
    extraction = payload.get("extraction", {})
    return extraction if isinstance(extraction, dict) else {}


class _NullExportContext:
    """Lightweight stand-in for collection-only processing passes."""

    def export(self) -> dict[str, Any]:
        """Return an empty v4-like payload."""

        return {}


class BulkTextCollector(AggressiveExtractionProcessingMixin):
    """Collect flattened user text with the existing processing router."""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.context = _NullExportContext()

    def extract_from_text(self, text: str, timestamp: object | None = None) -> None:
        """Collect emitted text chunks while ignoring timestamps."""

        if text and text.strip():
            self.texts.append(text)

    def post_process(self) -> None:
        """No-op hook required by the processing mixin."""


def collect_bulk_texts(data: Any, fmt: str) -> list[str]:
    """Flatten parsed export data into user-authored text chunks."""

    collector = BulkTextCollector()
    if fmt == "openai":
        collector.process_openai_export(data)
    elif fmt == "gemini":
        collector.process_gemini_export(data)
    elif fmt == "perplexity":
        collector.process_perplexity_export(data)
    elif fmt == "grok":
        collector.process_grok_export(data)
    elif fmt == "cursor":
        collector.process_cursor_export(data)
    elif fmt == "windsurf":
        collector.process_windsurf_export(data)
    elif fmt == "copilot":
        collector.process_copilot_export(data)
    elif fmt in ("jsonl", "claude_code"):
        collector.process_jsonl_messages(data)
    elif fmt == "api_logs":
        collector.process_api_logs(data)
    elif fmt == "messages":
        collector.process_messages_list(data)
    elif fmt == "text":
        collector.process_plain_text(data)
    else:
        if isinstance(data, list):
            collector.process_messages_list(data)
        elif isinstance(data, dict) and "messages" in data:
            collector.process_messages_list(data["messages"])
        else:
            collector.process_plain_text(json.dumps(data) if not isinstance(data, str) else data)
    return list(collector.texts)
