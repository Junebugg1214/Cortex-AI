"""
Multi-user authentication and authorization for Cortex CaaS.

This module provides:
- User signup/login with email/password
- Per-user isolated knowledge graphs
- Storage quotas and usage tracking
- Session management for both admin and users
"""

from cortex.caas.users.models import (
    AccountStatus,
    LoginRequest,
    SignupRequest,
    User,
    UserRole,
    UserSession,
)
from cortex.caas.users.password import (
    get_hasher_info,
    get_password_hasher,
    hash_password,
    verify_password,
)
from cortex.caas.users.store import AbstractUserStore
from cortex.caas.users.sqlite_store import SqliteUserStore
from cortex.caas.users.session_manager import MultiUserSessionManager
from cortex.caas.users.graph_resolver import UserGraphResolver

__all__ = [
    # Models
    "User",
    "UserSession",
    "UserRole",
    "AccountStatus",
    "SignupRequest",
    "LoginRequest",
    # Password
    "hash_password",
    "verify_password",
    "get_password_hasher",
    "get_hasher_info",
    # Stores
    "AbstractUserStore",
    "SqliteUserStore",
    # Session management
    "MultiUserSessionManager",
    # Graph resolution
    "UserGraphResolver",
]
