"""Tests for cortex.hooks — auto-inject context into Claude Code sessions."""

import json
from pathlib import Path

from cortex.graph import CortexGraph, Node, make_node_id
from cortex.hooks import (
    HookConfig,
    _format_compact_markdown,
    _load_graph,
    generate_compact_context,
    handle_session_start,
    hook_status,
    install_hook,
    load_hook_config,
    save_hook_config,
    uninstall_hook,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_v4_context(categories: dict) -> dict:
    """Build a minimal v4-format context dict."""
    return {
        "schema_version": "4.0",
        "meta": {"method": "test"},
        "categories": categories,
    }


def _make_sample_v4():
    """A sample v4 context with tech, projects, preferences."""
    return _make_v4_context(
        {
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
                {
                    "topic": "Git",
                    "brief": "Uses Git",
                    "confidence": 0.85,
                    "mention_count": 50,
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
                    "topic": "my-project",
                    "brief": "Active project: my-project — Build cool stuff",
                    "confidence": 0.9,
                    "mention_count": 1,
                    "extraction_method": "behavioral",
                    "metrics": [],
                    "relationships": [],
                    "timeline": ["current"],
                    "source_quotes": [],
                    "first_seen": "",
                    "last_seen": "",
                    "full_description": "Working directory: /home/user/my-project",
                },
            ],
            "domain_knowledge": [
                {
                    "topic": "AI/ML",
                    "brief": "Knowledge of AI/ML",
                    "confidence": 0.7,
                    "mention_count": 5,
                    "extraction_method": "declarative",
                    "metrics": [],
                    "relationships": [],
                    "timeline": ["current"],
                    "source_quotes": [],
                    "first_seen": "",
                    "last_seen": "",
                },
            ],
            "user_preferences": [
                {
                    "topic": "Plans before coding",
                    "brief": "Uses plan mode before implementation",
                    "confidence": 0.7,
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
        }
    )


def _write_graph_file(tmp_path: Path, data: dict) -> Path:
    """Write a context dict to a JSON file and return the path."""
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# TestHookConfig
# ---------------------------------------------------------------------------


class TestHookConfig:
    def test_defaults(self):
        config = HookConfig()
        assert config.graph_path == ""
        assert config.policy == "technical"
        assert config.max_chars == 1500
        assert config.include_project is True

    def test_load_missing_file(self, tmp_path):
        config = load_hook_config(tmp_path / "nonexistent.json")
        assert config.graph_path == ""
        assert config.policy == "technical"

    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "config.json"
        original = HookConfig(
            graph_path="/path/to/graph.json",
            policy="professional",
            max_chars=1000,
        )
        save_hook_config(original, path)
        loaded = load_hook_config(path)
        assert loaded.graph_path == "/path/to/graph.json"
        assert loaded.policy == "professional"
        assert loaded.max_chars == 1000

    def test_load_invalid_json(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("not valid json")
        config = load_hook_config(path)
        assert config.graph_path == ""


# ---------------------------------------------------------------------------
# TestLoadGraph
# ---------------------------------------------------------------------------


class TestLoadGraph:
    def test_load_v4(self, tmp_path):
        data = _make_sample_v4()
        path = _write_graph_file(tmp_path, data)
        graph = _load_graph(str(path))
        assert graph is not None
        assert len(graph.nodes) > 0

    def test_load_v5(self, tmp_path):
        # Build a v5 graph
        g = CortexGraph(schema_version="5.0")
        g.add_node(Node(id="abc123", label="Python", tags=["technical_expertise"], confidence=0.9, brief="Uses Python"))
        data = g.export_v5()
        path = _write_graph_file(tmp_path, data)
        graph = _load_graph(str(path))
        assert graph is not None
        assert "abc123" in graph.nodes

    def test_load_v6(self, tmp_path):
        g = CortexGraph(schema_version="6.0")
        g.add_node(Node(id="def456", label="Rust", tags=["technical_expertise"], confidence=0.8, brief="Uses Rust"))
        data = g.export_v5()  # export_v5 sets schema 6.0
        path = _write_graph_file(tmp_path, data)
        graph = _load_graph(str(path))
        assert graph is not None
        assert "def456" in graph.nodes

    def test_load_missing_file(self):
        assert _load_graph("/nonexistent/path.json") is None

    def test_load_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json")
        assert _load_graph(str(path)) is None


# ---------------------------------------------------------------------------
# TestFormatCompactMarkdown
# ---------------------------------------------------------------------------


class TestFormatCompactMarkdown:
    def _make_graph_with_nodes(self, nodes_spec):
        """Helper: nodes_spec is list of (label, tags, confidence, brief)."""
        g = CortexGraph()
        for label, tags, conf, brief in nodes_spec:
            nid = make_node_id(label)
            g.add_node(Node(id=nid, label=label, tags=tags, confidence=conf, brief=brief))
        return g

    def test_tech_section(self):
        g = self._make_graph_with_nodes(
            [
                ("Python", ["technical_expertise"], 0.9, "Uses Python"),
                ("Git", ["technical_expertise"], 0.85, "Uses Git"),
            ]
        )
        result = _format_compact_markdown(g, 1500)
        assert "## Your Cortex Context" in result
        assert "**Tech Stack:**" in result
        assert "Python (0.9)" in result
        assert "Git (0.8)" in result

    def test_projects_section(self):
        g = self._make_graph_with_nodes(
            [
                ("my-app", ["active_priorities"], 0.9, "Active project: my-app — Build cool stuff"),
            ]
        )
        result = _format_compact_markdown(g, 1500)
        assert "**Projects:**" in result
        assert "my-app" in result
        assert "Build cool stuff" in result

    def test_projects_strips_prefix(self):
        g = self._make_graph_with_nodes(
            [
                ("my-app", ["active_priorities"], 0.9, "Active project: my-app — Build cool stuff"),
            ]
        )
        result = _format_compact_markdown(g, 1500)
        # Should strip "Active project: " prefix
        assert "Active project:" not in result

    def test_empty_sections_omitted(self):
        g = self._make_graph_with_nodes(
            [
                ("Python", ["technical_expertise"], 0.9, "Uses Python"),
            ]
        )
        result = _format_compact_markdown(g, 1500)
        assert "**Projects:**" not in result
        assert "**Preferences:**" not in result
        assert "**Relationships:**" not in result

    def test_max_chars_truncation(self):
        g = self._make_graph_with_nodes(
            [(f"Tech{i}", ["technical_expertise"], 0.9, f"Uses Tech{i}") for i in range(50)]
        )
        result = _format_compact_markdown(g, 200)
        assert len(result) <= 200
        assert result.endswith("...")

    def test_multiple_sections(self):
        g = self._make_graph_with_nodes(
            [
                ("Python", ["technical_expertise"], 0.9, "Uses Python"),
                ("my-app", ["active_priorities"], 0.9, "Active project: my-app — Cool"),
                ("Plans first", ["user_preferences"], 0.7, "Plans before coding"),
            ]
        )
        result = _format_compact_markdown(g, 1500)
        assert "**Tech Stack:**" in result
        assert "**Projects:**" in result
        assert "**Preferences:**" in result

    def test_domain_section(self):
        g = self._make_graph_with_nodes(
            [
                ("AI/ML", ["domain_knowledge"], 0.7, "Knowledge of AI/ML"),
            ]
        )
        result = _format_compact_markdown(g, 1500)
        assert "**Domain:**" in result
        assert "AI/ML" in result

    def test_empty_graph(self):
        g = CortexGraph()
        result = _format_compact_markdown(g, 1500)
        assert result == "## Your Cortex Context"


# ---------------------------------------------------------------------------
# TestGenerateCompactContext
# ---------------------------------------------------------------------------


class TestGenerateCompactContext:
    def test_basic_generation(self, tmp_path):
        data = _make_sample_v4()
        path = _write_graph_file(tmp_path, data)
        config = HookConfig(graph_path=str(path))
        result = generate_compact_context(config)
        assert "Python" in result
        assert len(result) > 0

    def test_empty_graph(self, tmp_path):
        data = _make_v4_context({})
        path = _write_graph_file(tmp_path, data)
        config = HookConfig(graph_path=str(path))
        result = generate_compact_context(config)
        assert result == ""

    def test_bootstrap_empty_array_graph(self, tmp_path):
        path = tmp_path / "context.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "5.0",
                    "graph": {"nodes": [], "edges": []},
                    "meta": {},
                }
            ),
            encoding="utf-8",
        )
        config = HookConfig(graph_path=str(path))
        result = generate_compact_context(config)
        assert result == ""

    def test_missing_graph(self):
        config = HookConfig(graph_path="/nonexistent/graph.json")
        result = generate_compact_context(config)
        assert result == ""

    def test_no_graph_path(self):
        config = HookConfig(graph_path="")
        result = generate_compact_context(config)
        assert result == ""

    def test_policy_filtering(self, tmp_path):
        data = _make_sample_v4()
        path = _write_graph_file(tmp_path, data)
        # "minimal" policy only includes identity + communication_preferences
        config = HookConfig(graph_path=str(path), policy="minimal")
        result = generate_compact_context(config)
        # Technical nodes should be filtered out by minimal policy
        assert "Python" not in result

    def test_max_chars_respected(self, tmp_path):
        data = _make_sample_v4()
        path = _write_graph_file(tmp_path, data)
        config = HookConfig(graph_path=str(path), max_chars=50)
        result = generate_compact_context(config)
        assert len(result) <= 50

    def test_invalid_policy_falls_back(self, tmp_path):
        data = _make_sample_v4()
        path = _write_graph_file(tmp_path, data)
        config = HookConfig(graph_path=str(path), policy="nonexistent_policy")
        result = generate_compact_context(config)
        # Falls back to "technical" policy
        assert "Python" in result


