from __future__ import annotations

import json
import subprocess
from pathlib import Path

from cortex.cli import main


def _init_git_repo(project: Path) -> None:
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Cortex Test"], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "cortex@example.com"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: bootstrap portability smoke"], cwd=project, check=True, capture_output=True
    )


def test_portability_edge_smoke_uses_live_files_and_expected_routes(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    output_dir = tmp_path / "portable"
    switch_dir = tmp_path / "switch"
    export_path = tmp_path / "chatgpt-export.txt"

    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    (project_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "edge-port-app",
                "dependencies": {
                    "next": "14.1.0",
                    "react": "18.2.0",
                    "@trpc/server": "10.0.0",
                },
                "devDependencies": {"vitest": "1.5.0"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (project_dir / "README.md").write_text("# Edge Port App\n\nPortability edge smoke.\n", encoding="utf-8")
    export_path.write_text(
        (
            "I am Marc. "
            "I use Python, FastAPI, Next.js, and CockroachDB. "
            "I prefer direct answers. "
            "I am building Cortex-AI and edge-port-app."
        ),
        encoding="utf-8",
    )
    _init_git_repo(project_dir)

    rc = main(
        [
            "portable",
            str(export_path),
            "--to",
            "all",
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
    portable = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert portable["target_count"] == 9
    assert (project_dir / "AGENTS.md").exists()
    assert (project_dir / ".github" / "copilot-instructions.md").exists()
    assert (output_dir / "chatgpt" / "custom_instructions.json").exists()

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
    assert all(tool["configured"] for tool in scan["tools"])
    assert tool_map["copilot"]["fact_count"] > 0

    rc = main(
        [
            "status",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    status = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert status["issues"]
    assert not any(issue["stale"] for issue in status["issues"])

    rc = main(
        [
            "audit",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    audit = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert audit["issues"] == []

    rc = main(
        [
            "remember",
            "We migrated from PostgreSQL to CockroachDB in January.",
            "--smart",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    remember = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert remember["fact_count"] >= portable["extracted"]["total"]

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
    smart_sync = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert {"chatgpt", "claude-code", "copilot", "grok"} <= {item["target"] for item in smart_sync["targets"]}

    rc = main(
        [
            "build",
            "--from",
            "package.json",
            "--from",
            "git-history",
            "--sync",
            "--smart",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    built = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert {item["source"] for item in built["sources"]} == {"package.json", "git-history"}
    assert any("Next.js" in item.get("frameworks", []) for item in built["sources"])

    rc = main(
        [
            "switch",
            "--from",
            str(export_path),
            "--to",
            "claude",
            "--output",
            str(switch_dir),
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
        ]
    )
    capsys.readouterr()
    assert rc == 0
    assert (switch_dir / "claude" / "claude_preferences.txt").exists()
    assert (switch_dir / "claude" / "claude_memories.json").exists()

    rc = main(
        [
            "status",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    fresh_status = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert not any(issue["stale"] for issue in fresh_status["issues"])

    gemini_path = project_dir / "GEMINI.md"
    copilot_path = project_dir / ".github" / "copilot-instructions.md"
    gemini_path.unlink()
    copilot_path.write_text(copilot_path.read_text(encoding="utf-8") + "\nMongoDB\n", encoding="utf-8")

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
    drift_scan = json.loads(capsys.readouterr().out)
    drift_tools = {tool["target"]: tool for tool in drift_scan["tools"]}
    assert rc == 0
    assert drift_tools["gemini"]["configured"] is True
    assert drift_tools["gemini"]["note"] == "configured, files missing"
    assert any(label.lower() == "mongodb" for label in drift_tools["copilot"]["labels"])

    rc = main(
        [
            "status",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    drift_status = json.loads(capsys.readouterr().out)
    drift_map = {issue["target"]: issue for issue in drift_status["issues"]}
    assert rc == 0
    assert drift_map["gemini"]["stale"] is True
    assert drift_map["gemini"]["missing_paths"]
    assert drift_map["copilot"]["stale"] is True
    assert any(label.lower() == "mongodb" for label in drift_map["copilot"]["unexpected_labels"])
    assert all(
        label not in {"Shared AI Context", "Prefers: Direct answers", "Most active commit hours: 18:00"}
        for label in drift_map["copilot"]["unexpected_labels"]
    )
    assert not any(issue["stale"] for target, issue in drift_map.items() if target not in {"copilot", "gemini"})

    rc = main(
        [
            "audit",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    drift_audit = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert any(issue["type"] == "missing_files" and issue["target"] == "gemini" for issue in drift_audit["issues"])
    assert any(
        issue["type"] == "unexpected_context" and issue["target"] == "copilot" for issue in drift_audit["issues"]
    )


def test_portability_edge_smoke_handles_all_targets_and_clamps_scan_coverage(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    output_dir = tmp_path / "portable"
    switch_dir = tmp_path / "switch"
    export_path = tmp_path / "chatgpt-export.txt"

    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    (project_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "portable-all-app",
                "dependencies": {
                    "next": "14.1.0",
                    "react": "18.2.0",
                    "@trpc/server": "10.0.0",
                },
                "devDependencies": {"vitest": "1.5.0"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (project_dir / "README.md").write_text("# Portable All App\n\nHarder portability smoke.\n", encoding="utf-8")
    export_path.write_text(
        (
            "I am Marc. "
            "I use Python, FastAPI, Next.js, and CockroachDB. "
            "I prefer direct answers. "
            "I am building Cortex-AI and portable-all-app."
        ),
        encoding="utf-8",
    )
    _init_git_repo(project_dir)

    rc = main(
        [
            "portable",
            str(export_path),
            "--to",
            "all",
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
    portable = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert portable["target_count"] == 9

    rc = main(
        [
            "remember",
            "We use CockroachDB for production and Redis for queues.",
            "--to",
            "all",
            "--smart",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    remember = json.loads(capsys.readouterr().out)
    remember_targets = {item["target"] for item in remember["targets"]}
    assert rc == 0
    assert remember_targets == {
        "claude",
        "claude-code",
        "chatgpt",
        "codex",
        "copilot",
        "cursor",
        "gemini",
        "grok",
        "windsurf",
    }
    assert "all" not in remember_targets

    chatgpt_json = output_dir / "chatgpt" / "custom_instructions.json"
    copilot_path = project_dir / ".github" / "copilot-instructions.md"
    claude_memories = output_dir / "claude" / "claude_memories.json"

    chatgpt_payload = json.loads(chatgpt_json.read_text(encoding="utf-8"))
    chatgpt_payload["what_chatgpt_should_know_about_you"] += "\nDatabase: SQLite. Cache: Memcached."
    chatgpt_json.write_text(json.dumps(chatgpt_payload, indent=2), encoding="utf-8")
    copilot_path.write_text(
        copilot_path.read_text(encoding="utf-8") + "\nLua\nElixir\nMongoDB\nSQLite\nMemcached\n",
        encoding="utf-8",
    )
    claude_memories.unlink()

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
    assert scan["coverage"] <= 1.0
    assert scan["known_facts"] <= scan["total_facts"]
    assert tool_map["copilot"]["coverage"] <= 1.0
    assert tool_map["chatgpt"]["coverage"] <= 1.0
    assert tool_map["copilot"]["unexpected_fact_count"] > 0
    assert tool_map["chatgpt"]["unexpected_fact_count"] > 0
    assert any(label == "MongoDB" for label in tool_map["copilot"]["labels"])
    assert any(label == "SQLite" for label in tool_map["chatgpt"]["labels"])

    rc = main(
        [
            "status",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    status = json.loads(capsys.readouterr().out)
    status_map = {issue["target"]: issue for issue in status["issues"]}
    assert rc == 0
    assert status_map["copilot"]["stale"] is True
    assert status_map["chatgpt"]["stale"] is True
    assert status_map["claude"]["stale"] is True
    assert any(
        label in {"MongoDB", "Lua", "Elixir", "SQLite", "Memcached"}
        for label in status_map["copilot"]["unexpected_labels"]
    )
    assert "SQLite" in status_map["chatgpt"]["unexpected_labels"]
    assert status_map["claude"]["missing_paths"]

    rc = main(
        [
            "audit",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    audit = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert any(issue["type"] == "unexpected_context" and issue["target"] == "copilot" for issue in audit["issues"])
    assert any(issue["type"] == "unexpected_context" and issue["target"] == "chatgpt" for issue in audit["issues"])
    assert any(issue["type"] == "missing_files" and issue["target"] == "claude" for issue in audit["issues"])

    rc = main(
        [
            "build",
            "--from",
            "package.json",
            "--from",
            "git-history",
            "--sync",
            "--smart",
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
    built = json.loads(capsys.readouterr().out)
    built_targets = {item["target"] for item in built["targets"]}
    assert rc == 0
    assert built_targets == {
        "claude",
        "claude-code",
        "chatgpt",
        "codex",
        "copilot",
        "cursor",
        "gemini",
        "grok",
        "windsurf",
    }
    assert "all" not in built_targets
    assert claude_memories.exists()

    rc = main(
        [
            "status",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    recovered_status = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert not any(issue["stale"] for issue in recovered_status["issues"])

    rc = main(
        [
            "switch",
            "--from",
            str(export_path),
            "--to",
            "grok",
            "--output",
            str(switch_dir),
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
        ]
    )
    capsys.readouterr()
    assert rc == 0
    assert (switch_dir / "grok" / "context_prompt.md").exists()
    assert (switch_dir / "grok" / "context_prompt.json").exists()
