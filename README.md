# Cortex

You use multiple AI tools.
They all think you're a stranger.
Cortex fixes that.

Cortex is a CLI and MCP server for portable AI context across Claude, Claude Code, ChatGPT, Codex, Gemini, Grok, Windsurf, Cursor, and Copilot.

```bash
pip install "cortex-identity[server]"

cortex portable chatgpt-export.zip --to all --project .
cortex scan
cortex sync --smart
```

That flow extracts context once, writes local tool files where possible, generates honest import artifacts where needed, and gives you one source of truth you can keep updating.

## Supported Platforms

| Platform | How Cortex works |
| --- | --- |
| Claude Code | Writes `CLAUDE.md` directly |
| Codex | Writes `AGENTS.md` directly |
| Cursor | Writes `.cursor/rules/cortex.mdc` directly |
| Copilot | Writes `.github/copilot-instructions.md` directly |
| Gemini / Gemini CLI | Writes `GEMINI.md` directly |
| Windsurf | Writes `.windsurfrules` directly |
| Claude | Generates import-ready artifacts |
| ChatGPT | Generates import-ready artifacts |
| Grok | Generates import-ready artifacts |

## CLI for Humans, MCP for AI Tools

Humans use Cortex to scan, extract, remember, sync, and audit context.
AI tools use the Cortex MCP server to fetch their current routed slice live.

Run `cortex-mcp --config .cortex/config.toml` and MCP-capable tools can stay up to date automatically instead of relying only on stale local files.

## Core Commands

- `cortex scan` shows what each tool knows, what is missing, and what is stale
- `cortex extract` turns exports and source files into portable context
- `cortex sync --smart` routes the right slice to each tool
- `cortex remember "..."` teaches Cortex once and propagates it everywhere
- `cortex status` shows stale or missing context
- `cortex query` inspects the current graph directly

## Power Features

The portability front door is the point. The deeper infrastructure is still there when you need it.

- Portability guide: [docs/PORTABILITY.md](docs/PORTABILITY.md)
- Agent and MCP quickstarts: [docs/AGENT_QUICKSTARTS.md](docs/AGENT_QUICKSTARTS.md)
- Self-hosting and ops: [docs/SELF_HOSTING.md](docs/SELF_HOSTING.md)
- Advanced memory/versioning workflows: run `cortex --help-all`
