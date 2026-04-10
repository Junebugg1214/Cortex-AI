from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any

_STRUCTURED_COLLECTION_KEYS = (
    "messages",
    "items",
    "entries",
    "timeline",
    "bubbles",
    "history",
    "interactions",
    "sessions",
    "conversations",
    "chats",
    "chat",
    "conversation",
)
_ZIP_ENTRY_SIZE_LIMIT = 100 * 1024 * 1024  # 100 MB limit (#26)
_ZIP_FORMAT_PRIORITIES = {
    "openai": 70,
    "gemini": 60,
    "perplexity": 60,
    "cursor": 58,
    "windsurf": 58,
    "copilot": 58,
    "grok": 58,
    "claude_code": 55,
    "api_logs": 50,
    "messages": 40,
    "jsonl": 35,
    "generic": 20,
    "text": 10,
}


def detect_platform_record(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    if "composerId" in record or "bubbleId" in record:
        return "cursor"
    if "cascadeId" in record or "workspaceId" in record or "timelineId" in record:
        return "windsurf"
    if "copilotSessionId" in record or "request" in record:
        return "copilot"
    if "conversationId" in record and any(key in record for key in ("sender", "content", "text", "prompt")):
        return "grok"
    return None


def detect_platform_shape(value: Any, *, depth: int = 0) -> str | None:
    if depth > 2:
        return None
    detected = detect_platform_record(value)
    if detected is not None:
        return detected
    if isinstance(value, dict):
        for key in _STRUCTURED_COLLECTION_KEYS:
            if key not in value:
                continue
            detected = detect_platform_shape(value[key], depth=depth + 1)
            if detected is not None:
                return detected
        return None
    if isinstance(value, list):
        for item in value[:5]:
            detected = detect_platform_shape(item, depth=depth + 1)
            if detected is not None:
                return detected
    return None


def detect_json_format(data: Any, source_name: str = "") -> tuple[Any, str]:
    source_name_lower = source_name.lower()

    def hinted(*names: str) -> bool:
        return any(name in source_name_lower for name in names)

    if isinstance(data, list) and data and isinstance(data[0], dict) and "mapping" in data[0]:
        return data, "openai"
    if isinstance(data, dict) and ("conversations" in data or "mapping" in data):
        if "mapping" in data:
            return data, "openai"
        conversations = data.get("conversations", [])
        if conversations and isinstance(conversations, list) and conversations[0] and "mapping" in conversations[0]:
            return data, "openai"

    if isinstance(data, dict):
        if (
            "composerId" in data
            or "bubbles" in data
            or (hinted("cursor") and any(key in data for key in ("chat", "conversation", "messages")))
        ):
            return data, "cursor"
        if "cascadeId" in data or ("timeline" in data and ("workspace" in data or hinted("windsurf", "codeium"))):
            return data, "windsurf"
        if "interactions" in data or (
            hinted("copilot") and any(key in data for key in ("history", "sessions", "messages"))
        ):
            return data, "copilot"
        if hinted("grok", "xai") and any(key in data for key in ("conversations", "chats", "messages", "items")):
            return data, "grok"
    if isinstance(data, list) and data and isinstance(data[0], dict):
        first = data[0]
        if hinted("cursor") and any(key in first for key in ("composerId", "bubbleId", "prompt", "markdown", "text")):
            return data, "cursor"
        if hinted("windsurf", "codeium") and any(
            key in first for key in ("cascadeId", "workspaceId", "timelineId", "prompt", "text")
        ):
            return data, "windsurf"
        if hinted("copilot") and any(key in first for key in ("request", "prompt", "message", "copilotSessionId")):
            return data, "copilot"
        if hinted("grok", "xai") and any(
            key in first for key in ("sender", "conversationId", "prompt", "text", "content")
        ):
            return data, "grok"

    if isinstance(data, dict) and "threads" in data:
        threads = data["threads"]
        if threads and isinstance(threads[0], dict) and "messages" in threads[0]:
            return data, "perplexity"

    if isinstance(data, dict) and "conversations" in data:
        conversations = data["conversations"]
        if conversations and isinstance(conversations[0], dict):
            first_conversation = conversations[0]
            if "turns" in first_conversation:
                return data, "gemini"
            if "messages" in first_conversation:
                messages = first_conversation["messages"]
                if messages and isinstance(messages[0], dict) and messages[0].get("author") in ["user", "model"]:
                    return data, "gemini"

    detected_platform = detect_platform_shape(data)
    if detected_platform is not None:
        return data, detected_platform

    if isinstance(data, dict) and "requests" in data:
        return data, "api_logs"
    if isinstance(data, list) and data and isinstance(data[0], dict) and "messages" in data[0] and "model" in data[0]:
        return {"requests": data}, "api_logs"

    if isinstance(data, dict) and "messages" in data:
        return data.get("messages", []), "messages"

    if isinstance(data, list) and data and isinstance(data[0], dict):
        first = data[0]
        if first.get("type") in ("user", "assistant", "system") and "sessionId" in first and "cwd" in first:
            return data, "claude_code"
        if "role" in first or "author" in first or "type" in first:
            return data, "messages"

    return data, "generic"


def detect_jsonl_format(messages: list[dict], source_name: str = "") -> tuple[Any, str]:
    source_name_lower = source_name.lower()

    def hinted(*names: str) -> bool:
        return any(name in source_name_lower for name in names)

    if messages:
        first_real = next(
            (
                record
                for record in messages
                if isinstance(record, dict) and record.get("type") in ("user", "assistant", "system")
            ),
            None,
        )
        if first_real is not None and "sessionId" in first_real and "cwd" in first_real:
            return messages, "claude_code"
        detected_platform = detect_platform_shape(messages)
        if detected_platform is not None:
            return messages, detected_platform
        if first_real is not None:
            if hinted("cursor") and any(key in first_real for key in ("composerId", "bubbleId", "markdown", "prompt")):
                return messages, "cursor"
            if hinted("windsurf", "codeium") and any(
                key in first_real for key in ("cascadeId", "workspaceId", "timelineId", "prompt")
            ):
                return messages, "windsurf"
            if hinted("copilot") and any(
                key in first_real for key in ("request", "copilotSessionId", "prompt", "message")
            ):
                return messages, "copilot"
            if hinted("grok", "xai") and any(
                key in first_real for key in ("sender", "conversationId", "prompt", "content")
            ):
                return messages, "grok"
    return messages, "jsonl"


def load_jsonl_stream(handle) -> list[dict]:
    messages = []
    for raw_line in handle:
        if isinstance(raw_line, bytes):
            raw_line = raw_line.decode("utf-8")
        line = raw_line.strip()
        if not line:
            continue
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return messages


def _load_from_zip(file_path: Path) -> tuple[Any, str]:
    with zipfile.ZipFile(file_path, "r") as zip_file:
        best_payload: tuple[Any, str] | None = None
        best_priority = -1

        def consider(payload: tuple[Any, str]) -> None:
            nonlocal best_payload, best_priority
            _data, fmt = payload
            priority = _ZIP_FORMAT_PRIORITIES.get(fmt, 0)
            if priority > best_priority:
                best_priority = priority
                best_payload = payload

        for name in zip_file.namelist():
            if ".." in name or os.path.isabs(name):
                continue
            info = zip_file.getinfo(name)
            if info.file_size > _ZIP_ENTRY_SIZE_LIMIT:
                continue
            if name.endswith(".json"):
                with zip_file.open(name) as handle:
                    try:
                        consider(detect_json_format(json.load(handle), name))
                    except json.JSONDecodeError:
                        continue
                continue
            if name.endswith(".jsonl"):
                with zip_file.open(name) as handle:
                    consider(detect_jsonl_format(load_jsonl_stream(handle), name))
                continue
            if name.endswith((".txt", ".md")):
                with zip_file.open(name) as handle:
                    consider((handle.read().decode("utf-8"), "text"))

        if best_payload is not None:
            return best_payload
    raise ValueError("No supported files in zip")


def load_file(file_path: Path) -> tuple[Any, str]:
    if file_path.suffix == ".zip":
        return _load_from_zip(file_path)

    if file_path.suffix == ".jsonl":
        with open(file_path, "r", encoding="utf-8") as handle:
            return detect_jsonl_format(load_jsonl_stream(handle), file_path.name)

    if file_path.suffix == ".json":
        with open(file_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return detect_json_format(data, file_path.name)

    if file_path.suffix in [".txt", ".md"]:
        with open(file_path, "r", encoding="utf-8") as handle:
            return handle.read(), "text"
    raise ValueError(f"Unsupported format: {file_path.suffix}")


__all__ = [
    "detect_json_format",
    "detect_jsonl_format",
    "detect_platform_record",
    "detect_platform_shape",
    "load_file",
    "load_jsonl_stream",
]
