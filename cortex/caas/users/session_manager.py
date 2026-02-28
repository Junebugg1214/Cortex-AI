"""
Multi-user session management for Cortex.

Extends the base DashboardSessionManager to support multiple users
with email/password authentication, while maintaining backward
compatibility with the admin (identity-based) authentication.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional, Tuple

from cortex.caas.users.models import LoginRequest, SignupRequest, User, UserSession
from cortex.caas.users.password import hash_password, verify_password
from cortex.caas.users.sqlite_store import SqliteUserStore, generate_session_id

if TYPE_CHECKING:
    from cortex.upai.identity import UPAIIdentity

# Default session TTL: 7 days for users, 24 hours for admin
DEFAULT_USER_SESSION_TTL = 604800  # 7 days
DEFAULT_ADMIN_SESSION_TTL = 86400  # 24 hours

# Rate limiting defaults
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300  # 5 minutes


class RateLimiter:
    """Simple in-memory rate limiter for login attempts."""

    def __init__(
        self,
        max_attempts: int = MAX_LOGIN_ATTEMPTS,
        lockout_seconds: int = LOGIN_LOCKOUT_SECONDS,
    ) -> None:
        self._max_attempts = max_attempts
        self._lockout_seconds = lockout_seconds
        self._attempts: dict[str, list[float]] = {}  # key -> list of timestamps
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        """Check if an action is allowed for the given key."""
        now = time.monotonic()
        with self._lock:
            attempts = self._attempts.get(key, [])
            # Remove old attempts outside the lockout window
            attempts = [t for t in attempts if now - t < self._lockout_seconds]
            self._attempts[key] = attempts
            return len(attempts) < self._max_attempts

    def record_attempt(self, key: str) -> None:
        """Record a failed attempt for the given key."""
        now = time.monotonic()
        with self._lock:
            if key not in self._attempts:
                self._attempts[key] = []
            self._attempts[key].append(now)
            # Cleanup old entries periodically
            if len(self._attempts) > 10000:
                self._cleanup()

    def clear(self, key: str) -> None:
        """Clear attempts for a key (called on successful login)."""
        with self._lock:
            self._attempts.pop(key, None)

    def _cleanup(self) -> None:
        """Remove old entries (called under lock)."""
        now = time.monotonic()
        expired = []
        for key, attempts in self._attempts.items():
            fresh = [t for t in attempts if now - t < self._lockout_seconds]
            if not fresh:
                expired.append(key)
            else:
                self._attempts[key] = fresh
        for key in expired:
            del self._attempts[key]

    def get_remaining_lockout(self, key: str) -> int:
        """Get remaining lockout time in seconds, 0 if not locked."""
        now = time.monotonic()
        with self._lock:
            attempts = self._attempts.get(key, [])
            if len(attempts) < self._max_attempts:
                return 0
            oldest = min(attempts) if attempts else now
            remaining = self._lockout_seconds - (now - oldest)
            return max(0, int(remaining))


class MultiUserSessionManager:
    """
    Manages sessions for both admin (identity-based) and regular users.

    Admin sessions use the existing DashboardSessionManager pattern.
    User sessions are stored in the database via SqliteUserStore.
    """

    def __init__(
        self,
        identity: UPAIIdentity,
        user_store: SqliteUserStore,
        admin_session_ttl: float = DEFAULT_ADMIN_SESSION_TTL,
        user_session_ttl: float = DEFAULT_USER_SESSION_TTL,
    ) -> None:
        self._identity = identity
        self._user_store = user_store
        self._admin_session_ttl = admin_session_ttl
        self._user_session_ttl = user_session_ttl

        # Admin sessions (in-memory, same as DashboardSessionManager)
        self._admin_sessions: dict[str, float] = {}  # token -> expiry
        self._admin_lock = threading.Lock()

        # Derived admin password from identity
        self._admin_password = self._derive_admin_password()
        self._csrf_secret = self._derive_csrf_secret()

        # Rate limiting
        self._rate_limiter = RateLimiter()

    def _derive_admin_password(self) -> str:
        """Derive admin password from the identity private key."""
        pk = self._identity._private_key
        if pk is None:
            return hashlib.sha256(self._identity.did.encode()).hexdigest()[:24]
        return hmac.new(pk, b"cortex-dashboard", hashlib.sha256).hexdigest()[:24]

    def _derive_csrf_secret(self) -> bytes:
        """Derive a CSRF secret from the identity."""
        pk = self._identity._private_key or self._identity.did.encode()
        return hmac.new(pk, b"cortex-csrf-secret", hashlib.sha256).digest()

    @property
    def admin_password(self) -> str:
        """The derived admin password (for display at server start)."""
        return self._admin_password

    @property
    def csrf_secret(self) -> bytes:
        """The derived CSRF secret for CSRFProtection."""
        return self._csrf_secret

    # ── Admin authentication ──────────────────────────────────────

    def authenticate_admin(self, password: str) -> Optional[str]:
        """Authenticate with admin password, return session token or None."""
        if not hmac.compare_digest(password, self._admin_password):
            return None

        token = secrets.token_hex(32)
        expiry = time.monotonic() + self._admin_session_ttl

        with self._admin_lock:
            self._cleanup_admin_sessions()
            self._admin_sessions[token] = expiry

        return token

    def validate_admin_session(self, session_token: str) -> bool:
        """Check if an admin session token is valid."""
        with self._admin_lock:
            expiry = self._admin_sessions.get(session_token)
            if expiry is None:
                return False
            if time.monotonic() > expiry:
                del self._admin_sessions[session_token]
                return False
            return True

    def revoke_admin_session(self, session_token: str) -> None:
        """Revoke an admin session token."""
        with self._admin_lock:
            self._admin_sessions.pop(session_token, None)

    def _cleanup_admin_sessions(self) -> None:
        """Remove expired admin sessions (called under lock)."""
        now = time.monotonic()
        expired = [t for t, exp in self._admin_sessions.items() if now > exp]
        for t in expired:
            del self._admin_sessions[t]

    # ── User signup ───────────────────────────────────────────────

    def signup(self, request: SignupRequest) -> Tuple[Optional[User], list[str]]:
        """
        Create a new user account.

        Returns:
            Tuple of (User or None, list of error messages)
        """
        # Validate request
        errors = request.validate()
        if errors:
            return None, errors

        # Check if email already exists
        existing = self._user_store.get_user_by_email(request.normalized_email)
        if existing:
            return None, ["Email already registered"]

        # Hash password and create user
        password_hash = hash_password(request.password)
        user = User(
            user_id="",  # Will be generated
            email=request.normalized_email,
            password_hash=password_hash,
            display_name=request.display_name.strip() or request.normalized_email.split("@")[0],
        )

        try:
            created_user = self._user_store.create_user(user)
            return created_user, []
        except ValueError as e:
            return None, [str(e)]

    # ── User login ────────────────────────────────────────────────

    def login(
        self,
        request: LoginRequest,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[User], list[str]]:
        """
        Authenticate a user with email/password.

        Returns:
            Tuple of (session_token or None, User or None, list of error messages)
        """
        # Validate request
        errors = request.validate()
        if errors:
            return None, None, errors

        # Rate limiting check
        rate_key = f"login:{request.normalized_email}"
        if not self._rate_limiter.is_allowed(rate_key):
            remaining = self._rate_limiter.get_remaining_lockout(rate_key)
            # Always show at least 1 second to avoid confusing "0 seconds" message
            remaining = max(1, remaining)
            return None, None, [f"Too many attempts. Try again in {remaining} seconds."]

        # Find user
        user = self._user_store.get_user_by_email(request.normalized_email)
        if not user:
            self._rate_limiter.record_attempt(rate_key)
            return None, None, ["Invalid email or password"]

        # Check account status
        if user.account_status.value != "active":
            return None, None, [f"Account is {user.account_status.value}"]

        # Verify password
        if not verify_password(request.password, user.password_hash):
            self._rate_limiter.record_attempt(rate_key)
            return None, None, ["Invalid email or password"]

        # Clear rate limit on success
        self._rate_limiter.clear(rate_key)

        # Create session
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._user_session_ttl)
        session = UserSession(
            session_id=generate_session_id(),
            user_id=user.user_id,
            expires_at=expires_at.isoformat(),
            auth_method="password",
            ip_address=ip_address,
            user_agent=user_agent,
        )

        created_session = self._user_store.create_session(session)

        # Update last login
        self._user_store.update_last_login(user.user_id)

        return created_session.session_id, user, []

    # ── User session validation ───────────────────────────────────

    def validate_user_session(self, session_token: str) -> Optional[User]:
        """
        Validate a user session token.

        Returns:
            User if session is valid, None otherwise
        """
        session = self._user_store.get_session(session_token)
        if not session:
            return None

        if not session.is_valid:
            return None

        user = self._user_store.get_user_by_id(session.user_id)
        if not user:
            return None

        if user.account_status.value != "active":
            return None

        return user

    def logout_user(self, session_token: str) -> bool:
        """Revoke a user session token."""
        return self._user_store.revoke_session(session_token)

    def logout_user_all_sessions(self, user_id: str) -> int:
        """Revoke all sessions for a user."""
        return self._user_store.revoke_user_sessions(user_id)

    # ── Combined session validation ───────────────────────────────

    def validate_session(
        self, session_token: str
    ) -> Tuple[bool, Optional[str], Optional[User]]:
        """
        Validate any session token (admin or user).

        Returns:
            Tuple of (is_valid, session_type, user_or_none)
            session_type is "admin" or "user" or None
        """
        # Try admin session first
        if self.validate_admin_session(session_token):
            return True, "admin", None

        # Try user session
        user = self.validate_user_session(session_token)
        if user:
            return True, "user", user

        return False, None, None

    # ── Utilities ─────────────────────────────────────────────────

    def get_user(self, user_id: str) -> Optional[User]:
        """Get a user by ID."""
        return self._user_store.get_user_by_id(user_id)

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get a user by email."""
        return self._user_store.get_user_by_email(email)

    def update_user(self, user: User) -> bool:
        """Update a user."""
        return self._user_store.update_user(user)

    def cleanup_sessions(self) -> int:
        """Cleanup expired sessions."""
        with self._admin_lock:
            self._cleanup_admin_sessions()
        return self._user_store.cleanup_expired_sessions()

    def get_stats(self) -> dict:
        """Get session manager statistics."""
        user_stats = self._user_store.get_stats()
        with self._admin_lock:
            self._cleanup_admin_sessions()
            admin_sessions = len(self._admin_sessions)

        return {
            **user_stats,
            "admin_sessions": admin_sessions,
        }
