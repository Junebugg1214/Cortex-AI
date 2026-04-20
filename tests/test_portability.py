"""Tests for the one-command portability flow."""

from __future__ import annotations

import json
from pathlib import Path

from cortex.cli import main
from cortex.graph.graph import CortexGraph, Node
from cortex.import_memory import NormalizedContext
from cortex.portability.portability import (
    build_instruction_pack,
    export_chatgpt_artifacts,
    resolve_portable_targets,
)


def _make_graph_file(tmp_path: Path) -> Path:
    graph = CortexGraph()
    graph.add_node(
        Node(
            id="identity/marc",
            label="Marc Saint-Jour",
            tags=["identity"],
            confidence=0.95,
            brief="Marc Saint-Jour",
        )
    )
    graph.add_node(
        Node(
            id="project/cortex",
            label="Cortex-AI",
            tags=["active_priorities"],
            confidence=0.92,
            brief="Active project: Cortex-AI - portable AI context and memory infrastructure",
        )
    )
    graph.add_node(
        Node(
            id="tech/python",
            label="Python",
            tags=["technical_expertise"],
            confidence=0.9,
            brief="Python, FastAPI, and CLI tooling",
        )
    )
    graph.add_node(
        Node(
            id="pref/style",
            label="Direct communication",
            tags=["communication_preferences"],
            confidence=0.85,
            brief="Prefer concise, direct, technical answers",
        )
    )
    graph.add_node(
        Node(
            id="constraint/privacy",
            label="User-owned storage",
            tags=["constraints"],
            confidence=0.8,
            brief="Keep memory local and user-owned by default",
        )
    )

    path = tmp_path / "context.json"
    path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")
    return path


class TestPortabilityHelpers:
    def test_resolve_portable_targets_all(self):
        assert resolve_portable_targets(["all"]) == [
            "claude",
            "claude-code",
            "chatgpt",
            "codex",
            "copilot",
            "gemini",
            "grok",
            "hermes",
            "windsurf",
            "cursor",
        ]

    def test_build_instruction_pack(self, tmp_path):
        ctx = NormalizedContext.from_v5(json.loads(_make_graph_file(tmp_path).read_text(encoding="utf-8")))
        pack = build_instruction_pack(ctx)
        assert "Identity:" in pack.about
        assert "Current priorities:" in pack.about
        assert "Communication preferences:" in pack.respond
        assert "Constraints to respect:" in pack.respond
        assert pack.combined

    def test_export_chatgpt_artifacts(self, tmp_path):
        ctx = NormalizedContext.from_v5(json.loads(_make_graph_file(tmp_path).read_text(encoding="utf-8")))
        result = export_chatgpt_artifacts(ctx, tmp_path / "portable")
        assert result.target == "chatgpt"
        assert len(result.paths) == 2
        md_path, json_path = result.paths
        assert md_path.exists()
        assert json_path.exists()
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert "what_chatgpt_should_know_about_you" in payload
        assert "how_chatgpt_should_respond" in payload


class TestPortableCLI:
    def test_portable_installs_and_generates_artifacts(self, tmp_path, monkeypatch):
        home_dir = tmp_path / "home"
        project_dir = tmp_path / "project"
        out_dir = tmp_path / "portable"
        store_dir = tmp_path / ".cortex"
        monkeypatch.setenv("HOME", str(home_dir))

        graph_path = _make_graph_file(tmp_path)
        rc = main(
            [
                "portable",
                str(graph_path),
                "--to",
                "claude",
                "claude-code",
                "chatgpt",
                "codex",
                "gemini",
                "grok",
                "windsurf",
                "cursor",
                "-o",
                str(out_dir),
                "-d",
                str(project_dir),
                "--store-dir",
                str(store_dir),
            ]
        )

        assert rc == 0
        assert (out_dir / "context.json").exists()
        assert (home_dir / ".claude" / "CLAUDE.md").exists()
        assert (project_dir / "CLAUDE.md").exists()
        assert (project_dir / "AGENTS.md").exists()
        assert (project_dir / ".cursor" / "rules" / "cortex.mdc").exists()
        assert (project_dir / ".windsurfrules").exists()
        assert (project_dir / "GEMINI.md").exists()
        assert (out_dir / "claude" / "claude_preferences.txt").exists()
        assert (out_dir / "claude" / "claude_memories.json").exists()
        assert (out_dir / "chatgpt" / "custom_instructions.md").exists()
        assert (out_dir / "grok" / "context_prompt.md").exists()

        codex_instructions = (project_dir / "AGENTS.md").read_text(encoding="utf-8")
        assert "## Shared AI Context" in codex_instructions

    def test_portable_extracts_text_input_before_exporting(self, tmp_path, monkeypatch):
        home_dir = tmp_path / "home"
        store_dir = tmp_path / ".cortex"
        monkeypatch.setenv("HOME", str(home_dir))

        input_path = tmp_path / "notes.txt"
        input_path.write_text(
            (
                "I am Marc Saint-Jour.\n\n"
                "I am working on Cortex-AI.\n\n"
                "I use Python and FastAPI.\n\n"
                "I prefer direct technical answers.\n"
            ),
            encoding="utf-8",
        )
        out_dir = tmp_path / "portable"

        rc = main(["portable", str(input_path), "--to", "chatgpt", "-o", str(out_dir), "--store-dir", str(store_dir)])
        assert rc == 0
        assert (out_dir / "context.json").exists()
        assert (out_dir / "chatgpt" / "custom_instructions.json").exists()
