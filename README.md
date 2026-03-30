[![PyPI](https://img.shields.io/pypi/v/cortex-identity)](https://pypi.org/project/cortex-identity/)
[![Python](https://img.shields.io/pypi/pyversions/cortex-identity)](https://pypi.org/project/cortex-identity/)
[![License](https://img.shields.io/github/license/Junebugg1214/Cortex-AI)](https://github.com/Junebugg1214/Cortex-AI/blob/main/LICENSE)

# Cortex

You use multiple AI tools.  
They all think you're a stranger.  
Cortex fixes that.

Cortex is a CLI and MCP server for portable AI context across Claude, Claude Code, ChatGPT, Codex, Gemini, Grok, Windsurf, Cursor, and Copilot. Humans curate context with the CLI. AI tools fetch their live routed slice over MCP.

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
python3.11 -m pip install -e ".[server]"

cortex portable chatgpt-export.zip --to all --project .
cortex scan
cortex sync --smart
```

Use `python3.11 -m pip`, not plain `pip`. Cortex requires Python 3.10+, and the full CLI + MCP beta surface in this repo tracks the source install first. If you only want the published core package, use `python3.11 -m pip install cortex-identity`.

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

## Compatibility Matrix

| Platform | Direct file / artifact support | MCP support now | Best Cortex path |
| --- | --- | --- | --- |
| Claude Desktop | No direct file target | Native | `cortex-mcp` |
| Claude Code | `CLAUDE.md` | Native | `cortex-mcp` + `CLAUDE.md` |
| Claude.ai | Import-ready artifacts | Partial / workspace-dependent | Artifacts first, MCP where available |
| Codex | `AGENTS.md` | Native | `cortex-mcp` + `AGENTS.md` |
| Cursor | `.cursor/rules/cortex.mdc` | Native | `cortex-mcp` + direct rule file |
| GitHub Copilot | `.github/copilot-instructions.md` | Native | `cortex-mcp` + direct instruction file |
| Gemini CLI | `GEMINI.md` | Native | `cortex-mcp` + `GEMINI.md` |
| Gemini web app | `GEMINI.md` export path only | No clear consumer MCP path | Direct file output |
| Windsurf | `.windsurfrules` | Native | `cortex-mcp` + direct rule file |
| ChatGPT | Import-ready artifacts | Partial / beta / plan-dependent | Artifacts first, MCP where available |
| Grok API | Import-ready artifacts | Remote MCP via API | Remote MCP or artifacts |
| Grok consumer app | Import-ready artifacts | No clear consumer MCP path | Artifacts |

`cortex-mcp` is the live path for MCP-capable clients. Direct files and import-ready artifacts remain the safest universal path for everything else.

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

`cortex scan` also auto-detects known local platform files and MCP config definitions from the compatibility matrix, so it can recognize tools you already have installed before Cortex has written anything itself. It stays read-only by default; use `cortex extract --from-detected ...` to explicitly adopt detected local context.

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
- Copy-paste platform onboarding: exact first-run flows for ChatGPT, Claude, Claude Code, Codex, Gemini, Grok, Cursor, Copilot, and Windsurf. See [docs/PLATFORM_ONBOARDING.md](docs/PLATFORM_ONBOARDING.md).
- Agent loop integration: Python helpers, TypeScript SDK, and MCP quickstarts. See [docs/AGENT_QUICKSTARTS.md](docs/AGENT_QUICKSTARTS.md).
- Messaging runtime integration: OpenClaw, Hermes, Telegram, and WhatsApp design plus the minimum adapter API. See [docs/CHANNEL_INTEGRATIONS.md](docs/CHANNEL_INTEGRATIONS.md).
- OpenClaw-native plugin package: real `@cortex/openclaw` package scaffold with managed `cortex-mcp`, live prompt injection hooks, and per-user/per-thread memory seeding. See [docs/OPENCLAW_NATIVE_PLUGIN.md](docs/OPENCLAW_NATIVE_PLUGIN.md).
- Portability reference docs: extraction, sync, routing, artifacts, and platform notes. See [docs/PORTABILITY.md](docs/PORTABILITY.md).

## Uninstall

Cortex writes its managed content inside explicit `CORTEX:START` / `CORTEX:END` markers or dedicated generated files. Your own text outside those markers is left alone. To remove Cortex, delete the generated files you do not want anymore or remove the marked block from mixed files, then delete `.cortex/` and any exported `portable/` directory.
