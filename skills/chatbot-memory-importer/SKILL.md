---
name: chatbot-memory-importer
description: Convert universal portable user context (from chatbot-memory-extractor) into platform-specific memory formats. Use when users want to import their extracted profile into Claude, configure user preferences, generate system prompts for other LLMs, or apply their migrated chatbot history. Triggers on phrases like "import my context", "set up my profile", "configure Claude with my history", "apply my extracted memories", or "use my context file".
---

# Chatbot Memory Importer

Convert universal portable context into platform-specific memory formats.

## Quick Start

```bash
python scripts/import_memory.py <context_file.json> --output-dir <dir> --format all
```

**Input:** Universal context JSON from `chatbot-memory-extractor`

## Output Formats

| Format | Target | Use Case |
|--------|--------|----------|
| `claude-preferences` | Settings > Profile | Paste into Claude's user preferences |
| `claude-memories` | Memory system | Structured memory statements |
| `system-prompt` | Any LLM API | XML context block for system prompts |
| `summary` | Human review | Markdown preview before importing |
| `all` | All of the above | Generate everything |

## Options

```bash
--format, -f       Output format (default: all)
--confidence, -c   Minimum threshold: high|medium|low|all (default: medium)
--categories       Only include specific categories
```

## Confidence Filtering

| Level | Score | Description |
|-------|-------|-------------|
| high | ≥ 0.8 | Only well-established facts |
| medium | ≥ 0.6 | Reliable facts (recommended) |
| low | ≥ 0.4 | Include inferred facts |
| all | ≥ 0.0 | Everything |

## Workflow

1. Run `chatbot-memory-extractor` on source chatbot export
2. Review the generated `_context.md` for accuracy
3. Run this importer with desired confidence threshold
4. Apply outputs to target platform:
   - **Claude preferences:** Copy `_claude_preferences.txt` to Settings > Profile
   - **Claude memories:** Add items from `_claude_memories.json` to memory
   - **Other LLMs:** Prepend `_system_prompt.txt` to your system prompt

## Example

```bash
# High confidence only, just Claude formats
python scripts/import_memory.py context.json -c high -f claude-preferences

# All formats with medium confidence
python scripts/import_memory.py context.json -f all -c medium -o ./output
```

See `references/output_formats.md` for detailed format specifications.
