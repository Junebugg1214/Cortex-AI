---
name: chatbot-memory-importer
description: Convert universal portable user context (from chatbot-memory-extractor) into platform-specific memory formats including Claude preferences, Claude memories, system prompts, Notion pages, Notion databases, and Google Docs. Version 4.0 adds Notion export and Google Docs HTML export. Use when users want to import their context, set up their profile, configure Claude with their history, apply extracted memories, or export to Notion or Google Docs. Triggers on phrases like "import my context", "configure Claude with my history", "apply my extracted memories", "export to Notion", "create Google Doc from context".
---

# Chatbot Memory Importer v4.0

Convert universal context into platform-specific memory formats.

## What's New in v4

| Feature | Description |
|---------|-------------|
| **Notion Export** | Markdown pages + database JSON ready for import |
| **Google Docs Export** | Styled HTML that pastes directly into Google Docs |
| **Confidence Filtering** | Export only high/medium/low confidence items |

## Quick Start

```bash
# Export all formats
python scripts/import_memory.py context.json -f all -c medium -o ./output

# Just Claude formats
python scripts/import_memory.py context.json -f claude-preferences -c high

# Notion export
python scripts/import_memory.py context.json -f notion -c medium

# Preview without writing
python scripts/import_memory.py context.json --dry-run -c medium
```

## Output Formats

| Format | Flag | Output File | Use Case |
|--------|------|-------------|----------|
| Claude Preferences | `claude-preferences` | `claude_preferences.txt` | Settings > Profile |
| Claude Memories | `claude-memories` | `claude_memories.json` | memory_user_edits tool |
| System Prompt | `system-prompt` | `system_prompt.txt` | Any LLM API |
| Notion Page | `notion` | `notion_page.md` | Notion page import |
| Notion Database | `notion-db` | `notion_database.json` | Notion DB rows |
| Google Docs | `gdocs` | `google_docs.html` | Google Docs import |
| Summary | `summary` | `summary.md` | Human overview |
| Full JSON | `full` | `full_export.json` | Lossless backup |

## Confidence Levels

| Flag | Threshold | High Topics | Medium Topics | Low Topics |
|------|-----------|-------------|---------------|------------|
| `-c high` | 0.8 | Full detail | Excluded | Excluded |
| `-c medium` | 0.6 | Full detail | Moderate | Excluded |
| `-c low` | 0.4 | Full detail | Moderate | Minimal |
| `-c all` | 0.0 | Full detail | Moderate | Minimal |

## Output Examples

### Claude Preferences

```
I am Marc Saint-Jour; MD.
Role: CMO and co-founder of BurnaAI
Business: AI-powered oncology clinical intelligence platform
Currently focused on: Mayo validation study; CTCAE automation
Technical: TypeScript; Vercel; Convex
Values: Accuracy over agreement
```

### System Prompt (XML)

```xml
<user_context>
  <identity>
    - Marc Saint-Jour, MD
    - CMO and co-founder of BurnaAI
  </identity>
  <business_context>
    - BurnaAI: AI oncology platform
  </business_context>
</user_context>
```

### Notion Page

Markdown with emoji headers and confidence badges:
- 🟢 High confidence (≥0.8)
- 🟡 Medium confidence (0.6-0.8)
- 🟠 Low confidence (<0.6)

### Google Docs

Styled HTML with color-coded badges, summary tables, and clean typography.

## Workflow

1. Extract context using `chatbot-memory-extractor` skill
2. Preview with `--dry-run -c medium`
3. Export all formats with `-f all`
4. Apply to target platforms:
   - Copy `claude_preferences.txt` → Claude Settings > Profile
   - Import `notion_page.md` → Notion
   - Open `google_docs.html` → Copy to Google Docs

## Output Files

```
output/
├── claude_preferences.txt    # Settings > Profile
├── claude_memories.json      # memory_user_edits
├── system_prompt.txt         # LLM APIs
├── notion_page.md           # Notion page
├── notion_database.json     # Notion database
├── google_docs.html         # Google Docs
├── summary.md               # Human summary
└── full_export.json         # Lossless backup
```

## Dependencies

- Python 3.10+
- No external packages required (uses only stdlib)
