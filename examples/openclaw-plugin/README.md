# Cortex Native Plugin For OpenClaw

This directory now contains the real OpenClaw-native Cortex plugin package scaffold:

- [package.json](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/package.json)
- [openclaw.plugin.json](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/openclaw.plugin.json)
- [config.schema.json](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/config.schema.json)
- [src/index.js](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/src/index.js)
- [src/service.js](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/src/service.js)
- [src/hooks.js](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/src/hooks.js)
- [src/identity.js](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/src/identity.js)

What it does:

- starts a managed `cortex-mcp` sidecar by default
- injects live routed Cortex context in `before_prompt_build`
- seeds per-user and per-thread memory in `agent_end`
- resolves the same person across Telegram, WhatsApp, Discord, Slack, web chat, and similar channels
- keeps context self-hosted and user-owned

Install from a local packed tarball today:

```bash
cd examples/openclaw-plugin
npm pack
openclaw plugins install ./cortex-openclaw-1.4.1.tgz
openclaw plugins enable cortex
openclaw gateway restart
```

Once published, the install UX becomes:

```bash
openclaw plugins install @cortex/openclaw
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
        hooks: { allowPromptInjection: true },
        config: {
          transport: "managed-child",
          defaultTarget: "chatgpt",
          smartRouting: true,
          autoSeedThreads: true,
          maxContextChars: 1500,
          failOpen: true
        }
      }
    }
  }
}
```

OpenClaw handles channel delivery and agent execution. Cortex handles portable context, cross-channel identity, and durable memory.
