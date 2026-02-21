"""
SDK exception hierarchy for CortexClient.

Maps HTTP status codes to specific exception types.
"""

from __future__ import annotations


class CortexSDKError(Exception):
    """Base exception for all SDK errors."""

    def __init__(self, message: str, status_code: int = 0, body: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body or {}


class AuthenticationError(CortexSDKError):
    """401 Unauthorized — missing or invalid token."""
    pass


class ForbiddenError(CortexSDKError):
    """403 Forbidden — insufficient scope or immutable resource."""
    pass


class NotFoundError(CortexSDKError):
    """404 Not Found — resource does not exist."""
    pass


class ValidationError(CortexSDKError):
    """400 Bad Request — invalid request data."""
    pass


class RateLimitError(CortexSDKError):
    """429 Too Many Requests — rate limited."""
    pass


class ServerError(CortexSDKError):
    """5xx Server Error — unexpected server failure."""
    pass
