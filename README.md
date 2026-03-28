[![PyPI](https://img.shields.io/pypi/v/cortex-identity)](https://pypi.org/project/cortex-identity/)
[![Python](https://img.shields.io/pypi/pyversions/cortex-identity)](https://pypi.org/project/cortex-identity/)
[![License](https://img.shields.io/github/license/Junebugg1214/Cortex-AI)](https://github.com/Junebugg1214/Cortex-AI/blob/main/LICENSE)

# Cortex

You use multiple AI tools.  
They all think you're a stranger.  
Cortex fixes that.

Cortex is a CLI and MCP server for portable AI context across Claude, Claude Code, ChatGPT, Codex, Gemini, Grok, Windsurf, Cursor, and Copilot. Humans curate context with the CLI. AI tools fetch their live routed slice over MCP.

```bash
pip install "cortex-identity[server]"

cortex portable chatgpt-export.zip --to all --project .
cortex scan
cortex sync --smart
```

What that looks like:

```text
$ cortex portable chatgpt-export.zip --to all --project .
Portable context ready:
  context: portable/context.json
  source: openai
  extracted: 43 topics across 8 categories

$ cortex scan
Found 5 AI tools:
  Claude Code  ████████████░░░░░░░░   24 facts  (CLAUDE.md)
  Cursor       ████████░░░░░░░░░░░░   16 facts  (.cursor/rules/cortex.mdc)
  Copilot      ██████░░░░░░░░░░░░░░   12 facts  (copilot-instructions.md)
```

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

## The Data Model

`context.json` is a graph-shaped portable context file. Nodes represent facts like projects, preferences, identity, or tech stack. Edges connect those facts. Tags decide how facts are grouped and routed, which is why the same canonical graph can power Claude Code, Cursor, ChatGPT, and MCP without duplicating the same blob everywhere.

```json
{
  "schema_version": "6.0",
  "nodes": [
    {"id": "project/cortex", "label": "Cortex-AI", "tags": ["active_priorities"]},
    {"id": "tech/python", "label": "Python", "tags": ["technical_expertise"]}
  ],
  "edges": [
    {"source_id": "tech/python", "target_id": "project/cortex", "relation": "used_in"}
  ]
}
```

## CLI for Humans, MCP for AI Tools

Use `cortex scan`, `cortex remember`, `cortex portable`, and `cortex sync --smart` to curate your context. Run `cortex-mcp --config .cortex/config.toml` so MCP-capable tools can pull their live routed slice during conversations instead of relying only on local files.

## Smart Routing Tags

`cortex sync --smart` does not send the same slice everywhere.

| Tool | Default routed categories |
| --- | --- |
| Claude Code / Codex | `technical_expertise`, `domain_knowledge`, `active_priorities`, `communication_preferences`, `user_preferences` |
| Cursor / Windsurf | `technical_expertise`, `active_priorities`, `communication_preferences`, `user_preferences` |
| Copilot | `technical_expertise`, `communication_preferences`, `user_preferences`, `constraints` |
| ChatGPT / Grok | identity, professional context, priorities, domain context, values |
| Gemini | domain context, professional context, priorities, technical context |

## Beyond Portability

- Versioned graph runtime: diff, review, rollback, blame, and history when you need more than sync. Run `cortex --help-all`.
- Self-hosted API and UI: local REST API, web control plane, metrics, backup/restore, and scoped auth. See [docs/SELF_HOSTING.md](docs/SELF_HOSTING.md).
- Agent loop integration: Python helpers, TypeScript SDK, and MCP quickstarts. See [docs/AGENT_QUICKSTARTS.md](docs/AGENT_QUICKSTARTS.md).
- Portability reference docs: extraction, sync, routing, artifacts, and platform notes. See [docs/PORTABILITY.md](docs/PORTABILITY.md).

## Uninstall

Cortex writes its managed content inside explicit `CORTEX:START` / `CORTEX:END` markers or dedicated generated files. Your own text outside those markers is left alone. To remove Cortex, delete the generated files you do not want anymore or remove the marked block from mixed files, then delete `.cortex/` and any exported `portable/` directory.
