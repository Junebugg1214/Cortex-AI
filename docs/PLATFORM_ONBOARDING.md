# Platform Onboarding

Use this guide when you want a copy-paste setup flow for Cortex by platform.

The safest mental model is:

1. create or select a Mind
2. pull context into that Mind from the platform that already knows you best
3. attach Brainpacks only if you need specialist domain cognition
4. mount or sync that Mind back out to the rest of your tools
5. run `cortex mcp` for tools that can fetch live context during conversations

## Setup Once

Clone the repo, install from source, and create a local config:

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
python3.11 -m pip install -e ".[server]"
rehash

mkdir -p .cortex
cp docs/examples/config.toml .cortex/config.toml
```

Use `python3.11 -m pip`, not plain `pip`.

Create a Mind once:

```bash
cortex mind init marc --kind person --owner marc
cortex mind default marc
```

If you prefer the older portability-first workflow, you can skip this and still use `portable`, `remember`, and `sync` directly. If a default Mind is configured, those classic commands route through it behind the scenes.

## Quick Start By Situation

### I already have a rich chat export

Start with the platform that knows you best, then sync everywhere:

```bash
cortex portable ~/Downloads/YOUR-REAL-EXPORT.zip --to all --project .
cortex scan
cortex sync --smart
```

If you already set a default Mind with `cortex mind default <name>`, that flow updates the Mind-backed graph instead of a separate standalone portability graph.

If you want live MCP context after that:

```bash
cortex-mcp --config .cortex/config.toml
```

### I do not have an export yet

Seed Cortex directly, then grow from there:

```bash
cortex mind remember marc "We migrated from PostgreSQL to CockroachDB in January"
cortex scan
```

Or bootstrap from the repo you are already in:

```bash
cortex build --from github --from git-history --sync --smart
cortex scan
```

## Platform Cheat Sheet

### ChatGPT

ChatGPT is a first-class extraction source.

Pull into Cortex:

```bash
cortex portable ~/Downloads/chatgpt-export.zip --to all --project .
```

Extract only:

```bash
cortex extract ~/Downloads/chatgpt-export.zip -o context.json
```

Generate ChatGPT-ready output from an existing graph:

```bash
cortex portable context.json --to chatgpt --project .
```

Output:
- `portable/chatgpt/custom_instructions.md`
- `portable/chatgpt/custom_instructions.json`

### Claude.ai

Claude is currently strongest as a Cortex target, not a raw chat-history source.

Generate Claude-ready artifacts from an existing graph:

```bash
cortex portable context.json --to claude --project .
```

If you already have Claude-format artifacts and want to pull them back into Cortex:

```bash
cortex pull portable/claude/claude_memories.json --from claude -o claude_graph.json
```

Output:
- `portable/claude/claude_preferences.txt`
- `portable/claude/claude_memories.json`

### Claude Code

Claude Code is a first-class source and a first-class target.

Pull from discovered local sessions:

```bash
cortex extract-coding --discover
```

Or from a specific session file:

```bash
cortex extract-coding /path/to/claude-code-session.jsonl
```

Sync Cortex back into Claude Code:

```bash
cortex portable context.json --to claude-code --project .
```

Output:
- `~/.claude/CLAUDE.md`
- `./CLAUDE.md`

### Codex

Codex is currently best used as a Cortex target plus MCP client.

Sync Cortex into Codex:

```bash
cortex portable context.json --to codex --project .
```

Output:
- `./AGENTS.md`

For live context during runs:

```bash
cortex-mcp --config .cortex/config.toml
```

### Gemini

Gemini exports are a first-class extraction source.

Pull into Cortex:

```bash
cortex portable ~/Downloads/gemini-export.zip --input-format gemini --to all --project .
```

Extract only:

```bash
cortex extract ~/Downloads/gemini-export.zip --format gemini -o context.json
```

Sync Cortex back into Gemini:

```bash
cortex portable context.json --to gemini --project .
```

Output:
- `./GEMINI.md`

### Grok

Grok exports are supported as an extraction source.

Pull into Cortex:

```bash
cortex portable ~/Downloads/grok-export.json --input-format grok --to all --project .
```

Extract only:

```bash
cortex extract ~/Downloads/grok-export.json --format grok -o context.json
```

Sync Cortex back into Grok:

```bash
cortex portable context.json --to grok --project .
```

Output:
- `portable/grok/context_prompt.md`
- `portable/grok/context_prompt.json`

### Hermes

Hermes is now a first-class Cortex target.

Mount the current Mind into Hermes:

```bash
cortex mind mount marc --to hermes --task "support" --project .
```

Or sync Cortex into Hermes with the portability layer:

```bash
cortex portable context.json --to hermes --project .
```

Or, if you already have detected local context and want to install it into Hermes in one step:

```bash
cortex scan --project .
cortex portable --from-detected chatgpt claude claude-code cursor codex copilot gemini windsurf grok hermes --to hermes --project .
```

Output:
- `~/.hermes/memories/USER.md`
- `~/.hermes/memories/MEMORY.md`
- `~/.hermes/config.yaml`

### Cursor

Cursor exports are supported as an extraction source and Cursor is also a first-class target.

Pull into Cortex:

```bash
cortex portable ~/Downloads/cursor-export.json --input-format cursor --to all --project .
```

Extract only:

```bash
cortex extract ~/Downloads/cursor-export.json --format cursor -o context.json
```

Sync Cortex back into Cursor:

```bash
cortex portable context.json --to cursor --project .
```

Output:
- `./.cursor/rules/cortex.mdc`

### Copilot

Copilot exports are supported as an extraction source and Copilot is also a first-class target.

Pull into Cortex:

```bash
cortex portable ~/Downloads/copilot-export.json --input-format copilot --to all --project .
```

Extract only:

```bash
cortex extract ~/Downloads/copilot-export.json --format copilot -o context.json
```

Sync Cortex back into Copilot:

```bash
cortex portable context.json --to copilot --project .
```

Output:
- `./.github/copilot-instructions.md`

### Windsurf

Windsurf exports are supported as an extraction source and Windsurf is also a first-class target.

Pull into Cortex:

```bash
cortex portable ~/Downloads/windsurf-export.json --input-format windsurf --to all --project .
```

Extract only:

```bash
cortex extract ~/Downloads/windsurf-export.json --format windsurf -o context.json
```

Sync Cortex back into Windsurf:

```bash
cortex portable context.json --to windsurf --project .
```

Output:
- `./.windsurfrules`

## After Any Import

Once Cortex has a canonical graph, these are the normal day-to-day commands:

```bash
cortex scan
cortex status
cortex sync --smart
cortex remember "We use Vitest now." --smart
```

## MCP Everywhere It Fits

For MCP-capable clients, run:

```bash
cortex-mcp --config .cortex/config.toml
```

Then the client can fetch live context with:
- `portability_context`
- `portability_scan`
- `portability_status`
- `portability_audit`

## Best Starting Point

If you have multiple histories, start with the one that knows you best:

1. ChatGPT
2. Claude Code
3. Cursor
4. Gemini

Then make Cortex the source of truth and let every other tool consume from it.
