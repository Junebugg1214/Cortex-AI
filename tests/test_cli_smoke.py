from __future__ import annotations

import json
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


def test_first_class_cli_smoke_flow_and_json_contracts(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    init_rc = main(
        [
            "init",
            "--store-dir",
            str(store_dir),
            "--mind",
            "marc",
            "--owner",
            "marc",
            "--format",
            "json",
        ]
    )
    init_streams = capsys.readouterr()
    init_payload = json.loads(init_streams.out)

    assert init_rc == 0
    assert init_streams.err == ""
    assert set(init_payload) == {
        "status",
        "store_dir",
        "store_source",
        "config_path",
        "config_created",
        "auth_keys_created",
        "default_mind",
        "created_mind",
        "created_mind_id",
        "namespace",
        "warnings",
        "next_steps",
    }
    assert init_payload["status"] == "ok"
    assert init_payload["default_mind"] == "marc"
    assert init_payload["namespace"] == "team"

    remember_rc = main(
        [
            "mind",
            "remember",
            "marc",
            "I prefer concise technical answers.",
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    remember_streams = capsys.readouterr()
    remember_payload = json.loads(remember_streams.out)

    assert remember_rc == 0
    assert remember_streams.err == ""
    assert remember_payload["mind"] == "marc"
    assert remember_payload["statement"] == "I prefer concise technical answers."
    assert remember_payload["graph_ref"] == "refs/minds/marc/branches/main"

    status_rc = main(["mind", "status", "marc", "--store-dir", str(store_dir), "--format", "json"])
    status_streams = capsys.readouterr()
    status_payload = json.loads(status_streams.out)

    assert status_rc == 0
    assert status_streams.err == ""
    assert status_payload["mind"] == "marc"
    assert status_payload["graph_ref"] == "refs/minds/marc/branches/main"
    assert status_payload["manifest"]["current_branch"] == "main"
    assert status_payload["is_default"] is True

    connect_rc = main(
        [
            "connect",
            "manus",
            "--store-dir",
            str(store_dir),
            "--url",
            "https://example.ngrok-free.app",
            "--print-config",
            "--format",
            "json",
        ]
    )
    connect_streams = capsys.readouterr()
    connect_payload = json.loads(connect_streams.out)

    assert connect_rc == 0
    assert connect_streams.err == ""
    assert set(connect_payload) == {
        "status",
        "target",
        "store_dir",
        "config_path",
        "namespace",
        "connector_name",
        "mcp_url",
        "auth_ready",
        "key_name",
        "auth_header",
        "serve_command",
        "warnings",
        "errors",
        "next_steps",
        "connector_config",
    }
    assert connect_payload["status"] == "ok"
    assert connect_payload["target"] == "manus"
    assert connect_payload["mcp_url"] == "https://example.ngrok-free.app/mcp"
    assert connect_payload["serve_command"].startswith("cortex serve manus ")
    assert connect_payload["connector_config"]["mcpServers"]["Cortex-Manus"]["url"] == connect_payload["mcp_url"]

    api_rc = main(["serve", "api", "--store-dir", str(store_dir), "--check", "--format", "json"])
    api_streams = capsys.readouterr()
    api_payload = json.loads(api_streams.out)

    assert api_rc == 0
    assert api_streams.err == ""
    assert set(api_payload) == {
        "status",
        "target",
        "mode",
        "project_version",
        "api_version",
        "openapi_version",
        "config_path",
        "store_dir",
        "store_exists",
        "backend",
        "context_file",
        "server_host",
        "server_port",
        "mcp_namespace",
        "auth_enabled",
        "api_key_count",
        "api_keys",
        "warnings",
    }
    assert api_payload["status"] == "ok"
    assert api_payload["target"] == "api"
    assert api_payload["mode"] == "server"
    assert api_payload["auth_enabled"] is True

    mcp_rc = main(["serve", "mcp", "--store-dir", str(store_dir), "--check", "--format", "json"])
    mcp_streams = capsys.readouterr()
    mcp_payload = json.loads(mcp_streams.out)

    assert mcp_rc == 0
    assert mcp_streams.err == ""
    assert set(mcp_payload) == {
        "status",
        "target",
        "mode",
        "project_version",
        "api_version",
        "openapi_version",
        "config_path",
        "store_dir",
        "store_exists",
        "backend",
        "context_file",
        "server_host",
        "server_port",
        "mcp_namespace",
        "auth_enabled",
        "api_key_count",
        "api_keys",
        "warnings",
    }
    assert mcp_payload["status"] == "ok"
    assert mcp_payload["target"] == "mcp"
    assert mcp_payload["mode"] == "mcp"
    assert mcp_payload["mcp_namespace"] == "team"

    manus_rc = main(["serve", "manus", "--store-dir", str(store_dir), "--check", "--format", "json"])
    manus_streams = capsys.readouterr()
    manus_payload = json.loads(manus_streams.out)

    assert manus_rc == 0
    assert manus_streams.err == ""
    assert set(manus_payload) == {
        "status",
        "target",
        "mode",
        "project_version",
        "api_version",
        "openapi_version",
        "config_path",
        "store_dir",
        "store_exists",
        "backend",
        "context_file",
        "server_host",
        "server_port",
        "mcp_namespace",
        "auth_enabled",
        "api_key_count",
        "api_keys",
        "warnings",
        "bridge",
        "bridge_transport",
        "bridge_https_required",
        "mcp_path",
        "protocol_version",
        "tool_count",
        "tools",
        "allow_write_tools",
        "allow_insecure_no_auth",
    }
    assert manus_payload["status"] == "ok"
    assert manus_payload["target"] == "manus"
    assert manus_payload["bridge"] == "manus_http"
    assert manus_payload["protocol_version"] == "2024-11-05"
    assert manus_payload["tool_count"] == len(manus_payload["tools"])
    assert "mind_list" in manus_payload["tools"]


def test_legacy_cli_compatibility_flows_still_work_with_json_contracts(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    output_dir = tmp_path / "portable-output"
    graph_path = tmp_path / "context.json"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    _write_graph(
        graph_path,
        [
            ("Marc Saint-Jour", "identity", "Marc Saint-Jour"),
            ("Cortex-AI", "active_priorities", "Active project: Cortex-AI"),
            ("Python", "technical_expertise", "Uses Python"),
        ],
    )
    (project_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "cortex-app",
                "dependencies": {"next": "14.1.0", "react": "18.2.0"},
                "devDependencies": {"vitest": "1.5.0"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    init_rc = main(
        [
            "init",
            "--store-dir",
            str(store_dir),
            "--mind",
            "marc",
            "--owner",
            "marc",
            "--format",
            "json",
        ]
    )
    capsys.readouterr()
    assert init_rc == 0

    portable_rc = main(
        [
            "portable",
            str(graph_path),
            "--to",
            "chatgpt",
            "codex",
            "--output",
            str(output_dir),
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--dry-run",
            "--format",
            "json",
        ]
    )
    portable_streams = capsys.readouterr()
    portable_payload = json.loads(portable_streams.out)

    assert portable_rc == 0
    assert portable_streams.err == ""
    assert portable_payload["compatibility_mode"] == "default_mind"
    assert portable_payload["mind"] == "marc"
    assert portable_payload["graph_ref"] == "refs/minds/marc/branches/main"
    assert portable_payload["target_count"] == 2
    assert {item["target"] for item in portable_payload["targets"]} == {"chatgpt", "codex"}

    remember_rc = main(
        [
            "remember",
            "I prefer concise technical answers.",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    remember_streams = capsys.readouterr()
    remember_payload = json.loads(remember_streams.out)

    assert remember_rc == 0
    assert remember_streams.err == ""
    assert remember_payload["compatibility_mode"] == "default_mind"
    assert remember_payload["mind"] == "marc"
    assert remember_payload["statement"] == "I prefer concise technical answers."
    assert remember_payload["graph_ref"] == "refs/minds/marc/branches/main"

    build_rc = main(
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
    build_streams = capsys.readouterr()
    build_payload = json.loads(build_streams.out)

    assert build_rc == 0
    assert build_streams.err == ""
    assert build_payload["fact_count"] > 0
    assert [item["source"] for item in build_payload["sources"]] == ["package.json"]

    audit_rc = main(["audit", "--project", str(project_dir), "--store-dir", str(store_dir), "--format", "json"])
    audit_streams = capsys.readouterr()
    audit_payload = json.loads(audit_streams.out)

    assert audit_rc == 0
    assert audit_streams.err == ""
    assert set(audit_payload) == {"issues", "targets"}
    assert isinstance(audit_payload["issues"], list)

    serve_api_rc = main(["serve", "api", "--store-dir", str(store_dir), "--check", "--format", "json"])
    serve_api_streams = capsys.readouterr()
    serve_api_payload = json.loads(serve_api_streams.out)
    assert serve_api_rc == 0
    assert serve_api_streams.err == ""

    legacy_server_rc = main(["server", "--store-dir", str(store_dir), "--check", "--format", "json"])
    legacy_server_streams = capsys.readouterr()
    legacy_server_payload = json.loads(legacy_server_streams.out)

    assert legacy_server_rc == 0
    assert legacy_server_streams.err == ""
    assert legacy_server_payload == serve_api_payload

    serve_mcp_rc = main(["serve", "mcp", "--store-dir", str(store_dir), "--check", "--format", "json"])
    serve_mcp_streams = capsys.readouterr()
    serve_mcp_payload = json.loads(serve_mcp_streams.out)
    assert serve_mcp_rc == 0
    assert serve_mcp_streams.err == ""

    legacy_mcp_rc = main(["mcp", "--store-dir", str(store_dir), "--check", "--format", "json"])
    legacy_mcp_streams = capsys.readouterr()
    legacy_mcp_payload = json.loads(legacy_mcp_streams.out)

    assert legacy_mcp_rc == 0
    assert legacy_mcp_streams.err == ""
    assert legacy_mcp_payload == serve_mcp_payload
