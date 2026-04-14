from __future__ import annotations

from pathlib import Path

import pytest

from cortex.security.validate import (
    InputValidator,
    InvalidInputSecurityError,
    PathTraversalSecurityError,
)


def test_validate_text_accepts_plain_utf8_text():
    validator = InputValidator()

    assert validator.validate_text("Project Atlas", field_name="label") == "Project Atlas"


def test_validate_text_rejects_invalid_utf8_bytes():
    validator = InputValidator()

    with pytest.raises(InvalidInputSecurityError, match="valid UTF-8"):
        validator.validate_text(b"\xff\xfe", field_name="payload")


def test_validate_text_rejects_nul_bytes():
    validator = InputValidator()

    with pytest.raises(InvalidInputSecurityError, match="NUL"):
        validator.validate_text("bad\x00value", field_name="statement")


def test_validate_text_rejects_overlong_input():
    validator = InputValidator(max_text_length=8)

    with pytest.raises(InvalidInputSecurityError, match="maximum length"):
        validator.validate_text("0123456789", field_name="statement")


def test_validate_text_list_preserves_values():
    validator = InputValidator()

    assert validator.validate_text_list(["identity", "project"], field_name="tags") == ["identity", "project"]


def test_validate_path_resolves_existing_path(tmp_path: Path):
    validator = InputValidator()
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")

    assert validator.validate_path(target, field_name="source_path") == target.resolve()


def test_validate_path_rejects_missing_path(tmp_path: Path):
    validator = InputValidator()

    with pytest.raises(InvalidInputSecurityError, match="not found"):
        validator.validate_path(tmp_path / "missing.txt", field_name="source_path")


def test_validate_path_rejects_escape_outside_base(tmp_path: Path):
    validator = InputValidator()
    base = tmp_path / "safe"
    outside = tmp_path / "outside.txt"
    base.mkdir()
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(PathTraversalSecurityError, match="must stay within"):
        validator.validate_path(outside, field_name="source_path", base_dir=base)


def test_validate_path_allows_relative_path_inside_base(tmp_path: Path):
    validator = InputValidator()
    base = tmp_path / "safe"
    target = base / "docs" / "note.txt"
    target.parent.mkdir(parents=True)
    target.write_text("ok", encoding="utf-8")

    resolved = validator.validate_path("docs/note.txt", field_name="source_path", base_dir=base)

    assert resolved == target.resolve()
