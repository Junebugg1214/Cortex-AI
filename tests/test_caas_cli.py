"""
Tests for CaaS CLI integration — serve, grant, rotate subcommands.

Covers:
- Parser accepts new subcommands
- grant --create produces token
- grant --list and --revoke
- rotate produces new identity
"""

import json
import tempfile
from pathlib import Path

from cortex.cli import build_parser, main
from cortex.graph import CortexGraph, Node
from cortex.upai.identity import UPAIIdentity, has_crypto


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


# ============================================================================
# Parser tests
# ============================================================================


class TestCaaSParser:
    def test_serve_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "context.json"])
        assert args.subcommand == "serve"
        assert args.input_file == "context.json"
        assert args.port == 8421

    def test_serve_custom_port(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "context.json", "--port", "9000"])
        assert args.port == 9000

    def test_grant_create(self):
        parser = build_parser()
        args = parser.parse_args(["grant", "--create", "--audience", "Claude"])
        assert args.subcommand == "grant"
        assert args.create is True
        assert args.audience == "Claude"

    def test_grant_list(self):
        parser = build_parser()
        args = parser.parse_args(["grant", "--list"])
        assert args.subcommand == "grant"
        assert args.list_grants is True

    def test_grant_revoke(self):
        parser = build_parser()
        args = parser.parse_args(["grant", "--revoke", "some-grant-id"])
        assert args.subcommand == "grant"
        assert args.revoke == "some-grant-id"

    def test_rotate_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["rotate"])
        assert args.subcommand == "rotate"
        assert args.store_dir == ".cortex"

    def test_rotate_custom_store(self):
        parser = build_parser()
        args = parser.parse_args(["rotate", "--store-dir", "/tmp/test"])
        assert args.store_dir == "/tmp/test"

    def test_known_subcommands_includes_new(self):
        """The new subcommands should be in the known_subcommands tuple."""
        import inspect

        from cortex.cli import main

        source = inspect.getsource(main)
        assert '"serve"' in source
        assert '"grant"' in source
        assert '"rotate"' in source


# ============================================================================
# Grant CLI integration
# ============================================================================


class TestGrantCLI:
    def test_grant_create_e2e(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            result = main(
                [
                    "grant",
                    "--create",
                    "--audience",
                    "TestAudience",
                    "--policy",
                    "professional",
                    "--store-dir",
                    store_dir,
                ]
            )
            assert result == 0

    def test_grant_list_e2e(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            result = main(
                [
                    "grant",
                    "--list",
                    "--store-dir",
                    store_dir,
                ]
            )
            assert result == 0

    def test_grant_missing_audience(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            result = main(
                [
                    "grant",
                    "--create",
                    "--store-dir",
                    store_dir,
                ]
            )
            assert result == 1  # missing audience


# ============================================================================
# Rotate CLI integration
# ============================================================================


class TestRotateCLI:
    def test_rotate_e2e(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            result = main(
                [
                    "rotate",
                    "--store-dir",
                    store_dir,
                ]
            )
            assert result == 0

            # Verify new identity was saved
            new_identity = UPAIIdentity.load(Path(store_dir))
            assert new_identity.did.startswith("did:key:z6Mk")

    def test_rotate_no_identity(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            result = main(
                [
                    "rotate",
                    "--store-dir",
                    str(Path(tmpdir) / "nonexistent"),
                ]
            )
            assert result == 1

    def test_rotate_passes_reason(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            result = main(
                [
                    "rotate",
                    "--store-dir",
                    store_dir,
                    "--reason",
                    "compromised",
                ]
            )
            assert result == 0

            # Verify keychain has correct reason
            from cortex.upai.keychain import Keychain

            kc = Keychain(Path(store_dir))
            history = kc.get_history()
            revoked = [r for r in history if r.revoked_at]
            assert len(revoked) == 1
            assert revoked[0].revocation_reason == "compromised"


# ============================================================================
# Grant persistence tests
# ============================================================================


class TestGrantPersistence:
    def test_grant_create_persists(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path, store_dir = _setup_context(tmpdir)
            result = main(
                [
                    "grant",
                    "--create",
                    "--audience",
                    "PersistTest",
                    "--store-dir",
                    store_dir,
                ]
            )
            assert result == 0

            # Verify grants.json was created with the grant
            grants_path = Path(store_dir) / "grants.json"
            assert grants_path.exists()
            data = json.loads(grants_path.read_text())
            grants = data.get("grants", {})
            assert len(grants) == 1
            grant = list(grants.values())[0]
            assert grant["token_data"]["audience"] == "PersistTest"


# ============================================================================
# Serve parser with storage flags
# ============================================================================


class TestServeStorageFlags:
    def test_serve_default_storage(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "context.json"])
        assert args.storage == "json"
        assert args.db_path is None

    def test_serve_sqlite_storage(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "context.json", "--storage", "sqlite"])
        assert args.storage == "sqlite"

    def test_serve_custom_db_path(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "context.json", "--storage", "sqlite", "--db-path", "/tmp/test.db"])
        assert args.db_path == "/tmp/test.db"
