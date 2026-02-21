"""
PostgreSQL connection pool wrapper.

Uses ``psycopg_pool.ConnectionPool`` when available (from the ``psycopg[pool]``
extra).  Provides a thin wrapper so the rest of the codebase can treat pooled
and non-pooled connections uniformly.

Usage::

    pool = create_pool("dbname=cortex", min_size=2, max_size=10)
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    pool.close()
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator


class ConnectionPool:
    """Wrapper around ``psycopg_pool.ConnectionPool``.

    If the pool extra is not installed, falls back to a single-connection
    implementation that is functionally identical to the old behavior.
    """

    def __init__(
        self,
        conninfo: str,
        min_size: int = 2,
        max_size: int = 10,
        timeout: float = 30.0,
    ) -> None:
        self._conninfo = conninfo
        self._min_size = min_size
        self._max_size = max_size
        self._timeout = timeout
        self._pool: Any = None
        self._fallback_conn: Any = None
        self._use_pool = False

        try:
            from psycopg_pool import ConnectionPool as PgPool

            self._pool = PgPool(
                conninfo,
                min_size=min_size,
                max_size=max_size,
                timeout=timeout,
                kwargs={"autocommit": True},
            )
            self._use_pool = True
        except ImportError:
            # Fall back to single connection with lock (same as _PostgresBase)
            import threading

            import psycopg

            self._fallback_conn = psycopg.connect(conninfo, autocommit=True)
            self._fallback_lock = threading.Lock()
            self._use_pool = False

    @contextmanager
    def connection(self) -> Generator:
        """Yield a psycopg connection from the pool (or the fallback)."""
        if self._use_pool:
            with self._pool.connection() as conn:
                yield conn
        else:
            with self._fallback_lock:
                yield self._fallback_conn

    @property
    def is_pooled(self) -> bool:
        """Return True if using a real connection pool."""
        return self._use_pool

    @property
    def min_size(self) -> int:
        return self._min_size

    @property
    def max_size(self) -> int:
        return self._max_size

    def close(self) -> None:
        """Close the pool or fallback connection."""
        if self._use_pool and self._pool is not None:
            self._pool.close()
        elif self._fallback_conn is not None:
            self._fallback_conn.close()

    def stats(self) -> dict:
        """Return pool statistics (or synthetic stats for fallback)."""
        if self._use_pool and self._pool is not None:
            s = self._pool.get_stats()
            return {
                "pool_min": self._min_size,
                "pool_max": self._max_size,
                "pool_size": s.get("pool_size", 0),
                "pool_available": s.get("pool_available", 0),
                "requests_waiting": s.get("requests_waiting", 0),
            }
        return {
            "pool_min": 1,
            "pool_max": 1,
            "pool_size": 1,
            "pool_available": 1,
            "requests_waiting": 0,
        }


def create_pool(
    conninfo: str,
    min_size: int = 2,
    max_size: int = 10,
    timeout: float = 30.0,
) -> ConnectionPool:
    """Create a new connection pool.

    Args:
        conninfo: PostgreSQL connection string.
        min_size: Minimum connections to keep in the pool.
        max_size: Maximum connections allowed.
        timeout: Seconds to wait for a connection before raising.

    Returns:
        A ``ConnectionPool`` instance.
    """
    return ConnectionPool(
        conninfo,
        min_size=min_size,
        max_size=max_size,
        timeout=timeout,
    )
