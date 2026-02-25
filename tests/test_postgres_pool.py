"""Tests for cortex.caas.postgres_pool — connection pool wrapper.

These tests mock psycopg so they run without a real PostgreSQL instance.
"""

import threading
from contextlib import contextmanager
from unittest.mock import MagicMock, patch


class TestConnectionPoolFallback:
    """Test the fallback (single-connection) path when psycopg_pool is not available."""

    def test_fallback_when_no_pool_extra(self):
        """When psycopg_pool is not importable, fall back to single connection."""
        mock_conn = MagicMock()
        mock_conn.execute = MagicMock()

        with patch.dict("sys.modules", {"psycopg_pool": None}):
            with patch("psycopg.connect", return_value=mock_conn):
                # Importing with psycopg_pool failing
                from cortex.caas.postgres_pool import ConnectionPool

                pool = ConnectionPool.__new__(ConnectionPool)
                pool._conninfo = "dbname=test"
                pool._min_size = 2
                pool._max_size = 10
                pool._timeout = 30.0
                pool._pool = None
                pool._fallback_conn = mock_conn
                pool._fallback_lock = threading.Lock()
                pool._use_pool = False

                assert not pool.is_pooled
                assert pool.min_size == 2
                assert pool.max_size == 10

    def test_fallback_connection_context_manager(self):
        """Fallback connection() yields the single connection under lock."""
        from cortex.caas.postgres_pool import ConnectionPool

        mock_conn = MagicMock()
        pool = ConnectionPool.__new__(ConnectionPool)
        pool._conninfo = "dbname=test"
        pool._min_size = 1
        pool._max_size = 1
        pool._timeout = 30.0
        pool._pool = None
        pool._fallback_conn = mock_conn
        pool._fallback_lock = threading.Lock()
        pool._use_pool = False

        with pool.connection() as conn:
            assert conn is mock_conn

    def test_fallback_close(self):
        """Fallback close() closes the connection."""
        from cortex.caas.postgres_pool import ConnectionPool

        mock_conn = MagicMock()
        pool = ConnectionPool.__new__(ConnectionPool)
        pool._conninfo = "dbname=test"
        pool._min_size = 1
        pool._max_size = 1
        pool._timeout = 30.0
        pool._pool = None
        pool._fallback_conn = mock_conn
        pool._fallback_lock = threading.Lock()
        pool._use_pool = False

        pool.close()
        mock_conn.close.assert_called_once()

    def test_fallback_stats(self):
        """Fallback stats() returns synthetic single-connection stats."""
        from cortex.caas.postgres_pool import ConnectionPool

        pool = ConnectionPool.__new__(ConnectionPool)
        pool._conninfo = "dbname=test"
        pool._min_size = 1
        pool._max_size = 1
        pool._timeout = 30.0
        pool._pool = None
        pool._fallback_conn = MagicMock()
        pool._fallback_lock = threading.Lock()
        pool._use_pool = False

        stats = pool.stats()
        assert stats["pool_min"] == 1
        assert stats["pool_max"] == 1
        assert stats["pool_size"] == 1
        assert stats["pool_available"] == 1
        assert stats["requests_waiting"] == 0


class TestConnectionPoolWithMockedPoolExtra:
    """Test the pooled path with a mocked psycopg_pool."""

    def test_pooled_connection_context_manager(self):
        from cortex.caas.postgres_pool import ConnectionPool

        mock_inner_conn = MagicMock()

        @contextmanager
        def mock_connection():
            yield mock_inner_conn

        mock_pool = MagicMock()
        mock_pool.connection = mock_connection
        mock_pool.get_stats.return_value = {
            "pool_size": 5,
            "pool_available": 3,
            "requests_waiting": 0,
        }

        pool = ConnectionPool.__new__(ConnectionPool)
        pool._conninfo = "dbname=test"
        pool._min_size = 2
        pool._max_size = 10
        pool._timeout = 30.0
        pool._pool = mock_pool
        pool._fallback_conn = None
        pool._use_pool = True

        assert pool.is_pooled

        with pool.connection() as conn:
            assert conn is mock_inner_conn

    def test_pooled_stats(self):
        from cortex.caas.postgres_pool import ConnectionPool

        mock_pool = MagicMock()
        mock_pool.get_stats.return_value = {
            "pool_size": 5,
            "pool_available": 3,
            "requests_waiting": 1,
        }

        pool = ConnectionPool.__new__(ConnectionPool)
        pool._conninfo = "dbname=test"
        pool._min_size = 2
        pool._max_size = 10
        pool._timeout = 30.0
        pool._pool = mock_pool
        pool._fallback_conn = None
        pool._use_pool = True

        stats = pool.stats()
        assert stats["pool_min"] == 2
        assert stats["pool_max"] == 10
        assert stats["pool_size"] == 5
        assert stats["pool_available"] == 3
        assert stats["requests_waiting"] == 1

    def test_pooled_close(self):
        from cortex.caas.postgres_pool import ConnectionPool

        mock_pool = MagicMock()

        pool = ConnectionPool.__new__(ConnectionPool)
        pool._conninfo = "dbname=test"
        pool._min_size = 2
        pool._max_size = 10
        pool._timeout = 30.0
        pool._pool = mock_pool
        pool._fallback_conn = None
        pool._use_pool = True

        pool.close()
        mock_pool.close.assert_called_once()


