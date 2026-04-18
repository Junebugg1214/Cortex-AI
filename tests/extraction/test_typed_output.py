from __future__ import annotations

import json
from pathlib import Path

from cortex.extract_memory_context import ExtractedClaim, ExtractedFact, ExtractedRelationship
from cortex.extraction import HeuristicBackend
from cortex.extraction.pipeline import Document, ExtractionContext


def test_heuristic_pipeline_emits_typed_output() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "sample_chat.json"
    messages = json.loads(fixture.read_text())
    content = "\n\n".join(message["content"] for message in messages if message.get("role") == "user")

    result = HeuristicBackend().run(
        Document(source_id="sample-chat", source_type="chat", content=content),
        ExtractionContext(),
    )

    items = result.items
    facts = [item for item in items if isinstance(item, ExtractedFact)]
    claims = [item for item in items if isinstance(item, ExtractedClaim)]
    relationships = [item for item in items if isinstance(item, ExtractedRelationship)]

    assert facts
    assert claims
    assert relationships
    assert all(hasattr(item, "as_dict") for item in items)
