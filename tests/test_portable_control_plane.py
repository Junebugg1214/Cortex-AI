from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

from cortex.cli import main
from cortex.config import load_selfhost_config
from cortex.context import CORTEX_END, CORTEX_START
from cortex.graph import CortexGraph, Node, make_node_id_with_tag
from cortex.hermes_integration import HERMES_CONFIG_END, HERMES_CONFIG_START
from cortex.minds import compose_mind, init_mind, set_default_mind


def _write_graph(path: Path, rows: list[tuple[str, str, str]]) -> None:
    graph = CortexGraph()
    for label, tag, brief in rows:
        graph.add_node(
            Node(
                id=make_node_id_with_tag(label, tag),
                label=label,
                tags=[tag],
                confidence=0.9,
                brief=brief,
            )
        )
    path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def _init_git_repo(project: Path) -> None:
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Cortex Test"], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "cortex@example.com"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:test/cortex-portable.git"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: bootstrap project with Vitest and Prisma"],
        cwd=project,
        check=True,
        capture_output=True,
    )


def test_remember_propagates_and_scan_audits(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    rc = main(
        [
            "remember",
            "We migrated from PostgreSQL to CockroachDB in January.",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert {item["target"] for item in payload["targets"]} == {
        "claude",
        "claude-code",
        "chatgpt",
        "codex",
        "cursor",
        "copilot",
        "grok",
        "hermes",
        "windsurf",
        "gemini",
    }
    assert (store_dir / "portable" / "artifacts" / "claude" / "claude_preferences.txt").exists()
    assert (store_dir / "portable" / "artifacts" / "claude" / "claude_memories.json").exists()
    assert (store_dir / "portable" / "artifacts" / "chatgpt" / "custom_instructions.json").exists()
    assert (store_dir / "portable" / "artifacts" / "grok" / "context_prompt.json").exists()
    assert (home_dir / ".claude" / "CLAUDE.md").exists()
    assert (project_dir / "CLAUDE.md").exists()
    assert (project_dir / "AGENTS.md").exists()
    assert (project_dir / ".cursor" / "rules" / "cortex.mdc").exists()
    assert (project_dir / ".github" / "copilot-instructions.md").exists()
    assert (project_dir / ".windsurfrules").exists()
    assert (project_dir / "GEMINI.md").exists()
    assert (home_dir / ".hermes" / "memories" / "USER.md").exists()
    assert (home_dir / ".hermes" / "memories" / "MEMORY.md").exists()
    assert (home_dir / ".hermes" / "config.yaml").exists()

    rc = main(
        [
            "scan",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    scan = json.loads(capsys.readouterr().out)
    tool_map = {tool["target"]: tool for tool in scan["tools"]}

    assert rc == 0
    assert scan["coverage"] > 0
    assert tool_map["claude-code"]["fact_count"] > 0
    assert tool_map["copilot"]["fact_count"] > 0
    assert tool_map["cursor"]["fact_count"] > 0
    assert tool_map["chatgpt"]["fact_count"] > 0
    assert tool_map["grok"]["fact_count"] > 0


def test_build_and_smart_sync_cover_github_manifest_and_git_history(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    (project_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "portable-app",
                "description": "A portability-first AI context test app",
                "dependencies": {
                    "next": "14.1.0",
                    "react": "18.2.0",
                    "prisma": "5.10.0",
                },
                "devDependencies": {
                    "vitest": "1.5.0",
                    "typescript": "5.4.0",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (project_dir / "README.md").write_text("# Portable App\n\nPortable AI context demo.\n", encoding="utf-8")
    _init_git_repo(project_dir)

    rc = main(
        [
            "build",
            "--from",
            "package.json",
            "--from",
            "git-history",
            "--from",
            "github",
            "--sync",
            "--smart",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--search-root",
            str(tmp_path),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    source_map = {item["source"]: item for item in payload["sources"]}
    assert source_map["github"]["repo_count"] == 1
    assert "Next.js" in source_map["package.json"]["frameworks"]
    assert payload["fact_count"] > 0
    target_map = {item["target"]: item for item in payload["targets"]}
    assert "technical_expertise" in target_map["claude-code"]["route_tags"]
    assert "communication_preferences" in target_map["cursor"]["route_tags"]

    rc = main(
        [
            "sync",
            "--smart",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    sync_payload = json.loads(capsys.readouterr().out)
    sync_targets = {item["target"] for item in sync_payload["targets"]}

    assert rc == 0
    assert "chatgpt" in sync_targets
    assert "copilot" in sync_targets
    assert "grok" in sync_targets


def test_default_mind_remember_routes_through_mind_and_updates_targets(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    init_mind(store_dir, "marc", kind="person", owner="marc")
    set_default_mind(store_dir, "marc")

    rc = main(
        [
            "remember",
            "I prefer concise, implementation-first responses.",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    composed = compose_mind(
        store_dir,
        "marc",
        target="chatgpt",
        project_dir=str(project_dir),
        smart=True,
    )

    assert rc == 0
    assert payload["mind"] == "marc"
    assert payload["compatibility_mode"] == "default_mind"
    assert payload["statement"] == "I prefer concise, implementation-first responses."
    assert payload["graph_ref"] == "refs/minds/marc/branches/main"
    assert {item["target"] for item in payload["targets"]} == {
        "claude",
        "claude-code",
        "chatgpt",
        "codex",
        "cursor",
        "copilot",
        "grok",
        "hermes",
        "windsurf",
        "gemini",
    }
    assert composed["base_graph_source"] in {"mind_branch_ref", "mind_branch"}
    assert "Concise" in json.dumps(composed)


def test_default_mind_smart_sync_uses_mind_graph(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    init_mind(store_dir, "marc", kind="person", owner="marc")
    set_default_mind(store_dir, "marc")
    main(
        [
            "mind",
            "remember",
            "marc",
            "I prefer concise, implementation-first responses.",
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    capsys.readouterr()

    rc = main(
        [
            "sync",
            "--smart",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["mind"] == "marc"
    assert payload["compatibility_mode"] == "default_mind"
    assert payload["graph_ref"] == "refs/minds/marc/branches/main"
    assert payload["fact_count"] > 0
    assert {item["target"] for item in payload["targets"]} >= {"chatgpt", "codex", "cursor", "hermes"}


def test_default_mind_portable_detected_adopts_into_mind(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    chatgpt_dir = home_dir / "Downloads" / "Exports" / "ChatGPT"
    chatgpt_dir.mkdir(parents=True)
    (chatgpt_dir / "custom_instructions.json").write_text(
        json.dumps(
            {
                "what_chatgpt_should_know_about_you": "I use Python and FastAPI.",
                "how_chatgpt_should_respond": "Be concise.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    init_mind(store_dir, "marc", kind="person", owner="marc")
    set_default_mind(store_dir, "marc")

    rc = main(
        [
            "portable",
            "--from-detected",
            "chatgpt",
            "--to",
            "all",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    composed = compose_mind(
        store_dir,
        "marc",
        target="chatgpt",
        project_dir=str(project_dir),
        smart=True,
    )

    assert rc == 0
    assert payload["mind"] == "marc"
    assert payload["compatibility_mode"] == "default_mind"
    assert payload["detected_source_count"] == 1
    assert payload["selected_sources"][0]["target"] == "chatgpt"
    assert payload["graph_ref"] == "refs/minds/marc/branches/main"
    assert composed["base_graph_source"] in {"mind_branch_ref", "mind_branch"}
    assert "Python" in composed["labels"]


def test_scan_sync_scan_core_loop(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    output_dir = tmp_path / "portable"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    graph_path = tmp_path / "context.json"
    _write_graph(
        graph_path,
        [
            ("Marc Saint-Jour", "identity", "Marc Saint-Jour"),
            ("Cortex-AI", "active_priorities", "Active project: Cortex-AI"),
            ("Python", "technical_expertise", "Uses Python"),
        ],
    )

    rc = main(
        [
            "portable",
            str(graph_path),
            "--to",
            "chatgpt",
            "-o",
            str(output_dir),
            "-d",
            str(project_dir),
            "--store-dir",
            str(store_dir),
        ]
    )
    capsys.readouterr()
    assert rc == 0

    rc = main(["scan", "--project", str(project_dir), "--store-dir", str(store_dir), "--format", "json"])
    before = json.loads(capsys.readouterr().out)
    assert rc == 0

    rc = main(["sync", "--smart", "--project", str(project_dir), "--store-dir", str(store_dir), "--format", "json"])
    sync_payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert {item["target"] for item in sync_payload["targets"]}.issuperset(
        {"claude-code", "codex", "cursor", "chatgpt"}
    )

    rc = main(["scan", "--project", str(project_dir), "--store-dir", str(store_dir), "--format", "json"])
    after = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert after["coverage"] >= before["coverage"]
    assert sum(1 for tool in after["tools"] if tool["configured"]) >= sum(
        1 for tool in before["tools"] if tool["configured"]
    )


def test_scan_auto_detects_local_platform_paths_and_mcp_configs(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    (project_dir / ".cursor" / "rules").mkdir(parents=True)
    (project_dir / ".cursor" / "rules" / "team.mdc").write_text(
        "**Tech stack:** Python, FastAPI\n",
        encoding="utf-8",
    )
    (project_dir / ".github").mkdir()
    (project_dir / ".github" / "copilot-instructions.md").write_text("Use Python.\n", encoding="utf-8")
    (project_dir / ".vscode").mkdir()
    (project_dir / ".vscode" / "mcp.json").write_text(
        json.dumps(
            {
                "servers": {
                    "cortex": {"command": "cortex-mcp", "args": ["--config", ".cortex/config.toml"]},
                    "github": {"type": "stdio", "command": "npx", "args": ["-y", "github-mcp"]},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (project_dir / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cortex": {"command": "cortex-mcp", "args": ["--config", ".cortex/config.toml"]},
                    "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (home_dir / ".cursor").mkdir()
    (home_dir / ".cursor" / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cortex": {"command": "cortex-mcp", "args": ["--config", str(store_dir / "config.toml")]},
                    "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (home_dir / ".codex").mkdir()
    (home_dir / ".codex" / "config.toml").write_text(
        '[mcp_servers.cortex]\ncommand = "cortex-mcp"\nargs = ["--config", ".cortex/config.toml"]\n'
        '[mcp_servers.github]\ncommand = "npx"\nargs = ["-y", "github-mcp"]\n',
        encoding="utf-8",
    )
    (home_dir / ".gemini").mkdir()
    (home_dir / ".gemini" / "settings.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cortex": {"command": "cortex-mcp", "args": ["--config", ".cortex/config.toml"]},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    rc = main(["scan", "--project", str(project_dir), "--store-dir", str(store_dir), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    tool_map = {tool["target"]: tool for tool in payload["tools"]}

    assert rc == 0
    assert tool_map["cursor"]["configured"] is True
    assert tool_map["cursor"]["fact_count"] > 0
    assert tool_map["cursor"]["mcp_server_count"] == 2
    assert tool_map["cursor"]["cortex_mcp_configured"] is True
    assert "mcp" in tool_map["cursor"]["detection_sources"]
    assert any(path.endswith(".cursor/mcp.json") for path in tool_map["cursor"]["mcp_paths"])

    assert tool_map["claude-code"]["configured"] is True
    assert tool_map["claude-code"]["mcp_server_count"] == 2
    assert tool_map["claude-code"]["cortex_mcp_configured"] is True
    assert "MCP:" in tool_map["claude-code"]["note"]

    assert tool_map["codex"]["configured"] is True
    assert tool_map["codex"]["mcp_server_count"] == 2
    assert any(path.endswith(".codex/config.toml") for path in tool_map["codex"]["mcp_paths"])

    assert tool_map["copilot"]["configured"] is True
    assert tool_map["copilot"]["mcp_server_count"] == 2
    assert tool_map["gemini"]["configured"] is True
    assert tool_map["gemini"]["cortex_mcp_configured"] is True
    assert {"cursor", "copilot"}.issubset(set(payload["adoptable_targets"]))
    assert "codex" in payload["metadata_only_targets"]


def test_extract_from_detected_requires_explicit_permission_and_skips_mcp_metadata_by_default(
    tmp_path, capsys, monkeypatch
):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    output_path = tmp_path / "detected_context.json"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    (project_dir / ".cursor" / "rules").mkdir(parents=True)
    (project_dir / ".cursor" / "rules" / "team.mdc").write_text(
        "\n".join(
            [
                CORTEX_START,
                "**Tech stack:** Python, FastAPI",
                "**Current priorities:** Cortex-AI",
                CORTEX_END,
                "",
            ]
        ),
        encoding="utf-8",
    )
    (home_dir / ".codex").mkdir()
    (home_dir / ".codex" / "config.toml").write_text(
        '[mcp_servers.cortex]\ncommand = "cortex-mcp"\nargs = ["--config", ".cortex/config.toml"]\n',
        encoding="utf-8",
    )

    rc = main(
        [
            "extract",
            "--from-detected",
            "cursor",
            "codex",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--output",
            str(output_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert {item["target"] for item in payload["selected_sources"]} == {"cursor"}
    assert any(item["target"] == "codex" and item["reason"] == "metadata_only" for item in payload["skipped_sources"])
    graph = json.loads(output_path.read_text(encoding="utf-8"))
    labels = {node["label"] for node in graph["graph"]["nodes"].values()}
    assert "Python" in labels
    assert "Fastapi" in labels


def test_extract_from_detected_can_include_mcp_config_metadata(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    output_path = tmp_path / "detected_context.json"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    (home_dir / ".codex").mkdir()
    (home_dir / ".codex" / "config.toml").write_text(
        '[mcp_servers.cortex]\ncommand = "cortex-mcp"\nargs = ["--config", ".cortex/config.toml"]\n'
        '[mcp_servers.github]\ncommand = "npx"\nargs = ["-y", "github-mcp"]\n',
        encoding="utf-8",
    )

    rc = main(
        [
            "extract",
            "--from-detected",
            "codex",
            "--include-config-metadata",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--output",
            str(output_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert any(item["target"] == "codex" and item["kind"] == "mcp_config" for item in payload["selected_sources"])
    graph = json.loads(output_path.read_text(encoding="utf-8"))
    assert graph["schema_version"] == "6.0"
    assert len(graph["graph"]["nodes"]) > 0


def test_portable_to_hermes_writes_memory_files_and_config(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    export_path = tmp_path / "chatgpt-export.txt"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    export_path.write_text(
        (
            "My name is Casey. "
            "I use Python, FastAPI, and Next.js. "
            "I prefer direct answers. "
            "We migrated from PostgreSQL to CockroachDB in January."
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "portable",
            str(export_path),
            "--to",
            "hermes",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    user_path = home_dir / ".hermes" / "memories" / "USER.md"
    memory_path = home_dir / ".hermes" / "memories" / "MEMORY.md"
    config_path = home_dir / ".hermes" / "config.yaml"

    assert rc == 0
    assert payload["target_count"] == 1
    assert payload["targets"][0]["target"] == "hermes"
    assert user_path.exists()
    assert memory_path.exists()
    assert config_path.exists()
    assert "cortex-mcp" in config_path.read_text(encoding="utf-8")
    assert "memory_enabled: true" in config_path.read_text(encoding="utf-8")
    assert CORTEX_START in user_path.read_text(encoding="utf-8")
    assert CORTEX_START in memory_path.read_text(encoding="utf-8")


def test_scan_detects_hermes_memory_files_and_yaml_mcp(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    hermes_dir = home_dir / ".hermes"
    memories_dir = hermes_dir / "memories"
    memories_dir.mkdir(parents=True)
    (memories_dir / "USER.md").write_text(
        "\n".join(
            [
                CORTEX_START,
                "## Identity",
                "- Casey",
                "## Communication Preferences",
                "- Direct answers",
                CORTEX_END,
                "",
            ]
        ),
        encoding="utf-8",
    )
    (memories_dir / "MEMORY.md").write_text(
        "\n".join(
            [
                CORTEX_START,
                "## Technical Context",
                "- Python",
                "- FastAPI",
                "## Active Priorities",
                "- Cortex-AI",
                CORTEX_END,
                "",
            ]
        ),
        encoding="utf-8",
    )
    (hermes_dir / "config.yaml").write_text(
        "\n".join(
            [
                "mcp_servers:",
                "  cortex:",
                '    command: "cortex-mcp"',
                "    args:",
                '      - "--config"',
                '      - "/tmp/cortex/config.toml"',
                "  github:",
                '    command: "npx"',
                "    args:",
                '      - "-y"',
                '      - "@modelcontextprotocol/server-github"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    rc = main(["scan", "--project", str(project_dir), "--store-dir", str(store_dir), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    tool_map = {tool["target"]: tool for tool in payload["tools"]}

    assert rc == 0
    assert tool_map["hermes"]["configured"] is True
    assert tool_map["hermes"]["fact_count"] > 0
    assert tool_map["hermes"]["mcp_server_count"] == 2
    assert tool_map["hermes"]["cortex_mcp_configured"] is True
    assert any(path.endswith(".hermes/config.yaml") for path in tool_map["hermes"]["mcp_paths"])
    assert "hermes" in payload["adoptable_targets"]


def test_extract_from_detected_can_adopt_hermes_memory_files(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    output_path = tmp_path / "detected_context.json"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    memories_dir = home_dir / ".hermes" / "memories"
    memories_dir.mkdir(parents=True)
    (memories_dir / "USER.md").write_text(
        "\n".join(
            [
                CORTEX_START,
                "## Identity",
                "- Casey",
                "## Communication Preferences",
                "- Direct answers",
                CORTEX_END,
                "",
            ]
        ),
        encoding="utf-8",
    )
    (memories_dir / "MEMORY.md").write_text(
        "\n".join(
            [
                CORTEX_START,
                "## Technical Context",
                "- Python",
                "- FastAPI",
                "## Active Priorities",
                "- Cortex-AI",
                CORTEX_END,
                "",
            ]
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "extract",
            "--from-detected",
            "hermes",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--output",
            str(output_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert {item["target"] for item in payload["selected_sources"]} == {"hermes"}
    graph = json.loads(output_path.read_text(encoding="utf-8"))
    labels = {node["label"] for node in graph["graph"]["nodes"].values()}
    assert "Python" in labels
    assert "FastAPI" in labels
    assert "Casey" in labels


def test_portable_to_hermes_preserves_unmanaged_text_and_config_indent(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    export_path = tmp_path / "chatgpt-export.txt"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    hermes_dir = home_dir / ".hermes"
    memories_dir = hermes_dir / "memories"
    memories_dir.mkdir(parents=True)
    user_path = memories_dir / "USER.md"
    memory_path = memories_dir / "MEMORY.md"
    config_path = hermes_dir / "config.yaml"

    user_path.write_text(
        "\n".join(
            [
                "User-owned intro",
                "",
                CORTEX_START,
                "## Identity",
                "- Old profile",
                CORTEX_END,
                "",
                "User-owned footer",
                "",
            ]
        ),
        encoding="utf-8",
    )
    memory_path.write_text(
        "\n".join(
            [
                "Hand-written durable note",
                "",
                CORTEX_START,
                "## Technical Context",
                "- Legacy stack",
                CORTEX_END,
                "",
            ]
        ),
        encoding="utf-8",
    )
    config_path.write_text(
        "\n".join(
            [
                "mcp_servers:",
                "    cortex:",
                '      command: "old-cortex"',
                "      args:",
                '        - "--config"',
                '        - "/tmp/old.toml"',
                "    github:",
                '      command: "npx"',
                "      args:",
                '        - "-y"',
                '        - "@modelcontextprotocol/server-github"',
                "",
                "memory:",
                "  memory_enabled: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    export_path.write_text(
        "My name is Casey. I use Python and FastAPI. I prefer direct answers.",
        encoding="utf-8",
    )

    rc = main(
        [
            "portable",
            str(export_path),
            "--to",
            "hermes",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    capsys.readouterr()
    assert rc == 0

    rc = main(
        [
            "sync",
            "--to",
            "hermes",
            "--smart",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    capsys.readouterr()
    assert rc == 0

    user_text = user_path.read_text(encoding="utf-8")
    memory_text = memory_path.read_text(encoding="utf-8")
    config_text = config_path.read_text(encoding="utf-8")

    assert "User-owned intro" in user_text
    assert "User-owned footer" in user_text
    assert "Hand-written durable note" in memory_text
    assert user_text.count(CORTEX_START) == 1
    assert user_text.count(CORTEX_END) == 1
    assert memory_text.count(CORTEX_START) == 1
    assert memory_text.count(CORTEX_END) == 1
    assert config_text.count(HERMES_CONFIG_START) == 1
    assert config_text.count(HERMES_CONFIG_END) == 1
    assert config_text.count("cortex-mcp") == 1
    assert "\n    cortex:\n" in config_text
    assert "\n    github:\n" in config_text


def test_portable_to_hermes_normalizes_flow_style_mcp_servers(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    export_path = tmp_path / "chatgpt-export.txt"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    hermes_dir = home_dir / ".hermes"
    hermes_dir.mkdir(parents=True)
    config_path = hermes_dir / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "mcp_servers: {}",
                "memory:",
                "  memory_enabled: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    export_path.write_text("My name is Casey. I use Python.", encoding="utf-8")

    rc = main(
        [
            "portable",
            str(export_path),
            "--to",
            "hermes",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    capsys.readouterr()

    config_text = config_path.read_text(encoding="utf-8")
    assert rc == 0
    assert config_text.count("mcp_servers:") == 1
    assert "mcp_servers: {}" not in config_text
    assert "cortex-mcp" in config_text
    assert "memory_enabled: true" in config_text


def test_scan_and_portable_from_detected_prefer_newest_nested_artifact(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    downloads_dir = home_dir / "Downloads"
    desktop_dir = home_dir / "Desktop"
    documents_dir = home_dir / "Documents"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    output_dir = tmp_path / "portable"
    home_dir.mkdir()
    downloads_dir.mkdir()
    desktop_dir.mkdir()
    documents_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    old_export = documents_dir / "chatgpt-export.zip"
    with zipfile.ZipFile(old_export, "w") as handle:
        handle.writestr(
            "conversations.json",
            json.dumps(
                [
                    {
                        "mapping": {
                            "msg-1": {
                                "message": {
                                    "author": {"role": "user"},
                                    "content": {"parts": ["I use Rust and Axum."]},
                                    "create_time": "2025-01-01T00:00:00Z",
                                }
                            }
                        }
                    }
                ]
            ),
        )
    old_time = 1_700_000_000
    os.utime(old_export, (old_time, old_time))

    nested_artifact_dir = downloads_dir / "Exports" / "ChatGPT"
    nested_artifact_dir.mkdir(parents=True)
    new_artifact = nested_artifact_dir / "custom_instructions.json"
    new_artifact.write_text(
        json.dumps(
            {
                "what_chatgpt_should_know_about_you": "I use Python and FastAPI.",
                "how_chatgpt_should_respond": "Be concise.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    new_time = old_time + 10_000
    os.utime(new_artifact, (new_time, new_time))

    rc = main(
        [
            "scan",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    scan_payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert "chatgpt" in scan_payload["adoptable_targets"]
    chatgpt_sources = [item for item in scan_payload["adoptable_sources"] if item["target"] == "chatgpt"]
    assert len(chatgpt_sources) == 1
    assert chatgpt_sources[0]["kind"] == "artifact"
    assert chatgpt_sources[0]["path"].endswith("custom_instructions.json")

    rc = main(
        [
            "portable",
            "--from-detected",
            "chatgpt",
            "--to",
            "codex",
            "cursor",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--output",
            str(output_dir),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["source"] == "detected"
    assert {item["target"] for item in payload["selected_sources"]} == {"chatgpt"}
    assert any(item["kind"] == "artifact" for item in payload["selected_sources"])
    assert payload["selected_sources"][0]["path"].endswith("custom_instructions.json")
    assert payload["target_count"] == 2
    assert (output_dir / "context.json").exists()
    graph = json.loads((output_dir / "context.json").read_text(encoding="utf-8"))
    labels = {node["label"] for node in graph["graph"]["nodes"].values()}
    assert "Python" in labels
    assert "Fastapi" in labels
    assert "Rust" not in labels
    assert (project_dir / "AGENTS.md").exists()
    assert (project_dir / ".cursor" / "rules" / "cortex.mdc").exists()


def test_extract_from_detected_skips_unreadable_export_and_keeps_valid_sources(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    downloads_dir = home_dir / "Downloads"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    output_path = tmp_path / "detected_context.json"
    home_dir.mkdir()
    downloads_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    (downloads_dir / "chatgpt-export.zip").write_bytes(b"not-a-real-zip")
    (project_dir / ".cursor" / "rules").mkdir(parents=True)
    (project_dir / ".cursor" / "rules" / "team.mdc").write_text(
        "\n".join(
            [
                CORTEX_START,
                "**Tech stack:** Python, FastAPI",
                "**Current priorities:** Cortex-AI",
                CORTEX_END,
                "",
            ]
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "extract",
            "--from-detected",
            "chatgpt",
            "cursor",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--output",
            str(output_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert {item["target"] for item in payload["selected_sources"]} == {"cursor"}
    assert any(item["target"] == "chatgpt" and item["reason"] == "unreadable" for item in payload["skipped_sources"])
    graph = json.loads(output_path.read_text(encoding="utf-8"))
    labels = {node["label"] for node in graph["graph"]["nodes"].values()}
    assert "Python" in labels
    assert "Fastapi" in labels


def test_extract_from_detected_redacts_local_sources_by_default(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    downloads_dir = home_dir / "Downloads"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    output_path = tmp_path / "detected_context.json"
    home_dir.mkdir()
    downloads_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    (downloads_dir / "custom_instructions.json").write_text(
        json.dumps(
            {
                "what_chatgpt_should_know_about_you": "Email me at john@example.com. I use Python and FastAPI.",
                "how_chatgpt_should_respond": "Be concise.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "extract",
            "--from-detected",
            "chatgpt",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--output",
            str(output_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert {item["target"] for item in payload["selected_sources"]} == {"chatgpt"}
    graph_text = output_path.read_text(encoding="utf-8")
    assert "john@example.com" not in graph_text
    assert "Python" in graph_text


def test_extract_from_detected_uses_managed_blocks_only_by_default(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    output_path = tmp_path / "detected_context.json"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    (project_dir / "AGENTS.md").write_text(
        "\n".join(
            [
                "This unmanaged guidance says to use MongoDB.",
                CORTEX_START,
                "**Tech stack:** Python, FastAPI",
                CORTEX_END,
                "",
            ]
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "extract",
            "--from-detected",
            "codex",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--output",
            str(output_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert {item["target"] for item in payload["selected_sources"]} == {"codex"}
    labels = {node["label"] for node in json.loads(output_path.read_text(encoding="utf-8"))["graph"]["nodes"].values()}
    assert "Python" in labels
    assert "Fastapi" in labels
    assert not any("mongo" in label.lower() for label in labels)


def test_extract_from_detected_can_opt_into_unmanaged_instruction_text(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    output_path = tmp_path / "detected_context.json"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    (project_dir / "AGENTS.md").write_text(
        "\n".join(
            [
                "This unmanaged guidance says to use MongoDB.",
                CORTEX_START,
                "**Tech stack:** Python, FastAPI",
                CORTEX_END,
                "",
            ]
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "extract",
            "--from-detected",
            "codex",
            "--include-unmanaged-text",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--output",
            str(output_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert {item["target"] for item in payload["selected_sources"]} == {"codex"}
    labels = {node["label"] for node in json.loads(output_path.read_text(encoding="utf-8"))["graph"]["nodes"].values()}
    assert "Python" in labels
    assert any("mongo" in label.lower() for label in labels)


def test_status_and_audit_detect_stale_and_divergence(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    output_dir = tmp_path / "portable"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    base_graph = tmp_path / "base.json"
    _write_graph(
        base_graph,
        [
            ("PostgreSQL", "technical_expertise", "Uses PostgreSQL"),
            ("Cortex-AI", "active_priorities", "Active project: Cortex-AI"),
        ],
    )
    migrated_graph = tmp_path / "migrated.json"
    _write_graph(
        migrated_graph,
        [
            ("CockroachDB", "technical_expertise", "Uses CockroachDB"),
            ("Cortex-AI", "active_priorities", "Active project: Cortex-AI"),
        ],
    )

    assert (
        main(
            [
                "portable",
                str(base_graph),
                "--to",
                "chatgpt",
                "cursor",
                "-o",
                str(output_dir),
                "-d",
                str(project_dir),
                "--store-dir",
                str(store_dir),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "portable",
                str(migrated_graph),
                "--to",
                "cursor",
                "-o",
                str(output_dir),
                "-d",
                str(project_dir),
                "--store-dir",
                str(store_dir),
            ]
        )
        == 0
    )
    capsys.readouterr()

    rc = main(["audit", "--project", str(project_dir), "--store-dir", str(store_dir), "--format", "json"])
    audit = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert any(
        issue["type"] == "missing_context" and issue["target"] == "chatgpt" and "CockroachDB" in issue["missing_labels"]
        for issue in audit["issues"]
    )

    (project_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "portable-app",
                "description": "A portability-first AI context test app",
                "dependencies": {"next": "14.1.0", "react": "18.2.0"},
                "devDependencies": {"vitest": "1.5.0"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "build",
            "--from",
            "package.json",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    assert rc == 0
    capsys.readouterr()

    rc = main(["status", "--project", str(project_dir), "--store-dir", str(store_dir), "--format", "json"])
    status = json.loads(capsys.readouterr().out)
    status_map = {item["target"]: item for item in status["issues"]}

    assert rc == 0
    assert status_map["cursor"]["stale"] is True
    assert any(label in {"Next.js", "Vitest"} for label in status_map["cursor"]["missing_labels"])


def test_doctor_reports_portability_state_and_smart_routing(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    rc = main(
        [
            "remember",
            "We use Vitest and prefer direct technical answers.",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    capsys.readouterr()
    assert rc == 0

    rc = main(["doctor", "--project", str(project_dir), "--store-dir", str(store_dir), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "ok"
    assert payload["canonical_graph_exists"] is True
    assert payload["fact_count"] > 0
    assert payload["issues"] == []
    assert payload["fix_available"] is False
    assert "technical_expertise" in payload["smart_routing"]["claude-code"]


def test_doctor_fix_store_normalizes_root_store_into_dot_cortex(tmp_path, capsys):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    root_config = project_dir / "config.toml"
    root_config.write_text(
        """
[runtime]
store_dir = "."

[mcp]
namespace = "team"
""".strip(),
        encoding="utf-8",
    )

    rc = main(["mind", "init", "marc", "--store-dir", str(project_dir), "--format", "json"])
    capsys.readouterr()
    assert rc == 0

    rc = main(["mind", "default", "marc", "--store-dir", str(project_dir), "--format", "json"])
    capsys.readouterr()
    assert rc == 0

    rc = main(
        [
            "mind",
            "remember",
            "marc",
            "I am Marc Saint-Jour.",
            "--store-dir",
            str(project_dir),
            "--format",
            "json",
        ]
    )
    capsys.readouterr()
    assert rc == 0

    rc = main(["doctor", "--store-dir", str(project_dir), "--format", "json"])
    before = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert before["status"] == "warn"
    assert {issue["code"] for issue in before["issues"]} >= {"root_store_layout", "root_config_outside_store"}
    assert before["fix_available"] is True

    rc = main(["doctor", "--store-dir", str(project_dir), "--fix-store", "--format", "json"])
    after = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert after["status"] == "fixed"
    assert after["store_dir"] == str((project_dir / ".cortex").resolve())
    assert {action["action"] for action in after["repair_actions"]} >= {"move_config", "move_store_entry"}
    assert after["repair_errors"] == []
    assert after["issues"] == []
    assert not root_config.exists()
    assert not (project_dir / "minds").exists()
    assert not (project_dir / "versions").exists()
    assert (project_dir / ".cortex" / "config.toml").exists()
    assert (project_dir / ".cortex" / "minds" / "marc" / "manifest.json").exists()
    assert (project_dir / ".cortex" / "versions").exists()

    status_rc = main(["mind", "status", "marc", "--store-dir", str(project_dir / ".cortex"), "--format", "json"])
    status_payload = json.loads(capsys.readouterr().out)

    assert status_rc == 0
    assert status_payload["mind"] == "marc"
    assert status_payload["core_state"]["graph_ref"] == "refs/minds/marc/branches/main"


def test_doctor_fix_store_rewrites_canonical_config_mismatch(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    store_dir.mkdir()
    config_path = store_dir / "config.toml"
    config_path.write_text(
        """
[runtime]
store_dir = ".cortex"

[mcp]
namespace = "team"
""".strip(),
        encoding="utf-8",
    )

    rc = main(["doctor", "--store-dir", str(store_dir), "--format", "json"])
    before = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert before["status"] == "warn"
    assert {issue["code"] for issue in before["issues"]} >= {"config_store_mismatch"}

    rc = main(["doctor", "--store-dir", str(store_dir), "--fix", "--format", "json"])
    after = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert after["status"] == "fixed"
    assert after["repair_errors"] == []
    assert any(action["action"] == "normalize_config_store_dir" for action in after["repair_actions"])
    assert after["issues"] == []

    config = load_selfhost_config(config_path=config_path, env={})
    assert config.store_dir.resolve() == store_dir.resolve()
    assert 'store_dir = "."' in config_path.read_text(encoding="utf-8")


def test_switch_generates_target_specific_artifacts(tmp_path, capsys):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    store_dir = tmp_path / ".cortex"
    output_dir = tmp_path / "switch"
    source_notes = tmp_path / "chatgpt-export.txt"
    source_notes.write_text(
        "I am Marc. I use Python and FastAPI. I prefer direct answers. I am building Cortex-AI.",
        encoding="utf-8",
    )

    rc = main(
        [
            "switch",
            "--from",
            str(source_notes),
            "--to",
            "claude",
            "--output",
            str(output_dir),
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
        ]
    )
    capsys.readouterr()

    assert rc == 0
    assert (output_dir / "claude" / "claude_preferences.txt").exists()
    assert (output_dir / "claude" / "claude_memories.json").exists()
