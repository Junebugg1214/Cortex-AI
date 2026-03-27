# Portability

Cortex now has a single portability front door:

```bash
cortex portable chatgpt-export.zip --to all --project .
```

That command does three things in one pass:

1. Loads an existing Cortex graph or extracts one from a raw export.
2. Saves a portable `context.json`.
3. Installs or generates context for the targets you asked for.

## Target Model

Cortex is explicit about how each target works.

- **Direct installs** write into local instruction files the tool already understands.
- **Import-ready artifacts** generate files you can paste or import into chat apps that do not expose a stable local file path.

## Supported Targets

| Target | Delivery | Output |
|---|---|---|
| `claude-code` | Direct install | `~/.claude/CLAUDE.md` and `./CLAUDE.md` |
| `codex` | Direct install | `./AGENTS.md` |
| `cursor` | Direct install | `./.cursor/rules/cortex.mdc` |
| `gemini` | Direct install | `./GEMINI.md` |
| `windsurf` | Direct install | `./.windsurfrules` |
| `claude` | Import-ready artifacts | `portable/claude/claude_preferences.txt`, `portable/claude/claude_memories.json` |
| `chatgpt` | Import-ready artifacts | `portable/chatgpt/custom_instructions.md`, `portable/chatgpt/custom_instructions.json` |
| `grok` | Import-ready artifacts | `portable/grok/context_prompt.md`, `portable/grok/context_prompt.json` |

## Examples

Import a ChatGPT export and install everywhere:

```bash
cortex portable chatgpt-export.zip --to all --project .
```

Start from an existing graph and only target coding tools:

```bash
cortex portable context.json --to claude-code codex cursor gemini windsurf --project .
```

Generate only ChatGPT and Grok artifacts:

```bash
cortex portable context.json --to chatgpt grok -o ./portable
```

Dry run without writing files:

```bash
cortex portable chatgpt-export.zip --to all --project . --dry-run
```

## Notes

- `claude-code` installs both a global user file and a project file.
- `gemini-cli` is still accepted as an alias for `gemini`.
- The portability command keeps storage user-owned. It does not upload memory anywhere.
- If you want lower-level control, the older `extract`, `import`, `sync`, and `context-write` commands still exist.
