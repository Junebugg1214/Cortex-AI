"""Dashboard session authentication.

Derives a dashboard password from the identity private key via HMAC.
Issues random session tokens with a configurable TTL.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cortex.upai.identity import UPAIIdentity

# Default session TTL: 24 hours
DEFAULT_SESSION_TTL = 86400


class DashboardSessionManager:
    """Manages dashboard authentication sessions.

    The dashboard password is derived deterministically from the identity
    private key so the owner doesn't need to configure a separate secret.
    """

    def __init__(self, identity: UPAIIdentity, session_ttl: float = DEFAULT_SESSION_TTL) -> None:
        self._identity = identity
        self._session_ttl = session_ttl
        self._sessions: dict[str, float] = {}  # token -> expiry timestamp
        self._session_meta: dict[str, dict] = {}  # token -> {auth_method, provider, email}
        self._lock = threading.Lock()
        self._password = self._derive_password()
        self._csrf_secret = self._derive_csrf_secret()

    def _derive_password(self) -> str:
        """Derive a dashboard password from the identity private key."""
        pk = self._identity._private_key
        if pk is None:
            # Fallback: hash the DID (less secure, but functional for tests)
            return hashlib.sha256(self._identity.did.encode()).hexdigest()[:24]
        return hmac.new(pk, b"cortex-dashboard", hashlib.sha256).hexdigest()[:24]

    def _derive_csrf_secret(self) -> bytes:
        """Derive a CSRF secret from the identity for stateless CSRF tokens."""
        pk = self._identity._private_key or self._identity.did.encode()
        return hmac.new(pk, b"cortex-csrf-secret", hashlib.sha256).digest()

    @property
    def password(self) -> str:
        """The derived dashboard password (for display at server start)."""
        return self._password

    @property
    def csrf_secret(self) -> bytes:
        """The derived CSRF secret for CSRFProtection."""
        return self._csrf_secret

    def authenticate(self, password: str) -> str | None:
        """Validate password and return a session token, or None on failure."""
        if not hmac.compare_digest(password, self._password):
            return None
        token = secrets.token_hex(32)
        expiry = time.monotonic() + self._session_ttl
        with self._lock:
            self._cleanup()
            self._sessions[token] = expiry
        return token

    def validate(self, session_token: str) -> bool:
        """Check if a session token is valid and not expired."""
        with self._lock:
            expiry = self._sessions.get(session_token)
            if expiry is None:
                return False
            if time.monotonic() > expiry:
                del self._sessions[session_token]
                return False
            return True

    def create_oauth_session(self, provider: str, email: str, name: str = "") -> str:
        """Create a session for an OAuth-authenticated user (skips password check)."""
        token = secrets.token_hex(32)
        expiry = time.monotonic() + self._session_ttl
        with self._lock:
            self._cleanup()
            self._sessions[token] = expiry
            self._session_meta[token] = {
                "auth_method": "oauth",
                "provider": provider,
                "email": email,
                "name": name,
            }
        return token

    def get_session_meta(self, session_token: str) -> dict | None:
        """Return session metadata (auth_method, provider, email) or None."""
        with self._lock:
            return self._session_meta.get(session_token)

    def revoke(self, session_token: str) -> None:
        """Revoke a session token."""
        with self._lock:
            self._sessions.pop(session_token, None)
            self._session_meta.pop(session_token, None)

    def _cleanup(self) -> None:
        """Remove expired sessions (called under lock)."""
        now = time.monotonic()
        expired = [t for t, exp in self._sessions.items() if now > exp]
        for t in expired:
            del self._sessions[t]
