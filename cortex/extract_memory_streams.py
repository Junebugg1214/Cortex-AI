from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol


class MessageExtractor(Protocol):
    def extract_from_text(self, text: str, timestamp: datetime | None = None) -> None: ...


def parse_timestamp(ts: Any) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, TypeError, OSError, OverflowError):
            return None
    if isinstance(ts, str):
        for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
            try:
                return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
    return None


def is_user_message(message: dict) -> bool:
    role = message.get("role", "")
    if not role:
        author = message.get("author", {})
        if isinstance(author, dict):
            role = author.get("role", "")
        elif isinstance(author, str):
            role = author
    if not role:
        role = message.get("type", "")
    return str(role).lower() in ["user", "human"]


def get_message_text(message: dict) -> str:
    if "content" in message:
        content = message["content"]
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            parts = content.get("parts", [])
            if parts:
                return " ".join(str(part) for part in parts if isinstance(part, str))
            nested_content = content.get("content")
            if nested_content is not None:
                return get_message_text({"content": nested_content})
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and "text" in part:
                    parts.append(part["text"])
            return " ".join(parts)
    if "text" in message:
        return message["text"]
    if "message" in message:
        nested_message = message["message"]
        if isinstance(nested_message, dict):
            return get_message_text(nested_message)
        return get_message_text({"content": nested_message})
    return ""


def get_message_role(message: dict, *keys: str) -> str:
    for key in keys:
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, dict):
            nested = value.get("role") or value.get("type") or value.get("name")
            if isinstance(nested, str) and nested.strip():
                return nested
    return ""


def get_message_timestamp(message: dict, *keys: str) -> datetime | None:
    for key in keys:
        value = message.get(key)
        if value:
            parsed = parse_timestamp(value)
            if parsed is not None:
                return parsed
    return None


def get_nested_value(data: Any, path: tuple[str, ...]) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def flatten_text_payload(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [flatten_text_payload(item) for item in value]
        return " ".join(part.strip() for part in parts if part and part.strip())
    if isinstance(value, dict):
        preferred_keys = (
            "text",
            "content",
            "message",
            "body",
            "prompt",
            "input",
            "query",
            "markdown",
            "value",
            "parts",
            "chunks",
            "segments",
            "items",
        )
        for key in preferred_keys:
            if key in value:
                text = flatten_text_payload(value[key])
                if text:
                    return text
        if value.get("type") == "text" and "text" in value:
            return flatten_text_payload(value["text"])
    return ""


def first_text_from_paths(message: dict, *paths: tuple[str, ...]) -> str:
    for path in paths:
        text = flatten_text_payload(get_nested_value(message, path))
        if text:
            return text
    return ""


def extract_message_stream(
    extractor: MessageExtractor,
    messages: list[dict],
    *,
    role_keys: tuple[str, ...],
    user_values: tuple[str, ...],
    content_paths: tuple[tuple[str, ...], ...],
    timestamp_keys: tuple[str, ...],
) -> None:
    allowed_roles = {value.lower() for value in user_values}
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = get_message_role(message, *role_keys).lower()
        if role not in allowed_roles:
            continue
        text = first_text_from_paths(message, *content_paths)
        if not text:
            text = get_message_text(message)
        if not text:
            continue
        extractor.extract_from_text(text, get_message_timestamp(message, *timestamp_keys))


def message_collection(container: Any, *keys: str) -> list[dict]:
    if isinstance(container, list):
        return [item for item in container if isinstance(item, dict)]
    if not isinstance(container, dict):
        return []
    for key in keys:
        value = container.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if any(
        key in container
        for key in ("role", "author", "sender", "speaker", "type", "content", "text", "message", "prompt")
    ):
        return [container]
    return []


__all__ = [
    "extract_message_stream",
    "first_text_from_paths",
    "flatten_text_payload",
    "get_message_role",
    "get_message_text",
    "get_message_timestamp",
    "get_nested_value",
    "is_user_message",
    "message_collection",
    "parse_timestamp",
]
