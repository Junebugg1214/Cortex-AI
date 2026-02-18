"""
Unit tests for cortex.caas.oauth — PKCE, state HMAC, OAuthManager.

All tests are pure (no network calls).
"""

import base64
import hashlib
import re
import secrets
import time
import unittest

from cortex.caas.oauth import (
    OAuthProviderConfig,
    OAuthManager,
    GOOGLE_ENDPOINTS,
    GITHUB_ENDPOINTS,
    PROVIDER_DEFAULTS,
    generate_code_verifier,
    generate_code_challenge,
    generate_state,
    validate_state,
)


class TestPKCE(unittest.TestCase):
    """Tests for PKCE code verifier and code challenge."""

    def test_verifier_length(self):
        v = generate_code_verifier(64)
        # Must be between 43 and 128 characters per RFC 7636
        self.assertGreaterEqual(len(v), 43)
        self.assertLessEqual(len(v), 128)

    def test_verifier_url_safe_chars(self):
        v = generate_code_verifier()
        # URL-safe base64 characters only (no padding)
        self.assertTrue(re.match(r'^[A-Za-z0-9_-]+$', v), f"Invalid chars in verifier: {v}")

    def test_verifier_uniqueness(self):
        v1 = generate_code_verifier()
        v2 = generate_code_verifier()
        self.assertNotEqual(v1, v2)

    def test_challenge_deterministic(self):
        v = "test_verifier_12345"
        c1 = generate_code_challenge(v)
        c2 = generate_code_challenge(v)
        self.assertEqual(c1, c2)

    def test_challenge_url_safe(self):
        v = generate_code_verifier()
        c = generate_code_challenge(v)
        self.assertTrue(re.match(r'^[A-Za-z0-9_-]+$', c), f"Invalid chars in challenge: {c}")

    def test_challenge_roundtrip(self):
        """Challenge is S256(verifier) — verify manually."""
        v = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ"
        expected_digest = hashlib.sha256(v.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
        self.assertEqual(generate_code_challenge(v), expected)

    def test_challenge_differs_for_different_verifiers(self):
        v1 = generate_code_verifier()
        v2 = generate_code_verifier()
        c1 = generate_code_challenge(v1)
        c2 = generate_code_challenge(v2)
        self.assertNotEqual(c1, c2)


class TestState(unittest.TestCase):
    """Tests for state parameter generation and validation."""

    def setUp(self):
        self.secret = secrets.token_bytes(32)

    def test_generate_and_validate(self):
        state = generate_state(self.secret, "google", "nonce123")
        result = validate_state(self.secret, state)
        self.assertIsNotNone(result)
        provider, nonce = result
        self.assertEqual(provider, "google")
        self.assertEqual(nonce, "nonce123")

    def test_wrong_secret_rejects(self):
        state = generate_state(self.secret, "google", "nonce123")
        wrong = secrets.token_bytes(32)
        result = validate_state(wrong, state)
        self.assertIsNone(result)

    def test_tampered_rejects(self):
        state = generate_state(self.secret, "google", "nonce123")
        # Flip a character
        tampered = state[:-1] + ("A" if state[-1] != "A" else "B")
        result = validate_state(self.secret, tampered)
        self.assertIsNone(result)

    def test_expired_rejects(self):
        state = generate_state(self.secret, "github", "n1")
        result = validate_state(self.secret, state, max_age=0)
        # With max_age=0, even a fresh state should be expired (or borderline)
        # We allow it to be None or valid depending on timing
        # Use a definitely-expired approach:
        # Generate state, then validate with max_age that's clearly less than elapsed
        import time as _t
        _t.sleep(0.1)
        result = validate_state(self.secret, state, max_age=0)
        self.assertIsNone(result)

    def test_provider_preserved(self):
        for provider in ["google", "github", "custom-provider"]:
            state = generate_state(self.secret, provider, "n")
            result = validate_state(self.secret, state)
            self.assertIsNotNone(result)
            self.assertEqual(result[0], provider)

    def test_garbage_input(self):
        self.assertIsNone(validate_state(self.secret, ""))
        self.assertIsNone(validate_state(self.secret, "notbase64!!!"))
        self.assertIsNone(validate_state(self.secret, "dGVzdA"))  # decodes to "test"


class TestOAuthProviderConfig(unittest.TestCase):
    """Tests for provider config dataclass and defaults."""

    def test_google_endpoints(self):
        self.assertIn("accounts.google.com", GOOGLE_ENDPOINTS["authorize_url"])
        self.assertIn("googleapis.com", GOOGLE_ENDPOINTS["token_url"])
        self.assertIn("openid", GOOGLE_ENDPOINTS["scopes"])

    def test_github_endpoints(self):
        self.assertIn("github.com", GITHUB_ENDPOINTS["authorize_url"])
        self.assertIn("github.com", GITHUB_ENDPOINTS["token_url"])
        self.assertIn("read:user", GITHUB_ENDPOINTS["scopes"])

    def test_provider_defaults_both(self):
        self.assertIn("google", PROVIDER_DEFAULTS)
        self.assertIn("github", PROVIDER_DEFAULTS)

    def test_config_dataclass(self):
        cfg = OAuthProviderConfig(
            name="test",
            client_id="id",
            client_secret="secret",
            authorize_url="https://example.com/auth",
            token_url="https://example.com/token",
            userinfo_url="https://example.com/userinfo",
            scopes=["openid"],
        )
        self.assertEqual(cfg.name, "test")
        self.assertEqual(cfg.client_id, "id")
        self.assertEqual(cfg.scopes, ["openid"])


class TestOAuthManager(unittest.TestCase):
    """Tests for OAuthManager (no network calls)."""

    def _make_manager(self, providers=None, allowed_emails=None):
        secret = secrets.token_bytes(32)
        if providers is None:
            providers = {
                "google": OAuthProviderConfig(
                    name="google",
                    client_id="test-id",
                    client_secret="test-secret",
                    **GOOGLE_ENDPOINTS,
                ),
            }
        return OAuthManager(
            providers=providers,
            state_secret=secret,
            redirect_base="http://localhost:8421",
            allowed_emails=allowed_emails,
        )

    def test_enabled(self):
        om = self._make_manager()
        self.assertTrue(om.enabled)

    def test_disabled(self):
        om = self._make_manager(providers={})
        self.assertFalse(om.enabled)

    def test_provider_names(self):
        om = self._make_manager()
        self.assertEqual(om.provider_names, ["google"])

    def test_get_authorization_url_format(self):
        om = self._make_manager()
        result = om.get_authorization_url("google")
        self.assertIsNotNone(result)
        url, nonce = result
        self.assertIn("accounts.google.com", url)
        self.assertIn("client_id=test-id", url)
        self.assertIn("response_type=code", url)
        self.assertIn("code_challenge=", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("state=", url)
        self.assertIn("redirect_uri=", url)
        self.assertTrue(len(nonce) > 0)

    def test_unknown_provider(self):
        om = self._make_manager()
        result = om.get_authorization_url("unknown")
        self.assertIsNone(result)

    def test_email_allowlist_unrestricted(self):
        om = self._make_manager(allowed_emails=None)
        self.assertTrue(om.is_email_allowed("anyone@example.com"))

    def test_email_allowlist_restricted(self):
        om = self._make_manager(allowed_emails={"alice@example.com"})
        self.assertTrue(om.is_email_allowed("alice@example.com"))
        self.assertTrue(om.is_email_allowed("Alice@Example.Com"))  # case insensitive
        self.assertFalse(om.is_email_allowed("bob@example.com"))

    def test_cleanup_flows_cap(self):
        om = self._make_manager()
        # Generate MAX_PENDING + 10 flows
        for _ in range(om.MAX_PENDING + 10):
            om.get_authorization_url("google")
        # Should be capped at MAX_PENDING + 1 (the latest one was added after cleanup)
        self.assertLessEqual(len(om._pending), om.MAX_PENDING + 1)

    def test_handle_callback_invalid_state(self):
        om = self._make_manager()
        userinfo, error = om.handle_callback("some-code", "bad-state")
        self.assertIsNone(userinfo)
        self.assertEqual(error, "invalid_state")

    def test_multiple_providers(self):
        providers = {
            "google": OAuthProviderConfig(
                name="google", client_id="g-id", client_secret="g-secret",
                **GOOGLE_ENDPOINTS,
            ),
            "github": OAuthProviderConfig(
                name="github", client_id="gh-id", client_secret="gh-secret",
                **GITHUB_ENDPOINTS,
            ),
        }
        om = self._make_manager(providers=providers)
        self.assertEqual(sorted(om.provider_names), ["github", "google"])
        self.assertTrue(om.enabled)

        # Both providers produce valid authorize URLs
        g_result = om.get_authorization_url("google")
        gh_result = om.get_authorization_url("github")
        self.assertIsNotNone(g_result)
        self.assertIsNotNone(gh_result)
        self.assertIn("accounts.google.com", g_result[0])
        self.assertIn("github.com", gh_result[0])


if __name__ == "__main__":
    unittest.main()
