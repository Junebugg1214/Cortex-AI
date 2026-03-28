# OpenClaw Native Plugin Spec

This document defines the proposed one-click native OpenClaw plugin for Cortex.

Goal:

- install once with `openclaw plugins install @cortex/openclaw`
- enable once with `openclaw plugins enable cortex`
- restart the gateway
- get cross-channel identity resolution, live Cortex context, and durable per-user/per-thread memory automatically

This is a starter spec, not a claim that `@cortex/openclaw` is already published.

## Phase 1 Scope

Phase 1 should be a standard native OpenClaw plugin with:

- `openclaw.plugin.json`
- inline JSON Schema for config validation
- a managed background service that starts `cortex-mcp`
- typed runtime hooks for prompt injection and post-turn memory writes

Phase 1 should intentionally leave `kind` unset so it can coexist with OpenClaw's built-in `memory-core` plugin. Cortex adds cross-channel portable context and external durable memory first. If a later version owns `openclaw memory` CLI surfaces directly, promote it to `kind: "memory"` then.

## Package Layout

```text
@cortex/openclaw/
  package.json
  openclaw.plugin.json
  config.schema.json
  README.md
  src/
    index.ts
    service.ts
    hooks.ts
    identity.ts
```

Reference starter files in this repo:

- [package.json](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/package.json)
- [openclaw.plugin.json](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/openclaw.plugin.json)
- [config.schema.json](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/config.schema.json)
- [README.md](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/README.md)

## `openclaw.plugin.json`

Proposed manifest:

```json
{
  "id": "cortex",
  "configSchema": {
    "type": "object",
    "additionalProperties": false
  }
}
```

Exact starter manifest lives here:

- [openclaw.plugin.json](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/openclaw.plugin.json)

Design notes:

- `id` should stay `cortex` so the UX is `openclaw plugins enable cortex`
- do not set `kind: "memory"` in phase 1
- use `uiHints` so OpenClaw Control UI can render friendly labels and mark sensitive fields correctly

## Config Schema

The plugin config should validate these fields:

- `storeDir`: where Cortex data lives, default `~/.openclaw/cortex`
- `configPath`: path to Cortex `config.toml`, default `~/.openclaw/cortex/config.toml`
- `transport`: one of `managed-child`, `external-mcp`, `in-process-python`
- `mcpCommand`: default `cortex-mcp`
- `mcpArgs`: default `["--config", "~/.openclaw/cortex/config.toml"]`
- `defaultTarget`: routed portability target, default `chatgpt`
- `smartRouting`: whether to use Cortex smart routing, default `true`
- `autoSeedThreads`: whether to materialize subject/thread scaffolds automatically, default `true`
- `projectDirStrategy`: one of `agent-workspace`, `gateway-cwd`, `explicit`
- `projectDir`: explicit project dir when strategy is `explicit`
- `requestTimeoutMs`: timeout for Cortex calls
- `healthCheckTimeoutMs`: timeout for managed `cortex-mcp --check`
- `maxContextChars`: max routed context characters injected per turn
- `failOpen`: if Cortex is temporarily unavailable, let OpenClaw continue without injected context
- `identityFields`: precedence toggles for `canonicalSubjectId`, `phoneNumber`, `email`, and `username`
- `externalBaseUrl`: only used when `transport = external-mcp`

Exact starter schema lives here:

- [config.schema.json](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/config.schema.json)

Recommended OpenClaw config snippet:

```json5
{
  plugins: {
    entries: {
      cortex: {
        enabled: true,
        hooks: {
          allowPromptInjection: true,
        },
        config: {
          storeDir: "~/.openclaw/cortex",
          configPath: "~/.openclaw/cortex/config.toml",
          transport: "managed-child",
          defaultTarget: "chatgpt",
          smartRouting: true,
          autoSeedThreads: true,
          projectDirStrategy: "agent-workspace",
          maxContextChars: 1500,
          failOpen: true,
          requestTimeoutMs: 15000,
          healthCheckTimeoutMs: 5000,
        },
      },
    },
  },
}
```

## Runtime Hook Lifecycle

Use the current OpenClaw plugin APIs documented for `registerService` and `api.on(...)`.

