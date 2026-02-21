"""
CaaS Security — CSRF protection, SSRF prevention, Content-Type validation.

All implementations use stdlib only:
- CSRF: HMAC-SHA256 stateless tokens
- SSRF: socket.getaddrinfo() + IP range checks
- Content-Type: header validation
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import socket
import time
import urllib.parse

# ---------------------------------------------------------------------------
# CSRF Protection
# ---------------------------------------------------------------------------

class CSRFProtection:
    """Stateless CSRF token generation and validation using HMAC-SHA256.

    Tokens are: ``base_hex:timestamp_hex``
    - base_hex = HMAC-SHA256(secret, session_token + timestamp)[:16]
    - timestamp_hex = hex(unix_timestamp)
    """

    def __init__(self, secret: bytes) -> None:
        self._secret = secret

    def generate_token(self, session_token: str) -> str:
        """Generate a CSRF token bound to the given session token."""
        ts = int(time.time())
        return self._make_token(session_token, ts)

    def validate_token(
        self,
        session_token: str,
        csrf_token: str,
        max_age: int = 3600,
    ) -> bool:
        """Validate a CSRF token. Returns True if valid."""
        if not csrf_token or ":" not in csrf_token:
            return False
        parts = csrf_token.split(":", 1)
        if len(parts) != 2:
            return False
        token_hex, ts_hex = parts
        try:
            ts = int(ts_hex, 16)
        except ValueError:
            return False
        # Check expiry
        now = int(time.time())
        if now - ts > max_age:
            return False
        # Regenerate and compare
        expected = self._make_token(session_token, ts)
        return hmac.compare_digest(csrf_token, expected)

    def _make_token(self, session_token: str, timestamp: int) -> str:
        data = f"{session_token}:{timestamp}".encode("utf-8")
        mac = hmac.new(self._secret, data, hashlib.sha256).hexdigest()[:32]
        return f"{mac}:{timestamp:x}"


# ---------------------------------------------------------------------------
# SSRF Prevention
# ---------------------------------------------------------------------------

# Private/reserved IP ranges
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),      # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),     # RFC 1918
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("100.64.0.0/10"),      # Shared address space
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
]

# Specific blocked IPs (cloud metadata endpoints)
_BLOCKED_IPS = {
    ipaddress.ip_address("169.254.169.254"),    # AWS/GCP metadata
}


def is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is private, loopback, link-local, or a cloud metadata endpoint."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # If we can't parse it, block it
    if addr in _BLOCKED_IPS:
        return True
    for network in _PRIVATE_NETWORKS:
        if addr in network:
            return True
    return False


def validate_webhook_url(url: str) -> tuple[bool, str]:
    """Validate a webhook URL is not targeting private/internal IPs.

    Returns (is_valid, error_message). If valid, error_message is empty.
    Resolves the hostname via DNS to catch DNS rebinding.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False, "Invalid URL"

    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname"

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # Resolve DNS to get actual IPs
    try:
        addr_infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False, f"Cannot resolve hostname: {hostname}"

    for family, socktype, proto, canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        if is_private_ip(ip_str):
            return False, f"URL resolves to private IP: {ip_str}"

    return True, ""


# ---------------------------------------------------------------------------
# Content-Type Validation
# ---------------------------------------------------------------------------

def require_json_content_type(content_type: str | None) -> tuple[bool, str]:
    """Validate that Content-Type indicates JSON.

    Returns (is_valid, error_message).
    Accepts: application/json, application/json; charset=utf-8, etc.
    """
    if not content_type:
        return False, "Missing Content-Type header"
    ct = content_type.lower().strip()
    if ct.startswith("application/json"):
        return True, ""
    return False, f"Expected Content-Type: application/json, got: {content_type}"
