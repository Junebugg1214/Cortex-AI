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

- calls a local `cortexd` REST API over loopback
- injects live routed Cortex context in `before_prompt_build`
- seeds per-user and per-thread memory in `agent_end`
- resolves the same person across Telegram, WhatsApp, Discord, Slack, web chat, and similar channels
- keeps context self-hosted and user-owned

Start the local Cortex API first:

```bash
cortexd --store-dir ~/.openclaw/cortex --host 127.0.0.1 --port 8766
```

Then install from a local packed tarball:

```bash
cd examples/openclaw-plugin
TARBALL="$(npm pack --silent)"
openclaw plugins install "./$TARBALL" --force
openclaw plugins enable cortexai-openclaw
openclaw gateway restart
```

Once published, the install UX becomes:

```bash
openclaw plugins install cortexai-openclaw
openclaw plugins enable cortexai-openclaw
openclaw gateway restart
```

Version `1.6.1` does not launch child processes from inside OpenClaw. Running `cortexd` separately keeps the plugin install path scanner-friendly while preserving the same local-first memory behavior.

Recommended config:

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

OpenClaw handles channel delivery and agent execution. Cortex handles portable context, cross-channel identity, and durable memory.
