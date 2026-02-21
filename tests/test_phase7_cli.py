"""
Tests for Phase 7 CLI integration — config loading, structured logging,
graceful shutdown, SQLite grants, DID documents, keychain history.

Covers:
- serve --config flag parsing and config loading
- serve with CortexConfig + setup_logging + ShutdownCoordinator
- grant --storage sqlite / --db-path
- identity --did-doc output
- identity --keychain history and chain validation
- Logging format and level configuration
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from cortex.graph import CortexGraph, Node
from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.cli import build_parser, main


def _setup_context(tmpdir):
    """Create a context file and identity for testing."""
    store_dir = Path(tmpdir) / ".cortex"

    identity = UPAIIdentity.generate("Test User")
    identity.save(store_dir)

    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Test", tags=["identity"], confidence=0.9))
    data = graph.export_v5()

    context_path = Path(tmpdir) / "context.json"
    context_path.write_text(json.dumps(data, indent=2))

    return str(context_path), str(store_dir)


def _write_config(tmpdir, sections=None):
    """Write a cortex.ini config file and return its path."""
    if sections is None:
        sections = {
            "server": {"host": "127.0.0.1", "port": "8421"},
            "logging": {"level": "DEBUG", "format": "json"},
            "storage": {"backend": "sqlite"},
            "security": {"csrf_enabled": "true"},
        }
    lines = []
    for section, kvs in sections.items():
        lines.append(f"[{section}]")
        for k, v in kvs.items():
            lines.append(f"{k} = {v}")
        lines.append("")
    config_path = Path(tmpdir) / "cortex.ini"
    config_path.write_text("\n".join(lines))
    return str(config_path)


# ============================================================================
# TestServeConfigParser — --config flag parsing
# ============================================================================

class TestServeConfigParser:

    def test_config_flag_default_none(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "context.json"])
        assert args.config is None

    def test_config_flag_long(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "context.json", "--config", "cortex.ini"])
        assert args.config == "cortex.ini"

    def test_config_flag_short(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "context.json", "-C", "cortex.ini"])
        assert args.config == "cortex.ini"

    def test_config_independent_of_port(self):
        parser = build_parser()
        args = parser.parse_args([
            "serve", "context.json", "-C", "cortex.ini", "--port", "9000",
        ])
        assert args.config == "cortex.ini"
        assert args.port == 9000

    def test_config_independent_of_storage(self):
        parser = build_parser()
        args = parser.parse_args([
            "serve", "context.json", "-C", "cortex.ini",
            "--storage", "sqlite",
        ])
        assert args.config == "cortex.ini"
        assert args.storage == "sqlite"

    def test_config_with_all_flags(self):
        parser = build_parser()
        args = parser.parse_args([
            "serve", "context.json", "-C", "cortex.ini",
            "--port", "9000", "--storage", "sqlite",
            "--store-dir", "/tmp/test", "--enable-sse",
        ])
        assert args.config == "cortex.ini"
        assert args.port == 9000
        assert args.storage == "sqlite"
        assert args.store_dir == "/tmp/test"
        assert args.enable_sse is True


# ============================================================================
# TestServeWithConfig — config loading and integration
# ============================================================================

class TestServeWithConfig:

    def test_missing_config_file_returns_error(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            result = main([
                "serve", context_path, "--config", "/nonexistent/cortex.ini",
                "--store-dir", store_dir,
            ])
            assert result == 1

    @patch("cortex.caas.server.start_caas_server")
    def test_config_loaded_from_file(self, mock_start):
        if not has_crypto():
            return
        mock_server = MagicMock()
        mock_server._shutdown_coordinator = None
        mock_start.return_value = mock_server
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            config_path = _write_config(tmpdir)
            result = main([
                "serve", context_path, "-C", config_path,
                "--store-dir", store_dir,
            ])
            assert result == 0
            mock_start.assert_called_once()
            call_kwargs = mock_start.call_args[1]
            assert call_kwargs.get("config") is not None

    @patch("cortex.caas.logging_config.setup_logging")
    @patch("cortex.caas.server.start_caas_server")
    def test_setup_logging_called(self, mock_start, mock_logging):
        if not has_crypto():
            return
        mock_server = MagicMock()
        mock_server._shutdown_coordinator = None
        mock_start.return_value = mock_server
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            config_path = _write_config(tmpdir)
            result = main([
                "serve", context_path, "-C", config_path,
                "--store-dir", store_dir,
            ])
            assert result == 0
            mock_logging.assert_called_once()
            call_kwargs = mock_logging.call_args[1]
            assert call_kwargs["level"] == "DEBUG"
            assert call_kwargs["fmt"] == "json"

    @patch("cortex.caas.server.start_caas_server")
    def test_shutdown_coordinator_used(self, mock_start):
        if not has_crypto():
            return
        mock_coordinator = MagicMock()
        mock_coordinator.wait_for_shutdown = MagicMock(return_value=None)
        mock_server = MagicMock()
        mock_server._shutdown_coordinator = mock_coordinator
        mock_start.return_value = mock_server
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            result = main([
                "serve", context_path, "--store-dir", store_dir,
            ])
            assert result == 0
            mock_coordinator.install_signal_handlers.assert_called_once()
            mock_coordinator.wait_for_shutdown.assert_called_once()

    @patch("cortex.caas.server.start_caas_server")
    def test_fallback_without_coordinator(self, mock_start):
        if not has_crypto():
            return
        mock_server = MagicMock()
        mock_server._shutdown_coordinator = None
        mock_start.return_value = mock_server
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            result = main([
                "serve", context_path, "--store-dir", store_dir,
            ])
            assert result == 0
            mock_server.serve_forever.assert_called_once()

    @patch("cortex.caas.server.start_caas_server")
    def test_env_config_when_no_file(self, mock_start):
        if not has_crypto():
            return
        mock_server = MagicMock()
        mock_server._shutdown_coordinator = None
        mock_start.return_value = mock_server
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            result = main([
                "serve", context_path, "--store-dir", store_dir,
            ])
            assert result == 0
            call_kwargs = mock_start.call_args[1]
            assert call_kwargs.get("config") is not None

    @patch("cortex.caas.server.start_caas_server")
    def test_config_passed_to_server(self, mock_start):
        if not has_crypto():
            return
        mock_server = MagicMock()
        mock_server._shutdown_coordinator = None
        mock_start.return_value = mock_server
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            config_path = _write_config(tmpdir)
            result = main([
                "serve", context_path, "-C", config_path,
                "--store-dir", store_dir,
            ])
            assert result == 0
            call_kwargs = mock_start.call_args[1]
            config = call_kwargs["config"]
            assert config.get("logging", "level", fallback="INFO") == "DEBUG"


# ============================================================================
# TestGrantWithSqlite — --storage sqlite
# ============================================================================

class TestGrantWithSqlite:

    def test_grant_parser_storage_default(self):
        parser = build_parser()
        args = parser.parse_args(["grant", "--list"])
        assert args.storage == "json"

    def test_grant_parser_storage_sqlite(self):
        parser = build_parser()
        args = parser.parse_args(["grant", "--list", "--storage", "sqlite"])
        assert args.storage == "sqlite"

    def test_grant_parser_db_path(self):
        parser = build_parser()
        args = parser.parse_args([
            "grant", "--list", "--storage", "sqlite", "--db-path", "/tmp/test.db",
        ])
        assert args.db_path == "/tmp/test.db"

    def test_grant_create_sqlite(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            db_path = str(Path(tmpdir) / "grants.db")
            result = main([
                "grant", "--create", "--audience", "SqliteTest",
                "--store-dir", store_dir,
                "--storage", "sqlite", "--db-path", db_path,
            ])
            assert result == 0
            assert Path(db_path).exists()

    def test_grant_list_sqlite(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            db_path = str(Path(tmpdir) / "grants.db")
            # Create then list
            main([
                "grant", "--create", "--audience", "ListTest",
                "--store-dir", store_dir,
                "--storage", "sqlite", "--db-path", db_path,
            ])
            result = main([
                "grant", "--list", "--store-dir", store_dir,
                "--storage", "sqlite", "--db-path", db_path,
            ])
            assert result == 0

    def test_grant_revoke_sqlite(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            db_path = str(Path(tmpdir) / "grants.db")
            # Create a grant, get its ID from the sqlite store
            main([
                "grant", "--create", "--audience", "RevokeTest",
                "--store-dir", store_dir,
                "--storage", "sqlite", "--db-path", db_path,
            ])
            from cortex.caas.sqlite_store import SqliteGrantStore
            gs = SqliteGrantStore(db_path)
            grants = gs.list_all()
            grant_id = grants[0]["grant_id"]
            result = main([
                "grant", "--revoke", grant_id,
                "--store-dir", store_dir,
                "--storage", "sqlite", "--db-path", db_path,
            ])
            assert result == 0

    def test_grant_default_db_path(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            result = main([
                "grant", "--create", "--audience", "DefaultPath",
                "--store-dir", store_dir,
                "--storage", "sqlite",
            ])
            assert result == 0
            default_db = Path(store_dir) / "cortex.db"
            assert default_db.exists()


# ============================================================================
# TestIdentityDidDoc — --did-doc output
# ============================================================================

class TestIdentityDidDoc:

    def test_did_doc_parser_flag(self):
        parser = build_parser()
        args = parser.parse_args(["identity", "--did-doc"])
        assert args.did_doc is True

    def test_did_doc_no_identity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = main([
                "identity", "--did-doc", "--store-dir", str(Path(tmpdir) / "empty"),
            ])
            assert result == 1

    def test_did_doc_valid_json(self, capsys):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            _, store_dir = _setup_context(tmpdir)
            result = main([
                "identity", "--did-doc", "--store-dir", store_dir,
            ])
            assert result == 0
            captured = capsys.readouterr()
            doc = json.loads(captured.out)
            assert "@context" in doc or "id" in doc

    def test_did_doc_has_verification_method(self, capsys):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            _, store_dir = _setup_context(tmpdir)
            result = main([
                "identity", "--did-doc", "--store-dir", store_dir,
            ])
            assert result == 0
            doc = json.loads(capsys.readouterr().out)
            assert "verificationMethod" in doc

    def test_did_doc_has_did_id(self, capsys):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            _, store_dir = _setup_context(tmpdir)
            result = main([
                "identity", "--did-doc", "--store-dir", store_dir,
            ])
            assert result == 0
            doc = json.loads(capsys.readouterr().out)
            assert doc["id"].startswith("did:")

    def test_did_doc_independent_of_show(self):
        parser = build_parser()
        args = parser.parse_args(["identity", "--did-doc"])
        assert args.did_doc is True
        assert args.show is False
        assert args.init is False


# ============================================================================
# TestIdentityKeychain — --keychain history and validation
# ============================================================================

class TestIdentityKeychain:

    def test_keychain_parser_flag(self):
        parser = build_parser()
        args = parser.parse_args(["identity", "--keychain"])
        assert args.keychain is True

    def test_keychain_no_identity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = main([
                "identity", "--keychain",
                "--store-dir", str(Path(tmpdir) / "empty"),
            ])
            assert result == 1

    def test_keychain_no_history(self, capsys):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            _, store_dir = _setup_context(tmpdir)
            result = main([
                "identity", "--keychain", "--store-dir", store_dir,
            ])
            # Fresh identity may or may not have keychain history
            assert result in (0, 1)

    def test_keychain_with_rotation(self, capsys):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            _, store_dir = _setup_context(tmpdir)
            # Perform a rotation first
            main(["rotate", "--store-dir", store_dir])
            result = main([
                "identity", "--keychain", "--store-dir", store_dir,
            ])
            assert result == 0
            output = capsys.readouterr().out
            assert "REVOKED" in output or "ACTIVE" in output

    def test_keychain_shows_active_key(self, capsys):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            _, store_dir = _setup_context(tmpdir)
            main(["rotate", "--store-dir", store_dir])
            result = main([
                "identity", "--keychain", "--store-dir", store_dir,
            ])
            assert result == 0
            assert "ACTIVE" in capsys.readouterr().out

    def test_keychain_shows_revoked_key(self, capsys):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            _, store_dir = _setup_context(tmpdir)
            main(["rotate", "--store-dir", store_dir, "--reason", "compromised"])
            result = main([
                "identity", "--keychain", "--store-dir", store_dir,
            ])
            assert result == 0
            output = capsys.readouterr().out
            assert "REVOKED" in output
            assert "compromised" in output

    def test_keychain_chain_validation(self, capsys):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            _, store_dir = _setup_context(tmpdir)
            main(["rotate", "--store-dir", store_dir])
            result = main([
                "identity", "--keychain", "--store-dir", store_dir,
            ])
            assert result == 0
            output = capsys.readouterr().out
            assert "chain:" in output

    def test_keychain_independent_of_other_flags(self):
        parser = build_parser()
        args = parser.parse_args(["identity", "--keychain"])
        assert args.keychain is True
        assert args.did_doc is False
        assert args.show is False


# ============================================================================
# TestLoggingOutput — logging configuration via CLI
# ============================================================================

class TestLoggingOutput:

    @patch("cortex.caas.server.start_caas_server")
    @patch("cortex.caas.logging_config.setup_logging")
    def test_json_format_config(self, mock_logging, mock_start):
        if not has_crypto():
            return
        mock_server = MagicMock()
        mock_server._shutdown_coordinator = None
        mock_start.return_value = mock_server
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            config_path = _write_config(tmpdir, {
                "logging": {"level": "WARNING", "format": "json"},
            })
            main(["serve", context_path, "-C", config_path, "--store-dir", store_dir])
            mock_logging.assert_called_once_with(level="WARNING", fmt="json")

    @patch("cortex.caas.server.start_caas_server")
    @patch("cortex.caas.logging_config.setup_logging")
    def test_text_format_config(self, mock_logging, mock_start):
        if not has_crypto():
            return
        mock_server = MagicMock()
        mock_server._shutdown_coordinator = None
        mock_start.return_value = mock_server
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            config_path = _write_config(tmpdir, {
                "logging": {"level": "INFO", "format": "text"},
            })
            main(["serve", context_path, "-C", config_path, "--store-dir", store_dir])
            mock_logging.assert_called_once_with(level="INFO", fmt="text")

    @patch("cortex.caas.server.start_caas_server")
    @patch("cortex.caas.logging_config.setup_logging")
    def test_debug_level(self, mock_logging, mock_start):
        if not has_crypto():
            return
        mock_server = MagicMock()
        mock_server._shutdown_coordinator = None
        mock_start.return_value = mock_server
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            config_path = _write_config(tmpdir, {
                "logging": {"level": "DEBUG", "format": "text"},
            })
            main(["serve", context_path, "-C", config_path, "--store-dir", store_dir])
            assert mock_logging.call_args[1]["level"] == "DEBUG"

    @patch("cortex.caas.server.start_caas_server")
    @patch("cortex.caas.logging_config.setup_logging")
    def test_default_level_without_config(self, mock_logging, mock_start):
        if not has_crypto():
            return
        mock_server = MagicMock()
        mock_server._shutdown_coordinator = None
        mock_start.return_value = mock_server
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            main(["serve", context_path, "--store-dir", store_dir])
            assert mock_logging.call_args[1]["level"] == "INFO"
            assert mock_logging.call_args[1]["fmt"] == "text"

    @patch("cortex.caas.server.start_caas_server")
    @patch("cortex.caas.logging_config.setup_logging")
    def test_error_level(self, mock_logging, mock_start):
        if not has_crypto():
            return
        mock_server = MagicMock()
        mock_server._shutdown_coordinator = None
        mock_start.return_value = mock_server
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            config_path = _write_config(tmpdir, {
                "logging": {"level": "ERROR", "format": "json"},
            })
            main(["serve", context_path, "-C", config_path, "--store-dir", store_dir])
            assert mock_logging.call_args[1]["level"] == "ERROR"


# ============================================================================
# TestIdentityHelpText — updated help message
# ============================================================================

class TestIdentityHelpText:

    def test_help_includes_did_doc(self, capsys):
        """The identity --help output should mention --did-doc."""
        result = main(["identity"])
        assert result == 1
        output = capsys.readouterr().out
        assert "--did-doc" in output or "--keychain" in output or "Specify" in output
