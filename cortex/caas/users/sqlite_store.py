"""
SQLite implementation of the user store.

Thread-safe via a shared connection protected by threading.Lock.
Uses WAL journal mode for better concurrent read performance.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from cortex.caas.users.models import AccountStatus, User, UserRole, UserSession
from cortex.caas.users.store import AbstractUserStore


def generate_user_id() -> str:
    """Generate a unique user ID (24-char hex)."""
    return secrets.token_hex(12)


def generate_session_id() -> str:
    """Generate a unique session ID (64-char hex)."""
    return secrets.token_hex(32)


class SqliteUserStore(AbstractUserStore):
    """SQLite-backed user store with thread-safe access."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-8000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        """Create tables if they don't exist."""
        with self._lock:
            # Users table
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id         TEXT PRIMARY KEY,
                    email           TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    email_verified  INTEGER NOT NULL DEFAULT 0,
                    password_hash   TEXT NOT NULL,
                    display_name    TEXT NOT NULL DEFAULT '',
                    role            TEXT NOT NULL DEFAULT 'user',
                    storage_quota   INTEGER NOT NULL DEFAULT 1073741824,
                    storage_used    INTEGER NOT NULL DEFAULT 0,
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL,
                    last_login_at   TEXT,
                    account_status  TEXT NOT NULL DEFAULT 'active'
                )
            """)

            # Create index on email for fast lookups
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_email
                ON users (email COLLATE NOCASE)
            """)

            # User sessions table
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    session_id      TEXT PRIMARY KEY,
                    user_id         TEXT NOT NULL,
                    created_at      TEXT NOT NULL,
                    expires_at      TEXT NOT NULL,
                    revoked         INTEGER NOT NULL DEFAULT 0,
                    auth_method     TEXT NOT NULL DEFAULT 'password',
                    ip_address      TEXT,
                    user_agent      TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            # Create indexes for session queries
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_user_id
                ON user_sessions (user_id)
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_expires_at
                ON user_sessions (expires_at)
            """)

            self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # ── User operations ───────────────────────────────────────────

    def create_user(self, user: User) -> User:
        """Create a new user account."""
        if not user.user_id:
            user.user_id = generate_user_id()

        now = datetime.now(timezone.utc).isoformat()
        user.created_at = now
        user.updated_at = now

        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO users (
                        user_id, email, email_verified, password_hash,
                        display_name, role, storage_quota, storage_used,
                        created_at, updated_at, last_login_at, account_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user.user_id,
                        user.email.lower().strip(),
                        1 if user.email_verified else 0,
                        user.password_hash,
                        user.display_name,
                        user.role.value if isinstance(user.role, UserRole) else user.role,
                        user.storage_quota,
                        user.storage_used,
                        user.created_at,
                        user.updated_at,
                        user.last_login_at,
                        user.account_status.value if isinstance(user.account_status, AccountStatus) else user.account_status,
                    ),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as e:
                if "UNIQUE constraint failed" in str(e) and "email" in str(e).lower():
                    raise ValueError("Email already registered")
                raise

        return user

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get a user by their unique ID."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get a user by their email address (case-insensitive)."""
        normalized = email.lower().strip()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (normalized,)
            ).fetchone()
        return self._row_to_user(row) if row else None

    def update_user(self, user: User) -> bool:
        """Update an existing user."""
        user.updated_at = datetime.now(timezone.utc).isoformat()

        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE users SET
                    email = ?,
                    email_verified = ?,
                    password_hash = ?,
                    display_name = ?,
                    role = ?,
                    storage_quota = ?,
                    storage_used = ?,
                    updated_at = ?,
                    last_login_at = ?,
                    account_status = ?
                WHERE user_id = ?
                """,
                (
                    user.email.lower().strip(),
                    1 if user.email_verified else 0,
                    user.password_hash,
                    user.display_name,
                    user.role.value if isinstance(user.role, UserRole) else user.role,
                    user.storage_quota,
                    user.storage_used,
                    user.updated_at,
                    user.last_login_at,
                    user.account_status.value if isinstance(user.account_status, AccountStatus) else user.account_status,
                    user.user_id,
                ),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def delete_user(self, user_id: str) -> bool:
        """Delete a user and all their sessions."""
        with self._lock:
            # Sessions will be deleted via CASCADE
            cursor = self._conn.execute(
                "DELETE FROM users WHERE user_id = ?", (user_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def list_users(
        self,
        limit: int = 100,
        offset: int = 0,
        role: Optional[str] = None,
    ) -> list[User]:
        """List users with pagination and optional filtering."""
        with self._lock:
            if role:
                rows = self._conn.execute(
                    """
                    SELECT * FROM users
                    WHERE role = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (role, limit, offset),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM users
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
        return [self._row_to_user(row) for row in rows]

    def count_users(self, role: Optional[str] = None) -> int:
        """Count total users, optionally filtered by role."""
        with self._lock:
            if role:
                row = self._conn.execute(
                    "SELECT COUNT(*) as cnt FROM users WHERE role = ?", (role,)
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) as cnt FROM users"
                ).fetchone()
            return row["cnt"] if row else 0

    def update_storage_used(self, user_id: str, delta_bytes: int) -> bool:
        """Atomically update a user's storage_used counter."""
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE users
                SET storage_used = MAX(0, storage_used + ?),
                    updated_at = ?
                WHERE user_id = ?
                """,
                (delta_bytes, datetime.now(timezone.utc).isoformat(), user_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def update_last_login(self, user_id: str) -> bool:
        """Update user's last_login_at timestamp to now."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE users SET last_login_at = ?, updated_at = ? WHERE user_id = ?",
                (now, now, user_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    # ── Session operations ────────────────────────────────────────

    def create_session(self, session: UserSession) -> UserSession:
        """Create a new user session."""
        if not session.session_id:
            session.session_id = generate_session_id()

        if not session.created_at:
            session.created_at = datetime.now(timezone.utc).isoformat()

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO user_sessions (
                    session_id, user_id, created_at, expires_at,
                    revoked, auth_method, ip_address, user_agent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.user_id,
                    session.created_at,
                    session.expires_at,
                    1 if session.revoked else 0,
                    session.auth_method,
                    session.ip_address,
                    session.user_agent,
                ),
            )
            self._conn.commit()

        return session

    def get_session(self, session_id: str) -> Optional[UserSession]:
        """Get a session by its ID."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM user_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._row_to_session(row) if row else None

    def revoke_session(self, session_id: str) -> bool:
        """Revoke (invalidate) a session."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE user_sessions SET revoked = 1 WHERE session_id = ?",
                (session_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def revoke_user_sessions(self, user_id: str) -> int:
        """Revoke all sessions for a user."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE user_sessions SET revoked = 1 WHERE user_id = ?",
                (user_id,),
            )
            self._conn.commit()
            return cursor.rowcount

    def list_user_sessions(self, user_id: str, include_revoked: bool = False) -> list[UserSession]:
        """List all sessions for a user."""
        with self._lock:
            if include_revoked:
                rows = self._conn.execute(
                    """
                    SELECT * FROM user_sessions
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    """,
                    (user_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM user_sessions
                    WHERE user_id = ? AND revoked = 0
                    ORDER BY created_at DESC
                    """,
                    (user_id,),
                ).fetchall()
        return [self._row_to_session(row) for row in rows]

    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions from storage."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM user_sessions WHERE expires_at < ? OR revoked = 1",
                (now,),
            )
            self._conn.commit()
            return cursor.rowcount

    # ── Statistics ────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get user store statistics."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            total_users = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM users"
            ).fetchone()["cnt"]

            active_users = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE account_status = 'active'"
            ).fetchone()["cnt"]

            total_sessions = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM user_sessions"
            ).fetchone()["cnt"]

            active_sessions = self._conn.execute(
                """
                SELECT COUNT(*) as cnt FROM user_sessions
                WHERE revoked = 0 AND expires_at > ?
                """,
                (now,),
            ).fetchone()["cnt"]

            storage_row = self._conn.execute(
                "SELECT COALESCE(SUM(storage_used), 0) as total FROM users"
            ).fetchone()
            total_storage_used = storage_row["total"]

        return {
            "total_users": total_users,
            "active_users": active_users,
            "total_sessions": total_sessions,
            "active_sessions": active_sessions,
            "total_storage_used": total_storage_used,
        }

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        """Convert a database row to a User object."""
        return User(
            user_id=row["user_id"],
            email=row["email"],
            password_hash=row["password_hash"],
            display_name=row["display_name"],
            role=UserRole(row["role"]),
            email_verified=bool(row["email_verified"]),
            storage_quota=row["storage_quota"],
            storage_used=row["storage_used"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_login_at=row["last_login_at"],
            account_status=AccountStatus(row["account_status"]),
        )

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> UserSession:
        """Convert a database row to a UserSession object."""
        return UserSession(
            session_id=row["session_id"],
            user_id=row["user_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            revoked=bool(row["revoked"]),
            auth_method=row["auth_method"],
            ip_address=row["ip_address"],
            user_agent=row["user_agent"],
        )
