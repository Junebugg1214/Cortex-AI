from __future__ import annotations

from cortex.extraction import Document, ExtractionContext, ModelBackend
from cortex.extraction.eval.replay_cache import ReplayCache, replay_mode_from_env
from cortex.extraction.model_backend import _TYPED_EXTRACTION_TOOL_NAME


class _Usage:
    input_tokens = 12
    output_tokens = 7


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
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def create(self, **_kwargs):
        self.calls += 1
        return _Response(self.payload)


def _valid_fact_payload() -> dict:
    return {
        "items": [
            {
                "extraction_type": "fact",
                "topic": "Python",
                "category": "technical_expertise",
                "brief": "Uses Python",
                "confidence": 0.91,
                "attribute_name": "skill",
                "attribute_value": "Python",
            }
        ],
        "warnings": [],
    }


def _run_backend(backend: ModelBackend):
    return backend.run(
        Document(source_id="cache-doc", source_type="doc", content="I use Python."),
        ExtractionContext(prompt_version="cache-v1"),
    )


def test_second_call_hits_cache_without_network(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CORTEX_EXTRACTION_LOG_PATH", str(tmp_path / "extractions.jsonl"))
    cache_root = tmp_path / "replay"
    messages = _Messages(_valid_fact_payload())

    class _Client:
        def __init__(self, *, api_key: str) -> None:
            self.api_key = api_key
            self.messages = messages

    writer = ModelBackend(api_key="test-key", replay_cache=ReplayCache(root=cache_root, mode="write"))
    monkeypatch.setattr(writer, "_anthropic_client_cls", lambda: _Client)

    first = _run_backend(writer)

    assert messages.calls == 1
    assert len(first.items) == 1
    assert first.diagnostics.cache_hit is False
    assert list(cache_root.glob("*.json"))

    reader = ModelBackend(api_key="test-key", replay_cache=ReplayCache(root=cache_root, mode="read"))

    def _network_forbidden():
        raise AssertionError("network should not be used on replay cache hit")

    monkeypatch.setattr(reader, "_anthropic_client_cls", _network_forbidden)

    second = _run_backend(reader)

    assert messages.calls == 1
    assert len(second.items) == 1
    assert second.items[0].topic == "Python"
    assert second.diagnostics.cache_hit is True
    assert second.diagnostics.cost_usd == 0.0


def test_replay_mode_defaults_to_read_in_ci_and_off_in_dev() -> None:
    assert replay_mode_from_env({"CI": "true"}) == "read"
    assert replay_mode_from_env({}) == "off"
    assert replay_mode_from_env({"CORTEX_EXTRACTION_REPLAY": "write"}) == "write"
