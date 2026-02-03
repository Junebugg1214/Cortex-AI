# Chatbot Memory Skills v4.2

Migrate your AI conversation history between platforms. Extract context from ChatGPT, Claude, Gemini, Perplexity, or any chatbot and import it into Claude, Notion, Google Docs, or any LLM.

## What's New in v4.2

| Feature | Description |
|---------|-------------|
| **Typed Relationships** | Classify relationships as partner, mentor, advisor, investor, client, or competitor |
| **Conflict Detection** | Automatically flags contradictory statements (e.g., "I use Python" vs "I avoid Python") |
| **Incremental Merge** | `--merge` flag combines new extractions with existing context files |
| **Claude Memory Import** | Import Claude `memory_user_edits` exports back to v4 schema (bidirectional sync) |

## What's in v4.1

| Feature | Description |
|---------|-------------|
| **Negation Detection** | "I don't use Python" filters Python from technical skills |
| **Cross-Category Filtering** | Negated and corrected items removed from positive categories |
| **Preferences Category** | Captures "I prefer X", "I always use Y" patterns |
| **Constraints Category** | Extracts budget, timeline, team size, regulatory requirements |
| **Correction History** | Tracks "I meant X not Y" patterns for context |
| **Gemini Support** | Import from Google AI Studio / Gemini exports |
| **Perplexity Support** | Import from Perplexity conversation exports |
| **JSONL & API Logs** | Import from OpenAI/Anthropic API conversation logs |

## What's in v4.0

| Feature | Description |
|---------|-------------|
| **Semantic Deduplication** | Fuzzy matching merges "BurnaAI" and "Burna AI" automatically |
| **Better Name Handling** | Properly captures "Saint-Jour", "O'Brien", "Mary-Jane" |
| **Time Decay** | Recent mentions boost confidence more than old ones |
| **Topic Merging** | Combines related topics within categories |
| **Notion Export** | Markdown pages + database JSON ready for import |
| **Google Docs Export** | Styled HTML that pastes directly into Google Docs |

## Quick Start

```bash
# 1. Download your ChatGPT export (Settings → Data controls → Export)

# 2. Extract context
python skills/chatbot-memory-extractor/scripts/extract_memory.py \
  ~/Downloads/chatgpt-export.zip -o context.json

# 3. Export to all formats
python skills/chatbot-memory-importer/scripts/import_memory.py \
  context.json -f all -c medium -o ./output
```

## Skills Included

### chatbot-memory-extractor

Extracts user context from conversation exports:

- **Input:** ChatGPT `.zip`, Claude `.json`, Gemini, Perplexity, JSONL, API logs, plain text
- **Output:** Universal v4 context JSON
- **Features:** 16 extraction categories, negation filtering, semantic dedup, time decay, typed relationships, conflict detection, incremental merge

**Extraction Categories:**

| Category | Examples |
|----------|----------|
| Identity | Name, credentials (MD, PhD) |
| Professional Context | Role, title, company |
| Business Context | Company, products, metrics |
| Active Priorities | Current projects, goals |
| Relationships | Partners, clients, collaborators |
| Technical Expertise | Languages, frameworks, tools |
| Domain Knowledge | Healthcare, finance, AI/ML |
| Market Context | Competitors, industry |
| Metrics | Revenue, users, timelines |
| **Constraints** | Budget, timeline, team size |
| Values | Principles, beliefs |
| **Negations** | What user explicitly avoids |
| **User Preferences** | Style and tool preferences |
| Communication Preferences | Response style preferences |
| **Correction History** | Self-corrections and clarifications |
| Mentions | Catch-all for other entities |

```bash
# Basic extraction
python extract_memory.py conversations.json --verbose --stats

# Merge with existing context
python extract_memory.py new_export.json --merge existing_context.json -o merged.json
```

### chatbot-memory-importer

Converts context to platform-specific formats:

| Format | Output File | Use Case |
|--------|-------------|----------|
| Claude Preferences | `claude_preferences.txt` | Settings > Profile |
| Claude Memories | `claude_memories.json` | memory_user_edits |
| System Prompt | `system_prompt.txt` | Any LLM API |
| Notion Page | `notion_page.md` | Notion import |
| Notion Database | `notion_database.json` | Notion DB rows |
| Google Docs | `google_docs.html` | Google Docs |
| Summary | `summary.md` | Human overview |
| Full JSON | `full_export.json` | Lossless backup |

```bash
python import_memory.py context.json -f all -c medium -o ./output
```

## Supported Input Formats

