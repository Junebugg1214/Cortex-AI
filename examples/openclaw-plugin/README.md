# Cortex Native Plugin For OpenClaw

This directory contains the real OpenClaw-native Cortex plugin package scaffold:

- [package.json](package.json)
- [openclaw.plugin.json](openclaw.plugin.json)
- [config.schema.json](config.schema.json)
- [src/index.js](src/index.js)
- [src/service.js](src/service.js)
- [src/hooks.js](src/hooks.js)
- [src/identity.js](src/identity.js)

What it does:

- starts a managed `cortex-mcp` sidecar by default
- injects live routed Cortex context in `before_prompt_build`
- seeds per-user and per-thread memory in `agent_end`
- resolves the same person across Telegram, WhatsApp, Discord, Slack, web chat, and similar channels
- keeps context self-hosted and user-owned

Install from a local packed tarball today:

```bash
cd examples/openclaw-plugin
TARBALL="$(npm pack --silent)"
openclaw plugins install "./$TARBALL" --force --dangerously-force-unsafe-install
openclaw plugins enable cortex
openclaw gateway restart
```

OpenClaw's installer flags this package because it launches the managed `cortex-mcp` sidecar with Node process APIs. Use `--dangerously-force-unsafe-install` only for this trusted repo checkout or a pinned reviewed artifact.

Once published, the install UX becomes:

```bash
openclaw plugins install @cortex/openclaw --dangerously-force-unsafe-install
openclaw plugins enable cortex
openclaw gateway restart
```

Recommended config:

```json5
{
  plugins: {
    entries: {
      cortex: {
        enabled: true,
        hooks: {
          allowPromptInjection: true,
          allowConversationAccess: true
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

OpenClaw handles channel delivery and agent execution. Cortex handles portable context, cross-channel identity, and durable memory.
