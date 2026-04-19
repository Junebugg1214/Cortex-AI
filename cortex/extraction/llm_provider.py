from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class LLMProviderResponse:
    """Provider response plus request latency measured at the provider boundary."""

    response: Any
    latency_ms: float


class StructuredLLMProvider(Protocol):
    """Minimal provider contract for schema-constrained extraction calls."""

    provider_name: str

    def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
    ) -> LLMProviderResponse:
        """Create a plain text message response."""

    def create_tool_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any],
    ) -> LLMProviderResponse:
        """Create a tool-constrained structured message response."""


class AnthropicLLMProvider:
    """Anthropic Messages API adapter for the provider contract."""

    provider_name = "anthropic"

    def __init__(self, *, api_key: str, client_cls: Callable[[], Any]) -> None:
        self._client = client_cls()(api_key=api_key)

    def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
    ) -> LLMProviderResponse:
        started = perf_counter()
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return LLMProviderResponse(response=response, latency_ms=(perf_counter() - started) * 1000.0)

    def create_tool_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any],
    ) -> LLMProviderResponse:
        started = perf_counter()
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        return LLMProviderResponse(response=response, latency_ms=(perf_counter() - started) * 1000.0)
