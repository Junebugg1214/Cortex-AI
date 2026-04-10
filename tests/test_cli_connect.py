from __future__ import annotations

import json

from cortex.cli import build_parser, main


def test_cli_parser_supports_connect_and_serve_subcommands():
    connect_args = build_parser().parse_args(["connect", "manus", "--url", "https://example.ngrok-free.app/mcp"])
    serve_args = build_parser().parse_args(["serve", "manus", "--check"])

    assert connect_args.subcommand == "connect"
    assert connect_args.connect_subcommand == "manus"
    assert serve_args.subcommand == "serve"
    assert serve_args.serve_subcommand == "manus"


def test_connect_manus_prints_paste_ready_config_json(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"

    init_rc = main(["init", "--store-dir", str(store_dir), "--mind", "marc", "--owner", "marc", "--format", "json"])
    capsys.readouterr()
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
    payload = json.loads(capsys.readouterr().out)

    assert init_rc == 0
    assert connect_rc == 0
    assert payload["status"] == "ok"
    assert payload["target"] == "manus"
    assert payload["auth_ready"] is True
    assert payload["key_name"] == "reader"
    assert payload["mcp_url"] == "https://example.ngrok-free.app/mcp"
    assert payload["serve_command"].startswith("cortex serve manus ")
    connector = payload["connector_config"]["mcpServers"]["Cortex-Manus"]
    assert connector["type"] == "streamableHttp"
    assert connector["url"] == "https://example.ngrok-free.app/mcp"
    assert connector["headers"]["X-API-Key"].startswith("cortex-reader-")


def test_connect_manus_check_warns_until_public_url_is_known(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"

    main(["init", "--store-dir", str(store_dir), "--mind", "marc", "--owner", "marc", "--format", "json"])
    capsys.readouterr()
    rc = main(["connect", "manus", "--store-dir", str(store_dir), "--check", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "warn"
    assert payload["auth_ready"] is True
    assert payload["mcp_url"] == "https://your-https-endpoint.example/mcp"
    assert any("No public HTTPS URL was provided yet" in warning for warning in payload["warnings"])


def test_serve_api_mcp_and_manus_checks_round_trip(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"

    api_rc = main(["serve", "api", "--store-dir", str(store_dir), "--check"])
    api_output = capsys.readouterr().out
    mcp_rc = main(["serve", "mcp", "--store-dir", str(store_dir), "--check"])
    mcp_output = capsys.readouterr().out
    manus_rc = main(["serve", "manus", "--store-dir", str(store_dir), "--check"])
    manus_output = capsys.readouterr().out

    assert api_rc == 0
    assert "Cortex server diagnostics:" in api_output
    assert mcp_rc == 0
    assert "Cortex mcp diagnostics:" in mcp_output
    assert manus_rc == 0
    assert "Bridge:    Manus custom MCP over HTTP" in manus_output
