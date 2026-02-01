# Universal Context Schema Reference

This document defines the portable user context format used for cross-platform chatbot memory migration.

## Schema Version: 1.0

## JSON Structure

```json
{
  "schema_version": "1.0",
  "generated_at": "ISO8601 timestamp",
  "source": {
    "source_file": "filename",
    "source_type": "json|text",
    "total_messages": number,
    "user_messages": number,
    "extraction_date": "ISO8601 timestamp"
  },
  "categories": {
    "<category_name>": {
      "facts": [<fact_object>],
      "total_extracted": number
    }
  },
  "summary": {
    "total_facts": number,
    "high_confidence_facts": number,
    "categories_with_data": number
  }
}
```

## Categories

| Category | Description | Examples |
|----------|-------------|----------|
| `identity` | Name, role, title, company, location | "Marc", "CMO", "Delaware" |
| `professional_context` | Company, projects, industry, team, clients | "BurnaAI", "healthcare AI", "Mayo Clinic partnership" |
| `personal_context` | Family, hobbies, interests, lifestyle | "two kids", "enjoys hiking" |
| `communication_preferences` | Tone, format, verbosity, style preferences | "prefers bullet points", "be direct" |
| `technical_expertise` | Programming languages, tools, platforms, skills | "Python", "AWS", "TypeScript" |
| `recurring_workflows` | Common task patterns and requests | "writes investor materials", "creates presentations" |
| `domain_knowledge` | Specialized knowledge areas | "CTCAE grading", "clinical trials", "FDA compliance" |
| `active_priorities` | Current focus areas, deadlines, urgent work | "seed funding round", "Q4 launch" |

## Fact Object Structure

```json
{
  "text": "The extracted fact text",
  "normalized": "lowercase normalized version",
  "frequency": 5,
  "recency_score": 0.85,
  "frequency_score": 0.71,
  "combined_score": 0.79,
  "confidence": {
    "level": "high|medium|low|very_low",
    "score": 0.9,
    "factors": {
      "frequency": 5,
      "has_explicit_statement": true
    }
  },
  "occurrences": 5,
  "extraction_type": "pattern|entity"
}
```

## Scoring Algorithms

### Combined Score
```
combined_score = (recency_score × 0.6) + (frequency_score × 0.4)
```

- **Recency score**: Position of most recent mention (0 = oldest, 1 = newest)
- **Frequency score**: `min(1.0, (frequency / 10)^0.5)` — log scale to prevent outliers

### Confidence Levels

| Level | Score Range | Criteria |
|-------|-------------|----------|
| High | 0.8 - 1.0 | 5+ mentions AND explicit pattern match |
| Medium | 0.6 - 0.79 | 3+ mentions OR explicit pattern match |
| Low | 0.4 - 0.59 | 2+ mentions |
| Very Low | 0.3 - 0.39 | Single mention only |

## Supported Input Formats

The extractor auto-detects these formats:

1. **ChatGPT Export** — `conversations[].mapping{}.message{}`
2. **Claude Export** — `chat_messages[].text`
3. **Generic JSON** — Arrays with `role`/`content` or `author`/`text` fields
4. **Text Transcript** — `User:` / `Assistant:` turn markers

## Usage Notes

- Facts are deduplicated by normalized text
- Maximum 20 facts retained per category
- Markdown output shows top 10 per category for readability
- Review extracted data before importing to target platform
