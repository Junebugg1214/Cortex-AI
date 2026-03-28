"""Precision regression tests for portability-critical extraction paths."""

from cortex.extract_memory import AggressiveExtractor, keyword_search


def _extract_categories(text: str) -> dict:
    extractor = AggressiveExtractor()
    extractor.extract_from_text(text)
    return extractor.context.export().get("categories", {})


def test_keyword_search_requires_real_boundaries():
    assert keyword_search("we trust the process", "rust") is None
    assert keyword_search("we use rust in production", "rust") is not None


def test_trust_does_not_extract_rust_or_fake_priority():
    categories = _extract_categories("I am building trust with the team.")
    assert "technical_expertise" not in categories
    assert "active_priorities" not in categories


def test_react_fan_is_tech_not_role():
    categories = _extract_categories("I am a fan of React.")
    assert "professional_context" not in categories
    assert [item["topic"] for item in categories["technical_expertise"]] == ["React"]


def test_legit_project_phrase_still_extracts_priority_and_stack():
    categories = _extract_categories("I am building a trust platform with React and Rust.")
    priorities = [item["topic"] for item in categories["active_priorities"]]
    tech = {item["topic"] for item in categories["technical_expertise"]}
    assert "Trust platform with React and Rust" in priorities
    assert {"React", "Rust"} <= tech


def test_role_guard_keeps_real_titles():
    categories = _extract_categories("I work as a staff engineer on the platform team.")
    roles = [item["topic"] for item in categories["professional_context"]]
    assert "Staff engineer" in roles


def test_source_quote_comes_from_real_keyword_match():
    categories = _extract_categories("Trust matters, but we use Rust for systems work.")
    rust = next(item for item in categories["technical_expertise"] if item["topic"] == "Rust")
    assert "Rust" in rust["source_quotes"][0]
    assert rust["brief"] == "languages: rust"
