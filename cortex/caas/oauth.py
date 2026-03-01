"""OAuth 2.0 / OIDC integration for CaaS dashboard.

Supports Google and GitHub as providers via authorization code flow with PKCE.
All helpers use stdlib only (no external OAuth libraries).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

@dataclass
class OAuthProviderConfig:
    """Configuration for an OAuth 2.0 / OIDC provider."""

    name: str
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scopes: list[str] = field(default_factory=list)


GOOGLE_ENDPOINTS = {
    "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_url": "https://oauth2.googleapis.com/token",
    "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
    "scopes": ["openid", "email", "profile"],
}

GITHUB_ENDPOINTS = {
    "authorize_url": "https://github.com/login/oauth/authorize",
    "token_url": "https://github.com/login/oauth/access_token",
    "userinfo_url": "https://api.github.com/user",
    "scopes": ["read:user", "user:email"],
}

PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "google": GOOGLE_ENDPOINTS,
    "github": GITHUB_ENDPOINTS,
}


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def generate_code_verifier(length: int = 64) -> str:
    """Generate a PKCE code verifier (URL-safe, no padding)."""
    raw = secrets.token_bytes(length)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")[:128]


def generate_code_challenge(verifier: str) -> str:
    """Generate S256 code challenge from a verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------------------
# State parameter (CSRF protection)
# ---------------------------------------------------------------------------

def generate_state(secret: bytes, provider: str, nonce: str) -> str:
    """Create HMAC-signed state: ``provider:nonce:timestamp`` encoded as base64url."""
    ts = str(int(time.time()))
    payload = f"{provider}:{nonce}:{ts}"
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:16]
    state = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(state.encode()).rstrip(b"=").decode("ascii")


def validate_state(
    secret: bytes, state_str: str, max_age: int = 600
) -> tuple[str, str] | None:
    """Validate a state parameter. Returns ``(provider, nonce)`` or ``None``."""
    try:
        # Re-pad base64url
        padded = state_str + "=" * (-len(state_str) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode()
        parts = decoded.split(":")
        if len(parts) != 4:
            return None
        provider, nonce, ts, sig = parts
        payload = f"{provider}:{nonce}:{ts}"
        expected = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        if time.time() - int(ts) > max_age:
            return None
        return provider, nonce
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Token exchange (urllib.request)
# ---------------------------------------------------------------------------

def exchange_code_for_token(
    provider: OAuthProviderConfig,
    code: str,
    redirect_uri: str,
    code_verifier: str | None = None,
) -> dict | None:
    """POST to token endpoint. Returns parsed JSON or ``None``."""
    params: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": provider.client_id,
        "client_secret": provider.client_secret,
    }
    if code_verifier:
        params["code_verifier"] = code_verifier

    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(provider.token_url, data=data, method="POST")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            ct = resp.headers.get("Content-Type", "")
            if "json" in ct:
                return json.loads(body)
            # GitHub may return form-encoded
            return dict(urllib.parse.parse_qsl(body))
    except Exception:
        return None


def fetch_userinfo(
    provider: OAuthProviderConfig, access_token: str
) -> dict | None:
    """GET userinfo endpoint. For GitHub, also fetches primary email."""
    req = urllib.request.Request(provider.userinfo_url)
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            info = json.loads(resp.read().decode())
    except Exception:
        return None

    # GitHub doesn't return email in /user if it's private; fetch from /user/emails
    if provider.name == "github" and not info.get("email"):
        try:
            email_req = urllib.request.Request("https://api.github.com/user/emails")
            email_req.add_header("Authorization", f"Bearer {access_token}")
            email_req.add_header("Accept", "application/json")
            with urllib.request.urlopen(email_req, timeout=10) as email_resp:
                emails = json.loads(email_resp.read().decode())
            for e in emails:
                if e.get("primary") and e.get("verified"):
                    info["email"] = e["email"]
                    break
        except Exception:
            pass

    return info


# ---------------------------------------------------------------------------
# External token validation
# ---------------------------------------------------------------------------

