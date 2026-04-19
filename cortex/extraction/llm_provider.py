from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from time import perf_counter
from typing import Any, Callable, Protocol

DEFAULT_PROVIDER_NAME = "anthropic"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"


@dataclass(frozen=True)
class LLMProviderResponse:
    """Provider response plus request latency measured at the provider boundary."""

    response: Any
    latency_ms: float


class StructuredLLMProvider(Protocol):
    """Minimal provider contract for schema-constrained extraction calls."""

    provider_name: str
    default_model_id: str | None

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


class LLMProviderError(RuntimeError):
    """Raised when a configured LLM provider cannot be loaded."""


ProviderFactory = Callable[[], StructuredLLMProvider]
_PROVIDER_FACTORIES: dict[str, ProviderFactory] = {}


def register_llm_provider(name: str, factory: ProviderFactory) -> None:
    """Register an in-process provider factory for ModelBackend."""

    normalized = _normalize_provider_name(name)
    if not normalized or normalized == DEFAULT_PROVIDER_NAME:
        raise LLMProviderError("Custom LLM providers must use a non-empty, non-default name.")
    if not callable(factory):
        raise LLMProviderError(f"LLM provider '{name}' factory must be callable.")
    _PROVIDER_FACTORIES[normalized] = factory


def create_registered_llm_provider(name: str) -> StructuredLLMProvider:
    """Create a non-default provider from the registry or a module:function reference."""

    normalized = _normalize_provider_name(name)
    if not normalized or normalized == DEFAULT_PROVIDER_NAME:
        raise LLMProviderError("The default Anthropic provider is constructed by ModelBackend.")
    factory = _PROVIDER_FACTORIES.get(normalized)
    if factory is None and ":" in normalized:
        module_name, attr_name = normalized.split(":", 1)
        try:
            module = import_module(module_name)
            factory = getattr(module, attr_name)
        except (ImportError, AttributeError) as exc:
            raise LLMProviderError(f"Unable to load LLM provider '{name}': {exc}") from exc
    if factory is None:
        valid = ", ".join(sorted(_PROVIDER_FACTORIES)) or "none"
        raise LLMProviderError(
            f"Unknown LLM provider '{name}'. Use '{DEFAULT_PROVIDER_NAME}', register a provider, "
            "or pass a module:function reference. Registered providers: "
            f"{valid}."
        )
    if not callable(factory):
        raise LLMProviderError(f"LLM provider '{name}' factory must be callable.")
    try:
        provider = factory()
    except Exception as exc:
        raise LLMProviderError(f"Unable to create LLM provider '{name}': {exc}") from exc
    _validate_provider(provider, name=normalized)
    return provider


def _validate_provider(provider: Any, *, name: str) -> None:
    for method_name in ("create_message", "create_tool_message"):
        if not callable(getattr(provider, method_name, None)):
            raise LLMProviderError(f"LLM provider '{name}' is missing required method {method_name}().")
    provider_name = str(getattr(provider, "provider_name", "")).strip()
    if not provider_name:
        raise LLMProviderError(f"LLM provider '{name}' must expose provider_name.")


def _normalize_provider_name(name: str) -> str:
    return str(name or "").strip()


class AnthropicLLMProvider:
    """Anthropic Messages API adapter for the provider contract."""

    provider_name = "anthropic"
    default_model_id = DEFAULT_ANTHROPIC_MODEL

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
