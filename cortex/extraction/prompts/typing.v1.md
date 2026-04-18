---
version: v1
schema_ref: cortex.extraction.model_backend.typed_extraction_input_schema
inputs:
  - source_text
  - current_item
outputs:
  - ExtractedFact
  - ExtractedClaim
test_fixture: tests/extraction/test_pipeline_stages.py
---
Re-evaluate this low-confidence Cortex extraction item as a fact or claim only.
Return one corrected typed item preserving the source meaning.

Source text:
{source_text}

Current item:
{current_item}
