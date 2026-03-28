"""Precision regression tests for portability-critical extraction paths."""

import json
import zipfile

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


def test_identity_patterns_match_normal_sentence_case():
    categories = _extract_categories("I am Marc Saint-Jour. I use Python and FastAPI.")
    identity = [item["topic"] for item in categories["identity"]]
    assert "Marc Saint-Jour" in identity


def test_claude_code_jsonl_extracts_user_messages(tmp_path):
    session_path = tmp_path / "session.jsonl"
    session_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "sess-1",
                        "cwd": "/tmp/project",
                        "message": {"content": [{"text": "I use Python and FastAPI."}]},
                        "timestamp": "2025-01-01T00:00:00Z",
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "sessionId": "sess-1",
                        "cwd": "/tmp/project",
                        "message": {"content": [{"text": "ok"}]},
                        "timestamp": "2025-01-01T00:00:01Z",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    from cortex.extract_memory import load_file

    data, fmt = load_file(session_path)
    extractor = AggressiveExtractor()
    result = extractor.process_jsonl_messages(data)

    assert fmt == "claude_code"
    tech = {item["topic"] for item in result["categories"]["technical_expertise"]}
    assert {"Python", "Fastapi"} <= tech


def test_load_file_detects_gemini_zip_and_preserves_parser_path(tmp_path):
    zip_path = tmp_path / "gemini-export.zip"
    payload = {
        "conversations": [
            {
                "turns": [
                    {
                        "role": "user",
                        "text": "I use Gemini with Python and Next.js.",
                        "timestamp": "2025-01-01T00:00:00Z",
                    }
                ]
            }
        ]
    }
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("exports/gemini.json", json.dumps(payload))

    from cortex.extract_memory import load_file

    data, fmt = load_file(zip_path)
    extractor = AggressiveExtractor()
    result = extractor.process_gemini_export(data)

    assert fmt == "gemini"
    tech = {item["topic"] for item in result["categories"]["technical_expertise"]}
    assert {"Python", "Next.Js"} <= tech


def test_load_file_detects_claude_code_jsonl_inside_zip(tmp_path):
    zip_path = tmp_path / "claude-code-export.zip"
    session_lines = "\n".join(
        [
            json.dumps(
                {
                    "type": "user",
                    "sessionId": "sess-1",
                    "cwd": "/tmp/project",
                    "message": {"content": [{"text": "We use pytest and FastAPI."}]},
                    "timestamp": "2025-01-01T00:00:00Z",
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "sessionId": "sess-1",
                    "cwd": "/tmp/project",
                    "message": {"content": [{"text": "ok"}]},
                    "timestamp": "2025-01-01T00:00:01Z",
                }
            ),
        ]
    )
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("sessions/claude.jsonl", session_lines)

    from cortex.extract_memory import load_file

    data, fmt = load_file(zip_path)
    extractor = AggressiveExtractor()
    result = extractor.process_jsonl_messages(data)

    assert fmt == "claude_code"
    tech = {item["topic"] for item in result["categories"]["technical_expertise"]}
    assert {"Pytest", "Fastapi"} <= tech
