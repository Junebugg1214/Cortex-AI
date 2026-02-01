---
name: chatbot-memory-extractor
description: Extract user context and knowledge from any chatbot export (ChatGPT, Claude, Gemini, or generic conversation logs) into a universal portable format. Version 4.0 adds semantic deduplication, better hyphenated name handling, time decay for confidence scoring, and topic merging. Use when users want to migrate their chatbot history, import conversation context from another AI, extract their profile from chat exports, or preserve their accumulated knowledge. Triggers on phrases like "import my ChatGPT history", "extract my context", "migrate my conversations", "export my memory", or "transfer my profile from [chatbot]".
---

# Chatbot Memory Extractor v4.0

Extract user context from any chatbot export into a universal portable format.

## What's New in v4

| Feature | Description |
|---------|-------------|
| **Semantic Deduplication** | Fuzzy matching merges similar topics (85% threshold) |
| **Hyphenated Names** | Captures "Saint-Jour", "O'Brien", "Van Der Berg" |
| **Time Decay** | Recent mentions boost confidence more than old ones |
| **Topic Merging** | Combines related topics within categories |

## Quick Start

```bash
python scripts/extract_memory.py conversations.json -o context.json
python scripts/extract_memory.py conversations.json --verbose --stats
```

## Supported Formats

| Format | Extension | Detection |
|--------|-----------|-----------|
| OpenAI/ChatGPT | `.json`, `.zip` | Auto-detected by `mapping` structure |
| Claude | `.json` | Auto-detected by `messages` array |
| Generic JSON | `.json` | Fallback for message lists |
| Plain text | `.txt`, `.md` | Paragraph-based extraction |

## Categories Extracted (12)

| Category | What it captures |
|----------|------------------|
| Identity | Name, credentials, titles |
| Professional Context | Roles, positions, job titles |
| Business Context | Companies, products, stage |
| Active Priorities | Current focus, goals, projects |
| Relationships | Partners, advisors, collaborators |
| Technical Expertise | Languages, frameworks, tools |
| Domain Knowledge | Fields, specializations |
| Market Context | Competitors, market references |
| Metrics | Numbers, money, percentages |
| Values | Principles, beliefs |
| Communication Preferences | Style preferences |
| Mentions | Low-confidence catch-all |

## Confidence Scoring

Base confidence by extraction method:
- `explicit_statement`: 0.85 ("I am X", "My name is")
- `self_reference`: 0.80 ("my company", "our product")
- `direct_description`: 0.75 (describing own work)
- `contextual`: 0.60 (inferred from context)
- `mentioned`: 0.40 (passing reference)
- `inferred`: 0.30 (weak inference)

**Mention count boost:** +0.1 (2x), +0.15 (3x), +0.2 (5x), +0.25 (10x), +0.3 (20x)

**Time decay:** Recent mentions (< 1 week) get full boost, older mentions decay to 10%.

## Output Schema

See `references/context_schema.md` for complete v4 schema documentation.

```json
{
  "schema_version": "4.0",
  "meta": {
    "generated_at": "ISO timestamp",
    "method": "aggressive_extraction_v4",
    "features": ["semantic_dedup", "time_decay", "topic_merging"]
  },
  "categories": {
    "identity": [
      {
        "topic": "Name",
        "brief": "Short description",
        "full_description": "Detailed description",
        "confidence": 0.95,
        "mention_count": 5,
        "first_seen": "ISO timestamp",
        "last_seen": "ISO timestamp"
      }
    ]
  }
}
```

## Workflow

1. User provides chatbot export file (JSON, ZIP, or text)
2. Run extraction script with `--verbose` to preview
3. Review generated JSON for accuracy
4. Use `chatbot-memory-importer` skill to convert to target formats

## Dependencies

- Python 3.10+
- No external packages required (uses only stdlib)
