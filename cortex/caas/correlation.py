"""
Request correlation — unique IDs for tracing requests through the system.

Every request gets an X-Request-ID header (auto-generated or client-provided).
The ID is included in all audit entries and error responses for traceability.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

MAX_REQUEST_ID_LENGTH = 128


@dataclass
class RequestContext:
    """Context attached to each incoming request."""

    request_id: str
    method: str
    path: str
    client_ip: str
    start_time: float


def generate_request_id() -> str:
    """Generate a new unique request ID."""
    return str(uuid.uuid4())


def parse_request_id(header_value: str | None) -> str:
    """Honor a client-provided request ID if valid, otherwise generate a new one.

    Valid means non-empty, printable ASCII, and <= 128 characters.
    """
    if header_value and len(header_value) <= MAX_REQUEST_ID_LENGTH:
        # Only allow printable ASCII (space through tilde)
        if all(0x20 <= ord(c) <= 0x7E for c in header_value):
            return header_value
    return generate_request_id()
