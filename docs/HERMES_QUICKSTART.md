# Hermes Quickstart

Use this guide when you want Hermes to use Cortex as the shared portable context and memory layer.

The mental model is simple:

1. install Cortex
2. let Cortex discover or ingest the context you already have
3. install that context into Hermes-native files and MCP config
4. keep Hermes current with `cortex remember` and `cortex sync --smart`

## What You Get

After setup, Hermes keeps doing live reasoning and agent execution. Cortex adds:

- user-owned portable context outside the runtime
- `USER.md` and `MEMORY.md` kept in sync from the canonical graph
- managed `cortex-mcp` wiring in `~/.hermes/config.yaml`
- the same context available to your other AI tools too
- optional project-scoped `AGENTS.md` if you also sync the `codex` target

## 1. Install Cortex

Clone the repo and install from source with Python 3.11+:

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
python3.11 -m pip install -e ".[server]"
rehash
```

Use `python3.11 -m pip`, not plain `pip`.

## 2. Seed Cortex With Context

### Option A: You already have local AI exports or artifacts

Let Cortex detect them first:

```bash
cortex scan --project .
```

Then explicitly adopt the detected sources you want:

```bash
cortex portable --from-detected chatgpt claude claude-code cursor codex copilot gemini windsurf grok hermes --to hermes --project .
```

What this does:

- `scan` finds known local exports, artifacts, instruction files, and MCP configs
- `portable --from-detected ...` adopts the sources you named with permission
- common PII is redacted by default during detected-source adoption
- direct instruction files only ingest managed Cortex marker blocks by default

### Option B: You do not have exports yet

Seed Cortex directly:

```bash
cortex remember "We use FastAPI, React, and CockroachDB." --smart
cortex sync --to hermes --smart --project .
```

You can also bootstrap from the repo you are already in:

```bash
cortex build --from github --from git-history --sync --to hermes --project .
```

## 3. What Cortex Writes Into Hermes

When you target Hermes, Cortex installs the current canonical graph into Hermes-native locations:

- `~/.hermes/memories/USER.md`
- `~/.hermes/memories/MEMORY.md`
- `~/.hermes/config.yaml`

`config.yaml` gets a managed `mcp_servers.cortex` entry pointing Hermes at `cortex-mcp`. If Cortex creates the file from scratch, it also writes a recommended `memory:` block with memory enabled.

`USER.md` and `MEMORY.md` are non-destructive. Cortex only manages its own marked block and leaves surrounding human-authored text alone.

If you also want a shared project `AGENTS.md` for Hermes and Codex-style runtimes, sync the `codex` target alongside Hermes:

```bash
cortex sync --to hermes codex --smart --project .
```

## 4. Verify The Install

Use Cortex to confirm Hermes is now configured:

```bash
cortex scan --project .
```

You should see Hermes with detected facts plus MCP configured.

If you want Hermes to validate its side too:

```bash
hermes config check
```

## 5. Keep Hermes Current

Once Hermes is wired in, this is the human loop:

```bash
cortex remember "We migrated from PostgreSQL to CockroachDB in January." --smart
cortex scan --project .
cortex sync --to hermes --smart --project .
```

That keeps `USER.md`, `MEMORY.md`, and the Cortex MCP link up to date with the same canonical graph your other tools can also consume. If you also sync `codex`, Cortex will keep a shared project `AGENTS.md` in step too.

If you want to mount a compiled Brainpack directly into Hermes instead of syncing the whole canonical graph, use:

```bash
cortex pack mount ai-memory --to hermes --project . --smart
```

## 6. Example End State

At the end of setup:

- Hermes starts with Cortex-managed `USER.md` and `MEMORY.md`
- Hermes can call Cortex live over MCP through the configured `cortex` server
- the same context can also sync into Claude Code, Codex, Cursor, Copilot, Gemini, Windsurf, ChatGPT, Claude, and Grok

So the result is not just “Hermes remembers more.”

It is:

**Hermes now runs on top of a portable context layer instead of a runtime-local memory silo.**

## Related Docs

- [PLATFORM_ONBOARDING.md](/Users/marcsaint-jour/Desktop/Cortex-AI/docs/PLATFORM_ONBOARDING.md)
- [PORTABILITY.md](/Users/marcsaint-jour/Desktop/Cortex-AI/docs/PORTABILITY.md)
- [CHANNEL_INTEGRATIONS.md](/Users/marcsaint-jour/Desktop/Cortex-AI/docs/CHANNEL_INTEGRATIONS.md)
