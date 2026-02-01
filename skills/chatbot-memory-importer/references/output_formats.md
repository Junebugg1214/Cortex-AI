# Output Formats Reference v4.0

## Format Summary

| Format | File | Use Case |
|--------|------|----------|
| `claude-preferences` | `claude_preferences.txt` | Claude Settings > Profile |
| `claude-memories` | `claude_memories.json` | memory_user_edits tool |
| `system-prompt` | `system_prompt.txt` | Any LLM API system prompt |
| `notion` | `notion_page.md` | Notion page import |
| `notion-db` | `notion_database.json` | Notion database rows |
| `gdocs` | `google_docs.html` | Google Docs import |
| `summary` | `summary.md` | Human-readable summary |
| `full` | `full_export.json` | Lossless backup |

---

## Claude Preferences

**File:** `claude_preferences.txt`
**Use:** Copy to Claude Settings > Profile

Natural language format optimized for Claude's preference parsing:

```
I am Marc Saint-Jour; MD.
Role: CMO and co-founder of BurnaAI
Business: AI-powered oncology clinical intelligence platform
Currently focused on: Mayo validation study; CTCAE automation
Technical: TypeScript; Vercel; Convex
Domain expertise: Healthcare; AI/ML; Oncology
Values: Accuracy over agreement; Precise communication
Communication: Non-verbose; Professional
Key relationships: Mayo Clinic Platform; Duke
```

---

## Claude Memories

**File:** `claude_memories.json`
**Use:** For `memory_user_edits` tool or manual memory management

JSON array of memory items (max 30):

```json
[
  {
    "text": "User is Marc Saint-Jour, MD",
    "confidence": 0.95,
    "category": "identity"
  },
  {
    "text": "User's business: BurnaAI - AI oncology platform",
    "confidence": 0.9,
    "category": "business_context"
  }
]
```

---

## System Prompt

**File:** `system_prompt.txt`
**Use:** Include in system prompts for any LLM API

XML context block:

```xml
<user_context>
  <identity>
    - Marc Saint-Jour, MD
    - CMO and co-founder of BurnaAI
  </identity>
  <business_context>
    - BurnaAI: AI-powered oncology clinical intelligence platform
    - $15 billion market opportunity
  </business_context>
  <active_priorities>
    - Mayo Clinic Platform validation study
    - CTCAE grading automation
  </active_priorities>
  <technical_expertise>
    - TypeScript
    - Vercel
    - Convex
  </technical_expertise>
  <values>
    - Accuracy over agreement
    - Precise communication
  </values>
</user_context>
```

---

## Notion Page

**File:** `notion_page.md`
**Use:** Import directly into Notion as a page

Markdown with Notion-compatible formatting:

```markdown
# User Context Profile

> Generated: 2025-01-31 12:00
> Confidence threshold: 0.6

## 📊 Summary

| Metric | Value |
|--------|-------|
| Total Topics | 42 |
| High Confidence | 18 |
| Medium Confidence | 20 |
| Low Confidence | 4 |

## 👤 Identity

### 🟢 Marc Saint-Jour
CMO and co-founder of BurnaAI
- **Timeline:** current

### 🟢 MD

## 🏢 Business/Company

### 🟢 BurnaAI
AI-powered oncology clinical intelligence platform
- **Metrics:** $15B market, $5-10M seed
- **Related:** Mayo Clinic Platform
```

Confidence indicators:
- 🟢 High (≥0.8)
- 🟡 Medium (0.6-0.8)
- 🟠 Low (<0.6)

---

## Notion Database

**File:** `notion_database.json`
**Use:** Import as Notion database rows

JSON array of database rows:

```json
[
  {
    "Topic": "BurnaAI",
    "Category": "Business/Company",
    "Confidence": 0.9,
    "Detail Level": "full",
    "Brief": "AI oncology platform",
    "Full Description": "AI-powered oncology clinical intelligence platform",
    "Metrics": ["$15B market", "$5-10M seed"],
    "Relationships": ["Mayo Clinic Platform"],
    "Timeline": "current",
    "Mention Count": 5
  }
]
```

**Database Properties:**

| Property | Type | Description |
|----------|------|-------------|
| Topic | Title | Main topic name |
| Category | Select | Category classification |
| Confidence | Number | 0.0-1.0 score |
| Detail Level | Select | full/moderate/minimal |
| Brief | Text | Short description |
| Full Description | Text | Detailed description |
| Metrics | Multi-select | Associated metrics |
| Relationships | Multi-select | Related entities |
| Timeline | Text | current/past/planned |
| Mention Count | Number | Times mentioned |

---

## Google Docs

**File:** `google_docs.html`
**Use:** Open in browser, copy/paste to Google Docs

Styled HTML with Google Docs-compatible formatting:

```html
<!DOCTYPE html>
<html>
<head>
  <title>User Context Profile</title>
  <style>
    body { font-family: Arial, sans-serif; }
    .badge-high { background: #e6f4ea; color: #34a853; }
    .badge-medium { background: #fef7e0; color: #f9ab00; }
  </style>
</head>
<body>
  <h1>User Context Profile</h1>
  <h2>Identity</h2>
  <h3>Marc Saint-Jour <span class="badge badge-high">High</span></h3>
  <p>CMO and co-founder of BurnaAI</p>
</body>
</html>
```

---

## Summary

**File:** `summary.md`
**Use:** Human-readable overview

Markdown with confidence indicators:

```markdown
# User Context Summary

**Total:** 42 topics
- 🟢 High confidence: 18
- 🟡 Medium confidence: 20
- 🟠 Low confidence: 4

## Identity
- 🟢 **Marc Saint-Jour**: MD, CMO and co-founder of BurnaAI
- 🟢 **MD**: Medical degree

## Business/Company
- 🟢 **BurnaAI**: AI oncology platform | Metrics: $15B market
```

---

## Full JSON

**File:** `full_export.json`
**Use:** Lossless backup, transfer between systems

Complete v4 schema export with all metadata:

```json
{
  "schema_version": "4.0",
  "meta": {
    "generated_at": "2025-01-31T12:00:00Z",
    "exported_at": "2025-01-31T12:05:00Z",
    "confidence_threshold": 0.6
  },
  "categories": {
    "identity": [
      {
        "topic": "Marc Saint-Jour",
        "brief": "Marc Saint-Jour",
        "full_description": "CMO and co-founder of BurnaAI",
        "confidence": 0.95,
        "mention_count": 5,
        "detail_level": "full",
        "metrics": [],
        "relationships": ["BurnaAI"],
        "timeline": ["current"]
      }
    ]
  }
}
```
