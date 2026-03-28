from __future__ import annotations

import json
import subprocess
from pathlib import Path

from cortex.cli import main
from cortex.graph import CortexGraph, Node, make_node_id_with_tag


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
    assert "technical_expertise" in payload["smart_routing"]["claude-code"]


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
