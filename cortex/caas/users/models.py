"""
User and session data models for multi-user authentication.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

# Email validation regex - RFC 5322 simplified
_EMAIL_REGEX = re.compile(
    r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?'
    r'(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$'
)


class AccountStatus(str, Enum):
    """User account status."""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING_VERIFICATION = "pending_verification"


class UserRole(str, Enum):
    """User roles for access control."""
    USER = "user"
    ADMIN = "admin"


@dataclass
class User:
    """Represents a registered user account."""

    user_id: str
    email: str
    password_hash: str
    display_name: str = ""
    role: UserRole = UserRole.USER
    email_verified: bool = False
    storage_quota: int = 1_073_741_824  # 1GB default
    storage_used: int = 0
    created_at: str = ""
    updated_at: str = ""
    last_login_at: Optional[str] = None
    account_status: AccountStatus = AccountStatus.ACTIVE

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if isinstance(self.role, str):
            self.role = UserRole(self.role)
        if isinstance(self.account_status, str):
            self.account_status = AccountStatus(self.account_status)

    @property
    def storage_remaining(self) -> int:
        """Bytes remaining in user's quota."""
        return max(0, self.storage_quota - self.storage_used)

    @property
    def storage_usage_percent(self) -> float:
        """Percentage of quota used."""
        if self.storage_quota <= 0:
            return 100.0
        return min(100.0, (self.storage_used / self.storage_quota) * 100)

    def can_upload(self, size_bytes: int) -> bool:
        """Check if user can upload a file of given size."""
        return self.storage_used + size_bytes <= self.storage_quota

    def to_public_dict(self) -> dict:
        """Return user data safe for API responses (no password hash)."""
        return {
            "user_id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role.value,
            "email_verified": self.email_verified,
            "storage_quota": self.storage_quota,
            "storage_used": self.storage_used,
            "storage_remaining": self.storage_remaining,
            "storage_usage_percent": round(self.storage_usage_percent, 2),
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
            "account_status": self.account_status.value,
        }


@dataclass
class UserSession:
    """Represents an active user session."""

    session_id: str
    user_id: str
    created_at: str = ""
    expires_at: str = ""
    revoked: bool = False
    auth_method: str = "password"  # password, oauth, api_key
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        if not self.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.expires_at.replace('Z', '+00:00'))
            return datetime.now(timezone.utc) > expires
        except (ValueError, TypeError):
            return True

    @property
    def is_valid(self) -> bool:
        """Check if session is valid (not revoked, not expired)."""
        return not self.revoked and not self.is_expired


@dataclass
class SignupRequest:
    """Data for user signup validation."""

    email: str
    password: str
    display_name: str = ""

    def validate(self) -> list[str]:
        """Return list of validation errors, empty if valid."""
        errors = []

        # Email validation
        email = self.email.strip().lower()
        if not email:
            errors.append("Email is required")
        elif len(email) > 254:
            errors.append("Email too long")
        elif not _EMAIL_REGEX.match(email):
            errors.append("Invalid email format")

        # Password validation
        if len(self.password) < 8:
            errors.append("Password must be at least 8 characters")
        elif len(self.password) > 128:
            errors.append("Password too long")

        # Display name validation (optional but has limits)
        if self.display_name and len(self.display_name) > 100:
            errors.append("Display name too long (max 100 characters)")

        return errors

    @property
    def normalized_email(self) -> str:
        """Return normalized email (lowercase, stripped)."""
        return self.email.strip().lower()


@dataclass
class LoginRequest:
    """Data for user login validation."""

    email: str
    password: str

    def validate(self) -> list[str]:
        """Return list of validation errors, empty if valid."""
        errors = []
        if not self.email.strip():
            errors.append("Email is required")
        if not self.password:
            errors.append("Password is required")
        return errors

    @property
    def normalized_email(self) -> str:
        """Return normalized email (lowercase, stripped)."""
        return self.email.strip().lower()
