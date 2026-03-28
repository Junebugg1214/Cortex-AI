from __future__ import annotations

from pathlib import Path

import cortex.channel_runtime as channel_runtime
from cortex.channel_runtime import (
    ChannelContextBridge,
    ChannelMessage,
    TelegramAdapter,
    WhatsAppAdapter,
)


class _StubService:
    def __init__(self, store_dir: Path) -> None:
        self.store_dir = store_dir
        self.calls: list[dict] = []

    def portability_context(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "ok", "context": "portable context", "target": kwargs["target"]}


def test_cross_platform_phone_identity_shares_subject_namespace():
    telegram = ChannelMessage(
        platform="telegram",
        workspace_id="bot-main",
        conversation_id="telegram-chat-1",
        user_id="tg-123",
        text="hello",
        phone_number="+1 (555) 123-4567",
        display_name="Marc",
    )
    whatsapp = ChannelMessage(
        platform="whatsapp",
        workspace_id="bot-main",
        conversation_id="wa-chat-9",
        user_id="wa-999",
        text="hi",
        phone_number="+1 555 123 4567",
        display_name="Marc",
    )

    tg_identity = TelegramAdapter().resolve_identity(telegram)
    wa_identity = WhatsAppAdapter().resolve_identity(whatsapp)

    assert tg_identity.identity_type == "phone_number"
    assert wa_identity.identity_type == "phone_number"
    assert tg_identity.subject_key == wa_identity.subject_key
    assert tg_identity.subject_namespace == wa_identity.subject_namespace
    assert tg_identity.subject_namespace.startswith("people/phone_number/")
    assert tg_identity.conversation_namespace != wa_identity.conversation_namespace


def test_platform_only_identity_stays_channel_scoped():
    telegram = ChannelMessage(
        platform="telegram",
        workspace_id="bot-main",
        conversation_id="telegram-chat-1",
        user_id="tg-123",
        text="hello",
    )
    whatsapp = ChannelMessage(
        platform="whatsapp",
        workspace_id="bot-main",
        conversation_id="wa-chat-9",
        user_id="wa-123",
        text="hi",
    )

    tg_identity = TelegramAdapter().resolve_identity(telegram)
    wa_identity = WhatsAppAdapter().resolve_identity(whatsapp)

    assert tg_identity.identity_type == "external_user_id"
    assert wa_identity.identity_type == "external_user_id"
    assert tg_identity.subject_namespace.startswith("channels/telegram/")
    assert wa_identity.subject_namespace.startswith("channels/whatsapp/")
    assert tg_identity.subject_namespace != wa_identity.subject_namespace


def test_prepare_turn_returns_context_request_and_memory_operations(tmp_path):
    service = _StubService(tmp_path / ".cortex")
    bridge = ChannelContextBridge(service, default_project_dir=tmp_path)
    message = ChannelMessage(
        platform="telegram",
        workspace_id="support-bot",
        conversation_id="chat-42",
        user_id="user-1",
        text="Can you help?",
        display_name="Casey",
        phone_number="+15550101",
    )

    envelope = bridge.prepare_turn(message, smart=True, max_chars=900)

    assert envelope.target == "chatgpt"
    assert envelope.context["context"] == "portable context"
    assert service.calls == [
        {
            "target": "chatgpt",
            "project_dir": str(tmp_path),
            "smart": True,
            "max_chars": 900,
        }
    ]
    assert envelope.portability_tool_request["name"] == "portability_context"
    assert envelope.portability_tool_request["arguments"]["target"] == "chatgpt"
    assert len(envelope.suggested_memory_operations) == 3
    namespaces = {item["namespace"] for item in envelope.suggested_memory_operations}
    assert any(namespace.startswith("people/phone_number/") for namespace in namespaces)


def test_remember_global_fact_delegates_to_portability_runtime(tmp_path, monkeypatch):
    service = _StubService(tmp_path / ".cortex")
    bridge = ChannelContextBridge(service, default_project_dir=tmp_path)
    captured: dict = {}

    def _fake_remember(statement: str, **kwargs):
        captured["statement"] = statement
        captured.update(kwargs)
        return {"status": "ok", "statement": statement}

    monkeypatch.setattr(channel_runtime, "remember_and_sync", _fake_remember)

    payload = bridge.remember_global_fact(
        "The support bot should escalate billing issues.",
        smart=True,
        targets=["chatgpt", "claude"],
    )

    assert payload["status"] == "ok"
    assert captured["statement"] == "The support bot should escalate billing issues."
    assert captured["store_dir"] == service.store_dir
    assert captured["project_dir"] == tmp_path
    assert captured["targets"] == ["chatgpt", "claude"]
    assert captured["smart"] is True