# ---------------------------------------------------------------------------
# TestHandleSessionStart
# ---------------------------------------------------------------------------


class TestHandleSessionStart:
    def test_returns_hook_output(self, tmp_path):
        data = _make_sample_v4()
        path = _write_graph_file(tmp_path, data)
        config = HookConfig(graph_path=str(path))
        result = handle_session_start({"session_id": "test123", "cwd": "/tmp"}, config)

        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "additionalContext" in result["hookSpecificOutput"]

    def test_context_included(self, tmp_path):
        data = _make_sample_v4()
        path = _write_graph_file(tmp_path, data)
        config = HookConfig(graph_path=str(path))
        result = handle_session_start({"session_id": "x"}, config)
        context = result["hookSpecificOutput"]["additionalContext"]
        assert "Python" in context

    def test_empty_input(self, tmp_path):
        data = _make_sample_v4()
        path = _write_graph_file(tmp_path, data)
        config = HookConfig(graph_path=str(path))
        result = handle_session_start({}, config)
        assert "hookSpecificOutput" in result

    def test_no_graph_returns_empty_context(self):
        config = HookConfig(graph_path="")
        result = handle_session_start({"session_id": "x"}, config)
        assert result["hookSpecificOutput"]["additionalContext"] == ""


# ---------------------------------------------------------------------------
# TestInstallUninstall
# ---------------------------------------------------------------------------


