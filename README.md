# Chatbot Memory Migration Skills

Migrate your accumulated knowledge and context from one AI chatbot to another. Extract your profile from ChatGPT, Claude, Gemini, or any conversation export — then import it into your preferred platform.

## Why?

When you switch AI assistants, you lose all the context that chatbot learned about you — your name, job, projects, preferences, expertise, and workflows. These skills solve that problem by creating a **universal portable context format** that works across platforms.

## Skills Included

### 1. `chatbot-memory-extractor`

Extract user context from any chatbot export into a universal portable format.

**Features:**
- Structure-agnostic parsing (ChatGPT, Claude, Gemini, generic JSON, plain text)
- Recency + frequency weighting (recent & repeated = important)
- Confidence scoring (high/medium/low/very_low)
- Outputs both JSON (machine-readable) and Markdown (human-reviewable)

**Categories extracted:**
- Identity (name, role, company, location)
- Professional context (projects, industry, team)
- Personal context (interests, family, hobbies)
- Communication preferences (tone, format, style)
- Technical expertise (languages, tools, platforms)
- Recurring workflows (common tasks)
- Domain knowledge (specialized areas)
- Active priorities (current focus)

### 2. `chatbot-memory-importer`

Convert the universal context into platform-specific formats.

**Output formats:**
| Format | Use Case |
|--------|----------|
| `claude-preferences` | Paste into Claude Settings > Profile |
| `claude-memories` | Structured memory statements |
| `system-prompt` | XML block for any LLM API |
| `summary` | Human review before importing |

## Installation

### Claude Code

```bash
# Add this marketplace
/plugin marketplace add Junebugg1214/chatbot-memory-skills

# Install the skills
/plugin install chatbot-memory-extractor
/plugin install chatbot-memory-importer
```

### Manual Installation

```bash
# Clone to your skills directory
git clone https://github.com/Junebugg1214/chatbot-memory-skills.git
cp -r chatbot-memory-skills/skills/* ~/.claude/skills/
```

## Usage

### Step 1: Export your chatbot history

**ChatGPT:**
1. Go to Settings → Data controls → Export data
2. Download the ZIP, extract `conversations.json`

**Claude:** Export from Settings (if available) or copy conversation text

**Other chatbots:** Export JSON or copy/paste conversations

### Step 2: Extract your context

```bash
python extract_memory.py conversations.json -o ./output
```

**Output:**
- `conversations_context.json` — Universal portable format (source of truth)
- `conversations_context.md` — Human-readable for review

### Step 3: Review for accuracy

Open the Markdown file and verify the extracted facts are correct. The confidence indicators help you spot uncertain extractions:
- 🟢 High — Multiple explicit mentions
- 🟡 Medium — Clear references
- 🟠 Low — Inferred from context
- 🔴 Very Low — Single mention, verify

### Step 4: Import to target platform

```bash
python import_memory.py output/conversations_context.json -o ./output -c medium
```

**Options:**
- `--confidence, -c` — Filter by confidence: `high`, `medium`, `low`, `all`
- `--format, -f` — Output format: `claude-preferences`, `claude-memories`, `system-prompt`, `summary`, `all`

### Step 5: Apply to your new chatbot

**For Claude:**
1. Copy contents of `_claude_preferences.txt`
2. Go to Settings → Profile → "What would you like Claude to know about you?"
3. Paste and save

**For other LLMs (API):**
1. Prepend contents of `_system_prompt.txt` to your system prompt

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│  ANY CHATBOT EXPORT              UNIVERSAL FORMAT         TARGET PLATFORM
│                                                                         │
│  ChatGPT JSON ──┐                                    ┌─► Claude Preferences
│  Claude export ─┼──► EXTRACTOR ──► context.json ──► IMPORTER ─┼─► Claude Memories
│  Gemini export ─┤                       │                     ├─► System Prompt
│  Plain text ────┘                       ▼                     └─► Any LLM
│                                   context.md                            │
│                                 (human review)                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Universal Context Schema

```json
{
  "schema_version": "1.0",
  "generated_at": "ISO8601",
  "source": { ... },
  "categories": {
    "identity": { "facts": [...] },
    "professional_context": { "facts": [...] },
    ...
  },
  "summary": { ... }
}
```

Each fact includes:
- `text` — The extracted information
- `confidence` — Score (0-1) and level (high/medium/low/very_low)
- `combined_score` — Importance based on recency (60%) + frequency (40%)
- `occurrences` — How many times it was mentioned

## License

MIT License — use freely, attribution appreciated.

## Contributing

PRs welcome! Ideas for improvement:
- Add more source format parsers
- Add more target platform outputs
- Improve extraction patterns
- Add language support beyond English

## Credits

Built with Claude by BurnaAI.
