from cortex.config import format_startup_diagnostics, load_selfhost_config
from cortex.mcp import main as mcp_main
from cortex.server import main as server_main


def test_load_selfhost_config_resolves_relative_paths_and_env_overrides(tmp_path):
    config_dir = tmp_path / "ops"
    config_dir.mkdir()
    config_path = config_dir / "config.toml"
    (config_dir / "context.json").write_text("{}", encoding="utf-8")
    config_path.write_text(
        """
[runtime]
store_dir = "store"
context_file = "context.json"

[server]
host = "0.0.0.0"
port = 8766

[mcp]
namespace = "team"

[[auth.keys]]
name = "reader"
token = "reader-token"
scopes = ["read"]
namespaces = ["team"]
""".strip(),
        encoding="utf-8",
    )

    config = load_selfhost_config(
        config_path=config_path,
        env={"CORTEX_SERVER_PORT": "9911"},
    )

    assert config.store_dir == config_dir / "store"
    assert config.context_file == (config_dir / "context.json").resolve()
    assert config.server_host == "0.0.0.0"
    assert config.server_port == 9911
    assert config.mcp_namespace == "team"
    assert config.api_keys[0].name == "reader"
    assert config.api_keys[0].scopes == ("read",)


def test_server_check_prints_startup_diagnostics(tmp_path, capsys):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[runtime]
store_dir = ".cortex"

[[auth.keys]]
name = "writer"
token = "writer-token"
scopes = ["write"]
namespaces = ["team"]
""".strip(),
        encoding="utf-8",
    )

    rc = server_main(["--config", str(config_path), "--check"])
    output = capsys.readouterr().out

    assert rc == 0
    assert "Cortex server diagnostics:" in output
    assert "Release:" in output
    assert "Auth:" in output
    assert "writer" in output


def test_mcp_check_prints_startup_diagnostics(tmp_path, capsys):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[runtime]
store_dir = ".cortex"

[mcp]
namespace = "team"
""".strip(),
        encoding="utf-8",
    )

    rc = mcp_main(["--config", str(config_path), "--check"])
    output = capsys.readouterr().out

    assert rc == 0
    assert "Cortex mcp diagnostics:" in output
    assert "Namespace: team" in output


def test_invalid_config_reports_clear_error(tmp_path, capsys):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[[auth.keys]]
name = "bad"
token = "bad-token"
scopes = ["unknown-scope"]
""".strip(),
        encoding="utf-8",
    )

    rc = server_main(["--config", str(config_path), "--check"])
    error = capsys.readouterr().err

    assert rc == 1
    assert "Config error:" in error
    assert "Unknown auth scope" in error


def test_format_startup_diagnostics_mentions_local_trust_mode(tmp_path):
    config = load_selfhost_config(store_dir=tmp_path / ".cortex", env={})
    diagnostics = format_startup_diagnostics(config, mode="server")

    assert "local trust mode" in diagnostics
    assert "API v1" in diagnostics


def test_startup_diagnostics_show_key_name_but_not_token(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[[auth.keys]]
name = "maintainer"
token = "super-secret-token"
scopes = ["admin"]
namespaces = ["team"]
""".strip(),
        encoding="utf-8",
    )

    config = load_selfhost_config(config_path=config_path, env={})
    diagnostics = format_startup_diagnostics(config, mode="server")

    assert "maintainer" in diagnostics
    assert "super-secret-token" not in diagnostics
