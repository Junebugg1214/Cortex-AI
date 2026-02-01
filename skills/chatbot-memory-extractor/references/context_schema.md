# Context Schema v4.0

## Full Schema

```json
{
  "schema_version": "4.0",
  "meta": {
    "generated_at": "ISO-8601 timestamp",
    "method": "aggressive_extraction_v4",
    "features": ["semantic_dedup", "time_decay", "topic_merging"],
    "source_format": "openai|claude|generic|text"
  },
  "categories": {
    "<category_name>": [
      {
        "topic": "string - main topic name",
        "brief": "string - short description",
        "full_description": "string - detailed description with context",
        "confidence": 0.0-1.0,
        "mention_count": "integer",
        "extraction_method": "explicit_statement|self_reference|direct_description|contextual|mentioned|inferred",
        "metrics": ["array of related numbers/metrics"],
        "relationships": ["array of related entities"],
        "timeline": ["current", "past", "planned"],
        "source_quotes": ["array of source text snippets"],
        "first_seen": "ISO-8601 timestamp or null",
        "last_seen": "ISO-8601 timestamp or null"
      }
    ]
  }
}
```

## Categories

| Category | Description | Examples |
|----------|-------------|----------|
| `identity` | User's name, credentials, titles | "Marc Saint-Jour", "MD", "PhD" |
| `professional_context` | Roles, positions, job titles | "CMO", "Software Engineer" |
| `business_context` | Companies, products, stage | "BurnaAI", "Series A startup" |
| `active_priorities` | Current focus, goals, projects | "Mayo validation study" |
| `relationships` | Partners, advisors, collaborators | "Mayo Clinic Platform" |
| `technical_expertise` | Languages, frameworks, tools | "TypeScript", "React", "AWS" |
| `domain_knowledge` | Fields, specializations | "Healthcare", "AI/ML", "Legal" |
| `market_context` | Competitors, market references | "Flatiron Health" |
| `metrics` | Numbers, money, percentages | "$15B market", "≥0.8 kappa" |
| `values` | Principles, beliefs | "Accuracy over agreement" |
| `communication_preferences` | Style preferences | "Precise, non-verbose" |
| `mentions` | Low-confidence catch-all | Entities that don't fit elsewhere |

## Confidence Scoring

### Base Confidence by Extraction Method

| Method | Base Score | Example Pattern |
|--------|------------|-----------------|
| `explicit_statement` | 0.85 | "I am X", "My name is Y" |
| `self_reference` | 0.80 | "my company", "our product" |
| `direct_description` | 0.75 | "I'm building X" |
| `contextual` | 0.60 | Inferred from surrounding text |
| `mentioned` | 0.40 | Passing reference |
| `inferred` | 0.30 | Weak inference |

### Mention Count Boost

| Mentions | Boost |
|----------|-------|
| 1 | +0.00 |
| 2 | +0.10 |
| 3 | +0.15 |
| 5+ | +0.20 |
| 10+ | +0.25 |
| 20+ | +0.30 |

### Time Decay Multiplier

| Age | Multiplier |
|-----|------------|
| < 1 week | 1.0 |
| < 1 month | 0.9 |
| < 3 months | 0.7 |
| < 6 months | 0.5 |
| < 1 year | 0.3 |
| > 1 year | 0.1 |

Final confidence = min(0.95, base + (boost × decay))

## Semantic Deduplication

Topics are merged when similarity ≥ 85%:

```
Similarity = max(
  SequenceMatcher ratio,
  Word overlap (Jaccard)
)
```

When merged:
- Keep longer/better topic name
- Sum mention counts
- Take max confidence
- Combine metrics, relationships, timeline
- Keep first_seen from earliest, last_seen from latest

## Topic Merging

Within mergeable categories, topics with ≥80% similarity are combined:

- `technical_expertise`: "React" + "React.js" → merged
- `domain_knowledge`: "AI" + "Artificial Intelligence" → merged
- `business_context`: Company variants consolidated
- `relationships`: Partner references deduplicated
- `active_priorities`: Similar projects combined