| Format | File Type | Auto-Detected |
|--------|-----------|---------------|
| ChatGPT Export | `.zip` with `conversations.json` | Yes |
| Claude Export | `.json` with messages array | Yes |
| Claude Memories | `.json` array with `text` field | Yes |
| Gemini/AI Studio | `.json` with conversations/turns | Yes |
| Perplexity | `.json` with threads | Yes |
| API Logs | `.json` with requests array | Yes |
| JSONL | `.jsonl` (one message per line) | Yes |
| Plain Text | `.txt`, `.md` | Yes |
| Generic JSON | `.json` with messages | Yes |

## Confidence Levels

| Flag | Threshold | Behavior |
|------|-----------|----------|
| `-c high` | ≥0.8 | Only high-confidence topics |
| `-c medium` | ≥0.6 | High + medium confidence |
| `-c low` | ≥0.4 | Include low confidence |
| `-c all` | ≥0.0 | Everything |

## Installation

### As Claude Skills

1. Download this repo
2. In Claude.ai, go to **Settings > Skills**
3. Add each skill folder

### As Claude Code Plugin

```bash
/plugin marketplace add Junebugg1214/chatbot-memory-skills
/plugin install chatbot-memory-extractor
/plugin install chatbot-memory-importer
```

### Standalone

```bash
git clone https://github.com/Junebugg1214/chatbot-memory-skills.git
cd chatbot-memory-skills

# Extract
python skills/chatbot-memory-extractor/scripts/extract_memory.py input.json -o context.json

# Import
python skills/chatbot-memory-importer/scripts/import_memory.py context.json -f all -o ./output
```

## Example Workflow: ChatGPT → Claude + Notion

```bash
# Extract from ChatGPT
python extract_memory.py ~/Downloads/chatgpt-export.zip -o context.json

# Preview
python import_memory.py context.json --dry-run -c medium

# Export all formats
python import_memory.py context.json -f all -c medium -o ./import

# Apply:
# 1. Copy claude_preferences.txt → Claude Settings > Profile
# 2. Import notion_page.md → Notion
# 3. Open google_docs.html → Copy to Google Docs
```

## Typed Relationships

Relationships are now automatically classified by type:

```
Input: "We partner with Mayo Clinic. Dr. Smith is my mentor. Sequoia invested in us."

Result:
  relationships:
    - Mayo Clinic (type: partner)
    - Dr. Smith (type: mentor)
    - Sequoia (type: investor)
```

Supported relationship types: `partner`, `mentor`, `advisor`, `investor`, `client`, `competitor`

In system prompt exports, relationships are grouped by type for clarity.

## Conflict Detection

The extractor detects contradictory statements and flags them:

```json
{
  "conflicts": [
    {
      "type": "negation_conflict",
      "positive_category": "technical_expertise",
      "positive_topic": "Python",
      "negative_topic": "Python",
      "resolution": "prefer_negation"
    }
  ]
}
```

Resolution is based on timestamps - more recent statements take precedence.

## Incremental Merge

Combine new extractions with existing context using `--merge`:

```bash
# First extraction
python extract_memory.py export1.json -o context.json

# Later: merge new conversations without losing existing data
python extract_memory.py export2.json --merge context.json -o context.json
```

The merge:
- Preserves all existing topics
- Adds new topics from the new extraction
- Deduplicates similar topics automatically
- Preserves relationship types and other metadata

## Claude Memory Import (Bidirectional Sync)

Import Claude's `memory_user_edits` export back to v4 schema:

```bash
# Export your Claude memories from Claude.ai
# Then import them back to v4 format:
python import_memory.py claude_memories.json -f all -o ./output
```

The importer auto-detects Claude memory format (array with `text` field) and parses entries like:
- `"User is John Doe"` → identity
- `"User tech: Python"` → technical_expertise
- `"User avoids: Java"` → negations

This enables round-trip migration: ChatGPT → Claude → back to universal format.

## Negation Filtering Example

The extractor intelligently handles contradictions:

```
Input: "I don't use Python anymore, I prefer TypeScript"

Result:
  negations: ["Python anymore"]
  technical_expertise: ["TypeScript"]  # Python filtered out
  user_preferences: ["TypeScript"]
```

```
Input: "Actually, I meant React not Angular"

Result:
  correction_history: ["Corrected 'Angular' to 'React'"]
  technical_expertise: ["React"]  # Angular filtered out
```

This prevents contradictory information from appearing in your exported context.

## Requirements

- Python 3.9+
- No external packages (stdlib only)

## License

MIT License - See [LICENSE](LICENSE)

## Author

Created by [@Junebugg1214](https://github.com/Junebugg1214)
