"""
Tests for Cortex Phase 7: Coding Tool Extraction (v6.1)

Covers:
- Claude Code JSONL detection
- Session parsing (metadata, timestamps, tool usage, file paths, bash)
- Tech stack extraction (extensions, config files, frequency-confidence)
- Tool extraction (bash command patterns)
- Coding patterns (plan mode, test files, project path)
- Session-to-context conversion (v4 dict output)
- Multi-session aggregation
- Integration (coding -> graph roundtrip)
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cortex.coding import (
    BASH_TOOL_PATTERNS,
    CONFIG_FILE_PATTERNS,
    EXTENSION_MAP,
    CodingSession,
    ProjectMetadata,
    aggregate_sessions,
    enrich_project,
    enrich_session,
    is_claude_code_jsonl,
    load_claude_code_session,
    parse_claude_code_session,
    session_to_context,
    _detect_license,
    _extract_readme_summary,
    _frequency_confidence,
    _is_test_file,
    _parse_bash_command,
    _parse_readme_first_paragraph,
    _parse_ts,
    _toml_value,
    _track_file,
)


# ---------------------------------------------------------------------------
# Helpers — build synthetic Claude Code JSONL records
# ---------------------------------------------------------------------------

def _user_record(content, ts="2026-02-08T10:00:00.000Z", session_id="sess-1",
                 cwd="/home/user/myproject", branch="main", version="2.1.37"):
    return {
        "type": "user",
        "uuid": "u-1",
        "sessionId": session_id,
        "timestamp": ts,
        "cwd": cwd,
        "gitBranch": branch,
        "version": version,
        "message": {"role": "user", "content": content},
    }


def _assistant_record(tool_uses, ts="2026-02-08T10:01:00.000Z",
                      session_id="sess-1", model="claude-opus-4-6"):
    content = []
    for name, inp in tool_uses:
        content.append({
            "type": "tool_use",
            "id": f"toolu_{name}",
            "name": name,
            "input": inp,
        })
    return {
        "type": "assistant",
        "uuid": "a-1",
        "sessionId": session_id,
        "timestamp": ts,
        "cwd": "/home/user/myproject",
        "gitBranch": "main",
        "message": {
            "role": "assistant",
            "model": model,
            "content": content,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        },
    }


def _minimal_cc_records():
    """Minimal valid Claude Code session: 1 user + 1 assistant."""
    return [
        _user_record("Fix the bug in auth"),
        _assistant_record([
            ("Read", {"file_path": "/home/user/myproject/auth.py"}),
            ("Edit", {"file_path": "/home/user/myproject/auth.py",
                      "old_string": "x", "new_string": "y"}),
            ("Bash", {"command": "pytest tests/test_auth.py"}),
        ], ts="2026-02-08T10:05:00.000Z"),
    ]


# ============================================================================
# Claude Code Detection
# ============================================================================

class TestClaudeCodeDetection:

    def test_positive_detection(self):
        records = _minimal_cc_records()
        assert is_claude_code_jsonl(records) is True

    def test_negative_regular_jsonl(self):
        records = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        assert is_claude_code_jsonl(records) is False

    def test_empty_records(self):
        assert is_claude_code_jsonl([]) is False

    def test_single_record(self):
        assert is_claude_code_jsonl([_user_record("hi")]) is False


# ============================================================================
# Claude Code Parsing
# ============================================================================

class TestClaudeCodeParsing:

    def test_session_metadata(self):
        records = _minimal_cc_records()
        session = parse_claude_code_session(records)
        assert session.session_id == "sess-1"
        assert session.project_path == "/home/user/myproject"
        assert session.git_branch == "main"
        assert session.version == "2.1.37"
        assert session.tool == "claude_code"

    def test_timestamps(self):
        records = _minimal_cc_records()
        session = parse_claude_code_session(records)
        assert session.start_time == datetime(2026, 2, 8, 10, 0, 0, tzinfo=timezone.utc)
        assert session.end_time == datetime(2026, 2, 8, 10, 5, 0, tzinfo=timezone.utc)

    def test_user_prompts(self):
        records = _minimal_cc_records()
        session = parse_claude_code_session(records)
        assert session.user_prompts == ["Fix the bug in auth"]

    def test_tool_usage(self):
        records = _minimal_cc_records()
        session = parse_claude_code_session(records)
        assert session.tool_usage["Read"] == 1
        assert session.tool_usage["Edit"] == 1
        assert session.tool_usage["Bash"] == 1

    def test_file_paths(self):
        records = _minimal_cc_records()
        session = parse_claude_code_session(records)
        assert "/home/user/myproject/auth.py" in session.files_touched
        # Read + Edit = 2 touches
        assert session.files_touched["/home/user/myproject/auth.py"] == 2

    def test_bash_commands(self):
        records = _minimal_cc_records()
        session = parse_claude_code_session(records)
        assert "pytest tests/test_auth.py" in session.bash_commands

    def test_model_extracted(self):
        records = _minimal_cc_records()
        session = parse_claude_code_session(records)
        assert session.model == "claude-opus-4-6"

    def test_branches_tracked(self):
        records = [
            _user_record("work", branch="main"),
            _user_record("more work", branch="feature/auth",
                         ts="2026-02-08T11:00:00.000Z"),
        ]
        session = parse_claude_code_session(records)
        assert "main" in session.branches
        assert "feature/auth" in session.branches


# ============================================================================
# Tech Stack Extraction
# ============================================================================

class TestTechStackExtraction:

    def test_python_from_py_files(self):
        records = [
            _user_record("Fix it"),
            _assistant_record([
                ("Read", {"file_path": "/app/main.py"}),
                ("Edit", {"file_path": "/app/utils.py"}),
                ("Write", {"file_path": "/app/new_module.py"}),
            ]),
        ]
        session = parse_claude_code_session(records)
        assert session.technologies["Python"] >= 3

    def test_typescript_from_ts_files(self):
        records = [
            _user_record("Add component"),
            _assistant_record([
                ("Write", {"file_path": "/app/src/App.tsx"}),
                ("Edit", {"file_path": "/app/src/utils.ts"}),
            ]),
        ]
        session = parse_claude_code_session(records)
        assert session.technologies["TypeScript"] >= 2

    def test_multiple_languages(self):
        records = [
            _user_record("Setup"),
            _assistant_record([
                ("Write", {"file_path": "/app/main.py"}),
                ("Write", {"file_path": "/app/frontend/App.tsx"}),
                ("Write", {"file_path": "/app/deploy.sh"}),
            ]),
        ]
        session = parse_claude_code_session(records)
        assert "Python" in session.technologies
        assert "TypeScript" in session.technologies
        assert "Shell" in session.technologies

    def test_config_files_detected(self):
        records = [
            _user_record("Setup project"),
            _assistant_record([
                ("Read", {"file_path": "/app/package.json"}),
                ("Read", {"file_path": "/app/pyproject.toml"}),
            ]),
        ]
        session = parse_claude_code_session(records)
        assert "Node.js" in session.technologies
        assert "Python" in session.technologies
        assert "package.json" in session.config_files

    def test_frequency_confidence_scaling(self):
        assert _frequency_confidence(1) == 0.50
        assert _frequency_confidence(3) == 0.65
        assert _frequency_confidence(5) == 0.75
        assert _frequency_confidence(10) == 0.85
        assert _frequency_confidence(20) == 0.90


# ============================================================================
# Tool Extraction
# ============================================================================

class TestToolExtraction:

    def test_pytest_from_bash(self):
        records = [
            _user_record("Run tests"),
            _assistant_record([
                ("Bash", {"command": "pytest tests/ -v"}),
            ]),
        ]
        session = parse_claude_code_session(records)
        assert session.bash_tools["Pytest"] >= 1

    def test_git_from_bash(self):
        records = [
            _user_record("Commit"),
            _assistant_record([
                ("Bash", {"command": "git add . && git commit -m 'fix'"}),
            ]),
        ]
        session = parse_claude_code_session(records)
        assert session.bash_tools["Git"] >= 1

    def test_docker_from_bash(self):
        records = [
            _user_record("Build"),
            _assistant_record([
                ("Bash", {"command": "docker build -t myapp ."}),
            ]),
        ]
        session = parse_claude_code_session(records)
        assert session.bash_tools["Docker"] >= 1

    def test_tool_usage_counts(self):
        records = [
            _user_record("Work"),
            _assistant_record([
                ("Read", {"file_path": "/a.py"}),
                ("Read", {"file_path": "/b.py"}),
                ("Edit", {"file_path": "/a.py"}),
                ("Write", {"file_path": "/c.py"}),
                ("Bash", {"command": "pytest"}),
            ]),
        ]
        session = parse_claude_code_session(records)
        assert session.total_reads == 2
        assert session.total_edits == 1
        assert session.total_writes == 1


# ============================================================================
# Coding Patterns
# ============================================================================

class TestCodingPatterns:

    def test_plan_mode_detected(self):
        records = [
            _user_record("Plan this"),
            _assistant_record([
                ("EnterPlanMode", {}),
            ]),
            _assistant_record([
                ("ExitPlanMode", {}),
            ], ts="2026-02-08T10:10:00.000Z"),
        ]
        session = parse_claude_code_session(records)
        assert session.plan_mode_used is True

    def test_no_plan_mode(self):
        records = _minimal_cc_records()
        session = parse_claude_code_session(records)
        assert session.plan_mode_used is False

    def test_test_files_counted(self):
        records = [
            _user_record("Write tests"),
            _assistant_record([
                ("Write", {"file_path": "/app/tests/test_auth.py"}),
                ("Write", {"file_path": "/app/tests/test_api.py"}),
                ("Write", {"file_path": "/app/src/auth.py"}),
            ]),
        ]
        session = parse_claude_code_session(records)
        assert session.test_files_written == 2
        assert session.impl_files_written == 1

    def test_project_path_extracted(self):
        records = [
            _user_record("Go", cwd="/Users/marc/Desktop/chatbot-memory-skills"),
        ]
        session = parse_claude_code_session(records)
        assert session.project_path == "/Users/marc/Desktop/chatbot-memory-skills"


# ============================================================================
# Session to Context
# ============================================================================

class TestSessionToContext:

    def test_produces_valid_v4_dict(self):
        records = _minimal_cc_records()
        session = parse_claude_code_session(records)
        ctx = session_to_context(session)
        assert ctx["schema_version"] == "4.0"
        assert "meta" in ctx
        assert "categories" in ctx
        assert ctx["meta"]["method"] == "coding_session_extraction_v1"

    def test_technical_expertise_populated(self):
        records = [
            _user_record("Fix it"),
            _assistant_record([
                ("Read", {"file_path": "/app/main.py"}),
                ("Edit", {"file_path": "/app/utils.py"}),
                ("Write", {"file_path": "/app/lib.py"}),
            ]),
        ]
        session = parse_claude_code_session(records)
        ctx = session_to_context(session)
        tech_topics = [t["topic"] for t in ctx["categories"].get("technical_expertise", [])]
        assert "Python" in tech_topics

    def test_active_priorities_from_project(self):
        records = [_user_record("Go", cwd="/home/user/myproject")]
        session = parse_claude_code_session(records)
        ctx = session_to_context(session)
        priorities = ctx["categories"].get("active_priorities", [])
        assert len(priorities) == 1
        assert priorities[0]["topic"] == "myproject"

    def test_user_preferences_from_plan_mode(self):
        records = [
            _user_record("Plan"),
            _assistant_record([("EnterPlanMode", {})]),
        ]
        session = parse_claude_code_session(records)
        ctx = session_to_context(session)
        prefs = ctx["categories"].get("user_preferences", [])
        topics = [p["topic"] for p in prefs]
        assert "Plans before coding" in topics

    def test_behavioral_extraction_method(self):
        records = _minimal_cc_records()
        session = parse_claude_code_session(records)
        ctx = session_to_context(session)
        for cat_topics in ctx["categories"].values():
            for topic in cat_topics:
                assert topic["extraction_method"] == "behavioral"


# ============================================================================
# Multi-Session Aggregation
# ============================================================================

class TestMultiSessionAggregation:

    def test_aggregate_merges_counters(self):
        s1 = CodingSession(tool="claude_code")
        s1.technologies["Python"] = 5
        s1.technologies["Git"] = 2
        s2 = CodingSession(tool="claude_code")
        s2.technologies["Python"] = 3
        s2.technologies["Docker"] = 1

        agg = aggregate_sessions([s1, s2])
        assert agg.technologies["Python"] == 8
        assert agg.technologies["Git"] == 2
        assert agg.technologies["Docker"] == 1

    def test_aggregate_time_bounds(self):
        s1 = CodingSession(tool="claude_code")
        s1.start_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        s1.end_time = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        s2 = CodingSession(tool="claude_code")
        s2.start_time = datetime(2026, 1, 2, tzinfo=timezone.utc)
        s2.end_time = datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)

        agg = aggregate_sessions([s1, s2])
        assert agg.start_time == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert agg.end_time == datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)

    def test_aggregate_plan_mode(self):
        s1 = CodingSession(plan_mode_used=False)
        s2 = CodingSession(plan_mode_used=True)
        agg = aggregate_sessions([s1, s2])
        assert agg.plan_mode_used is True


# ============================================================================
# Helper Functions
# ============================================================================

class TestHelpers:

    def test_is_test_file_positive(self):
        assert _is_test_file("/app/tests/test_auth.py") is True
        assert _is_test_file("/app/auth_test.py") is True
        assert _is_test_file("/app/src/App.test.ts") is True
        assert _is_test_file("/app/src/App.spec.js") is True
        assert _is_test_file("/app/__tests__/foo.js") is True

    def test_is_test_file_negative(self):
        assert _is_test_file("/app/src/auth.py") is False
        assert _is_test_file("/app/main.ts") is False

    def test_parse_ts_valid(self):
        dt = _parse_ts("2026-02-08T10:30:00.000Z")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 2
        assert dt.hour == 10

    def test_parse_ts_none(self):
        assert _parse_ts(None) is None
        assert _parse_ts("") is None

    def test_parse_ts_no_millis(self):
        dt = _parse_ts("2026-02-08T10:30:00Z")
        assert dt is not None


# ============================================================================
# Integration
# ============================================================================

class TestIntegration:

    def test_coding_to_graph_roundtrip(self):
        """CodingSession -> v4 dict -> CortexGraph has nodes."""
        from cortex.compat import upgrade_v4_to_v5

        records = [
            _user_record("Build the auth system"),
            _assistant_record([
                ("Write", {"file_path": "/app/auth.py"}),
                ("Write", {"file_path": "/app/tests/test_auth.py"}),
                ("Bash", {"command": "pytest tests/ -v"}),
                ("Bash", {"command": "git add . && git commit -m 'add auth'"}),
            ]),
        ]
        session = parse_claude_code_session(records)
        ctx = session_to_context(session)
        graph = upgrade_v4_to_v5(ctx)

        # Should have nodes for Python, Pytest, Git, project, etc.
        assert len(graph.nodes) > 0
        labels = [n.label for n in graph.nodes.values()]
        assert "Python" in labels

    def test_empty_session_produces_minimal_context(self):
        """An empty session should produce a valid but minimal context."""
        session = CodingSession(tool="claude_code")
        ctx = session_to_context(session)
        assert ctx["schema_version"] == "4.0"
        assert "categories" in ctx


# ============================================================================
# README Parsing
# ============================================================================

class TestReadmeParsing:

    def test_standard_readme(self):
        text = "# My Project\n\nThis is a tool for doing X.\nIt supports Y and Z.\n"
        result = _parse_readme_first_paragraph(text)
        assert "tool for doing X" in result
        assert "supports Y and Z" in result

    def test_skips_badges(self):
        text = (
            "# MyApp\n\n"
            "[![Build](https://img.shields.io/badge)]\n"
            "![Logo](logo.png)\n\n"
            "A real-time data processor.\n"
        )
        result = _parse_readme_first_paragraph(text)
        assert "real-time data processor" in result

    def test_empty_readme(self):
        assert _parse_readme_first_paragraph("") == ""

    def test_headings_only(self):
        text = "# Title\n\n## Section 1\n\n## Section 2\n"
        assert _parse_readme_first_paragraph(text) == ""

    def test_long_paragraph_truncated(self):
        text = "# Title\n\n" + "word " * 200 + "\n"
        result = _parse_readme_first_paragraph(text)
        assert len(result) <= 504  # 500 + "..."
        assert result.endswith("...")

    def test_skips_code_fences(self):
        text = "# Title\n\n```bash\npip install foo\n```\n\nActual description here.\n"
        result = _parse_readme_first_paragraph(text)
        assert "Actual description" in result


# ============================================================================
# Manifest Extraction
# ============================================================================

class TestManifestExtraction:

    def test_package_json(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({
            "name": "my-app",
            "description": "A web app for task management",
            "license": "MIT",
            "keywords": ["tasks", "productivity"],
        }))
        meta = enrich_project(str(tmp_path))
        assert meta.name == "my-app"
        assert meta.description == "A web app for task management"
        assert meta.license == "MIT"
        assert meta.keywords == ["tasks", "productivity"]
        assert meta.manifest_file == "package.json"
        assert "JavaScript" in meta.languages

    def test_package_json_with_typescript(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({
            "name": "ts-app",
            "description": "A TypeScript app",
            "devDependencies": {"typescript": "^5.0.0"},
        }))
        meta = enrich_project(str(tmp_path))
        assert "TypeScript" in meta.languages

    def test_pyproject_toml(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            '[project]\nname = "cortex"\n'
            'description = "Portable AI identity"\n'
            'license = "MIT"\n'
        )
        meta = enrich_project(str(tmp_path))
        assert meta.name == "cortex"
        assert meta.description == "Portable AI identity"
        assert meta.license == "MIT"
        assert meta.manifest_file == "pyproject.toml"
        assert "Python" in meta.languages

    def test_cargo_toml(self, tmp_path):
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text(
            '[package]\nname = "mylib"\n'
            'description = "A Rust library"\n'
            'license = "Apache-2.0"\n'
        )
        meta = enrich_project(str(tmp_path))
        assert meta.name == "mylib"
        assert meta.description == "A Rust library"
        assert meta.manifest_file == "Cargo.toml"
        assert "Rust" in meta.languages

    def test_setup_cfg(self, tmp_path):
        cfg = tmp_path / "setup.cfg"
        cfg.write_text(
            "[metadata]\nname = mypackage\n"
            "description = A Python package\n"
            "license = BSD-3-Clause\n"
        )
        meta = enrich_project(str(tmp_path))
        assert meta.name == "mypackage"
        assert meta.description == "A Python package"
        assert "Python" in meta.languages


# ============================================================================
# TOML Value Extraction
# ============================================================================

class TestTomlValue:

    def test_double_quoted(self):
        assert _toml_value('name = "hello"', "name") == "hello"

    def test_single_quoted(self):
        assert _toml_value("name = 'hello'", "name") == "hello"

    def test_missing_key(self):
        assert _toml_value('name = "hello"', "version") == ""

    def test_whitespace_around_equals(self):
        assert _toml_value('  name  =  "hello"  ', "name") == "hello"


# ============================================================================
# License Detection
# ============================================================================

class TestLicenseDetection:

    def test_mit_license(self, tmp_path):
        lic = tmp_path / "LICENSE"
        lic.write_text("MIT License\n\nCopyright (c) 2026\n")
        assert _detect_license(tmp_path) == "MIT"

    def test_apache_license(self, tmp_path):
        lic = tmp_path / "LICENSE"
        lic.write_text("Apache License Version 2.0\n\nTerms...\n")
        assert _detect_license(tmp_path) == "Apache-2.0"

    def test_no_license_file(self, tmp_path):
        assert _detect_license(tmp_path) == ""


# ============================================================================
# Enrich Project (Full Integration)
# ============================================================================

class TestEnrichProject:

    def test_full_project(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "# MyApp\n\n**Own your data.** A privacy-first tool.\n"
        )
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "myapp",
            "description": "A privacy-first tool",
            "license": "MIT",
        }))
        (tmp_path / "LICENSE").write_text("MIT License\n")
        meta = enrich_project(str(tmp_path))
        assert meta.enriched is True
        assert meta.name == "myapp"
        assert meta.description == "A privacy-first tool"
        assert "privacy-first" in meta.readme_summary
        assert meta.license == "MIT"

    def test_readme_only(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "# Tool\n\nA command-line tool for converting data formats.\n"
        )
        meta = enrich_project(str(tmp_path))
        assert meta.enriched is True
        assert "converting data formats" in meta.description

    def test_manifest_only(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "api-server",
            "description": "REST API server",
        }))
        meta = enrich_project(str(tmp_path))
        assert meta.enriched is True
        assert meta.description == "REST API server"
        assert meta.readme_summary == ""

    def test_nonexistent_directory(self):
        meta = enrich_project("/nonexistent/path/12345")
        assert meta.enriched is False
        assert meta.name == ""

    def test_ci_detection(self, tmp_path):
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        (tmp_path / ".github" / "workflows" / "ci.yml").write_text("on: push\n")
        meta = enrich_project(str(tmp_path))
        assert meta.has_ci is True

    def test_docker_detection(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
        meta = enrich_project(str(tmp_path))
        assert meta.has_docker is True

    def test_docker_compose_detection(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text("version: '3'\n")
        meta = enrich_project(str(tmp_path))
        assert meta.has_docker is True

    def test_empty_project(self, tmp_path):
        meta = enrich_project(str(tmp_path))
        assert meta.enriched is False
        assert meta.name == tmp_path.name


# ============================================================================
# Enriched Session to Context
# ============================================================================

class TestEnrichedSessionToContext:

    def test_enriched_active_priorities(self):
        session = CodingSession(tool="claude_code", project_path="/home/user/myapp")
        session.project_meta = ProjectMetadata(
            name="myapp",
            description="A privacy-first data tool",
            readme_summary="A privacy-first data tool for converting formats.",
            license="MIT",
            languages=["Python"],
            manifest_file="pyproject.toml",
            enriched=True,
        )
        ctx = session_to_context(session)
        priorities = ctx["categories"].get("active_priorities", [])
        assert len(priorities) == 1
        p = priorities[0]
        assert "privacy-first" in p["brief"]
        assert p["confidence"] == 0.90
        assert "MIT" in p["full_description"]
        assert "Python" in p["full_description"]

    def test_domain_knowledge_added(self):
        session = CodingSession(tool="claude_code", project_path="/home/user/myapp")
        session.project_meta = ProjectMetadata(
            name="myapp",
            description="A privacy-first data tool for converting formats",
            enriched=True,
        )
        ctx = session_to_context(session)
        dk = ctx["categories"].get("domain_knowledge", [])
        assert len(dk) == 1
        assert dk[0]["topic"] == "myapp purpose"
        assert "privacy-first" in dk[0]["brief"]

    def test_unenriched_backward_compat(self):
        """Without enrichment, behavior is identical to original."""
        records = [_user_record("Go", cwd="/home/user/myproject")]
        session = parse_claude_code_session(records)
        ctx = session_to_context(session)
        priorities = ctx["categories"].get("active_priorities", [])
        assert len(priorities) == 1
        assert priorities[0]["topic"] == "myproject"
        assert priorities[0]["confidence"] == 0.85
        assert "domain_knowledge" not in ctx["categories"]

    def test_short_description_no_domain_knowledge(self):
        """Description <= 20 chars should not add domain_knowledge."""
        session = CodingSession(tool="claude_code", project_path="/home/user/x")
        session.project_meta = ProjectMetadata(
            name="x", description="A tool", enriched=True,
        )
        ctx = session_to_context(session)
        assert "domain_knowledge" not in ctx["categories"]


# ============================================================================
# Aggregation with Project Metadata
# ============================================================================

class TestAggregationWithMeta:

    def test_keeps_enriched_metadata(self):
        s1 = CodingSession(tool="claude_code", project_path="/app")
        s1.project_meta = ProjectMetadata(enriched=False)
        s2 = CodingSession(tool="claude_code")
        s2.project_meta = ProjectMetadata(
            name="myapp", description="A great app", enriched=True,
        )
        agg = aggregate_sessions([s1, s2])
        assert agg.project_meta.enriched is True
        assert agg.project_meta.description == "A great app"

    def test_keeps_richer_metadata(self):
        s1 = CodingSession(tool="claude_code")
        s1.project_meta = ProjectMetadata(
            name="app", description="Short", enriched=True,
        )
        s2 = CodingSession(tool="claude_code")
        s2.project_meta = ProjectMetadata(
            name="app", description="A much longer and richer description", enriched=True,
        )
        agg = aggregate_sessions([s1, s2])
        assert agg.project_meta.description == "A much longer and richer description"


# ============================================================================
# Enrich Session Convenience Function
# ============================================================================

class TestEnrichSession:

    def test_enrich_session_modifies_in_place(self, tmp_path):
        (tmp_path / "README.md").write_text("# Hello\n\nA great project.\n")
        session = CodingSession(tool="claude_code", project_path=str(tmp_path))
        enrich_session(session)
        assert session.project_meta.enriched is True
        assert "great project" in session.project_meta.readme_summary

    def test_enrich_session_no_project_path(self):
        session = CodingSession(tool="claude_code")
        enrich_session(session)
        assert session.project_meta.enriched is False


# ============================================================================
# Runner
# ============================================================================

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
