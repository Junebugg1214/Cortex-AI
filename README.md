# Chatbot Memory Skills v4.0

Migrate your AI conversation history between platforms. Extract context from ChatGPT, Claude, or any chatbot and import it into Claude, Notion, Google Docs, or any LLM.

## What's New in v4

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

- **Input:** ChatGPT `.zip`, Claude `.json`, generic messages, plain text
- **Output:** Universal v4 context JSON
- **Features:** 12 extraction categories, semantic dedup, time decay

```bash
python extract_memory.py conversations.json --verbose --stats
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

## Requirements

- Python 3.10+
- No external packages (stdlib only)

## License

MIT License - See [LICENSE](LICENSE)

## Author

Created by [@Junebugg1214](https://github.com/Junebugg1214)
