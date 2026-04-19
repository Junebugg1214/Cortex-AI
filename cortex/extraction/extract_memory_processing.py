from __future__ import annotations

from typing import Any

from cortex.extraction.extract_memory_streams import (
    extract_message_stream,
    first_text_from_paths,
    get_message_text,
    is_user_message,
    message_collection,
    parse_timestamp,
)


class AggressiveExtractionProcessingMixin:
    def process_openai_export(self, data: list | dict) -> dict:
        if isinstance(data, list):
            conversations = data
        elif isinstance(data, dict) and "mapping" in data:
            conversations = [data]
        else:
            conversations = data.get("conversations", data.get("items", []))
        for conv in conversations:
            for node in conv.get("mapping", {}).values():
                if not isinstance(node, dict):
                    continue
                message = node.get("message")
                if message and is_user_message(message):
                    self.extract_from_text(get_message_text(message), parse_timestamp(message.get("create_time")))
        self.post_process()
        return self.context.export()

    def process_messages_list(self, messages: list) -> dict:
        for message in messages:
            if is_user_message(message):
                self.extract_from_text(
                    get_message_text(message), parse_timestamp(message.get("timestamp", message.get("created_at")))
                )
        self.post_process()
        return self.context.export()

    def process_plain_text(self, text: str) -> dict:
        for chunk in text.split("\n\n"):
            if len(chunk.strip()) > 20:
                self.extract_from_text(chunk)
        self.post_process()
        return self.context.export()

    def process_gemini_export(self, data: dict) -> dict:
        conversations = data.get("conversations", [])

        for conv in conversations:
            if "turns" in conv:
                for turn in conv["turns"]:
                    if turn.get("role") == "user":
                        self.extract_from_text(
                            turn.get("text", ""), parse_timestamp(turn.get("timestamp", turn.get("create_time")))
                        )
            elif "messages" in conv:
                for msg in conv["messages"]:
                    author = msg.get("author", msg.get("role", ""))
                    if author in ["user", "human"]:
                        content = msg.get("content", msg.get("text", ""))
                        if isinstance(content, list):
                            content = " ".join(
                                p.get("text", str(p)) if isinstance(p, dict) else str(p) for p in content
                            )
                        self.extract_from_text(content, parse_timestamp(msg.get("timestamp", msg.get("create_time"))))

        self.post_process()
        return self.context.export()

    def process_perplexity_export(self, data: dict) -> dict:
        threads = data.get("threads", [])

        for thread in threads:
            for msg in thread.get("messages", []):
                if msg.get("role") == "user":
                    self.extract_from_text(msg.get("content", ""), parse_timestamp(msg.get("created_at")))

        self.post_process()
        return self.context.export()

    def process_grok_export(self, data: list | dict) -> dict:
        conversations = data if isinstance(data, list) else data.get("conversations", data.get("chats", [data]))
        for conv in conversations:
            messages = message_collection(conv, "messages", "items", "entries", "turns")
            extract_message_stream(
                self,
                messages,
                role_keys=("role", "sender", "author", "speaker", "type"),
                user_values=("user", "human", "prompt"),
                content_paths=(
                    ("content",),
                    ("text",),
                    ("body",),
                    ("message",),
                    ("prompt",),
                    ("query",),
                ),
                timestamp_keys=("timestamp", "created_at", "createdAt", "time"),
            )

        self.post_process()
        return self.context.export()

    def process_cursor_export(self, data: list | dict) -> dict:
        conversations = data if isinstance(data, list) else data.get("conversations", data.get("sessions", [data]))
        for conv in conversations:
            messages = message_collection(conv, "bubbles", "messages", "items", "conversation", "chat")
            extract_message_stream(
                self,
                messages,
                role_keys=("type", "role", "speaker", "kind", "author"),
                user_values=("user", "human", "prompt"),
                content_paths=(
                    ("text",),
                    ("content",),
                    ("message",),
                    ("prompt",),
                    ("markdown",),
                    ("body",),
                ),
                timestamp_keys=("timestamp", "created_at", "createdAt", "updatedAt"),
            )

        self.post_process()
        return self.context.export()

    def process_windsurf_export(self, data: list | dict) -> dict:
        conversations = data if isinstance(data, list) else data.get("conversations", data.get("sessions", [data]))
        for conv in conversations:
            messages = message_collection(conv, "timeline", "messages", "entries", "items", "conversation")
            extract_message_stream(
                self,
                messages,
                role_keys=("role", "speaker", "type", "author"),
                user_values=("user", "human", "prompt"),
                content_paths=(
                    ("text",),
                    ("content",),
                    ("message",),
                    ("body",),
                    ("prompt",),
                    ("input",),
                ),
                timestamp_keys=("timestamp", "created_at", "createdAt", "updatedAt"),
            )

        self.post_process()
        return self.context.export()

    def process_copilot_export(self, data: list | dict) -> dict:
        if isinstance(data, list):
            interactions = data
        else:
            interactions = data.get("interactions")
            if interactions is None:
                interactions = data.get("history")
            if interactions is None:
                interactions = data.get("sessions")
            if interactions is None:
                interactions = [data]

        for interaction in interactions:
            if not isinstance(interaction, dict):
                continue
            if "request" in interaction or "prompt" in interaction:
                pseudo_message = {
                    "role": "user",
                    "content": first_text_from_paths(
                        interaction,
                        ("request", "message"),
                        ("request", "content"),
                        ("request", "prompt"),
                        ("prompt",),
                        ("message",),
                        ("content",),
                    ),
                    "created_at": interaction.get(
                        "createdAt", interaction.get("timestamp", interaction.get("created_at"))
                    ),
                }
                extract_message_stream(
                    self,
                    [pseudo_message],
                    role_keys=("role",),
                    user_values=("user",),
                    content_paths=(("content",),),
                    timestamp_keys=("created_at",),
                )
                continue

            messages = message_collection(interaction, "messages", "entries", "items")
            normalized_messages: list[dict[str, Any]] = []
            for message in messages:
                if not isinstance(message, dict):
                    continue
                if "request" in message or "prompt" in message:
                    normalized_messages.append(
                        {
                            "role": "user",
                            "content": first_text_from_paths(
                                message,
                                ("request", "message"),
                                ("request", "content"),
                                ("request", "prompt"),
                                ("prompt",),
                                ("message",),
                                ("content",),
                            ),
                            "created_at": message.get("createdAt", message.get("timestamp", message.get("created_at"))),
                        }
                    )
                    continue
                normalized_messages.append(message)
            extract_message_stream(
                self,
                normalized_messages,
                role_keys=("role", "author", "speaker", "type"),
                user_values=("user", "human", "prompt"),
                content_paths=(
                    ("content",),
                    ("text",),
                    ("message",),
                    ("prompt",),
                    ("body",),
                ),
                timestamp_keys=("timestamp", "created_at", "createdAt"),
            )

        self.post_process()
        return self.context.export()

    def process_jsonl_messages(self, messages: list) -> dict:
        for msg in messages:
            if is_user_message(msg):
                self.extract_from_text(
                    get_message_text(msg), parse_timestamp(msg.get("timestamp", msg.get("created_at")))
                )

        self.post_process()
        return self.context.export()

    def process_api_logs(self, data: dict) -> dict:
        requests = data.get("requests", [])

        for req in requests:
            messages = req.get("messages", [])
            for msg in messages:
                if msg.get("role") in ["user", "human"]:
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(
                            block.get("text", "")
                            for block in content
                            if isinstance(block, dict) and block.get("type") == "text"
                        )
                    self.extract_from_text(content, parse_timestamp(req.get("timestamp", req.get("created_at"))))

        self.post_process()
        return self.context.export()
