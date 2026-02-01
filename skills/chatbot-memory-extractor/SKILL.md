---
name: chatbot-memory-extractor
description: Extract user context and knowledge from any chatbot export (ChatGPT, Claude, Gemini, or generic conversation logs) into a universal portable format. Use when users want to migrate their chatbot history, import conversation context from another AI, extract their profile from chat exports, or preserve their accumulated knowledge from one assistant to use with another. Triggers on phrases like "import my ChatGPT history", "extract my context", "migrate my conversations", "export my memory", or "transfer my profile from [chatbot]".
---

# Chatbot Memory Extractor

Extract user context from any chatbot export into a universal portable format (JSON + Markdown).

## Quick Start

```bash
python scripts/extract_memory.py <input_file> --output-dir <dir>
```

**Output:** `<filename>_context.json` + `<filename>_context.md`

## How It Works

1. **Structure-agnostic parsing** — Auto-detects ChatGPT, Claude, or generic JSON/text formats
2. **Pattern extraction** — Identifies identity, professional context, preferences, expertise, etc.
3. **Weighting algorithm** — Recency (60%) + Frequency (40%) = importance score
4. **Confidence scoring** — Each fact rated high/medium/low/very_low based on evidence strength

## Categories Extracted

| Category | What it captures |
|----------|------------------|
| Identity | Name, role, title, company, location |
| Professional Context | Industry, projects, goals, team, clients |
| Personal Context | Family, interests, hobbies, lifestyle |
| Communication Preferences | Tone, format, verbosity, style |
| Technical Expertise | Languages, tools, platforms, skills |
| Recurring Workflows | Common task patterns |
| Domain Knowledge | Specialized knowledge areas |
| Active Priorities | Current focus, deadlines, urgent work |

## Workflow

1. User provides chatbot export file (JSON or text)
2. Run extraction script
3. Review generated Markdown for accuracy
4. Use JSON for import to target platform (see `chatbot-memory-importer` skill)

## Output Format

See `references/context_schema.md` for complete schema documentation.

### Confidence Levels

- 🟢 **High** — Multiple explicit mentions, reliable
- 🟡 **Medium** — Clear references, likely accurate
- 🟠 **Low** — Inferred or few mentions
- 🔴 **Very Low** — Single mention, verify before using

## Supported Input Formats

- ChatGPT export (JSON with `conversations[]` → `mapping{}`)
- Claude export (JSON with `chat_messages[]`)
- Generic JSON (arrays with `role`/`content` fields)
- Plain text transcripts (`User:` / `Assistant:` format)

## Notes

- Extraction focuses on **user messages only** (what the user said, not the assistant)
- Facts are deduplicated and weighted by importance
- Maximum 20 facts per category retained
- Always review extracted data before importing — automated extraction may miss context or misinterpret statements
