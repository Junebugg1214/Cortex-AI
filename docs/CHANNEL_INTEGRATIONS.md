# Channel Runtime Integrations

Cortex can act as the shared context and memory control plane behind messaging runtimes such as OpenClaw and Hermes.

The model is simple:

- the messaging runtime handles Telegram, WhatsApp, Discord, Slack, and similar channels
- Cortex owns the canonical portable context plus durable per-user and per-thread memory
- the runtime asks Cortex for live context before generating a reply
- the runtime writes durable outcomes back to Cortex after the turn

This lets the same person carry context across chat platforms instead of starting over in each channel.

## OpenClaw + Cortex

OpenClaw is a good fit for Cortex when you want one assistant reachable across messaging channels while keeping memory
outside the runtime itself.

Recommended flow:

1. OpenClaw receives an inbound Telegram or WhatsApp event.
2. OpenClaw resolves the sender to a Cortex subject namespace.
3. OpenClaw asks Cortex for live routed context with `portability_context`.
4. OpenClaw adds that context to the model turn.
5. If the turn creates durable new knowledge, OpenClaw writes it back to Cortex.

Reference shape with the built-in bridge:

```python
from pathlib import Path

from cortex import ChannelContextBridge, ChannelMessage
from cortex.service import MemoryService
from cortex.storage import get_storage_backend

store_dir = Path(".cortex")
service = MemoryService(store_dir=store_dir, backend=get_storage_backend(store_dir))
bridge = ChannelContextBridge(service)

message = ChannelMessage(
    platform="telegram",
    workspace_id="support-bot",
    conversation_id="chat-42",
    user_id="tg-123",
    phone_number="+15551234567",
    text="Do you still support CockroachDB?",
    display_name="Casey",
)

turn = bridge.prepare_turn(message, target="chatgpt", smart=True)
portable_context = turn.context["context"]
subject_namespace = turn.identity.subject_namespace
conversation_namespace = turn.identity.conversation_namespace
```

OpenClaw can then use `subject_namespace` and `conversation_namespace` when it calls the object API, claim API, or
future channel-specific write paths.

## Hermes + Cortex

Hermes is a good fit when you want a lighter agent runtime that still shares the same user-owned context layer.

Recommended flow:

1. Hermes receives a channel event.
2. Hermes resolves the sender identity with the Cortex bridge.
3. Hermes fetches live portability context over MCP or directly through the bridge.
4. Hermes stores durable facts in the subject or thread namespace.

Hermes can use either integration mode:

- in-process Python bridge via `ChannelContextBridge`
- external runtime via `cortex-mcp` and `portability_context`

The bridge also returns an MCP tool payload you can forward directly:

```python
tool_call = turn.portability_tool_request
```

That payload maps cleanly onto the built-in MCP tool:

- `portability_context`
- `portability_scan`
- `portability_status`
- `portability_audit`

## Telegram and WhatsApp Identity Mapping

The key design problem is identity collapse across platforms.

If the same person messages you on Telegram and WhatsApp, you usually do not want two isolated memory silos. You want
one shared subject identity and separate per-thread namespaces under it.

Cortex uses this precedence order:

1. `canonical_subject_id`
2. `phone_number`
3. `email`
4. `username`
5. `external user id`

That means:

- if Telegram and WhatsApp both provide the same phone number, they resolve to the same subject namespace
- if you have your own CRM or account mapping, pass `canonical_subject_id` and Cortex will use that instead
- if there is no stable shared identifier, Cortex falls back to a platform-scoped subject namespace

Namespace shape:

- shared identity:
  - `people/phone_number/<stable-key>`
  - `people/email/<stable-key>`
  - `people/canonical_subject_id/<slug>`
- platform-only fallback:
  - `channels/<platform>/<workspace>/subjects/<stable-key>`
- per-thread:
  - `<subject-namespace>/threads/<platform>/<workspace>/<stable-thread-key>`

This gives you:

- cross-platform person memory when you have a shared identifier
- separate platform-scoped memory when you do not
- isolated per-thread memory under the same person when needed

## Minimum Adapter API

The minimum adapter API in Cortex is intentionally small.

Core types:

- `ChannelMessage`
- `ResolvedChannelIdentity`
- `ChannelTurnEnvelope`
- `ChannelContextBridge`

Built-in adapters:

- `TelegramAdapter`
- `WhatsAppAdapter`

Minimum runtime contract:

1. Build a `ChannelMessage` from the inbound event.
2. Call `ChannelContextBridge.prepare_turn(...)`.
3. Use `turn.context` in the model prompt.
4. Use `turn.identity.subject_namespace` and `turn.identity.conversation_namespace` for durable writes.
5. Optionally use `turn.suggested_memory_operations` to seed the subject and thread nodes in Cortex.

That is enough to make shared context work end to end without inventing a second memory system.

## Example Durable Write Patterns

Global user fact:

```python
bridge.remember_global_fact(
    "Casey prefers concise billing explanations.",
    targets=["chatgpt", "claude"],
    smart=True,
)
```

Per-user or per-thread memory:

- use `turn.identity.subject_namespace` for durable user facts
- use `turn.identity.conversation_namespace` for thread-scoped memory
- write through existing object, claim, or batch APIs

## Why This Shape

This design keeps Cortex focused on what it does best:

- portable context
- user-owned memory
- live MCP access
- namespace-scoped durable memory

And it keeps OpenClaw, Hermes, Telegram, WhatsApp, and future channel runtimes focused on what they do best:

- receiving messages
- invoking models
- handling channel delivery and retries

That split is what makes the integration practical.
