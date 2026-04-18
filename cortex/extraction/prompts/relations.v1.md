---
version: v1
schema_ref: cortex.extraction.extract_memory_context.ExtractedRelationship
inputs:
  - items
  - existing_graph
outputs:
  - bound_relationships
test_fixture: tests/extraction/test_pipeline_stages.py
---
Bind extracted relationships to canonical source and target endpoints.
Keep relationships only when both endpoints resolve to extracted or existing graph entities.
Drop dangling relationships instead of inventing endpoint IDs.
