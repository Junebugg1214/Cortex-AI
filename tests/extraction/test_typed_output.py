from __future__ import annotations

import json
from pathlib import Path

from cortex.extract_memory import AggressiveExtractor
from cortex.extract_memory_context import ExtractedClaim, ExtractedFact, ExtractedRelationship


def test_aggressive_extractor_emits_typed_output() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "sample_chat.json"
    messages = json.loads(fixture.read_text())

    extractor = AggressiveExtractor()
    extractor.process_messages_list(messages)

    items = [item for category in extractor.context.topics.values() for item in category.values()]
    facts = [item for item in items if isinstance(item, ExtractedFact)]
    claims = [item for item in items if isinstance(item, ExtractedClaim)]
    relationships = [item for item in items if isinstance(item, ExtractedRelationship)]

    assert facts
    assert claims
    assert relationships
    assert all(hasattr(item, "as_dict") for item in items)
