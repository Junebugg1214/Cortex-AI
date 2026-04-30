# OpenClaw Quickstart

Use this guide when you want OpenClaw to use Cortex as the shared context and memory layer behind Telegram, WhatsApp, Discord, Slack, web chat, and similar channels.

The mental model is simple:

1. install Cortex
2. seed Cortex with context
3. start the local Cortex API
4. install the OpenClaw plugin
5. allow the plugin to inject prompt context and observe conversation-end events
6. let OpenClaw fetch live context from Cortex and write durable memory back after each turn

## What You Get

After setup, OpenClaw keeps doing runtime and channel delivery. Cortex adds:

- cross-channel identity resolution
- per-user memory
- per-thread memory
- live routed context before the model replies
- self-hosted, user-owned memory outside the runtime

## 1. Install Cortex

Clone the repo and install from source with Python 3.10+.

The examples below use `python3.11` when it is available:

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
python3.11 -m pip install -e ".[server]"
rehash
```

Use `python3.11 -m pip`, not plain `pip`, when you are following this guide exactly. If your environment only has another supported Python 3.10+ interpreter, replace `python3.11` with that interpreter.

OpenClaw itself should already be installed and configured:

```bash
openclaw --version
openclaw gateway status
```

If the gateway refuses to start because `gateway.mode` is missing, run OpenClaw setup/onboarding for local mode or set `gateway.mode` to `local` in your OpenClaw config before continuing.

## 2. Seed Cortex With Context

### Option A: You already have local AI exports or artifacts

Let Cortex detect them and adopt them in one step:

```bash
cortex scan --project .
cortex portable --from-detected chatgpt claude cursor codex copilot gemini windsurf grok --to all --project .
```

What this does:

- `scan` finds known local context files, exports, artifacts, and MCP configs
- `portable --from-detected ...` adopts the selected sources into Cortex and syncs them back out across supported tools

### Option B: You do not have exports yet

Seed Cortex directly:

```bash
cortex remember "We use FastAPI, React, and CockroachDB." --smart
cortex scan
```

You can also bootstrap from the repo you are already in:

```bash
cortex build --from github --from git-history --sync --smart --project .
cortex scan
```

## 3. Start The Local Cortex API

Run `cortexd` on loopback with the store OpenClaw should use:

```bash
cortexd --store-dir ~/.openclaw/cortex --host 127.0.0.1 --port 8766
```

Keep that process running while OpenClaw is active. If you configure Cortex API authentication, add the same API key under `plugins.entries["cortexai-openclaw"].config.apiKey` in the OpenClaw config below.

## 4. Install the OpenClaw Plugin

Until `cortexai-openclaw` is published to npm, install from the local packed plugin tarball:

```bash
cd examples/openclaw-plugin
TARBALL="$(npm pack --silent)"
openclaw plugins install "./$TARBALL" --force
openclaw plugins enable cortexai-openclaw
```

Once the package is published on ClawHub, the install command becomes:

```bash
openclaw plugins install cortexai-openclaw
openclaw plugins enable cortexai-openclaw
```

Restart the gateway after the config in the next step is in place.

## 5. Configure the Plugin

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

What the important fields mean:

- `hooks.allowPromptInjection: true` lets the plugin prepend routed Cortex context before the model turn
- `hooks.allowConversationAccess: true` lets the plugin run `agent_end`; without it OpenClaw blocks the post-turn memory write hook
- `apiBaseUrl` points at the local `cortexd` REST API
- `storeDir` points at the same Cortex store used by `cortexd`
- `defaultTarget` controls which routed slice OpenClaw asks for
- `smartRouting: true` lets Cortex send the right slice for the runtime instead of one generic blob
- `autoSeedThreads: true` creates the default per-user and per-thread memory scaffold automatically
- `failOpen: true` keeps OpenClaw working even if Cortex is temporarily unavailable

Apply the config, then restart and verify:

```bash
openclaw gateway restart
openclaw plugins inspect cortexai-openclaw --json
# Optional broad diagnostics across all plugins:
openclaw plugins doctor
```

In the `plugins inspect` output, `services` should include `cortex` and `typedHooks` should include `message_received`, `before_prompt_build`, and `agent_end`.

## 6. What Happens At Runtime

Once OpenClaw is running with the Cortex plugin:

1. OpenClaw receives a message from Telegram, WhatsApp, Discord, Slack, or web chat.
2. The plugin normalizes that event into the Cortex channel contract.
3. Cortex resolves the sender to a shared subject identity.
4. Before OpenClaw builds the prompt, the plugin asks Cortex for live routed context.
5. OpenClaw injects that context into the turn.
6. OpenClaw replies.
7. After the turn, the plugin asks Cortex to seed or update per-user and per-thread memory.

That means the same person can carry context across channels when a stable identity matches, while each conversation still gets its own thread memory.

## 7. The Ongoing Human Loop

After the plugin is installed, the human still uses Cortex directly to curate identity and memory:

```bash
cortex scan --project .
cortex remember "We migrated from PostgreSQL to CockroachDB in January." --smart
cortex sync --smart
```

This is the full loop:

- humans curate context with the CLI
- OpenClaw consumes live routed context over the local Cortex API
- Cortex stores durable per-user and per-thread memory outside the runtime itself

## 7. Example End State

Imagine the same person first messages your OpenClaw bot on Telegram and later on WhatsApp.

With Cortex underneath:

- the person can resolve to one shared subject identity when phone, email, or canonical ID matches
- Telegram and WhatsApp still get separate thread namespaces
- OpenClaw gets live context before replying
- durable facts survive across channels and future sessions

So the result is not just “OpenClaw has memory.”

It is:

**OpenClaw handles runtime and delivery. Cortex becomes the memory and context control plane behind it.**

## Related Docs

- [OPENCLAW_NATIVE_PLUGIN.md](OPENCLAW_NATIVE_PLUGIN.md)
- [CHANNEL_INTEGRATIONS.md](CHANNEL_INTEGRATIONS.md)
- [PLATFORM_ONBOARDING.md](PLATFORM_ONBOARDING.md)
- [PORTABILITY.md](PORTABILITY.md)
