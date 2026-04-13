from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex.cli import main
from cortex.extract_memory import AggressiveExtractor
from cortex.extract_memory_context import ExtractionContext
from cortex.minds import ingest_detected_sources_into_mind, init_mind


def _topic_payload(ctx: ExtractionContext, category: str, topic: str) -> dict:
    exported = ctx.export()
    for item in exported["categories"].get(category, []):
        if item["topic"] == topic:
            return item
    raise AssertionError(f"topic not found: {category} / {topic}")


def _seed_detected_chatgpt_artifact(home_dir: Path, *, know: str, respond: str = "Be concise.") -> Path:
    downloads_dir = home_dir / "Downloads" / "Exports" / "ChatGPT"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    artifact = downloads_dir / "custom_instructions.json"
    artifact.write_text(
        json.dumps(
            {
                "what_chatgpt_should_know_about_you": know,
                "how_chatgpt_should_respond": respond,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return artifact


@pytest.mark.parametrize(
    ("category", "topic"),
    [
        ("identity", "Jordan Lee"),
        ("technical_expertise", "Python"),
        ("business_context", "OpenAI"),
    ],
)
def test_known_entity_match_produces_high_confidence_without_flag(category, topic):
    ctx = ExtractionContext()
    ctx.add_topic(category, topic, extraction_method="explicit_statement")
    ctx.add_topic(category, topic, extraction_method="explicit_statement")

    payload = _topic_payload(ctx, category, topic)

    assert payload["_extraction_confidence"] >= 0.9
    assert payload["_entity_resolution"] == "canonical_match"
    assert "resolution_conflicts" not in ctx.export()


@pytest.mark.parametrize(
    ("existing", "incoming"),
    [
        ("OpenAI", "Open AI"),
        ("Project Atlas", "Atlas Project"),
        ("Acme Health", "Acme-Health"),
    ],
)
def test_fuzzy_name_match_produces_medium_confidence_and_flag(existing, incoming):
    ctx = ExtractionContext()
    ctx.add_topic("business_context", existing, extraction_method="explicit_statement")
    ctx.add_topic("business_context", incoming, extraction_method="mentioned")

    merged_topic = _topic_payload(ctx, "business_context", existing)
    conflicts = ctx.export()["resolution_conflicts"]

    assert 0.6 <= merged_topic["_extraction_confidence"] <= 0.7
    assert merged_topic["_entity_resolution"] == "fuzzy_match"
    assert "fuzzy_match" in merged_topic["_extraction_flags"]
    assert conflicts[0]["type"] == "fuzzy_entity_match"


@pytest.mark.parametrize("extraction_method", ["mentioned", "inferred", "mentioned", "inferred"])
def test_net_new_entity_with_no_corroboration_is_low_confidence(extraction_method):
    ctx = ExtractionContext()
    ctx.add_topic("relationships", "Acme Ventures", extraction_method=extraction_method, source_quote="Acme Ventures")

    payload = _topic_payload(ctx, "relationships", "Acme Ventures")
    conflicts = ctx.export()["resolution_conflicts"]

    assert payload["_extraction_confidence"] == 0.35
    assert payload["_entity_resolution"] == "net_new_uncorroborated"
    assert "requires_reviewer_approval" in payload["_extraction_flags"]
    assert conflicts[0]["type"] == "low_confidence_extraction"


@pytest.mark.parametrize(
    ("text", "entity"),
    [
        ("Working with Alice on launch readiness.", "Alice"),
        ("Meeting with Bob about the rollout.", "Bob"),
        ("Partnering with Charlie for the pilot.", "Charlie"),
        ("Collaborating with Dana on the migration.", "Dana"),
    ],
)
def test_ambiguous_relationship_direction_preserves_both_candidates(text, entity):
    extractor = AggressiveExtractor()
    extractor.extract_from_text(text)
    extractor.post_process()

    conflicts = extractor.context.export()["resolution_conflicts"]
    relationship_conflict = next(item for item in conflicts if item["type"] == "ambiguous_relationship_direction")

    assert relationship_conflict["topic"] == entity
    assert relationship_conflict["metadata"]["candidate_directions"] == [
        {"source": "self", "target": entity},
        {"source": entity, "target": "self"},
    ]


def test_resolution_conflicts_include_source_span():
    extractor = AggressiveExtractor()
    extractor.extract_from_text("Working with Alice on launch readiness.")
    extractor.post_process()

    conflict = extractor.context.export()["resolution_conflicts"][0]

    assert "Working with Alice" in conflict["source_span"]
    assert conflict["confidence"] == 0.45


@pytest.mark.parametrize(
    "know_text",
    [
        "Working with Alice on launch readiness.",
        "Meeting with Bob about the rollout.",
        "Acme Ventures is adjacent to our work.",
    ],
)
def test_net_new_or_ambiguous_extraction_blocks_auto_branch_creation(tmp_path, monkeypatch, know_text):
    store_dir = tmp_path / ".cortex"
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_detected_chatgpt_artifact(home_dir, know=know_text)
    init_mind(store_dir, "ops", owner="tester")

    payload = ingest_detected_sources_into_mind(
        store_dir,
        "ops",
        targets=["chatgpt"],
        project_dir=tmp_path,
    )

    assert payload["pending_review"] is True
    assert payload["auto_branch_blocked"] is True
    assert payload["resolution_conflicts"]


def test_review_pending_cli_can_show_resolution_conflicts(tmp_path, monkeypatch, capsys):
    store_dir = tmp_path / ".cortex"
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_detected_chatgpt_artifact(home_dir, know="Working with Alice on launch readiness.")
    init_mind(store_dir, "ops", owner="tester")
    ingest_detected_sources_into_mind(store_dir, "ops", targets=["chatgpt"], project_dir=tmp_path)

    rc = main(["review", "pending", "--mind", "ops", "--show-conflicts", "--store-dir", str(store_dir)])
    output = capsys.readouterr().out

    assert rc == 0
    assert "Pending review proposals" in output
    assert "ambiguous_relationship_direction" in output


def test_review_pending_cli_hides_resolution_conflicts_by_default(tmp_path, monkeypatch, capsys):
    store_dir = tmp_path / ".cortex"
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_detected_chatgpt_artifact(home_dir, know="Working with Alice on launch readiness.")
    init_mind(store_dir, "ops", owner="tester")
    ingest_detected_sources_into_mind(store_dir, "ops", targets=["chatgpt"], project_dir=tmp_path)

    rc = main(["review", "pending", "--mind", "ops", "--store-dir", str(store_dir)])
    output = capsys.readouterr().out

    assert rc == 0
    assert "ambiguous_relationship_direction" not in output


@pytest.mark.parametrize(
    ("category", "topic", "expected_resolution"),
    [
        ("identity", "Jordan Lee", "canonical_match"),
        ("business_context", "OpenAI", "canonical_match"),
        ("technical_expertise", "Python", "canonical_match"),
    ],
)
def test_exact_match_updates_existing_topic_metadata(category, topic, expected_resolution):
    ctx = ExtractionContext()
    ctx.add_topic(category, topic, extraction_method="explicit_statement")
    ctx.add_topic(category, topic, extraction_method="mentioned", source_quote=topic)

    payload = _topic_payload(ctx, category, topic)

    assert payload["_entity_resolution"] == expected_resolution
    assert payload["_extraction_confidence"] >= 0.9
