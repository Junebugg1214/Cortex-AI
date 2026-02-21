"""Tests for cortex.caas.security — CSRF, SSRF, Content-Type validation."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest

from cortex.caas.security import (
    CSRFProtection,
    is_private_ip,
    validate_webhook_url,
    require_json_content_type,
)


# ---------------------------------------------------------------------------
# TestCSRF
# ---------------------------------------------------------------------------

class TestCSRF:
    def _make_csrf(self) -> CSRFProtection:
        return CSRFProtection(secret=b"test-csrf-secret-32-bytes-long!!")

    def test_generate_and_validate(self):
        csrf = self._make_csrf()
        token = csrf.generate_token("session-abc")
        assert csrf.validate_token("session-abc", token)

    def test_different_session_rejected(self):
        csrf = self._make_csrf()
        token = csrf.generate_token("session-abc")
        assert not csrf.validate_token("session-xyz", token)

    def test_expired_token_rejected(self):
        csrf = self._make_csrf()
        # Generate a token, then pretend time has passed
        token = csrf.generate_token("session-abc")
        assert csrf.validate_token("session-abc", token, max_age=3600)
        # Modify to appear old
        parts = token.split(":")
        old_ts = int(time.time()) - 7200  # 2 hours ago
        old_token = f"{parts[0]}:{old_ts:x}"
        # Old token with wrong HMAC will fail
        assert not csrf.validate_token("session-abc", old_token, max_age=3600)

    def test_tampered_token_rejected(self):
        csrf = self._make_csrf()
        token = csrf.generate_token("session-abc")
        # Tamper with the HMAC part
        tampered = "0000000000000000" + token[16:]
        assert not csrf.validate_token("session-abc", tampered)

    def test_empty_token_rejected(self):
        csrf = self._make_csrf()
        assert not csrf.validate_token("session-abc", "")

    def test_no_colon_rejected(self):
        csrf = self._make_csrf()
        assert not csrf.validate_token("session-abc", "no-colon-here")

    def test_invalid_timestamp_rejected(self):
        csrf = self._make_csrf()
        assert not csrf.validate_token("session-abc", "abc:not-hex")

    def test_token_format(self):
        csrf = self._make_csrf()
        token = csrf.generate_token("session-abc")
        parts = token.split(":")
        assert len(parts) == 2
        assert len(parts[0]) == 32  # hex HMAC truncated
        # Timestamp should be valid hex
        int(parts[1], 16)

    def test_different_secrets_incompatible(self):
        csrf1 = CSRFProtection(secret=b"secret-one-32-bytes-long!!!!!!!!")
        csrf2 = CSRFProtection(secret=b"secret-two-32-bytes-long!!!!!!!!")
        token = csrf1.generate_token("session-abc")
        assert not csrf2.validate_token("session-abc", token)

    def test_max_age_zero_still_validates_current(self):
        csrf = self._make_csrf()
        token = csrf.generate_token("session-abc")
        # With max_age=0, should still be valid in the same second
        assert csrf.validate_token("session-abc", token, max_age=1)


# ---------------------------------------------------------------------------
# TestSSRF — is_private_ip
# ---------------------------------------------------------------------------

class TestSSRFPrivateIP:
    def test_loopback_127(self):
        assert is_private_ip("127.0.0.1") is True

    def test_loopback_127_x(self):
        assert is_private_ip("127.0.0.2") is True

    def test_rfc1918_10(self):
        assert is_private_ip("10.0.0.1") is True

    def test_rfc1918_172(self):
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("172.31.255.255") is True

    def test_rfc1918_192(self):
        assert is_private_ip("192.168.1.1") is True

    def test_link_local(self):
        assert is_private_ip("169.254.1.1") is True

    def test_cloud_metadata(self):
        assert is_private_ip("169.254.169.254") is True

    def test_ipv6_loopback(self):
        assert is_private_ip("::1") is True

    def test_ipv6_unique_local(self):
        assert is_private_ip("fd00::1") is True

    def test_public_ip_allowed(self):
        assert is_private_ip("8.8.8.8") is False

    def test_public_ip_allowed_2(self):
        assert is_private_ip("93.184.216.34") is False

    def test_invalid_ip_blocked(self):
        assert is_private_ip("not-an-ip") is True

    def test_zero_network_blocked(self):
        assert is_private_ip("0.0.0.1") is True

    def test_shared_address_blocked(self):
        assert is_private_ip("100.64.0.1") is True

    def test_172_outside_private_allowed(self):
        assert is_private_ip("172.32.0.1") is False


# ---------------------------------------------------------------------------
# TestSSRF — validate_webhook_url
# ---------------------------------------------------------------------------

class TestSSRFWebhookURL:
    def test_public_url_allowed(self):
        # Mock DNS resolution to return a public IP
        with patch("cortex.caas.security.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 443)),
            ]
            valid, err = validate_webhook_url("https://example.com/webhook")
            assert valid is True
            assert err == ""

    def test_private_ip_blocked(self):
        with patch("cortex.caas.security.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("127.0.0.1", 80)),
            ]
            valid, err = validate_webhook_url("http://localhost/webhook")
            assert valid is False
            assert "private IP" in err

    def test_rfc1918_blocked(self):
        with patch("cortex.caas.security.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("10.0.0.5", 80)),
            ]
            valid, err = validate_webhook_url("http://internal-host/webhook")
            assert valid is False

    def test_metadata_endpoint_blocked(self):
        with patch("cortex.caas.security.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("169.254.169.254", 80)),
            ]
            valid, err = validate_webhook_url("http://metadata.internal/latest")
            assert valid is False

    def test_dns_resolution_failure(self):
        import socket
        with patch("cortex.caas.security.socket.getaddrinfo") as mock_gai:
            mock_gai.side_effect = socket.gaierror("Name resolution failed")
            valid, err = validate_webhook_url("http://nonexistent.invalid/hook")
            assert valid is False
            assert "resolve" in err.lower()

    def test_missing_hostname(self):
        valid, err = validate_webhook_url("not-a-url")
        assert valid is False


# ---------------------------------------------------------------------------
# TestContentType
# ---------------------------------------------------------------------------

class TestContentType:
    def test_valid_json(self):
        valid, err = require_json_content_type("application/json")
        assert valid is True

    def test_json_with_charset(self):
        valid, err = require_json_content_type("application/json; charset=utf-8")
        assert valid is True

    def test_json_uppercase(self):
        valid, err = require_json_content_type("Application/JSON")
        assert valid is True

    def test_missing_rejected(self):
        valid, err = require_json_content_type(None)
        assert valid is False
        assert "Missing" in err

    def test_wrong_type_rejected(self):
        valid, err = require_json_content_type("text/html")
        assert valid is False
        assert "Expected" in err

    def test_form_urlencoded_rejected(self):
        valid, err = require_json_content_type("application/x-www-form-urlencoded")
        assert valid is False

    def test_empty_string_rejected(self):
        valid, err = require_json_content_type("")
        assert valid is False
