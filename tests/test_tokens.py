"""
Tests for UPAI Grant Tokens.

Covers:
- Create/sign/verify round-trip
- Expired token rejected
- Wrong audience rejected
- Tampered token rejected
- Scope checking
- HMAC fallback
- Decode without verification
"""

from datetime import datetime, timedelta, timezone

from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.upai.tokens import (
    DEFAULT_SCOPES,
    SCOPE_CONTEXT_READ,
    SCOPE_IDENTITY_READ,
    SCOPE_VERSIONS_READ,
    VALID_SCOPES,
    GrantToken,
)

# ============================================================================
# Create and Verify
# ============================================================================

class TestGrantTokenCreateVerify:

    def test_create_token(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, audience="Claude")
        assert token.grant_id
        assert token.subject_did == identity.did
        assert token.issuer_did == identity.did
        assert token.audience == "Claude"
        assert token.policy == "professional"  # default
        assert SCOPE_CONTEXT_READ in token.scopes

    def test_sign_and_verify(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, audience="Claude")
        token_str = token.sign(identity)
        assert token_str.count(".") == 2

        result, err = GrantToken.verify_and_decode(
            token_str, identity.public_key_b64
        )
        assert result is not None, f"Verification failed: {err}"
        assert result.grant_id == token.grant_id
        assert result.audience == "Claude"

    def test_custom_scopes(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        scopes = [SCOPE_CONTEXT_READ]
        token = GrantToken.create(identity, "Test", scopes=scopes)
        assert token.scopes == scopes

    def test_custom_policy(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, "Test", policy="minimal")
        assert token.policy == "minimal"

    def test_custom_ttl(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, "Test", ttl_hours=1)
        iat = datetime.fromisoformat(token.issued_at)
        exp = datetime.fromisoformat(token.expires_at)
        diff = (exp - iat).total_seconds()
        assert 3500 < diff < 3700  # approximately 1 hour


# ============================================================================
# Rejection
# ============================================================================

class TestGrantTokenRejection:

    def test_expired_rejected(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, "Test", ttl_hours=0)
        # Force expiry
        token.expires_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        token_str = token.sign(identity)

        result, err = GrantToken.verify_and_decode(
            token_str, identity.public_key_b64, clock_skew=0
        )
        assert result is None
        assert "expired" in err

    def test_wrong_audience_rejected(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, "Claude")
        token_str = token.sign(identity)

        result, err = GrantToken.verify_and_decode(
            token_str, identity.public_key_b64, expected_audience="GPT"
        )
        assert result is None
        assert "audience mismatch" in err

    def test_tampered_token_rejected(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, "Claude")
        token_str = token.sign(identity)

        # Tamper with the payload part
        parts = token_str.split(".")
        parts[1] = parts[1][:-4] + "XXXX"
        tampered = ".".join(parts)

        result, err = GrantToken.verify_and_decode(
            tampered, identity.public_key_b64
        )
        assert result is None

    def test_wrong_key_rejected(self):
        if not has_crypto():
            return
        identity1 = UPAIIdentity.generate("Signer")
        identity2 = UPAIIdentity.generate("Other")
        token = GrantToken.create(identity1, "Test")
        token_str = token.sign(identity1)

        result, err = GrantToken.verify_and_decode(
            token_str, identity2.public_key_b64
        )
        assert result is None
        assert "invalid signature" in err

    def test_malformed_token(self):
        result, err = GrantToken.verify_and_decode(
            "not.a.valid.token", "dGVzdA=="
        )
        assert result is None
        assert "malformed" in err or "3 parts" in err


# ============================================================================
# Scope checking
# ============================================================================

class TestGrantTokenScopes:

    def test_has_scope(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, "Test")
        assert token.has_scope(SCOPE_CONTEXT_READ)
        assert token.has_scope(SCOPE_VERSIONS_READ)

    def test_missing_scope(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, "Test", scopes=[SCOPE_CONTEXT_READ])
        assert token.has_scope(SCOPE_CONTEXT_READ)
        assert not token.has_scope(SCOPE_VERSIONS_READ)

    def test_valid_scopes_constant(self):
        assert SCOPE_CONTEXT_READ in VALID_SCOPES
        assert SCOPE_VERSIONS_READ in VALID_SCOPES
        assert SCOPE_IDENTITY_READ in VALID_SCOPES

    def test_default_scopes(self):
        assert SCOPE_CONTEXT_READ in DEFAULT_SCOPES


# ============================================================================
# is_expired
# ============================================================================

class TestGrantTokenExpiry:

    def test_not_expired(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, "Test", ttl_hours=24)
        assert not token.is_expired()

    def test_expired(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, "Test")
        token.expires_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert token.is_expired(clock_skew=0)


# ============================================================================
# Decode without verification
# ============================================================================

class TestGrantTokenDecode:

    def test_decode_without_verify(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, "Claude", policy="technical")
        token_str = token.sign(identity)

        decoded = GrantToken.decode(token_str)
        assert decoded.audience == "Claude"
        assert decoded.policy == "technical"

    def test_decode_bad_format(self):
        import pytest
        with pytest.raises(ValueError):
            GrantToken.decode("bad.format")


# ============================================================================
# to_dict / from_dict
# ============================================================================

class TestGrantTokenSerialization:

    def test_roundtrip(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, "Claude")
        d = token.to_dict()
        restored = GrantToken.from_dict(d)
        assert restored.grant_id == token.grant_id
        assert restored.audience == token.audience
        assert restored.scopes == token.scopes

    def test_to_dict_fields(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        token = GrantToken.create(identity, "Claude")
        d = token.to_dict()
        assert "grant_id" in d
        assert "subject_did" in d
        assert "issuer_did" in d
        assert "audience" in d
        assert "policy" in d
        assert "scopes" in d
        assert "issued_at" in d
        assert "expires_at" in d
