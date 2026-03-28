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


def test_load_file_detects_grok_export_and_uses_dedicated_parser(tmp_path):
    export_path = tmp_path / "grok-export.json"
    export_path.write_text(
        json.dumps(
            {
                "chats": [
                    {
                        "messages": [
                            {
                                "sender": "user",
                                "content": "I am Riley. I use Rust and React.",
                                "created_at": "2025-01-01T00:00:00Z",
                            }
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    from cortex.extract_memory import load_file

    data, fmt = load_file(export_path)
    extractor = AggressiveExtractor()
    result = extractor.process_grok_export(data)

    assert fmt == "grok"
    labels = {item["topic"] for item in result["categories"]["technical_expertise"]}
    assert {"Rust", "React"} <= labels
    assert "Riley" in {item["topic"] for item in result["categories"]["identity"]}


def test_load_file_detects_cursor_jsonl_and_uses_dedicated_parser(tmp_path):
    export_path = tmp_path / "cursor-session.jsonl"
    export_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "composerId": "cmp-1",
                        "type": "user",
                        "text": "I am Lee. We use TypeScript and Prisma.",
                        "createdAt": "2025-01-01T00:00:00Z",
                    }
                ),
                json.dumps({"composerId": "cmp-1", "type": "assistant", "text": "ok"}),
            ]
        ),
        encoding="utf-8",
    )

    from cortex.extract_memory import load_file

    data, fmt = load_file(export_path)
    extractor = AggressiveExtractor()
    result = extractor.process_cursor_export(data)

    assert fmt == "cursor"
    labels = {item["topic"] for item in result["categories"]["technical_expertise"]}
    assert "Typescript" in labels
    assert "Prisma" in {item["topic"] for item in result["categories"]["mentions"]}
    assert "Lee" in {item["topic"] for item in result["categories"]["identity"]}


def test_load_file_detects_windsurf_export_and_uses_dedicated_parser(tmp_path):
    export_path = tmp_path / "windsurf-session.json"
    export_path.write_text(
        json.dumps(
            {
                "workspace": {"name": "demo"},
                "timeline": [
                    {
                        "role": "user",
                        "content": "I am Dana. We use Python and Postgres.",
                        "timestamp": "2025-01-01T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    from cortex.extract_memory import load_file

    data, fmt = load_file(export_path)
    extractor = AggressiveExtractor()
    result = extractor.process_windsurf_export(data)

    assert fmt == "windsurf"
    labels = {item["topic"] for item in result["categories"]["technical_expertise"]}
    assert {"Python", "Postgres"} <= labels
    assert "Dana" in {item["topic"] for item in result["categories"]["identity"]}


def test_load_file_detects_copilot_export_and_uses_dedicated_parser(tmp_path):
    export_path = tmp_path / "copilot-history.json"
    export_path.write_text(
        json.dumps(
            {
                "interactions": [
                    {
                        "request": {"message": "I am Avery. We use Python and Django."},
                        "createdAt": "2025-01-01T00:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    from cortex.extract_memory import load_file

    data, fmt = load_file(export_path)
    extractor = AggressiveExtractor()
    result = extractor.process_copilot_export(data)

    assert fmt == "copilot"
    labels = {item["topic"] for item in result["categories"]["technical_expertise"]}
    assert {"Python", "Django"} <= labels
    assert "Avery" in {item["topic"] for item in result["categories"]["identity"]}


def test_load_file_detects_vendor_specific_json_without_filename_hints(tmp_path):
    cases = [
        (
            "cursor",
            {
                "messages": [
                    {
                        "composerId": "cmp-1",
                        "type": "user",
                        "text": "I am Lee. We use TypeScript and Prisma.",
                    }
                ]
            },
        ),
        (
            "windsurf",
            {
                "messages": [
                    {
                        "cascadeId": "cas-1",
                        "role": "user",
                        "content": "I am Dana. We use Python and Postgres.",
                    }
                ]
            },
        ),
        (
            "copilot",
            {
                "messages": [
                    {
                        "copilotSessionId": "cp-1",
                        "request": {"message": "I am Avery. We use Python and Django."},
                    }
                ]
            },
        ),
        (
            "grok",
            {
                "messages": [
                    {
                        "conversationId": "g-1",
                        "sender": "user",
                        "content": "I am Riley. I use Rust and React.",
                    }
                ]
            },
        ),
    ]

    from cortex.extract_memory import load_file

    for expected_format, payload in cases:
        export_path = tmp_path / f"generic-{expected_format}.json"
        export_path.write_text(json.dumps(payload), encoding="utf-8")
        _, fmt = load_file(export_path)
        assert fmt == expected_format


def test_load_file_detects_vendor_specific_jsonl_without_filename_hints(tmp_path):
    cases = [
        (
            "cursor",
            {
                "composerId": "cmp-1",
                "type": "user",
                "text": "I use TypeScript and Prisma.",
            },
        ),
        (
            "windsurf",
            {
                "cascadeId": "cas-1",
                "role": "user",
                "content": "I use Python and Postgres.",
            },
        ),
        (
            "copilot",
            {
                "copilotSessionId": "cp-1",
                "request": {"message": "I use Python and Django."},
            },
        ),
        (
            "grok",
            {
                "conversationId": "g-1",
                "sender": "user",
                "content": "I use Rust and React.",
            },
        ),
    ]

    from cortex.extract_memory import load_file

    for expected_format, record in cases:
        export_path = tmp_path / f"generic-{expected_format}.jsonl"
        export_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        _, fmt = load_file(export_path)
        assert fmt == expected_format
