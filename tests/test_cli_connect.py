from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex.cli import build_parser, main


def test_cli_parser_supports_connect_and_serve_subcommands():
    connect_args = build_parser().parse_args(["connect", "manus", "--url", "https://example.ngrok-free.app/mcp"])
    codex_args = build_parser().parse_args(["connect", "codex", "--check"])
    serve_args = build_parser().parse_args(["serve", "manus", "--check"])

    assert connect_args.subcommand == "connect"
    assert connect_args.connect_subcommand == "manus"
    assert codex_args.subcommand == "connect"
    assert codex_args.connect_subcommand == "codex"
    assert serve_args.subcommand == "serve"
    assert serve_args.serve_subcommand == "manus"


def test_connect_manus_masks_secret_in_printed_config_json(tmp_path, capsys):
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
    assert payload["secrets_revealed"] is False
    connector = payload["connector_config"]["mcpServers"]["Cortex-Manus"]
    assert connector["type"] == "streamableHttp"
    assert connector["url"] == "https://example.ngrok-free.app/mcp"
    assert connector["headers"]["X-API-Key"].startswith("cortex-reader-")
    assert "..." in connector["headers"]["X-API-Key"]


def test_connect_manus_can_write_full_config_to_file(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    output_path = tmp_path / "manus-mcp.json"

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
            "--write-config",
            str(output_path),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    written = json.loads(output_path.read_text(encoding="utf-8"))

    assert init_rc == 0
    assert connect_rc == 0
    assert payload["connector_config_path"] == str(output_path.resolve())
    assert written["mcpServers"]["Cortex-Manus"]["headers"]["X-API-Key"].startswith("cortex-reader-")
    assert "..." not in written["mcpServers"]["Cortex-Manus"]["headers"]["X-API-Key"]


def test_connect_manus_can_reveal_secret_explicitly(tmp_path, capsys):
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
            "--reveal-secret",
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    connector = payload["connector_config"]["mcpServers"]["Cortex-Manus"]

    assert init_rc == 0
    assert connect_rc == 0
    assert payload["secrets_revealed"] is True
    assert connector["headers"]["X-API-Key"].startswith("cortex-reader-")
    assert "..." not in connector["headers"]["X-API-Key"]


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


def test_serve_api_and_ui_reject_unsafe_non_loopback_by_default(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"

    api_rc = main(["serve", "api", "--store-dir", str(store_dir), "--host", "0.0.0.0", "--check"])
    api_streams = capsys.readouterr()
    ui_rc = main(["serve", "ui", "--store-dir", str(store_dir), "--host", "0.0.0.0", "--check"])
    ui_streams = capsys.readouterr()

    assert api_rc == 1
    assert "local-single-user mode" in api_streams.err
    assert ui_rc == 1
    assert "local-single-user mode" in ui_streams.err


def test_serve_api_allows_hosted_service_with_auth_and_ui_needs_explicit_override(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"

    api_rc = main(
        [
            "serve",
            "api",
            "--store-dir",
            str(store_dir),
            "--host",
            "0.0.0.0",
            "--runtime-mode",
            "hosted-service",
            "--api-key",
            "secret-token",
            "--check",
            "--format",
            "json",
        ]
    )
    api_payload = json.loads(capsys.readouterr().out)

    ui_rc = main(
        [
            "serve",
            "ui",
            "--store-dir",
            str(store_dir),
            "--host",
            "0.0.0.0",
            "--runtime-mode",
            "hosted-service",
            "--check",
        ]
    )
    ui_streams = capsys.readouterr()

    assert api_rc == 0
    assert api_payload["runtime_mode"] == "hosted-service"
    assert api_payload["auth_enabled"] is True
    assert ui_rc == 1
    assert "does not yet enforce remote auth" in ui_streams.err


def _connect_target_config_path(target: str, home_dir: Path, project_dir: Path) -> Path:
    return {
        "codex": home_dir / ".codex" / "config.toml",
        "cursor": project_dir / ".cursor" / "mcp.json",
        "claude-code": project_dir / ".mcp.json",
        "hermes": home_dir / ".hermes" / "config.yaml",
    }[target]


@pytest.mark.parametrize("target", ["hermes", "codex", "cursor", "claude-code"])
def test_connect_runtime_targets_print_config_before_install(tmp_path, capsys, monkeypatch, target):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    init_rc = main(["init", "--store-dir", str(store_dir), "--mind", "marc", "--owner", "marc", "--format", "json"])
    capsys.readouterr()
    rc = main(
        [
            "connect",
            target,
            "--store-dir",
            str(store_dir),
            "--project",
            str(project_dir),
            "--print-config",
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert init_rc == 0
    assert rc == 0
    assert payload["status"] == "warn"
    assert payload["target"] == target
    assert payload["mcp_configured"] is False
    assert payload["config_path"] == str((store_dir / "config.toml").resolve())
    assert payload["mcp_config_path"] == str(_connect_target_config_path(target, home_dir, project_dir).resolve())
    assert payload["config_snippet"]
    assert "cortex-mcp" in payload["config_snippet"]
    assert any(f"cortex connect {target} --install" in step for step in payload["next_steps"])


@pytest.mark.parametrize("target", ["hermes", "codex", "cursor", "claude-code"])
def test_connect_runtime_targets_install_and_check(tmp_path, capsys, monkeypatch, target):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    init_rc = main(["init", "--store-dir", str(store_dir), "--mind", "marc", "--owner", "marc", "--format", "json"])
    capsys.readouterr()
    rc = main(
        [
            "connect",
            target,
            "--store-dir",
            str(store_dir),
            "--project",
            str(project_dir),
            "--install",
            "--check",
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    target_config_path = _connect_target_config_path(target, home_dir, project_dir)

    assert init_rc == 0
    assert rc == 0
    assert payload["status"] == "ok"
    assert payload["target"] == target
    assert payload["mcp_configured"] is True
    assert payload["config_path"] == str((store_dir / "config.toml").resolve())
    assert payload["mcp_config_path"] == str(target_config_path.resolve())
    assert target_config_path.exists()
    assert "cortex-mcp" in target_config_path.read_text(encoding="utf-8")
    assert payload["install_actions"]
    assert payload["install_actions"][-1]["path"] == str(target_config_path.resolve())
    assert str(target_config_path.resolve()) in payload["mcp_paths"]
    assert any(f"cortex mind mount marc --to {target}" in step for step in payload["next_steps"])
