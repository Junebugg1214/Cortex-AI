"""
Cortex SDK — Python client for the CaaS API.

Usage::

    from cortex_sdk import CortexClient

    client = CortexClient(base_url="http://localhost:8421", token="...")
    info = client.info()
"""

from .client import CortexClient
from .exceptions import (
    AuthenticationError,
    CortexSDKError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)

__version__ = "1.3.0"

__all__ = [
    "CortexClient",
    "CortexSDKError",
    "AuthenticationError",
    "ForbiddenError",
    "NotFoundError",
    "RateLimitError",
    "ServerError",
    "ValidationError",
]
