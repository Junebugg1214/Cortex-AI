"""
HTTP Caching — ETags and Cache-Control for CaaS API responses.

Uses weak ETags (W/"...") derived from SHA-256 of the response body.
Cache-Control profiles are mapped by path pattern.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass
class CacheProfile:
    """Cache configuration for a route pattern."""
    max_age: int = 0
    no_cache: bool = False
    no_store: bool = False
    immutable: bool = False

    def to_header(self) -> str:
        parts = []
        if self.no_store:
            return "no-store"
        if self.no_cache:
            parts.append("no-cache")
        if self.max_age > 0:
            parts.append(f"max-age={self.max_age}")
        if self.immutable:
            parts.append("immutable")
        return ", ".join(parts) if parts else "no-store"


# Path pattern → cache profile
CACHE_PROFILES: list[tuple[re.Pattern, CacheProfile]] = [
    (re.compile(r"^/identity$"), CacheProfile(max_age=300)),
    (re.compile(r"^/\.well-known/upai-configuration$"), CacheProfile(max_age=300)),
    (re.compile(r"^/health$"), CacheProfile(max_age=10)),
    (re.compile(r"^/context(/.*)?$"), CacheProfile(no_cache=True)),
    (re.compile(r"^/credentials(/.*)?$"), CacheProfile(no_cache=True)),
    (re.compile(r"^/versions(/.*)?$"), CacheProfile(no_cache=True)),
]


def get_cache_profile(path: str) -> CacheProfile:
    """Look up cache profile for a given path."""
    for pattern, profile in CACHE_PROFILES:
        if pattern.match(path):
            return profile
    return CacheProfile(no_store=True)


def generate_etag(body: bytes) -> str:
    """Generate a weak ETag from the response body SHA-256 (first 16 hex chars)."""
    digest = hashlib.sha256(body).hexdigest()[:16]
    return f'W/"{digest}"'


def check_if_none_match(if_none_match: str, current_etag: str) -> bool:
    """Check If-None-Match header against current ETag. Returns True if match (304)."""
    if not if_none_match or not current_etag:
        return False

    # Handle wildcard
    if if_none_match.strip() == "*":
        return True

    # Handle comma-separated list of ETags
    for etag in if_none_match.split(","):
        etag = etag.strip()
        if etag == current_etag:
            return True
        # Weak comparison: strip W/ prefix for comparison
        if etag.startswith('W/'):
            etag_val = etag[2:]
        else:
            etag_val = etag
        if current_etag.startswith('W/'):
            current_val = current_etag[2:]
        else:
            current_val = current_etag
        if etag_val == current_val:
            return True

    return False
