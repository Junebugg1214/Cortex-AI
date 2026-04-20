from __future__ import annotations

from pathlib import Path

import cortex.channel_runtime as channel_runtime
from cortex.channel_runtime import (
    ChannelContextBridge,
    ChannelMessage,
    TelegramAdapter,
    WhatsAppAdapter,
)
from cortex.service.service import MemoryService
from cortex.storage import get_storage_backend


class _StubService:
    def __init__(self, store_dir: Path) -> None:
        self.store_dir = store_dir
        self.calls: list[dict] = []

    def portability_context(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "ok", "context": "portable context", "target": kwargs["target"]}


def _real_service(store_dir: Path) -> MemoryService:
    backend = get_storage_backend(store_dir)
    return MemoryService(store_dir=store_dir, backend=backend)


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
    assert tg_identity.subject_root_namespace == wa_identity.subject_root_namespace
    assert tg_identity.subject_namespace.startswith("people/phone_number/")
    assert tg_identity.subject_namespace.endswith("/profile")
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


def test_conversation_fallback_prevents_blank_user_collapse():
    first = ChannelMessage(
        platform="telegram",
        workspace_id="bot-main",
        conversation_id="chat-1",
        user_id="",
        text="hello",
    )
    second = ChannelMessage(
        platform="telegram",
        workspace_id="bot-main",
        conversation_id="chat-2",
        user_id="",
        text="hello",
    )

    first_identity = TelegramAdapter().resolve_identity(first)
    second_identity = TelegramAdapter().resolve_identity(second)

    assert first_identity.identity_type == "conversation_fallback"
    assert second_identity.identity_type == "conversation_fallback"
    assert first_identity.subject_namespace != second_identity.subject_namespace


def test_event_fallback_uses_message_metadata_when_ids_are_missing():
    first = ChannelMessage(
        platform="discord",
        workspace_id="support-bot",
        conversation_id="",
        user_id="",
        text="Need help",
        metadata={"message_id": "m-1"},
    )
    second = ChannelMessage(
        platform="discord",
        workspace_id="support-bot",
        conversation_id="",
        user_id="",
        text="Need help",
        metadata={"message_id": "m-2"},
    )

    first_identity = channel_runtime.adapter_for_platform(first.platform).resolve_identity(first)
    second_identity = channel_runtime.adapter_for_platform(second.platform).resolve_identity(second)

    assert first_identity.identity_type == "event_fallback"
    assert second_identity.identity_type == "event_fallback"
    assert first_identity.subject_namespace != second_identity.subject_namespace
    assert first_identity.conversation_namespace != second_identity.conversation_namespace


def test_missing_conversation_id_falls_back_to_same_user_thread():
    first = ChannelMessage(
        platform="whatsapp",
        workspace_id="support-bot",
        conversation_id="",
        user_id="wa-123",
        text="hello",
    )
    second = ChannelMessage(
        platform="whatsapp",
        workspace_id="support-bot",
        conversation_id="",
        user_id="wa-123",
        text="follow up",
    )

    first_identity = WhatsAppAdapter().resolve_identity(first)
    second_identity = WhatsAppAdapter().resolve_identity(second)

    assert first_identity.subject_namespace == second_identity.subject_namespace
    assert first_identity.conversation_namespace == second_identity.conversation_namespace


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
    assert len(envelope.write_plan) == 2
    assert {batch.namespace for batch in envelope.write_plan} == {
        envelope.identity.subject_namespace,
        envelope.identity.conversation_namespace,
    }
    assert len(envelope.suggested_memory_operations) == 4
    namespaces = {item["namespace"] for item in envelope.suggested_memory_operations}
    assert any(namespace.startswith("people/phone_number/") for namespace in namespaces)


def test_prepare_turn_falls_back_to_generic_channel_adapter(tmp_path):
    service = _StubService(tmp_path / ".cortex")
    bridge = ChannelContextBridge(service, default_project_dir=tmp_path)
    message = ChannelMessage(
        platform="discord",
        workspace_id="support-bot",
        conversation_id="thread-9",
        user_id="discord-user-1",
        text="Need help",
        username="casey_dev",
    )

    envelope = bridge.prepare_turn(message, smart=True)

    assert envelope.identity.platform == "discord"
    assert envelope.identity.subject_namespace.startswith("channels/discord/")
    assert envelope.identity.subject_namespace.endswith("/profile")
    assert envelope.identity.conversation_namespace.startswith(envelope.identity.subject_root_namespace + "/threads/")


def test_seed_turn_memory_applies_executable_namespaced_batches(tmp_path, monkeypatch):
    service = _real_service(tmp_path / ".cortex")
    monkeypatch.setattr(
        MemoryService,
        "portability_context",
        lambda self, **kwargs: {"status": "ok", "context": "portable context", "target": kwargs["target"]},
    )
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

    envelope = bridge.prepare_turn(message, smart=True)
    result = bridge.seed_turn_memory(envelope)

    assert result["status"] == "ok"
    assert len(result["batches"]) == 2
    assert service.backend.versions.current_branch() == "main"

    subject_node_id = f"contact/{envelope.identity.subject_key}"
    thread_node_id = f"thread/{envelope.identity.conversation_key}"

    subject_node = service.get_node(
        node_id=subject_node_id,
        ref=envelope.identity.subject_namespace,
        namespace=envelope.identity.subject_namespace,
    )
    conversation_subject_node = service.get_node(
        node_id=subject_node_id,
        ref=envelope.identity.conversation_namespace,
        namespace=envelope.identity.conversation_namespace,
    )
    thread_node = service.get_node(
        node_id=thread_node_id,
        ref=envelope.identity.conversation_namespace,
        namespace=envelope.identity.conversation_namespace,
    )
    edges = service.lookup_edges(
        source_id=subject_node_id,
        target_id=thread_node_id,
        relation="participates_in",
        ref=envelope.identity.conversation_namespace,
        namespace=envelope.identity.conversation_namespace,
    )

    assert subject_node["node"]["id"] == subject_node_id
    assert conversation_subject_node["node"]["properties"]["subject_namespace"] == envelope.identity.subject_namespace
    assert (
        conversation_subject_node["node"]["properties"]["subject_root_namespace"]
        == envelope.identity.subject_root_namespace
    )
    assert thread_node["node"]["id"] == thread_node_id
    assert edges["count"] == 1


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
