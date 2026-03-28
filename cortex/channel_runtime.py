from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from cortex.portable_runtime import remember_and_sync
from cortex.service import MemoryService


def _slug_fragment(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def _normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if not digits:
        return ""
    if value.strip().startswith("+"):
        return f"+{digits}"
    return digits


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def _stable_key(*parts: str, prefix: str) -> str:
    payload = "|".join(part.strip() for part in parts if part and part.strip())
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _workspace_key(platform: str, workspace_id: str) -> str:
    cleaned = _slug_fragment(workspace_id, fallback="")
    if cleaned:
        return cleaned
    return _stable_key(platform, workspace_id, prefix="workspace")


@dataclass(slots=True)
class ChannelMessage:
    platform: str
    workspace_id: str
    conversation_id: str
    user_id: str
    text: str
    display_name: str = ""
    username: str = ""
    phone_number: str = ""
    email: str = ""
    canonical_subject_id: str = ""
    timestamp: str = ""
    project_dir: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ResolvedChannelIdentity:
    platform: str
    workspace_key: str
    subject_key: str
    conversation_key: str
    subject_root_namespace: str
    subject_namespace: str
    conversation_namespace: str
    actor: str
    identity_type: str
    normalized_phone: str = ""
    normalized_email: str = ""
    aliases: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ChannelTurnEnvelope:
    identity: ResolvedChannelIdentity
    target: str
    context: dict[str, Any]
    portability_tool_request: dict[str, Any]
    write_plan: list["ChannelWriteBatch"]
    suggested_memory_operations: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RuntimeProfile:
    name: str
    recommended_target: str
    notes: str


OPENCLAW_PROFILE = RuntimeProfile(
    name="openclaw",
    recommended_target="chatgpt",
    notes="Gateway-style agent runtime across messaging platforms. Use broad chat-style routed context plus namespace-scoped memory.",
)

HERMES_PROFILE = RuntimeProfile(
    name="hermes",
    recommended_target="chatgpt",
    notes="Autonomous messaging agent runtime. Use broad live context plus per-user and per-thread namespaces for durable learning.",
)


class ChannelAdapter(Protocol):
    name: str

    def supports(self, message: ChannelMessage) -> bool: ...

    def resolve_identity(self, message: ChannelMessage) -> ResolvedChannelIdentity: ...

    def recommended_target(self) -> str: ...


class BaseChannelAdapter:
    name = "base"

    def supports(self, message: ChannelMessage) -> bool:
        return message.platform == self.name

    def recommended_target(self) -> str:
        return "chatgpt"

    def resolve_identity(self, message: ChannelMessage) -> ResolvedChannelIdentity:
        platform = _slug_fragment(message.platform, fallback="channel")
        workspace_key = _workspace_key(platform, message.workspace_id)
        normalized_phone = _normalize_phone(message.phone_number)
        normalized_email = _normalize_email(message.email)

        identity_type = "external_user_id"
        shared_identity = False
        if message.canonical_subject_id.strip():
            subject_key = _slug_fragment(message.canonical_subject_id, fallback="subject")
            identity_type = "canonical_subject_id"
            shared_identity = True
        elif normalized_phone:
            subject_key = _stable_key(normalized_phone, prefix="phone")
            identity_type = "phone_number"
            shared_identity = True
        elif normalized_email:
            subject_key = _stable_key(normalized_email, prefix="email")
            identity_type = "email"
            shared_identity = True
        elif message.username.strip():
            subject_key = _stable_key(platform, workspace_key, message.username.strip().lower(), prefix="user")
            identity_type = "username"
        else:
            subject_key = _stable_key(platform, workspace_key, message.user_id, prefix="user")

        conversation_key = _stable_key(platform, workspace_key, message.conversation_id, prefix="thread")
        if shared_identity:
            subject_root_namespace = f"people/{identity_type}/{subject_key}"
        else:
            subject_root_namespace = f"channels/{platform}/{workspace_key}/subjects/{subject_key}"
        subject_namespace = f"{subject_root_namespace}/profile"
        conversation_namespace = f"{subject_root_namespace}/threads/{platform}/{workspace_key}/{conversation_key}"
        actor = f"runtime/{platform}/{workspace_key}"

        aliases: list[str] = []
        if normalized_phone:
            aliases.append(f"phone:{normalized_phone}")
        if normalized_email:
            aliases.append(f"email:{normalized_email}")
        if message.username.strip():
            aliases.append(f"username:{message.username.strip().lower()}")
        aliases.append(f"{platform}:{message.user_id}")

        return ResolvedChannelIdentity(
            platform=platform,
            workspace_key=workspace_key,
            subject_key=subject_key,
            conversation_key=conversation_key,
            subject_root_namespace=subject_root_namespace,
            subject_namespace=subject_namespace,
            conversation_namespace=conversation_namespace,
            actor=actor,
            identity_type=identity_type,
            normalized_phone=normalized_phone,
            normalized_email=normalized_email,
            aliases=aliases,
        )


class TelegramAdapter(BaseChannelAdapter):
    name = "telegram"


class WhatsAppAdapter(BaseChannelAdapter):
    name = "whatsapp"


class GenericChannelAdapter(BaseChannelAdapter):
    def __init__(self, platform: str) -> None:
        self.name = _slug_fragment(platform, fallback="channel")


CHANNEL_ADAPTERS: dict[str, ChannelAdapter] = {
    "telegram": TelegramAdapter(),
    "whatsapp": WhatsAppAdapter(),
}


def adapter_for_platform(platform: str) -> ChannelAdapter:
    normalized = platform.strip().lower()
    adapter = CHANNEL_ADAPTERS.get(normalized)
    if adapter is not None:
        return adapter
    if not normalized:
        raise ValueError("Unsupported channel platform: empty value")
    return GenericChannelAdapter(normalized)


@dataclass(slots=True)
class ChannelWriteBatch:
    namespace: str
    operations: list[dict[str, Any]]
    purpose: str = ""
    message: str = ""


def channel_write_plan(message: ChannelMessage, identity: ResolvedChannelIdentity) -> list[ChannelWriteBatch]:
    subject_label = message.display_name.strip() or message.username.strip() or f"{message.platform.title()} contact"
    subject_node_id = f"contact/{identity.subject_key}"
    thread_node_id = f"thread/{identity.conversation_key}"
    thread_label = f"{message.platform.title()} thread {message.conversation_id}"

    subject_tags = ["identity", "relationships", message.platform]
    thread_tags = ["active_priorities", "channel_thread", message.platform]

    subject_node = {
        "id": subject_node_id,
        "canonical_id": identity.subject_key,
        "label": subject_label,
        "brief": f"{message.platform.title()} contact in workspace {identity.workspace_key}",
        "tags": subject_tags,
        "aliases": identity.aliases,
    }
    conversation_subject_node = {
        **subject_node,
        "brief": f"{subject_label} as a participant in the {message.platform.title()} thread.",
        "tags": sorted({*subject_tags, "channel_participant"}),
        "properties": {
            "subject_namespace": identity.subject_namespace,
            "subject_root_namespace": identity.subject_root_namespace,
            "conversation_namespace": identity.conversation_namespace,
            "identity_type": identity.identity_type,
        },
    }
    thread_node = {
        "id": thread_node_id,
        "canonical_id": identity.conversation_key,
        "label": thread_label,
        "brief": f"{message.platform.title()} conversation for {subject_label}",
        "tags": thread_tags,
        "properties": {
            "workspace_key": identity.workspace_key,
            "conversation_id": message.conversation_id,
        },
    }
    edge = {
        "id": f"edge/{identity.subject_key}/{identity.conversation_key}",
        "source_id": subject_node_id,
        "target_id": thread_node_id,
        "relation": "participates_in",
        "description": f"{subject_label} participates in the {message.platform.title()} thread.",
    }
    return [
        ChannelWriteBatch(
            namespace=identity.subject_namespace,
            purpose="seed_subject_identity",
            message=f"Seed channel subject for {subject_label}",
            operations=[{"op": "upsert_node", "node": subject_node}],
        ),
        ChannelWriteBatch(
            namespace=identity.conversation_namespace,
            purpose="seed_thread_context",
            message=f"Seed {message.platform.title()} thread scaffold for {subject_label}",
            operations=[
                {"op": "upsert_node", "node": conversation_subject_node},
                {"op": "upsert_node", "node": thread_node},
                {"op": "upsert_edge", "edge": edge},
            ],
        ),
    ]


def suggested_memory_operations(message: ChannelMessage, identity: ResolvedChannelIdentity) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for batch in channel_write_plan(message, identity):
        for operation in batch.operations:
            preview.append(
                {
                    "namespace": batch.namespace,
                    "purpose": batch.purpose,
                    **operation,
                }
            )
    return preview


class ChannelContextBridge:
    def __init__(self, service: MemoryService, *, default_project_dir: str | Path | None = None) -> None:
        self.service = service
        self.default_project_dir = Path(default_project_dir).resolve() if default_project_dir else Path.cwd()

    def prepare_turn(
        self,
        message: ChannelMessage,
        *,
        target: str | None = None,
        smart: bool = True,
        max_chars: int = 1500,
    ) -> ChannelTurnEnvelope:
        adapter = adapter_for_platform(message.platform)
        identity = adapter.resolve_identity(message)
        project_dir = message.project_dir or str(self.default_project_dir)
        effective_target = target or adapter.recommended_target()
        context_payload = self.service.portability_context(
            target=effective_target,
            project_dir=project_dir,
            smart=smart,
            max_chars=max_chars,
        )
        write_plan = channel_write_plan(message, identity)
        return ChannelTurnEnvelope(
            identity=identity,
            target=effective_target,
            context=context_payload,
            portability_tool_request={
                "name": "portability_context",
                "arguments": {
                    "target": effective_target,
                    "project_dir": project_dir,
                    "smart": smart,
                    "max_chars": max_chars,
                },
            },
            write_plan=write_plan,
            suggested_memory_operations=suggested_memory_operations(message, identity),
        )

    def remember_global_fact(
        self,
        statement: str,
        *,
        project_dir: str | Path | None = None,
        targets: list[str] | None = None,
        smart: bool = True,
        policy_name: str = "full",
        max_chars: int = 1500,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        project_path = Path(project_dir).resolve() if project_dir else self.default_project_dir
        return remember_and_sync(
            statement,
            store_dir=self.service.store_dir,
            project_dir=project_path,
            targets=targets,
            smart=smart,
            policy_name=policy_name,
            max_chars=max_chars,
            dry_run=dry_run,
        )

    def _activate_namespace_branch(
        self,
        *,
        namespace: str,
        actor: str,
        approve: bool,
        base_ref: str,
    ) -> None:
        current_branch = self.service.backend.versions.current_branch()
        if self.service._branch_in_namespace(current_branch, namespace):
            return
        branches = {branch.name for branch in self.service.backend.versions.list_branches()}
        if namespace in branches:
            self.service.switch_branch(
                name=namespace,
                actor=actor,
                approve=approve,
                namespace=namespace,
            )
            return
        self.service.create_branch(
            name=namespace,
            from_ref=base_ref,
            switch=True,
            actor=actor,
            approve=approve,
        )

    def seed_turn_memory(
        self,
        turn: ChannelTurnEnvelope,
        *,
        ref: str = "HEAD",
        source: str = "channel.runtime",
        approve: bool = False,
    ) -> dict[str, Any]:
        if ref != "HEAD":
            raise ValueError("seed_turn_memory only supports ref='HEAD' while materializing namespace branches.")
        base_branch = self.service.backend.versions.current_branch()
        batch_results: list[dict[str, Any]] = []
        try:
            for batch in turn.write_plan:
                self._activate_namespace_branch(
                    namespace=batch.namespace,
                    actor=turn.identity.actor,
                    approve=approve,
                    base_ref=base_branch,
                )
                result = self.service.memory_batch(
                    operations=batch.operations,
                    ref=ref,
                    message=batch.message,
                    source=source,
                    actor=turn.identity.actor,
                    approve=approve,
                    namespace=batch.namespace,
                )
                batch_results.append(
                    {
                        "namespace": batch.namespace,
                        "purpose": batch.purpose,
                        "result": result,
                    }
                )
        finally:
            current_branch = self.service.backend.versions.current_branch()
            if current_branch != base_branch:
                self.service.switch_branch(
                    name=base_branch,
                    actor=turn.identity.actor,
                    approve=approve,
                )
        return {
            "status": "ok",
            "subject_namespace": turn.identity.subject_namespace,
            "conversation_namespace": turn.identity.conversation_namespace,
            "batches": batch_results,
        }
