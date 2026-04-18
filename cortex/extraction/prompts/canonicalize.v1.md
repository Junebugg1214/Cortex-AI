---
version: v1
schema_ref: cortex.extraction.retrieval.NodeHint
inputs:
  - chunk_text
  - existing_graph
  - retrieval_hints
outputs:
  - entity_resolution
test_fixture: tests/extraction/test_retrieval_augmented.py
---
## Existing known entities
Reuse these IDs when a new mention refers to the same entity. Do not invent new IDs for known entities.
Set entity_resolution to the matching node_id when an extracted item refers to one of these entities.
