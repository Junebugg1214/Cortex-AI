"""Tests for cortex.context — Cross-Platform Context Writer."""

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

from cortex.portability.context import (  # noqa: E402
    CONTEXT_TARGET_ALIASES,
    CONTEXT_TARGETS,
    CORTEX_END,
    CORTEX_START,
    _format_cursor_mdc,
    _format_plain,
    _resolve_path,
    _write_non_destructive,
    resolve_context_targets,
    watch_and_refresh,
    write_context,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sample_graph_file(tmp_path: Path) -> Path:
    """Create a minimal v4 context JSON file for testing."""
    data = {
        "schema_version": "4.0",
        "meta": {"method": "test"},
        "categories": {
            "technical_expertise": [
                {
                    "topic": "Python",
                    "brief": "Uses Python",
                    "confidence": 0.9,
                    "mention_count": 100,
                    "extraction_method": "behavioral",
                    "metrics": [],
                    "relationships": [],
                    "timeline": ["current"],
                    "source_quotes": [],
                    "first_seen": "",
                    "last_seen": "",
                },
            ],
            "active_priorities": [
                {
                    "topic": "test-project",
                    "brief": "Active project: test-project — A test project",
                    "confidence": 0.9,
                    "mention_count": 1,
                    "extraction_method": "behavioral",
                    "metrics": [],
                    "relationships": [],
                    "timeline": ["current"],
                    "source_quotes": [],
                    "first_seen": "",
                    "last_seen": "",
                },
            ],
        },
    }
    graph_path = tmp_path / "test_graph.json"
    graph_path.write_text(json.dumps(data), encoding="utf-8")
    return graph_path


# ===========================================================================
# TestWriteNonDestructive
# ===========================================================================


class TestWriteNonDestructive:
    """Tests for _write_non_destructive()."""

    def test_create_new_file(self, tmp_path):
        """Creates a new file when it doesn't exist."""
        target = tmp_path / "new_file.md"
        content = f"{CORTEX_START}\nHello\n{CORTEX_END}\n"
        status = _write_non_destructive(target, content)
        assert status == "created"
        assert target.read_text() == content

    def test_update_existing_markers(self, tmp_path):
        """Replaces content between existing markers."""
        target = tmp_path / "existing.md"
        original = f"# My Rules\n\n{CORTEX_START}\nOld content\n{CORTEX_END}\n\n# More rules\n"
        target.write_text(original, encoding="utf-8")

        new_content = f"{CORTEX_START}\nNew content\n{CORTEX_END}\n"
        status = _write_non_destructive(target, new_content)
        assert status == "updated"

        result = target.read_text()
        assert "New content" in result
        assert "Old content" not in result
        assert "# My Rules" in result
        assert "# More rules" in result

    def test_append_to_existing_no_markers(self, tmp_path):
        """Appends marked section when file has no markers."""
        target = tmp_path / "existing.md"
        original = "# My Custom Rules\n\nSome user content.\n"
        target.write_text(original, encoding="utf-8")

        content = f"{CORTEX_START}\nCortex data\n{CORTEX_END}\n"
        status = _write_non_destructive(target, content)
        assert status == "updated"

        result = target.read_text()
        assert result.startswith("# My Custom Rules")
        assert "Some user content." in result
        assert CORTEX_START in result
        assert "Cortex data" in result

    def test_preserve_user_content(self, tmp_path):
        """Never overwrites content outside markers."""
        target = tmp_path / "rules.md"
        original = (
            "# User Rules\n\nImportant stuff.\n\n"
            f"{CORTEX_START}\nOld\n{CORTEX_END}\n\n"
            "# More User Rules\n\nAlso important.\n"
        )
        target.write_text(original, encoding="utf-8")

        new_content = f"{CORTEX_START}\nUpdated\n{CORTEX_END}\n"
        _write_non_destructive(target, new_content)

        result = target.read_text()
        assert "# User Rules" in result
        assert "Important stuff." in result
        assert "# More User Rules" in result
        assert "Also important." in result
        assert "Updated" in result
        assert "Old" not in result

    def test_dry_run(self, tmp_path):
        """Dry run returns status without writing."""
        target = tmp_path / "dryrun.md"
        status = _write_non_destructive(target, "content", dry_run=True)
        assert status == "dry-run"
        assert not target.exists()

    def test_create_parent_dirs(self, tmp_path):
        """Creates parent directories when they don't exist."""
        target = tmp_path / "deep" / "nested" / "file.md"
        content = f"{CORTEX_START}\nData\n{CORTEX_END}\n"
        status = _write_non_destructive(target, content)
        assert status == "created"
        assert target.exists()
        assert "Data" in target.read_text()

    def test_append_separator_no_trailing_newline(self, tmp_path):
        """Adds double newline separator when file has no trailing newline."""
        target = tmp_path / "no_newline.md"
        target.write_text("Content without newline", encoding="utf-8")

        content = f"{CORTEX_START}\nData\n{CORTEX_END}\n"
        _write_non_destructive(target, content)

        result = target.read_text()
        assert "Content without newline\n\n" in result

    def test_append_separator_single_trailing_newline(self, tmp_path):
        """Adds single newline when file ends with one newline."""
        target = tmp_path / "one_newline.md"
        target.write_text("Content\n", encoding="utf-8")

        content = f"{CORTEX_START}\nData\n{CORTEX_END}\n"
        _write_non_destructive(target, content)

        result = target.read_text()
        assert result.startswith("Content\n\n")

    def test_reject_multiple_marker_pairs(self, tmp_path):
        """Refuses ambiguous files with more than one Cortex block."""
        target = tmp_path / "ambiguous.md"
        original = f"{CORTEX_START}\nOld one\n{CORTEX_END}\n\nUser content\n\n{CORTEX_START}\nOld two\n{CORTEX_END}\n"
        target.write_text(original, encoding="utf-8")

        with pytest.raises(ValueError, match="Ambiguous Cortex marker layout"):
            _write_non_destructive(target, f"{CORTEX_START}\nNew\n{CORTEX_END}\n")

        assert target.read_text(encoding="utf-8") == original

    def test_reject_unbalanced_markers(self, tmp_path):
        """Refuses files with unmatched Cortex markers instead of appending blindly."""
        target = tmp_path / "broken.md"
        original = f"# Rules\n\n{CORTEX_START}\nUnclosed section\n"
        target.write_text(original, encoding="utf-8")

        with pytest.raises(ValueError, match="Ambiguous Cortex marker layout"):
            _write_non_destructive(target, f"{CORTEX_START}\nNew\n{CORTEX_END}\n")

        assert target.read_text(encoding="utf-8") == original

    def test_reject_binary_file(self, tmp_path):
        """Refuses to modify binary files instead of guessing."""
        target = tmp_path / "binary.md"
        target.write_bytes(b"\x00\x01\x02not-text")

        with pytest.raises(ValueError, match="binary file"):
            _write_non_destructive(target, f"{CORTEX_START}\nNew\n{CORTEX_END}\n")


# ===========================================================================
# TestPlatformFormatting
# ===========================================================================


class TestPlatformFormatting:
    """Tests for platform-specific formatters."""

    def test_format_plain(self):
        """Plain format wraps with section markers."""
        result = _format_plain("Hello World")
        assert result.startswith(CORTEX_START)
        assert result.endswith(f"{CORTEX_END}\n")
        assert "Hello World" in result

    def test_format_cursor_mdc(self):
        """Cursor .mdc format includes YAML frontmatter."""
        result = _format_cursor_mdc("Hello World")
        assert result.startswith("---\n")
        assert "alwaysApply: true" in result
        assert "description: Cortex shared AI context" in result
        assert CORTEX_START in result
        assert "Hello World" in result

    def test_all_targets_in_registry(self):
        """All expected platforms are in the registry."""
        expected = {"claude-code", "claude-code-project", "codex", "cursor", "copilot", "windsurf", "gemini-cli"}
        assert set(CONTEXT_TARGETS.keys()) == expected

    def test_alias_registry(self):
        assert CONTEXT_TARGET_ALIASES["gemini"] == "gemini-cli"

    def test_target_fields(self):
        """Each target has all required fields populated."""
        for name, target in CONTEXT_TARGETS.items():
            assert target.name == name
            assert target.file_path
            assert target.scope in ("global", "project")
            assert target.default_policy
            assert callable(target.format_fn)
            assert target.description

    def test_cursor_uses_mdc_formatter(self):
        """Cursor target uses the .mdc formatter."""
        assert CONTEXT_TARGETS["cursor"].format_fn is _format_cursor_mdc

    def test_non_cursor_use_plain_formatter(self):
        """Non-cursor targets use the plain formatter."""
        for name, target in CONTEXT_TARGETS.items():
            if name != "cursor":
                assert target.format_fn is _format_plain, f"{name} should use _format_plain"


# ===========================================================================
# TestResolvePath
# ===========================================================================


class TestResolvePath:
    """Tests for _resolve_path()."""

    def test_resolve_home(self):
        """Expands {home} to actual home directory."""
        result = _resolve_path("{home}/.claude/CLAUDE.md")
        assert str(Path.home()) in str(result)
        assert ".claude/CLAUDE.md" in str(result)

    def test_resolve_project(self):
        """Expands {project} to provided project directory."""
        result = _resolve_path("{project}/.cursor/rules/cortex.mdc", project_dir="/tmp/myproject")
        assert result == Path("/tmp/myproject/.cursor/rules/cortex.mdc").resolve()

    def test_resolve_project_default_cwd(self):
        """Uses cwd when no project_dir provided."""
        import os

        result = _resolve_path("{project}/GEMINI.md")
        assert str(result).startswith(os.getcwd())

    def test_reject_prefix_escape_path(self):
        """Rejects sibling paths that only share a string prefix with the project dir."""
        with pytest.raises(ValueError, match="outside allowed directories"):
            _resolve_path("{project}-evil/.cursor/rules/cortex.mdc", project_dir="/tmp/myproject")


# ===========================================================================
# TestWriteContext
# ===========================================================================


class TestWriteContext:
    """Tests for write_context() main function."""

    def test_resolve_context_targets_alias(self):
        assert resolve_context_targets(["gemini"]) == ["gemini-cli"]

    def test_single_platform(self, tmp_path):
        """Writes context to a single platform."""
        graph_path = _make_sample_graph_file(tmp_path)
        project_dir = str(tmp_path / "project")
        Path(project_dir).mkdir()

        results = write_context(
            graph_path=str(graph_path),
            platforms=["gemini-cli"],
            project_dir=project_dir,
        )

        assert len(results) == 1
        name, fpath, status = results[0]
        assert name == "gemini-cli"
        assert status in ("created", "updated")
        assert fpath.exists()
        content = fpath.read_text()
        assert CORTEX_START in content
        assert CORTEX_END in content

    def test_multiple_platforms(self, tmp_path):
        """Writes context to multiple platforms."""
        graph_path = _make_sample_graph_file(tmp_path)
        project_dir = str(tmp_path / "project")
        Path(project_dir).mkdir()

        results = write_context(
            graph_path=str(graph_path),
            platforms=["gemini-cli", "windsurf", "copilot"],
            project_dir=project_dir,
        )

        assert len(results) == 3
        for name, fpath, status in results:
            assert status in ("created", "updated")

    def test_all_shortcut(self, tmp_path):
        """'all' expands to all platforms."""
        graph_path = _make_sample_graph_file(tmp_path)
        project_dir = str(tmp_path / "project")
        Path(project_dir).mkdir()

        results = write_context(
            graph_path=str(graph_path),
            platforms=["all"],
            project_dir=project_dir,
        )

        assert len(results) == len(CONTEXT_TARGETS)

    def test_unknown_platform_skipped(self, tmp_path):
        """Unknown platform names are skipped."""
        graph_path = _make_sample_graph_file(tmp_path)
        results = write_context(
            graph_path=str(graph_path),
            platforms=["nonexistent-platform"],
        )
        assert len(results) == 1
        assert results[0][2] == "skipped"

    def test_dry_run(self, tmp_path):
        """Dry run doesn't create files."""
        graph_path = _make_sample_graph_file(tmp_path)
        project_dir = str(tmp_path / "project")
        Path(project_dir).mkdir()

        results = write_context(
            graph_path=str(graph_path),
            platforms=["gemini-cli"],
            project_dir=project_dir,
            dry_run=True,
        )

        assert len(results) == 1
        assert results[0][2] == "dry-run"
        gemini_path = Path(project_dir) / "GEMINI.md"
        assert not gemini_path.exists()

    def test_policy_override(self, tmp_path):
        """Policy override is passed through without errors."""
        graph_path = _make_sample_graph_file(tmp_path)
        project_dir = str(tmp_path / "project")
        Path(project_dir).mkdir()

        # All policies should run without error; some may skip if
        # the policy filters out all nodes (e.g. "minimal" on sparse data)
        for policy in ["full", "professional", "technical", "minimal"]:
            results = write_context(
                graph_path=str(graph_path),
                platforms=["gemini-cli"],
                project_dir=project_dir,
                policy=policy,
            )
            assert len(results) == 1
            assert results[0][2] in ("created", "updated", "skipped")

    def test_idempotent_writes(self, tmp_path):
        """Running write_context twice updates rather than duplicates."""
        graph_path = _make_sample_graph_file(tmp_path)
        project_dir = str(tmp_path / "project")
        Path(project_dir).mkdir()

        # First write
        write_context(
            graph_path=str(graph_path),
            platforms=["gemini-cli"],
            project_dir=project_dir,
        )

        gemini_path = Path(project_dir) / "GEMINI.md"
        first_content = gemini_path.read_text()

        # Second write
        results = write_context(
            graph_path=str(graph_path),
            platforms=["gemini-cli"],
            project_dir=project_dir,
        )

        second_content = gemini_path.read_text()
        assert results[0][2] == "updated"
        # Content should be the same (idempotent)
        assert second_content == first_content
        # Only one pair of markers
        assert second_content.count(CORTEX_START) == 1
        assert second_content.count(CORTEX_END) == 1

    def test_cursor_gets_mdc_format(self, tmp_path):
        """Cursor platform gets .mdc YAML frontmatter."""
        graph_path = _make_sample_graph_file(tmp_path)
        project_dir = str(tmp_path / "project")
        Path(project_dir).mkdir()

        write_context(
            graph_path=str(graph_path),
            platforms=["cursor"],
            project_dir=project_dir,
        )

        cursor_path = Path(project_dir) / ".cursor" / "rules" / "cortex.mdc"
        assert cursor_path.exists()
        content = cursor_path.read_text()
        assert content.startswith("---\n")
        assert "alwaysApply: true" in content

    def test_write_context_returns_error_for_malformed_existing_markers(self, tmp_path):
        """Malformed existing Cortex blocks fail closed instead of corrupting the file."""
        graph_path = _make_sample_graph_file(tmp_path)
        project_dir = Path(tmp_path / "project")
        project_dir.mkdir()
        gemini_path = project_dir / "GEMINI.md"
        original = f"# Existing rules\n\n{CORTEX_START}\nfirst\n{CORTEX_END}\n\n{CORTEX_START}\nsecond\n{CORTEX_END}\n"
        gemini_path.write_text(original, encoding="utf-8")

        results = write_context(
            graph_path=str(graph_path),
            platforms=["gemini-cli"],
            project_dir=str(project_dir),
        )

        assert results == [("gemini-cli", gemini_path.resolve(), "error")]
        assert gemini_path.read_text(encoding="utf-8") == original


# ===========================================================================
# TestWatchAndRefresh
# ===========================================================================


class TestWatchAndRefresh:
    """Tests for watch_and_refresh()."""

    def test_missing_graph_returns_immediately(self, tmp_path):
        """Returns immediately if graph file doesn't exist."""
        # Should not hang or raise
        watch_and_refresh(
            graph_path=str(tmp_path / "nonexistent.json"),
            platforms=["gemini-cli"],
        )

    def test_initial_write_happens(self, tmp_path):
        """Initial write happens before watching starts."""
        import threading

        graph_path = _make_sample_graph_file(tmp_path)
        project_dir = str(tmp_path / "project")
        Path(project_dir).mkdir()
        stop_event = threading.Event()

        # Run in thread and interrupt quickly
        def run():
            try:
                watch_and_refresh(
                    graph_path=str(graph_path),
                    platforms=["gemini-cli"],
                    project_dir=project_dir,
                    interval=60,  # Long interval so it doesn't loop
                    stop_event=stop_event,
                )
            except (KeyboardInterrupt, SystemExit):
                pass

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout=2)

        # Initial write should have created the file
        gemini_path = Path(project_dir) / "GEMINI.md"
        assert gemini_path.exists()
        assert CORTEX_START in gemini_path.read_text()
        stop_event.set()
        t.join(timeout=1)

    def test_watch_refresh_triggers_on_graph_change(self, tmp_path):
        """Graph mtime changes trigger a mounted context re-render."""
        import threading
        import time

        graph_path = _make_sample_graph_file(tmp_path)
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        gemini_path = project_dir / "GEMINI.md"
        interval = 0.25
        stop_event = threading.Event()
        errors = []

        def run():
            try:
                watch_and_refresh(
                    graph_path=str(graph_path),
                    platforms=["gemini-cli"],
                    project_dir=str(project_dir),
                    interval=interval,
                    stop_event=stop_event,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            startup_deadline = time.monotonic() + 2
            while time.monotonic() < startup_deadline and not gemini_path.exists():
                time.sleep(0.01)
            assert gemini_path.exists()
            assert "Rust" not in gemini_path.read_text(encoding="utf-8")

            data = json.loads(graph_path.read_text(encoding="utf-8"))
            data["categories"]["technical_expertise"].append(
                {
                    "topic": "Rust",
                    "brief": "Uses Rust",
                    "confidence": 0.8,
                    "mention_count": 2,
                    "extraction_method": "behavioral",
                    "metrics": [],
                    "relationships": [],
                    "timeline": ["current"],
                    "source_quotes": [],
                    "first_seen": "",
                    "last_seen": "",
                }
            )
            graph_path.write_text(json.dumps(data), encoding="utf-8")

            changed_at = time.monotonic()
            refresh_deadline = changed_at + (interval * 2)
            refreshed_at = None
            while time.monotonic() <= refresh_deadline:
                if "Rust" in gemini_path.read_text(encoding="utf-8"):
                    refreshed_at = time.monotonic()
                    break
                time.sleep(interval / 10)

            assert refreshed_at is not None
            assert refreshed_at - changed_at <= interval * 2
            assert errors == []
        finally:
            stop_event.set()
            thread.join(timeout=1)


# ===========================================================================
# TestMigrateSubcommand
# ===========================================================================


class TestMigrateSubcommand:
    """Tests for the context-write subcommand in migrate.py."""

    def test_context_write_help(self):
        """context-write --help doesn't error."""
        import subprocess

        result = subprocess.run(
            [sys.executable, str(_ROOT / "migrate.py"), "context-write", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "context-write" in result.stdout or "platforms" in result.stdout

    def test_context_write_missing_file(self):
        """context-write with missing file returns error."""
        import subprocess

        result = subprocess.run(
            [sys.executable, str(_ROOT / "migrate.py"), "context-write", "/nonexistent/graph.json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1

    def test_context_write_dry_run(self, tmp_path):
        """context-write --dry-run shows platforms without writing."""
        import subprocess

        graph_path = _make_sample_graph_file(tmp_path)
        result = subprocess.run(
            [
                sys.executable,
                str(_ROOT / "migrate.py"),
                "context-write",
                str(graph_path),
                "--platforms",
                "gemini-cli",
                "--dry-run",
                "--project",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "dry-run" in result.stdout
