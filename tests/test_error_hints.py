"""Tests for cortex.upai.error_hints — contextual error suggestions."""

from __future__ import annotations

import pytest

from cortex.upai.error_hints import (
    enrich_error,
    hint_for_insufficient_scope,
    hint_for_invalid_token,
    hint_for_not_found,
    hint_for_policy,
    hint_for_role,
    hint_for_scope,
)
from cortex.upai.errors import ERR_INSUFFICIENT_SCOPE, ERR_INVALID_POLICY, ERR_INVALID_TOKEN, UPAIError


# ---------------------------------------------------------------------------
# hint_for_scope
# ---------------------------------------------------------------------------

class TestHintForScope:
    def test_close_match(self):
        hint = hint_for_scope("context:reda")
        assert 'context:read' in hint
        assert "Did you mean" in hint

    def test_exact_match(self):
        hint = hint_for_scope("context:read")
        assert 'context:read' in hint

    def test_no_match_shows_valid(self):
        hint = hint_for_scope("zzzzz:nonexistent")
        assert "Valid scopes:" in hint
        assert "context:read" in hint

    def test_write_typo(self):
        hint = hint_for_scope("context:writ")
        assert 'context:write' in hint


# ---------------------------------------------------------------------------
# hint_for_role
# ---------------------------------------------------------------------------

class TestHintForRole:
    def test_close_match(self):
        hint = hint_for_role("owne")
        assert 'owner' in hint
        assert "Did you mean" in hint

    def test_no_match_shows_valid(self):
        hint = hint_for_role("zzzzxyz")
        assert "Valid roles:" in hint

    def test_editor_typo(self):
        hint = hint_for_role("edito")
        assert 'editor' in hint


# ---------------------------------------------------------------------------
# hint_for_policy
# ---------------------------------------------------------------------------

class TestHintForPolicy:
    def test_close_match(self):
        hint = hint_for_policy("ful")
        assert 'full' in hint
        assert "Did you mean" in hint

    def test_custom_known_policies(self):
        hint = hint_for_policy("custm", ["custom_v1", "custom_v2"])
        assert "custom_v1" in hint or "custom_v2" in hint

    def test_no_match_shows_available(self):
        hint = hint_for_policy("zzzznonexistent")
        assert "Available policies:" in hint

    def test_professional_typo(self):
        hint = hint_for_policy("profesional")
        assert 'professional' in hint


# ---------------------------------------------------------------------------
# hint_for_insufficient_scope
# ---------------------------------------------------------------------------

class TestHintForInsufficientScope:
    def test_includes_required(self):
        hint = hint_for_insufficient_scope("context:write")
        assert "context:write" in hint
        assert "Valid scopes:" in hint

    def test_includes_all_scopes(self):
        hint = hint_for_insufficient_scope("context:read")
        assert "context:read" in hint


# ---------------------------------------------------------------------------
# hint_for_invalid_token
# ---------------------------------------------------------------------------

class TestHintForInvalidToken:
    def test_returns_string(self):
        hint = hint_for_invalid_token()
        assert isinstance(hint, str)
        assert len(hint) > 10

    def test_mentions_common_issues(self):
        hint = hint_for_invalid_token()
        assert "expired" in hint.lower() or "signature" in hint.lower()


# ---------------------------------------------------------------------------
# hint_for_not_found
# ---------------------------------------------------------------------------

class TestHintForNotFound:
    def test_includes_resource(self):
        hint = hint_for_not_found("node")
        assert "node" in hint

    def test_suggests_verification(self):
        hint = hint_for_not_found("edge")
        assert "Verify" in hint or "verify" in hint


# ---------------------------------------------------------------------------
# enrich_error
# ---------------------------------------------------------------------------

class TestEnrichError:
    def test_adds_hint(self):
        err = ERR_INVALID_POLICY("bad_policy")
        d = err.to_dict()
        enriched = enrich_error(d, "Did you mean 'full'?")
        assert enriched["error"]["hint"] == "Did you mean 'full'?"

    def test_empty_hint_no_change(self):
        err = ERR_INVALID_TOKEN()
        d = err.to_dict()
        original_keys = set(d["error"].keys())
        enrich_error(d, "")
        assert set(d["error"].keys()) == original_keys

    def test_returns_same_dict(self):
        d = {"error": {"code": "X", "message": "test"}}
        result = enrich_error(d, "hint text")
        assert result is d


# ---------------------------------------------------------------------------
# UPAIError hint field
# ---------------------------------------------------------------------------

class TestUPAIErrorHint:
    def test_hint_in_to_dict(self):
        err = UPAIError(
            code="UPAI-4001",
            error_type="invalid_token",
            message="Bad token",
            hint="Check your token",
        )
        d = err.to_dict()
        assert d["error"]["hint"] == "Check your token"

    def test_no_hint_not_in_dict(self):
        err = UPAIError(
            code="UPAI-4001",
            error_type="invalid_token",
            message="Bad token",
        )
        d = err.to_dict()
        assert "hint" not in d["error"]

    def test_hint_default_empty(self):
        err = ERR_INVALID_TOKEN()
        assert err.hint == ""
