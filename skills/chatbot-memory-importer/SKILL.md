# Chatbot Memory Importer

Convert universal portable user context (from chatbot-memory-extractor) into platform-specific memory formats including Claude, Notion, Google Docs, and more.

## Version

4.0.0

## Triggers

Use when users want to:
- "import my context"
- "set up my profile"
- "configure Claude with my history"
- "apply my extracted memories"
- "use my context file"
- "export to Notion"
- "create Google Doc from context"

## Output Formats (v4)

| Format | Flag | Description |
|--------|------|-------------|
| Claude Preferences | `claude-preferences` | Natural language for Settings > Profile |
| Claude Memories | `claude-memories` | JSON for memory_user_edits tool |
| System Prompt | `system-prompt` | XML context block for LLM APIs |
| Notion Page | `notion` | Markdown with emoji headers and badges |
| Notion Database | `notion-db` | JSON rows for database import |
| Google Docs | `gdocs` | Styled HTML for Google Docs |
| Summary | `summary` | Markdown with confidence indicators |
| Full JSON | `full` | Lossless v4 schema backup |

## Usage

```bash
# Export all formats
python import_memory.py context.json -f all -c medium -o ./output

# Just Claude formats
python import_memory.py context.json -f claude-preferences -c high

# Notion export
python import_memory.py context.json -f notion -c medium -o ./notion

# Google Docs
python import_memory.py context.json -f gdocs -c high

# Preview without writing
python import_memory.py context.json --dry-run -c medium
```

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
Values: Accuracy over agreement; Precise communication
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

```markdown
# User Context Profile

## 👤 Identity
### 🟢 Marc Saint-Jour
CMO and co-founder of BurnaAI
- **Timeline:** current

## 🏢 Business/Company
- 🟢 **BurnaAI**: AI oncology platform
```

### Google Docs (HTML)

Styled HTML with:
- Color-coded confidence badges
- Summary tables
- Metric highlights
- Clean typography

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

## Workflow

```bash
# 1. Extract from source chatbot
python extract_memory.py chatgpt-export.zip -o context.json

# 2. Preview what will be imported
python import_memory.py context.json --dry-run -c medium

# 3. Export all formats
python import_memory.py context.json -f all -c medium -o ./import

# 4. Apply to platforms:
#    - Copy claude_preferences.txt → Claude Settings > Profile
#    - Import notion_page.md → Notion
#    - Open google_docs.html → Copy to Google Docs
```

## Dependencies

- Python 3.10+
- No external packages required (uses only stdlib)
