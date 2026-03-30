# OpenClaw Native Plugin

This document describes the real Cortex native plugin package for OpenClaw.

If you want the shortest copy-paste install and onboarding flow first, start with [OPENCLAW_QUICKSTART.md](/Users/marcsaint-jour/Desktop/Cortex-AI/docs/OPENCLAW_QUICKSTART.md).

Goal:

- install with `openclaw plugins install @cortex/openclaw`
- enable with `openclaw plugins enable cortex`
- restart the gateway
- get live Cortex context plus cross-channel durable memory automatically

The package scaffold lives in:

- [examples/openclaw-plugin/package.json](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/package.json)
- [examples/openclaw-plugin/openclaw.plugin.json](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/openclaw.plugin.json)
- [examples/openclaw-plugin/config.schema.json](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/config.schema.json)
- [examples/openclaw-plugin/src/index.js](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/src/index.js)
- [examples/openclaw-plugin/src/service.js](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/src/service.js)
- [examples/openclaw-plugin/src/hooks.js](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/src/hooks.js)
- [examples/openclaw-plugin/src/identity.js](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/src/identity.js)

## Package Shape

The package is publish-ready:

- public `package.json`
- `openclaw.extensions` points at a real runtime file
- manifest and config schema ship at the package root
- `npm pack` produces an installable tarball

The current local test/install flow is:

```bash
cd examples/openclaw-plugin
npm pack
openclaw plugins install ./cortex-openclaw-1.4.1.tgz
openclaw plugins enable cortex
openclaw gateway restart
```

## Runtime Model

The plugin does not take over OpenClaw's exclusive `memory` slot yet.

Instead it runs as a normal plugin with:

- a managed background service
- typed runtime hooks
- channel normalization
- durable memory seeding

The managed sidecar is `cortex-mcp`, not a custom wrapper.

That keeps the runtime aligned with the broader Cortex loop:

- humans curate context with the Cortex CLI
- OpenClaw consumes and updates that context through the native plugin
- other AI runtimes can still consume Cortex over MCP directly

## Config Schema

Important config fields:

- `storeDir`: where Cortex data lives, default `~/.openclaw/cortex`
- `configPath`: path to the managed Cortex `config.toml`
- `transport`: `managed-child` or `custom-command`
- `mcpCommand`: default `cortex-mcp`
- `mcpArgs`: default `["--config", "~/.openclaw/cortex/config.toml"]`
- `defaultTarget`: routed target for the live context slice
- `smartRouting`: whether to use Cortex smart routing
- `autoSeedThreads`: whether to materialize subject/thread memory after each turn
- `projectDirStrategy`: `agent-workspace`, `gateway-cwd`, or `explicit`
- `projectDir`: explicit project dir when strategy is `explicit`
- `requestTimeoutMs`: timeout for Cortex MCP requests
- `healthCheckTimeoutMs`: timeout for `cortex-mcp --check`
- `maxContextChars`: cap for injected live context
- `failOpen`: keep OpenClaw running even if Cortex is temporarily unavailable
- `serviceRestartLimit`: bounded restart count for the managed child
- `serviceRestartBackoffMs`: restart backoff base
- `namespace`: optional namespace pin for the Cortex MCP session
- `identityFields`: which incoming fields are allowed to collapse identity across channels

Recommended OpenClaw config:

```json5
{
  plugins: {
    entries: {
      cortex: {
        enabled: true,
        hooks: {
          allowPromptInjection: true
        },
        config: {
          transport: "managed-child",
          defaultTarget: "chatgpt",
          smartRouting: true,
          autoSeedThreads: true,
          projectDirStrategy: "agent-workspace",
          maxContextChars: 1500,
          failOpen: true,
          serviceRestartLimit: 3,
          serviceRestartBackoffMs: 1000
        }
      }
    }
  }
}
```

## Hook Lifecycle

### `gateway_start`

The managed service starts `cortex-mcp`, writes a default config if one does not exist yet, runs `--check`, initializes the MCP session, and verifies health.

### `message_received`

The plugin normalizes the incoming OpenClaw event into a Cortex `ChannelMessage` shape and caches it for the run.

### `before_prompt_build`

The plugin calls `channel_prepare_turn` over MCP.

That returns:

- shared identity resolution
- the routed context slice for the target runtime
- the per-user and per-thread write plan

If routed context exists, the plugin injects it through `prependContext`.

### `agent_end`

The plugin calls `channel_seed_turn_memory` over MCP and materializes the prepared per-user and per-thread memory branches.

### `gateway_stop`

The managed sidecar stops cleanly and the plugin clears its caches.

## Identity And Channels

The plugin normalizes OpenClaw events into the Cortex channel contract and intentionally supports sparse real-world payloads.

Identity collapse prefers:

1. `canonicalSubjectId`
2. phone number
3. email
4. username
5. channel-local ids
6. conversation and event fallback anchors

That lets the same person carry memory across Telegram, WhatsApp, Discord, Slack, SMS, web chat, and similar channels without collapsing unrelated sparse events together.

## Operational Model

Default mode is `managed-child`.

That means the plugin owns the lifecycle of `cortex-mcp`:

- health check before startup
- initialization handshake
- automatic bounded restarts
- degraded mode when `failOpen = true`

Advanced mode is `custom-command`.

Use it when operators want to point OpenClaw at a custom Cortex MCP wrapper or a non-default launcher command.

## Current State

This repo now includes the real package scaffold and runtime logic.

What still remains operational rather than code-level:

- publishing `@cortex/openclaw` to npm
- exercising `openclaw plugins install @cortex/openclaw` against the published package in release automation

Those are release steps, not missing runtime architecture.
