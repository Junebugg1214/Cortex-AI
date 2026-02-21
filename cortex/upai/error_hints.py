"""
Error Hints — contextual suggestions for common UPAI errors.

Provides "did you mean?" suggestions for policy names, scope names,
and other common mistakes.  Uses ``difflib.get_close_matches`` from
the standard library.

Usage::

    from cortex.upai.error_hints import hint_for_scope, hint_for_policy

    hint = hint_for_scope("context:reda")
    # → 'Did you mean "context:read"?'
"""

from __future__ import annotations

import difflib

from cortex.upai.rbac import ALL_SCOPES, VALID_ROLES

# ---------------------------------------------------------------------------
# Known values
# ---------------------------------------------------------------------------

_VALID_SCOPES: list[str] = sorted(ALL_SCOPES)
_VALID_ROLES: list[str] = sorted(VALID_ROLES)


# ---------------------------------------------------------------------------
# Hint generators
# ---------------------------------------------------------------------------

def hint_for_scope(scope: str) -> str:
    """Return a hint string for an unknown scope, or empty string."""
    matches = difflib.get_close_matches(scope, _VALID_SCOPES, n=1, cutoff=0.5)
    if matches:
        return f'Did you mean "{matches[0]}"?'
    return f"Valid scopes: {', '.join(_VALID_SCOPES)}"


def hint_for_role(role: str) -> str:
    """Return a hint string for an unknown role, or empty string."""
    matches = difflib.get_close_matches(role, _VALID_ROLES, n=1, cutoff=0.5)
    if matches:
        return f'Did you mean "{matches[0]}"?'
    return f"Valid roles: {', '.join(_VALID_ROLES)}"


def hint_for_policy(policy: str, known_policies: list[str] | None = None) -> str:
    """Return a hint for an unknown policy name."""
    if known_policies is None:
        from cortex.upai.disclosure import BUILTIN_POLICIES
        known_policies = sorted(BUILTIN_POLICIES.keys())
    matches = difflib.get_close_matches(policy, known_policies, n=1, cutoff=0.5)
    if matches:
        return f'Did you mean "{matches[0]}"?'
    return f"Available policies: {', '.join(known_policies)}"


def hint_for_insufficient_scope(required: str) -> str:
    """Return a hint listing available scopes when a scope is insufficient."""
    return f"Required scope: {required}. Valid scopes: {', '.join(_VALID_SCOPES)}"


def hint_for_invalid_token() -> str:
    """Return a hint for common token issues."""
    return (
        "Check that the token is not expired, the signature matches the "
        "server's DID, and the token includes a valid nonce."
    )


def hint_for_not_found(resource: str) -> str:
    """Return a hint for a 404 resource."""
    return f"Verify the {resource} ID is correct and the resource has not been deleted."


def enrich_error(error_dict: dict, hint: str) -> dict:
    """Add a 'hint' field to an error response dict.

    Mutates and returns *error_dict* for convenience.  If *hint* is
    empty, the dict is returned unchanged.
    """
    if hint and "error" in error_dict:
        error_dict["error"]["hint"] = hint
    return error_dict
