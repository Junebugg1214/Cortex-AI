# Extraction Eval Corpus

This directory contains hand-authored extraction evaluation fixtures. Each case is
listed in `manifest.yml` and lives in its own directory with exactly one input
file plus a `gold.json` expected graph.

## Case Layout

Each case directory contains:

- `input.md`, `input.json`, or `input.jsonl`: the source document submitted to
  the extraction pipeline.
- `gold.json`: the expected graph for the source document.

## Gold Schema

`gold.json` files use this shape:

```json
{
  "schema_version": "extraction-eval-v1",
  "case_id": "case-directory-name",
  "source_type": "chat|doc|code|transcript",
  "expected_graph": {
    "nodes": [
      {
        "id": "node-id",
        "canonical_id": "stable-canonical-id",
        "label": "Human label",
        "type": "semantic_type",
        "confidence": 0.95
      }
    ],
    "edges": [
      {
        "id": "edge-id",
        "source": "source-node-canonical-id",
        "target": "target-node-canonical-id",
        "type": "relationship_type",
        "confidence": 0.9
      }
    ]
  }
}
```

The corpus is intentionally small. It is meant to lock down extraction harness
shape first, then grow into scoring data as the intelligent extractor matures.
