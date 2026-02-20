"""
UPAI RBAC — Role-Based Access Control for CaaS API.

Roles map to pre-defined scope sets. Grant tokens can include a ``role``
field which auto-resolves to the corresponding scopes, simplifying
token creation and management.

Roles:
    owner       — all 10 scopes (full control)
    admin       — all except devices:manage
    reader      — read-only (context, versions, identity, credentials)
    subscriber  — read + subscribe (for SSE consumers)
"""

from __future__ import annotations

# ── Scope constants (all 10) ──────────────────────────────────────────────

ALL_SCOPES: set[str] = {
    "context:read",
    "context:subscribe",
    "versions:read",
    "identity:read",
    "credentials:read",
    "credentials:write",
    "webhooks:manage",
    "policies:manage",
    "grants:manage",
    "devices:manage",
}

# ── Role → scope mapping ─────────────────────────────────────────────────

ROLE_SCOPES: dict[str, set[str]] = {
    "owner": set(ALL_SCOPES),
    "admin": ALL_SCOPES - {"devices:manage"},
    "reader": {
        "context:read",
        "versions:read",
        "identity:read",
        "credentials:read",
    },
    "subscriber": {
        "context:read",
        "context:subscribe",
        "identity:read",
    },
}

VALID_ROLES: set[str] = set(ROLE_SCOPES.keys())


def scopes_for_role(role: str) -> set[str]:
    """Return the scope set for a named role, or empty set if unknown."""
    return set(ROLE_SCOPES.get(role, set()))


def role_has_scope(role: str, scope: str) -> bool:
    """Check if a role includes a specific scope."""
    return scope in ROLE_SCOPES.get(role, set())


def infer_role(scopes: set[str] | list[str]) -> str:
    """Infer the best-fit role name from a set of scopes.

    Returns the most restrictive matching role, or 'custom' if no role
    matches exactly.
    """
    scope_set = set(scopes)

    # Check in order of most-restrictive → least-restrictive
    for role_name in ("subscriber", "reader", "admin", "owner"):
        if scope_set == ROLE_SCOPES[role_name]:
            return role_name
    return "custom"
