from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

from cortex.cli import main
from cortex.mcp.mcp import CortexMCPServer
from cortex.service.service import MemoryService
from cortex.storage import build_sqlite_backend


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


def _initialize_mcp(server: CortexMCPServer) -> None:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        }
    )
    assert response is not None
    server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})


def _mcp_tool_call(server: CortexMCPServer, tool: str, arguments: dict, request_id: int) -> dict:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
    )
    assert response is not None
    assert response["result"]["isError"] is False
    return response["result"]["structuredContent"]


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
    assert portable["target_count"] == 10
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
            "--global",
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
            "--global",
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
    assert portable["target_count"] == 10

    rc = main(
        [
            "remember",
            "We use CockroachDB for production and Redis for queues.",
            "--global",
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
        "hermes",
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
        "hermes",
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


def test_portability_edge_smoke_handles_multi_source_exports_with_live_mcp(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()

    chatgpt_zip = sources_dir / "chatgpt-export.zip"
    with zipfile.ZipFile(chatgpt_zip, "w") as zf:
        zf.writestr(
            "conversations.json",
            json.dumps(
                [
                    {
                        "mapping": {
                            "msg-1": {
                                "message": {
                                    "author": {"role": "user"},
                                    "content": {"parts": ["I am Marc. I use Python and FastAPI."]},
                                    "create_time": "2025-01-01T00:00:00Z",
                                }
                            }
                        }
                    }
                ]
            ),
        )

    gemini_zip = sources_dir / "gemini-export.zip"
    with zipfile.ZipFile(gemini_zip, "w") as zf:
        zf.writestr(
            "exports/gemini.json",
            json.dumps(
                {
                    "conversations": [
                        {
                            "turns": [
                                {
                                    "role": "user",
                                    "text": "I am Nadia. I use TypeScript and React. Please be concise.",
                                    "timestamp": "2025-01-02T00:00:00Z",
                                }
                            ]
                        }
                    ]
                }
            ),
        )

    claude_code_jsonl = sources_dir / "claude-code.jsonl"
    claude_code_jsonl.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "session-1",
                        "cwd": "/tmp/project",
                        "message": {"content": [{"text": "I am Jules. We use FastAPI and pytest."}]},
                        "timestamp": "2025-01-03T00:00:00Z",
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "sessionId": "session-1",
                        "cwd": "/tmp/project",
                        "message": {"content": [{"text": "Understood."}]},
                        "timestamp": "2025-01-03T00:00:01Z",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    api_logs_json = sources_dir / "codex-api-logs.json"
    api_logs_json.write_text(
        json.dumps(
            {
                "requests": [
                    {
                        "timestamp": "2025-01-04T00:00:00Z",
                        "messages": [
                            {"role": "system", "content": "You are helpful."},
                            {
                                "role": "user",
                                "content": [{"type": "text", "text": "I am River. We use Redis and CockroachDB."}],
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cases = [
        (chatgpt_zip, {"Marc", "Python", "Fastapi"}),
        (gemini_zip, {"Nadia", "Typescript", "React"}),
        (claude_code_jsonl, {"Jules", "Fastapi", "Pytest"}),
        (api_logs_json, {"River", "Redis", "CockroachDB"}),
    ]

    request_id = 10
    for index, (source_path, expected_labels) in enumerate(cases):
        project_dir = tmp_path / f"project-{index}"
        store_dir = tmp_path / f".cortex-{index}"
        output_dir = tmp_path / f"portable-{index}"
        project_dir.mkdir()
        (project_dir / "README.md").write_text("# Portability Source\n\nStress test project.\n", encoding="utf-8")

        rc = main(
            [
                "portable",
                str(source_path),
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
        assert portable["target_count"] == 10
        assert portable["extracted"]["total"] > 0

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
        assert rc == 0
        assert all(tool["configured"] for tool in scan["tools"])

        backend = build_sqlite_backend(store_dir)
        server = CortexMCPServer(service=MemoryService(store_dir=store_dir, backend=backend))
        _initialize_mcp(server)
        payload = _mcp_tool_call(
            server,
            "portability_context",
            {
                "target": "chatgpt",
                "project_dir": str(project_dir),
                "smart": False,
                "policy": "full",
            },
            request_id,
        )
        request_id += 1

        assert payload["target"] == "chatgpt"
        assert payload["fact_count"] > 0
        assert expected_labels <= set(payload["labels"])


def test_portability_edge_smoke_handles_generic_named_vendor_exports_with_live_mcp(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    sources = [
        (
            "export.json",
            json.dumps(
                {
                    "messages": [
                        {
                            "composerId": "cmp-1",
                            "type": "user",
                            "text": "I am Lee. We use TypeScript and Prisma.",
                        }
                    ]
                }
            ),
            {"Lee", "Typescript"},
        ),
        (
            "export.jsonl",
            json.dumps(
                {
                    "cascadeId": "cas-1",
                    "role": "user",
                    "content": "I am Dana. We use Python and Postgres.",
                }
            )
            + "\n",
            {"Dana", "Python", "Postgres"},
        ),
        (
            "export.json",
            json.dumps(
                {
                    "messages": [
                        {
                            "copilotSessionId": "cp-1",
                            "request": {"message": "I am Avery. We use Python and Django."},
                        }
                    ]
                }
            ),
            {"Avery", "Python", "Django"},
        ),
        (
            "export.jsonl",
            json.dumps(
                {
                    "conversationId": "g-1",
                    "sender": "user",
                    "content": "I am Riley. I use Rust and React.",
                }
            )
            + "\n",
            {"Riley", "Rust", "React"},
        ),
    ]

    request_id = 40
    for index, (filename, content, expected_labels) in enumerate(sources):
        source_dir = tmp_path / f"generic-source-{index}"
        source_dir.mkdir()
        source_path = source_dir / filename
        source_path.write_text(content, encoding="utf-8")

        project_dir = tmp_path / f"generic-project-{index}"
        store_dir = tmp_path / f"generic-store-{index}"
        output_dir = tmp_path / f"generic-output-{index}"
        project_dir.mkdir()
        (project_dir / "README.md").write_text("# Portability Source\n\nGeneric vendor export.\n", encoding="utf-8")

        rc = main(
            [
                "portable",
                str(source_path),
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
        assert portable["target_count"] == 10
        assert portable["extracted"]["total"] > 0

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
        assert rc == 0
        assert scan["coverage"] > 0

        backend = build_sqlite_backend(store_dir)
        server = CortexMCPServer(service=MemoryService(store_dir=store_dir, backend=backend))
        _initialize_mcp(server)
        payload = _mcp_tool_call(
            server,
            "portability_context",
            {
                "target": "chatgpt",
                "project_dir": str(project_dir),
                "smart": False,
                "policy": "full",
            },
            request_id,
        )
        request_id += 1

        assert payload["target"] == "chatgpt"
        assert payload["fact_count"] > 0
        assert expected_labels <= set(payload["labels"])