### 1. Plugin load

On plugin registration:

- read and validate `plugins.entries.cortex.config`
- normalize `~` and relative paths before starting any child process
- register a background service named `cortex-mcp`
- register typed runtime hooks

### 2. `gateway_start`

On `gateway_start`:

- ensure `storeDir` exists
- ensure `configPath` exists, copying a starter config when needed
- if `transport = managed-child`, start `cortex-mcp --config <configPath>`
- run a lightweight health check before marking the service ready
- if `failOpen = true`, mark the plugin degraded instead of blocking the whole gateway

### 3. `message_received`

On `message_received`:

- normalize the inbound channel event into a `ChannelMessage`
- cache a lightweight turn envelope seed keyed by session or run id
- preserve the raw channel ids needed for thread scoping

### 4. `before_prompt_build`

On `before_prompt_build`:

- rebuild or load the `ChannelMessage`
- call Cortex through the Python bridge or MCP:
  - `ChannelContextBridge.prepare_turn(...)` for in-process mode
  - `portability_context` for MCP mode
- cap injected content with `maxContextChars`
- inject the returned routed slice using `prependContext`

Why `prependContext`:

- the OpenClaw docs recommend it for per-turn dynamic content
- routed Cortex context is dynamic and channel/user-specific

If `plugins.entries.cortex.hooks.allowPromptInjection = false`, skip prompt mutation and only keep the cached envelope for later memory writes.

### 5. `agent_end`

On `agent_end`:

- if `autoSeedThreads` is enabled, call `bridge.seed_turn_memory(turn)` or the MCP-backed equivalent
- write durable user or thread facts only when extraction confidence is high
- keep writes idempotent by reusing the Cortex subject/thread namespace model
- if one namespace write fails, log it with namespace and purpose and keep the gateway process alive

### 6. `gateway_stop`

On `gateway_stop`:

- stop the managed Cortex child process cleanly
- flush pending writes
- clear in-memory turn caches

## MCP / Background Service Behavior

Default mode should be `managed-child`.

### `managed-child`

OpenClaw owns the lifecycle:

- start `cortex-mcp --config <configPath>` on `gateway_start`
- probe with `cortex-mcp --config <configPath> --check`
- restart on crash with bounded exponential backoff
- stop on `gateway_stop`
- always expand `~` and relative paths before spawning the child

This is the best one-click UX because the user does not manage Cortex separately.

### `external-mcp`

Use this when operators already run Cortex themselves:

- do not spawn a child process
- connect to the existing Cortex MCP endpoint
- surface clearer diagnostics if the endpoint is unavailable

### `in-process-python`

Reserve this for advanced or embedded installs:

- import Cortex directly
- use `ChannelContextBridge`
- use this only when Python environment and dependency management are controlled carefully

## Install UX and CLI Copy

The target UX should be:

```bash
openclaw plugins install @cortex/openclaw
openclaw plugins enable cortex
openclaw gateway restart
```

Optional chat-native control:

```text
/plugin install clawhub:@cortex/openclaw
/plugin show cortex
/plugin enable cortex
```

Recommended success copy:

```text
✓ Installed plugin: cortex
✓ Enabled plugin: cortex
✓ Cortex shared context is now active for OpenClaw
  - live routed context via Cortex MCP
  - cross-channel identity resolution
  - per-user and per-thread memory scaffolding

Restart the gateway to finish activation:
  openclaw gateway restart
```

Recommended config guidance after install:

```text
Set `plugins.entries.cortex.config.storeDir` if you want a non-default Cortex store.
Set `plugins.entries.cortex.hooks.allowPromptInjection = false` if operators want Cortex memory writes without prompt mutation.
Set `plugins.entries.cortex.config.failOpen = false` only if you want Cortex outages to block prompt execution.
```

## Why This Is Worth Shipping

OpenClaw already has its own memory model. Cortex adds:

- cross-channel identity collapse
- portable context outside the runtime
- per-user plus per-thread namespaces
- live MCP-backed context retrieval
- self-hosted, user-owned memory shared across channels and AI tools

That is the difference between "memory inside one runtime" and "portable context across every surface that runtime touches."
