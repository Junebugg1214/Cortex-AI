"""
Path parameter validation for the CaaS API.

All path params (node_id, grant_id, webhook_id, version_id, etc.) are extracted
via string slicing with no validation. This module provides validation functions
to block null bytes, path traversal, and extreme lengths.
"""

from __future__ import annotations

import re

# Maximum allowed length for any path parameter
MAX_PATH_PARAM_LEN = 256

# General safe-id pattern: alphanumeric + common separators
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9._:\-]{1,256}$")

# UUID4 pattern (grant_id, webhook_id)
_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Hex32 pattern (version_id — 32-char hex)
_HEX32_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)

# Policy name pattern: alphanumeric + hyphen + underscore
_POLICY_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def validate_path_param(value: str) -> tuple[bool, str]:
    """Validate a path parameter for basic safety.

    Returns (is_valid, error_message).
    """
    if not value:
        return False, "Path parameter must not be empty"
    if "\x00" in value:
        return False, "Path parameter must not contain null bytes"
    if "/" in value:
        return False, "Path parameter must not contain '/'"
    if ".." in value:
        return False, "Path parameter must not contain '..'"
    if len(value) > MAX_PATH_PARAM_LEN:
        return False, f"Path parameter exceeds maximum length ({MAX_PATH_PARAM_LEN})"
    return True, ""


def is_valid_safe_id(value: str) -> bool:
    """Check if value matches the safe-id pattern."""
    return bool(_SAFE_ID_RE.match(value))


def validate_node_id(value: str) -> tuple[bool, str]:
    """Validate a node_id — safe string."""
    ok, msg = validate_path_param(value)
    if not ok:
        return ok, msg
    if not is_valid_safe_id(value):
        return False, "Invalid node_id format"
    return True, ""


def validate_grant_id(value: str) -> tuple[bool, str]:
    """Validate a grant_id — UUID4 format."""
    ok, msg = validate_path_param(value)
    if not ok:
        return ok, msg
    if not _UUID4_RE.match(value):
        return False, "Invalid grant_id format (expected UUID)"
    return True, ""


def validate_webhook_id(value: str) -> tuple[bool, str]:
    """Validate a webhook_id — UUID4 format."""
    ok, msg = validate_path_param(value)
    if not ok:
        return ok, msg
    if not _UUID4_RE.match(value):
        return False, "Invalid webhook_id format (expected UUID)"
    return True, ""


def validate_version_id(value: str) -> tuple[bool, str]:
    """Validate a version_id — 32-char hex."""
    ok, msg = validate_path_param(value)
    if not ok:
        return ok, msg
    if not _HEX32_RE.match(value):
        return False, "Invalid version_id format (expected 32-char hex)"
    return True, ""


def validate_policy_name(value: str) -> tuple[bool, str]:
    """Validate a policy_name — alphanumeric + hyphen + underscore."""
    ok, msg = validate_path_param(value)
    if not ok:
        return ok, msg
    if not _POLICY_NAME_RE.match(value):
        return False, "Invalid policy name format"
    return True, ""
