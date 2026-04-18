from __future__ import annotations

import pytest

from cortex.extraction import Document, ExtractedFact, ExtractionContext, ModelBackend
from cortex.extraction.model_backend import _TYPED_EXTRACTION_TOOL_NAME


class _Usage:
    input_tokens = 10
    output_tokens = 5


class _ToolBlock:
    type = "tool_use"
    name = _TYPED_EXTRACTION_TOOL_NAME

    def __init__(self, tool_input: dict) -> None:
        self.input = tool_input


class _Response:
    usage = _Usage()
    model = "claude-3-5-sonnet-20241022"

    def __init__(self, payload: dict) -> None:
        self.content = [_ToolBlock(payload)]


class _Messages:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.payloads.pop(0))


def _install_stubbed_client(monkeypatch: pytest.MonkeyPatch, backend: ModelBackend, payloads: list[dict]) -> _Messages:
    messages = _Messages(payloads)

    class _Client:
        def __init__(self, *, api_key: str) -> None:
            self.api_key = api_key
            self.messages = messages

    monkeypatch.setattr(backend, "_anthropic_client_cls", lambda: _Client)
    return messages


def _valid_fact_payload(topic: str = "Python") -> dict:
    return {
        "items": [
            {
                "extraction_type": "fact",
                "topic": topic,
                "category": "technical_expertise",
                "brief": f"Uses {topic}",
                "confidence": 0.91,
                "attribute_name": "skill",
                "attribute_value": topic,
            }
        ],
        "warnings": [],
    }


def _invalid_fact_payload() -> dict:
    return {
        "items": [
            {
                "extraction_type": "fact",
                "topic": "Python",
                "category": "technical_expertise",
                "attribute_name": "skill",
            }
        ],
        "warnings": [],
    }


def _run_backend(backend: ModelBackend):
    return backend.run(
        Document(source_id="schema-doc", source_type="chat", content="I use Python."),
        ExtractionContext(prompt_version="schema-v1"),
    )


def test_model_backend_accepts_valid_schema_tool_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CORTEX_EXTRACTION_LOG_PATH", str(tmp_path / "extractions.jsonl"))
    backend = ModelBackend(api_key="test-key")
    messages = _install_stubbed_client(monkeypatch, backend, [_valid_fact_payload()])

    result = _run_backend(backend)

    assert len(result.items) == 1
    assert isinstance(result.items[0], ExtractedFact)
    assert result.items[0].attribute_value == "Python"
    assert result.diagnostics.warnings == []
    call = messages.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": _TYPED_EXTRACTION_TOOL_NAME}
    assert call["tools"][0]["input_schema"]["type"] == "object"


def test_model_backend_retries_invalid_then_accepts_valid_schema_tool_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CORTEX_EXTRACTION_LOG_PATH", str(tmp_path / "extractions.jsonl"))
    backend = ModelBackend(api_key="test-key")
    messages = _install_stubbed_client(monkeypatch, backend, [_invalid_fact_payload(), _valid_fact_payload()])

    result = _run_backend(backend)

    assert len(result.items) == 1
    assert result.diagnostics.warnings == []
    assert len(messages.calls) == 2
    retry_messages = messages.calls[1]["messages"]
    assert any("Validation error" in item["content"] for item in retry_messages if item["role"] == "user")


def test_model_backend_returns_empty_items_after_three_schema_failures(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CORTEX_EXTRACTION_LOG_PATH", str(tmp_path / "extractions.jsonl"))
    backend = ModelBackend(api_key="test-key")
    messages = _install_stubbed_client(
        monkeypatch,
        backend,
        [_invalid_fact_payload(), _invalid_fact_payload(), _invalid_fact_payload()],
    )

    result = _run_backend(backend)

    assert result.items == []
    assert result.diagnostics.warnings == ["schema_violation"]
    assert len(messages.calls) == 3
