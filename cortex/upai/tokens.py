"""
UPAI Grant Tokens — Signed, scoped access tokens for CaaS API.

Three-part Ed25519 format: base64url(header).base64url(payload).base64url(signature)
Similar to JWT but with Ed25519 and UPAI-specific claims.
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from cortex.upai.identity import (
    UPAIIdentity,
    _base64url_encode,
    _base64url_decode,
)

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Scope constants
# ---------------------------------------------------------------------------

SCOPE_CONTEXT_READ = "context:read"
SCOPE_CONTEXT_WRITE = "context:write"
SCOPE_CONTEXT_SUBSCRIBE = "context:subscribe"
SCOPE_VERSIONS_READ = "versions:read"
SCOPE_IDENTITY_READ = "identity:read"
SCOPE_CREDENTIALS_READ = "credentials:read"
SCOPE_CREDENTIALS_WRITE = "credentials:write"
SCOPE_WEBHOOKS_MANAGE = "webhooks:manage"
SCOPE_POLICIES_MANAGE = "policies:manage"
SCOPE_GRANTS_MANAGE = "grants:manage"
SCOPE_DEVICES_MANAGE = "devices:manage"

VALID_SCOPES: set[str] = {
    SCOPE_CONTEXT_READ,
    SCOPE_CONTEXT_WRITE,
    SCOPE_CONTEXT_SUBSCRIBE,
    SCOPE_VERSIONS_READ,
    SCOPE_IDENTITY_READ,
    SCOPE_CREDENTIALS_READ,
    SCOPE_CREDENTIALS_WRITE,
    SCOPE_WEBHOOKS_MANAGE,
    SCOPE_POLICIES_MANAGE,
    SCOPE_GRANTS_MANAGE,
    SCOPE_DEVICES_MANAGE,
}

DEFAULT_SCOPES: list[str] = [SCOPE_CONTEXT_READ, SCOPE_VERSIONS_READ, SCOPE_IDENTITY_READ]


# ---------------------------------------------------------------------------
# GrantToken
# ---------------------------------------------------------------------------

@dataclass
class GrantToken:
    """A signed grant token for CaaS API access."""

    grant_id: str         # uuid4
    subject_did: str      # identity granting access
    issuer_did: str       # same as subject (self-issued)
    audience: str         # platform name/URL
    policy: str           # disclosure policy name
    scopes: list[str]     # ["context:read", "versions:read", ...]
    issued_at: str        # ISO-8601
    expires_at: str       # ISO-8601
    not_before: str = ""  # optional
    role: str = ""        # optional RBAC role (owner, admin, reader, subscriber)

    @classmethod
    def create(
        cls,
        identity: UPAIIdentity,
        audience: str,
        policy: str = "professional",
        scopes: list[str] | None = None,
        ttl_hours: int = 24,
    ) -> GrantToken:
        """Create a new grant token."""
        now = datetime.now(timezone.utc)
        return cls(
            grant_id=str(uuid.uuid4()),
            subject_did=identity.did,
            issuer_did=identity.did,
            audience=audience,
            policy=policy,
            scopes=list(scopes) if scopes else list(DEFAULT_SCOPES),
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(hours=ttl_hours)).isoformat(),
        )

    def to_dict(self) -> dict:
        d = {
            "grant_id": self.grant_id,
            "subject_did": self.subject_did,
            "issuer_did": self.issuer_did,
            "audience": self.audience,
            "policy": self.policy,
            "scopes": list(self.scopes),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "not_before": self.not_before,
        }
        if self.role:
            d["role"] = self.role
        return d

    @classmethod
    def from_dict(cls, d: dict) -> GrantToken:
        return cls(
            grant_id=d["grant_id"],
            subject_did=d["subject_did"],
            issuer_did=d["issuer_did"],
            audience=d["audience"],
            policy=d["policy"],
            scopes=list(d["scopes"]),
            issued_at=d["issued_at"],
            expires_at=d["expires_at"],
            not_before=d.get("not_before", ""),
            role=d.get("role", ""),
        )

    def sign(self, identity: UPAIIdentity) -> str:
        """Sign token and return three-part string: header.payload.signature."""
        alg = "Ed25519" if identity._key_type == "ed25519" else "HMAC-SHA256"
        header = {"alg": alg, "typ": "UPAI-Grant"}

        header_b64 = _base64url_encode(
            json.dumps(header, sort_keys=True, ensure_ascii=False).encode("utf-8")
        )
        payload_b64 = _base64url_encode(
            json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False).encode("utf-8")
        )

        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        sig = identity.sign(signing_input)
        sig_b64url = _base64url_encode(base64.b64decode(sig))

        return f"{header_b64}.{payload_b64}.{sig_b64url}"

    @classmethod
    def decode(cls, token_str: str) -> GrantToken:
        """Decode token without verification. Returns the GrantToken payload."""
        parts = token_str.split(".")
        if len(parts) != 3:
            raise ValueError(f"Expected 3 parts, got {len(parts)}")
        payload = json.loads(_base64url_decode(parts[1]))
        return cls.from_dict(payload)

    @classmethod
    def verify_and_decode(
        cls,
        token_str: str,
        public_key_b64: str,
        expected_audience: str = "",
        clock_skew: int = 60,
    ) -> tuple[GrantToken | None, str]:
        """Verify signature + expiry + audience, then decode.

        Returns (token, error_message). token is None on failure.
        """
        parts = token_str.split(".")
        if len(parts) != 3:
            return None, "malformed token: expected 3 parts"

        header_b64, payload_b64, sig_b64url = parts

        # Decode header to determine algorithm
        try:
            header = json.loads(_base64url_decode(header_b64))
        except Exception:
            return None, "malformed header"

        try:
            payload = json.loads(_base64url_decode(payload_b64))
        except Exception:
            return None, "malformed payload"

        # Verify signature
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        sig_bytes = _base64url_decode(sig_b64url)
        sig_b64_standard = base64.b64encode(sig_bytes).decode("ascii")

        alg = header.get("alg", "Ed25519")
        key_type = "ed25519" if alg == "Ed25519" else "sha256"

        if not UPAIIdentity.verify(
            signing_input, sig_b64_standard, public_key_b64, key_type=key_type
        ):
            return None, "invalid signature"

        # Parse token
        try:
            token = cls.from_dict(payload)
        except (KeyError, TypeError) as e:
            return None, f"invalid payload: {e}"

        # Check expiry
        now = datetime.now(timezone.utc)
        if token.expires_at:
            exp = datetime.fromisoformat(token.expires_at)
            if now.timestamp() > exp.timestamp() + clock_skew:
                return None, "token expired"

        # Check not_before
        if token.not_before:
            nbf = datetime.fromisoformat(token.not_before)
            if now.timestamp() < nbf.timestamp() - clock_skew:
                return None, "token not yet valid"

        # Check audience
        if expected_audience and token.audience != expected_audience:
            return None, f"audience mismatch: expected {expected_audience!r}, got {token.audience!r}"

        return token, ""

    def is_expired(self, clock_skew: int = 60) -> bool:
        """Check if token is expired (with optional clock skew)."""
        if not self.expires_at:
            return False
        now = datetime.now(timezone.utc)
        exp = datetime.fromisoformat(self.expires_at)
        return now.timestamp() > exp.timestamp() + clock_skew

    def has_scope(self, scope: str) -> bool:
        """Check if token has a specific scope."""
        return scope in self.scopes