class TestCreatePool:
    def test_create_pool_function(self):
        """create_pool() returns a ConnectionPool."""
        from cortex.caas.postgres_pool import create_pool

        mock_conn = MagicMock()
        with patch("psycopg.connect", return_value=mock_conn):
            with patch.dict("sys.modules", {"psycopg_pool": None}):
                pool = create_pool("dbname=test", min_size=1, max_size=5, timeout=10)
                assert pool.min_size == 1
                assert pool.max_size == 5
                pool.close()


class TestPostgresBasePoolIntegration:
    """Test that _PostgresBase correctly uses pool when provided."""

    def test_base_with_pool_param(self):
        """_PostgresBase uses pool._exec path when pool is passed."""
        mock_conn = MagicMock()

        @contextmanager
        def mock_connection():
            yield mock_conn

        mock_pool = MagicMock()
        mock_pool.connection = mock_connection

        with patch("psycopg.connect"):
            from cortex.caas.postgres_store import _PostgresBase

            base = _PostgresBase.__new__(_PostgresBase)
            base._conninfo = "dbname=test"
            base._pool = mock_pool
            base._lock = None
            base._conn = None

            # _exec should use pool
            base._exec("SELECT 1")
            # The connection within the pool context was used
            mock_conn.execute.assert_called_once_with("SELECT 1", None)

    def test_base_without_pool_uses_lock(self):
        """_PostgresBase uses lock path when pool is None."""
        mock_conn = MagicMock()

        with patch("psycopg.connect", return_value=mock_conn):
            from cortex.caas.postgres_store import _PostgresBase

            base = _PostgresBase("dbname=test")
            assert base._pool is None
            assert base._lock is not None

            base._exec("SELECT 1")
            mock_conn.execute.assert_called_with("SELECT 1", None)
            base.close()


class TestConfigPoolDefaults:
    def test_pool_config_defaults(self):
        from cortex.caas.config import CortexConfig

        config = CortexConfig.defaults()
        assert config.getint("storage", "pool_min", fallback=2) == 2
        assert config.getint("storage", "pool_max", fallback=10) == 10
        assert config.getint("storage", "pool_timeout", fallback=30) == 30


class TestCLIPoolSizeFlag:
    def test_serve_parser_has_pool_size(self):
        from cortex.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["serve", "test.json", "--pool-size", "20"])
        assert args.pool_size == 20

    def test_serve_parser_pool_size_default_none(self):
        from cortex.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["serve", "test.json"])
        assert args.pool_size is None


class TestPoolWiringToStores:
    """Test that start_caas_server signature accepts pool= and wiring logic."""

    def test_start_caas_server_accepts_pool_param(self):
        """start_caas_server has pool= in its signature."""
        import inspect
        from cortex.caas.server import start_caas_server
        sig = inspect.signature(start_caas_server)
        assert "pool" in sig.parameters
        assert sig.parameters["pool"].default is None

    def test_postgres_stores_accept_pool_kwarg(self):
        """All 5 Postgres store classes accept pool= in __init__."""
        import inspect
        mock_conn = MagicMock()
        with patch("psycopg.connect", return_value=mock_conn):
            from cortex.caas.postgres_store import (
                PostgresAuditLog,
                PostgresDeliveryLog,
                PostgresGrantStore,
                PostgresPolicyStore,
                PostgresWebhookStore,
            )
            for cls in [PostgresGrantStore, PostgresWebhookStore, PostgresAuditLog,
                        PostgresDeliveryLog, PostgresPolicyStore]:
                sig = inspect.signature(cls.__init__)
                assert "pool" in sig.parameters, f"{cls.__name__} missing pool param"

    def test_postgres_base_uses_pool_when_provided(self):
        """_PostgresBase routes _exec through pool.connection() when pool is set."""
        mock_inner_conn = MagicMock()

        @contextmanager
        def mock_connection():
            yield mock_inner_conn

        mock_pool = MagicMock()
        mock_pool.connection = mock_connection

        mock_conn = MagicMock()
        with patch("psycopg.connect", return_value=mock_conn):
            from cortex.caas.postgres_store import _PostgresBase
            base = _PostgresBase.__new__(_PostgresBase)
            base._conninfo = "dbname=test"
            base._pool = mock_pool
            base._lock = None
            base._conn = None

            base._exec("SELECT 1")
            mock_inner_conn.execute.assert_called_once_with("SELECT 1", None)
            # The direct connection should NOT have been used
            mock_conn.execute.assert_not_called()

    def test_shutdown_coordinator_registers_pool_close(self):
        """ShutdownCoordinator.register is called with pool.close."""
        from cortex.caas.shutdown import ShutdownCoordinator

        mock_pool = MagicMock()
        coordinator = ShutdownCoordinator()
        coordinator.register("pg_pool", mock_pool.close)

        callback_names = [name for name, _ in coordinator._callbacks]
        assert "pg_pool" in callback_names

        coordinator.shutdown()
        mock_pool.close.assert_called_once()

    def test_cli_pool_creation_for_postgres(self):
        """CLI creates pool when storage_backend=postgres and pool-size is set."""
        from cortex.caas.postgres_pool import ConnectionPool

        mock_conn = MagicMock()
        with patch("psycopg.connect", return_value=mock_conn):
            with patch.dict("sys.modules", {"psycopg_pool": None}):
                pool = ConnectionPool("dbname=test", min_size=2, max_size=20)
                assert pool.max_size == 20
                pool.close()
