# Chatbot Memory Extractor

Extract user context and knowledge from any chatbot export (ChatGPT, Claude, Gemini, or generic conversation logs) into a universal portable format.

## Version

4.0.0

## Triggers

Use when users want to:
- "import my ChatGPT history"
- "extract my context"
- "migrate my conversations"
- "export my memory"
- "transfer my profile from [chatbot]"

## Features (v4)

| Feature | Description |
|---------|-------------|
| **Semantic Deduplication** | Fuzzy matching merges similar topics (85% threshold) |
| **Hyphenated Names** | Captures "Saint-Jour", "O'Brien", "Van Der Berg" |
| **Time Decay** | Recent mentions boost confidence more than old ones |
| **Topic Merging** | Combines related topics within categories |
| **12 Categories** | Identity, professional, business, priorities, relationships, technical, domain, market, metrics, values, communication, mentions |

## Usage

```bash
# Basic extraction
python extract_memory.py conversations.json -o context.json

# With verbose output
python extract_memory.py conversations.json --verbose --stats

# Specify format explicitly
python extract_memory.py export.zip -f openai -o context.json
```

## Supported Formats

| Format | Extension | Detection |
|--------|-----------|-----------|
| OpenAI/ChatGPT | `.json`, `.zip` | Auto-detected by `mapping` structure |
| Claude | `.json` | Auto-detected by `messages` array |
| Generic JSON | `.json` | Fallback for message lists |
| Plain text | `.txt`, `.md` | Paragraph-based extraction |

## Output Schema (v4)

```json
{
  "schema_version": "4.0",
  "meta": {
    "generated_at": "2025-01-31T12:00:00Z",
    "method": "aggressive_extraction_v4",
    "features": ["semantic_dedup", "time_decay", "topic_merging"]
  },
  "categories": {
    "identity": [
      {
        "topic": "Marc Saint-Jour",
        "brief": "Marc Saint-Jour",
        "full_description": "CMO and co-founder, MD",
        "confidence": 0.95,
        "mention_count": 5,
        "metrics": [],
        "relationships": ["BurnaAI"],
        "timeline": ["current"],
        "first_seen": "2025-01-15T10:00:00Z",
        "last_seen": "2025-01-31T12:00:00Z"
      }
    ]
  }
}
```

## Confidence Scoring

Base confidence by extraction method:
- `explicit_statement`: 0.85 ("I am X", "My name is")
- `self_reference`: 0.80 ("my company", "our product")
- `direct_description`: 0.75 (describing own work)
- `contextual`: 0.60 (inferred from context)
- `mentioned`: 0.40 (passing reference)
- `inferred`: 0.30 (weak inference)

Mention count boost: +0.1 (2x), +0.15 (3x), +0.2 (5x), +0.25 (10x), +0.3 (20x)

Time decay: Recent mentions (< 1 week) get full boost, older mentions decay to 10% boost.

## Workflow

```bash
# 1. Download export from ChatGPT/Claude
# 2. Extract context
python extract_memory.py ~/Downloads/chatgpt-export.zip -o context.json

# 3. Preview extraction
python extract_memory.py context.json --verbose

# 4. Import to target platform
python import_memory.py context.json -f all -c medium -o ./output
```

## Dependencies

- Python 3.10+
- No external packages required (uses only stdlib)