class TestInstallUninstall:
    def test_install_creates_config_and_settings(self, tmp_path):
        graph_path = _write_graph_file(tmp_path, _make_sample_v4())
        config_path = tmp_path / "config.json"
        settings_path = tmp_path / "settings.json"

        cfg, sett = install_hook(
            graph_path=str(graph_path),
            policy="professional",
            max_chars=1000,
            config_path=config_path,
            settings_path=settings_path,
        )

        assert config_path.exists()
        assert settings_path.exists()

        # Check config
        config = json.loads(config_path.read_text())
        assert config["policy"] == "professional"
        assert config["max_chars"] == 1000

        # Check settings has hook entry
        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings
        assert "SessionStart" in settings["hooks"]
        assert len(settings["hooks"]["SessionStart"]) == 1

    def test_install_idempotent(self, tmp_path):
        graph_path = _write_graph_file(tmp_path, _make_sample_v4())
        config_path = tmp_path / "config.json"
        settings_path = tmp_path / "settings.json"

        # Install twice
        install_hook(str(graph_path), config_path=config_path, settings_path=settings_path)
        install_hook(str(graph_path), config_path=config_path, settings_path=settings_path)

        settings = json.loads(settings_path.read_text())
        # Should only have one hook entry, not two
        assert len(settings["hooks"]["SessionStart"]) == 1

    def test_install_preserves_existing_settings(self, tmp_path):
        graph_path = _write_graph_file(tmp_path, _make_sample_v4())
        settings_path = tmp_path / "settings.json"
        # Pre-existing settings
        settings_path.write_text(json.dumps({"theme": "dark"}))

        install_hook(str(graph_path), config_path=tmp_path / "config.json", settings_path=settings_path)

        settings = json.loads(settings_path.read_text())
        assert settings["theme"] == "dark"
        assert "hooks" in settings

    def test_uninstall_removes_hook(self, tmp_path):
        graph_path = _write_graph_file(tmp_path, _make_sample_v4())
        config_path = tmp_path / "config.json"
        settings_path = tmp_path / "settings.json"

        install_hook(str(graph_path), config_path=config_path, settings_path=settings_path)
        removed = uninstall_hook(config_path=config_path, settings_path=settings_path)

        assert removed is True
        assert not config_path.exists()

        settings = json.loads(settings_path.read_text())
        # hooks should be cleaned up
        assert "hooks" not in settings or "SessionStart" not in settings.get("hooks", {})

    def test_uninstall_nothing_to_remove(self, tmp_path):
        removed = uninstall_hook(
            config_path=tmp_path / "no.json",
            settings_path=tmp_path / "no_settings.json",
        )
        assert removed is False


# ---------------------------------------------------------------------------
# TestHookStatus
# ---------------------------------------------------------------------------


class TestHookStatus:
    def test_not_installed(self, tmp_path):
        status = hook_status(
            config_path=tmp_path / "config.json",
            settings_path=tmp_path / "settings.json",
        )
        assert status["installed"] is False
        assert status["config"]["graph_path"] == ""

    def test_installed(self, tmp_path):
        graph_path = _write_graph_file(tmp_path, _make_sample_v4())
        config_path = tmp_path / "config.json"
        settings_path = tmp_path / "settings.json"

        install_hook(str(graph_path), config_path=config_path, settings_path=settings_path)

        status = hook_status(config_path=config_path, settings_path=settings_path)
        assert status["installed"] is True
        assert "graph.json" in status["config"]["graph_path"]
