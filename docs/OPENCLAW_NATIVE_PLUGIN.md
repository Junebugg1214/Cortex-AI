# OpenClaw Native Plugin

This document describes the Cortex native plugin package for OpenClaw.

If you want the shortest copy-paste onboarding flow first, start with [OPENCLAW_QUICKSTART.md](OPENCLAW_QUICKSTART.md).

Goal:

- run `cortexd` locally on loopback
- install with `openclaw plugins install cortexai-openclaw`
- enable with `openclaw plugins enable cortexai-openclaw`
- restart the gateway
- get live Cortex context plus cross-channel durable memory automatically

The package scaffold lives in:

- [examples/openclaw-plugin/package.json](../examples/openclaw-plugin/package.json)
- [examples/openclaw-plugin/openclaw.plugin.json](../examples/openclaw-plugin/openclaw.plugin.json)
- [examples/openclaw-plugin/config.schema.json](../examples/openclaw-plugin/config.schema.json)
- [examples/openclaw-plugin/src/index.js](../examples/openclaw-plugin/src/index.js)
- [examples/openclaw-plugin/src/service.js](../examples/openclaw-plugin/src/service.js)
- [examples/openclaw-plugin/src/hooks.js](../examples/openclaw-plugin/src/hooks.js)
- [examples/openclaw-plugin/src/identity.js](../examples/openclaw-plugin/src/identity.js)

## Package Shape

The package is publish-ready:

- public `package.json`
- `openclaw.extensions` points at a real runtime file
- manifest and config schema ship at the package root
- `npm pack` produces an installable tarball
- the published runtime does not import Node child-process APIs

The local test/install flow is:

```bash
cortexd --store-dir ~/.openclaw/cortex --host 127.0.0.1 --port 8766

cd examples/openclaw-plugin
TARBALL="$(npm pack --silent)"
openclaw plugins install "./$TARBALL" --force
openclaw plugins enable cortexai-openclaw
openclaw gateway restart
```

Version `1.6.1` uses the local Cortex REST API instead of spawning `cortex-mcp` inside OpenClaw. That keeps the ClawHub install path free of installer override flags while preserving the same local-first trust boundary.

## Runtime Model

The plugin does not take over OpenClaw's exclusive `memory` slot yet.

Instead it runs as a normal plugin with:

- a lightweight API client pointed at `cortexd`
- typed runtime hooks
- channel normalization
- durable memory seeding

That keeps the runtime aligned with the broader Cortex loop:

- humans curate context with the Cortex CLI
- `cortexd` exposes the local Cortex API on loopback
- OpenClaw consumes and updates that context through the native plugin
- other AI runtimes can still consume Cortex over MCP directly if they support MCP

If you want OpenClaw to consume a compiled Brainpack directly, mount it into the plugin store with:

```bash
cortex pack mount ai-memory --to openclaw --project . --openclaw-store-dir ~/.openclaw/cortex --smart
```

That writes a Brainpack mount registry into the OpenClaw Cortex store so the plugin injects the pack live on each turn alongside the normal routed portability context.

## Config Schema

Important config fields:

- `storeDir`: where Cortex data lives, default `~/.openclaw/cortex`
- `apiBaseUrl`: local Cortex API base URL, default `http://127.0.0.1:8766`
- `apiKey`: optional Cortex API key when `cortexd` is configured with authentication
- `defaultTarget`: routed target for the live context slice
- `smartRouting`: whether to use Cortex smart routing
- `autoSeedThreads`: whether to materialize subject/thread memory after each turn
- `projectDirStrategy`: `agent-workspace`, `gateway-cwd`, or `explicit`
- `projectDir`: explicit project dir when strategy is `explicit`
- `requestTimeoutMs`: timeout for Cortex API requests
- `maxContextChars`: cap for injected live context
- `failOpen`: keep OpenClaw running even if Cortex is temporarily unavailable
- `namespace`: optional namespace pin for the Cortex API session
- `identityFields`: which incoming fields are allowed to collapse identity across channels

Recommended OpenClaw config:

```json5
{
  plugins: {
    entries: {
      "cortexai-openclaw": {
        enabled: true,
        hooks: {
          allowPromptInjection: true,
          allowConversationAccess: true
        },
        config: {
          apiBaseUrl: "http://127.0.0.1:8766",
          storeDir: "~/.openclaw/cortex",
          defaultTarget: "chatgpt",
          smartRouting: true,
          autoSeedThreads: true,
          projectDirStrategy: "agent-workspace",
          maxContextChars: 1500,
          failOpen: true
        }
      }
    }
  }
}
```

## Hook Lifecycle

### `gateway_start`

The plugin checks the configured Cortex API health endpoint and enters fail-open degraded mode if the API is unavailable.

### `message_received`

The plugin normalizes the incoming OpenClaw event into a Cortex `ChannelMessage` shape and caches it for the run.

### `before_prompt_build`

The plugin calls `POST /v1/channel/prepare-turn` on the local Cortex API.

That returns:

- shared identity resolution
- the routed context slice for the target runtime
- the per-user and per-thread write plan

If routed context exists, the plugin injects it through `prependContext`.

### `agent_end`

The plugin calls `POST /v1/channel/seed-turn-memory` and materializes the prepared per-user and per-thread memory branches.

OpenClaw blocks this hook for non-bundled plugins unless `plugins.entries["cortexai-openclaw"].hooks.allowConversationAccess` is `true`. Without that setting, context injection can still work, but durable post-turn memory seeding will not run.

### `gateway_stop`

The plugin clears its in-memory turn caches. The external `cortexd` process remains operator-managed.

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

The default mode is local API mode:

- OpenClaw runs the plugin
- the plugin calls `cortexd` over `http://127.0.0.1:8766`
- operators own the `cortexd` lifecycle using their normal shell, service manager, or launch agent
- `failOpen = true` keeps OpenClaw responding if Cortex is temporarily down

This is intentionally less automatic than the original managed sidecar, but it is easier for users and registry scanners to reason about: the plugin is not launching arbitrary commands inside OpenClaw.

## Current State

This repo now includes the real package scaffold and runtime logic.

What still remains operational rather than code-level:

- publishing `cortexai-openclaw@1.6.1` on ClawHub
- exercising `openclaw plugins install cortexai-openclaw` against the ClawHub package in release automation

Those are release steps, not missing runtime architecture.
