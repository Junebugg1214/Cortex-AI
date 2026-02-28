"""
Abstract user store interface for multi-user authentication.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from cortex.caas.users.models import User, UserSession


class AbstractUserStore(ABC):
    """Abstract interface for user data storage."""

    # ── User operations ───────────────────────────────────────────

    @abstractmethod
    def create_user(self, user: User) -> User:
        """Create a new user account.

        Raises:
            ValueError: If email already exists
        """
        ...

    @abstractmethod
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get a user by their unique ID."""
        ...

    @abstractmethod
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get a user by their email address (case-insensitive)."""
        ...

    @abstractmethod
    def update_user(self, user: User) -> bool:
        """Update an existing user.

        Returns True if user was found and updated, False otherwise.
        """
        ...

    @abstractmethod
    def delete_user(self, user_id: str) -> bool:
        """Delete a user and all their sessions.

        Returns True if user was found and deleted, False otherwise.
        """
        ...

    @abstractmethod
    def list_users(
        self,
        limit: int = 100,
        offset: int = 0,
        role: Optional[str] = None,
    ) -> list[User]:
        """List users with pagination and optional filtering."""
        ...

    @abstractmethod
    def count_users(self, role: Optional[str] = None) -> int:
        """Count total users, optionally filtered by role."""
        ...

    @abstractmethod
    def update_storage_used(self, user_id: str, delta_bytes: int) -> bool:
        """Atomically update a user's storage_used counter.

        Args:
            user_id: The user's ID
            delta_bytes: Bytes to add (positive) or subtract (negative)

        Returns:
            True if update succeeded, False if user not found
        """
        ...

    @abstractmethod
    def update_last_login(self, user_id: str) -> bool:
        """Update user's last_login_at timestamp to now."""
        ...

    # ── Session operations ────────────────────────────────────────

    @abstractmethod
    def create_session(self, session: UserSession) -> UserSession:
        """Create a new user session."""
        ...

    @abstractmethod
    def get_session(self, session_id: str) -> Optional[UserSession]:
        """Get a session by its ID."""
        ...

    @abstractmethod
    def revoke_session(self, session_id: str) -> bool:
        """Revoke (invalidate) a session.

        Returns True if session was found and revoked, False otherwise.
        """
        ...

    @abstractmethod
    def revoke_user_sessions(self, user_id: str) -> int:
        """Revoke all sessions for a user.

        Returns the number of sessions revoked.
        """
        ...

    @abstractmethod
    def list_user_sessions(self, user_id: str, include_revoked: bool = False) -> list[UserSession]:
        """List all sessions for a user."""
        ...

    @abstractmethod
    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions from storage.

        Returns the number of sessions cleaned up.
        """
        ...

    # ── Statistics ────────────────────────────────────────────────

    @abstractmethod
    def get_stats(self) -> dict:
        """Get user store statistics.

        Returns dict with:
            - total_users: int
            - active_users: int
            - total_sessions: int
            - active_sessions: int
            - total_storage_used: int
        """
        ...