def validate_google_id_token(id_token: str, client_id: str) -> dict | None:
    """Validate Google ID token via tokeninfo endpoint. Returns claims or ``None``."""
    url = f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(id_token)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            claims = json.loads(resp.read().decode())
            if claims.get("aud") != client_id:
                return None
            return claims
    except Exception:
        return None


def validate_github_token(access_token: str) -> dict | None:
    """Validate GitHub access token via user API. Returns user info or ``None``."""
    req = urllib.request.Request("https://api.github.com/user")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# OAuthManager
# ---------------------------------------------------------------------------

class OAuthManager:
    """Manages OAuth flows for the CaaS dashboard.

    Stores pending authorization flows (code verifiers keyed by nonce)
    and orchestrates the authorize → callback cycle.
    """

    MAX_PENDING = 50

    def __init__(
        self,
        providers: dict[str, OAuthProviderConfig],
        state_secret: bytes,
        redirect_base: str,
        allowed_emails: set[str] | None = None,
    ) -> None:
        self._providers = providers
        self._state_secret = state_secret
        self._redirect_base = redirect_base.rstrip("/")
        self._allowed_emails = allowed_emails
        self._pending: dict[str, dict[str, str]] = {}  # nonce → {verifier, provider}

    @property
    def enabled(self) -> bool:
        return len(self._providers) > 0

    @property
    def provider_names(self) -> list[str]:
        return list(self._providers.keys())

    def get_authorization_url(self, provider_name: str) -> tuple[str, str] | None:
        """Build authorization URL with PKCE + state.

        Returns ``(url, nonce)`` or ``None`` if provider unknown.
        """
        provider = self._providers.get(provider_name)
        if provider is None:
            return None

        nonce = secrets.token_hex(16)
        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier)
        state = generate_state(self._state_secret, provider_name, nonce)

        self._cleanup_flows()
        self._pending[nonce] = {"verifier": verifier, "provider": provider_name}

        redirect_uri = f"{self._redirect_base}/dashboard/oauth/callback"

        params = {
            "client_id": provider.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(provider.scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        # Google-specific: prompt=consent for refresh token
        if provider_name == "google":
            params["access_type"] = "offline"

        url = f"{provider.authorize_url}?{urllib.parse.urlencode(params)}"
        return url, nonce

    def handle_callback(
        self, code: str, state: str
    ) -> tuple[dict | None, str]:
        """Handle OAuth callback.

        Returns ``(userinfo, provider_name)`` on success or
        ``(None, error_message)`` on failure.
        """
        result = validate_state(self._state_secret, state)
        if result is None:
            return None, "invalid_state"

        provider_name, nonce = result
        flow = self._pending.pop(nonce, None)
        if flow is None:
            return None, "unknown_flow"

        provider = self._providers.get(provider_name)
        if provider is None:
            return None, "unknown_provider"

        redirect_uri = f"{self._redirect_base}/dashboard/oauth/callback"
        token_data = exchange_code_for_token(
            provider, code, redirect_uri, flow["verifier"]
        )
        if token_data is None:
            return None, "token_exchange_failed"

        access_token = token_data.get("access_token")
        if not access_token:
            return None, "no_access_token"

        userinfo = fetch_userinfo(provider, access_token)
        if userinfo is None:
            return None, "userinfo_failed"

        # Normalize email
        email = userinfo.get("email", "")
        if not email:
            return None, "no_email"

        if not self.is_email_allowed(email):
            return None, "email_not_allowed"

        return userinfo, provider_name

    def is_email_allowed(self, email: str) -> bool:
        """Check if email is in the allowlist. ``None`` allowlist = unrestricted."""
        if self._allowed_emails is None:
            return True
        return email.lower() in {e.lower() for e in self._allowed_emails}

    def _cleanup_flows(self) -> None:
        """Cap pending flows to prevent DoS."""
        while len(self._pending) > self.MAX_PENDING:
            # Remove oldest (first inserted)
            oldest = next(iter(self._pending))
            del self._pending[oldest]
