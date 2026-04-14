"""Centralized input validation for Cortex runtime and ingestion surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class SecurityError(ValueError):
    """Base class for security-related validation failures."""


class PathTraversalSecurityError(SecurityError):
    """Raised when an input path escapes the allowed base directory."""


class InvalidInputSecurityError(SecurityError):
    """Raised when a user-supplied value is malformed or unsafe."""


DEFAULT_MAX_TEXT_LENGTH = 200_000
DEFAULT_MAX_PATH_LENGTH = 4_096


@dataclass(frozen=True, slots=True)
class InputValidator:
    """Validate user-controlled text and file paths before Cortex uses them."""

    max_text_length: int = DEFAULT_MAX_TEXT_LENGTH
    max_path_length: int = DEFAULT_MAX_PATH_LENGTH

    def validate_text(
        self,
        value: str | bytes,
        *,
        field_name: str = "input",
        max_length: int | None = None,
    ) -> str:
        """Return a validated UTF-8 text value or raise a security error."""
        if isinstance(value, bytes):
            try:
                text = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise InvalidInputSecurityError(f"{field_name} must be valid UTF-8 text.") from exc
        elif isinstance(value, str):
            text = value
        else:
            raise InvalidInputSecurityError(f"{field_name} must be text, not {type(value).__name__}.")
        if "\x00" in text:
            raise InvalidInputSecurityError(f"{field_name} cannot contain NUL bytes.")
        limit = self.max_text_length if max_length is None else int(max_length)
        if limit <= 0:
            raise InvalidInputSecurityError(f"{field_name} maximum length must be positive.")
        if len(text) > limit:
            raise InvalidInputSecurityError(f"{field_name} exceeds the maximum length of {limit} characters.")
        try:
            text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise InvalidInputSecurityError(f"{field_name} must round-trip as UTF-8 text.") from exc
        return text

    def validate_text_list(
        self,
        values: Iterable[str | bytes],
        *,
        field_name: str,
        item_max_length: int | None = None,
    ) -> list[str]:
        """Validate a list of text values without silently coercing them."""
        return [
            self.validate_text(value, field_name=f"{field_name}[{index}]", max_length=item_max_length)
            for index, value in enumerate(values)
        ]

    def validate_path(
        self,
        value: str | Path,
        *,
        field_name: str = "path",
        base_dir: str | Path | None = None,
        must_exist: bool = True,
    ) -> Path:
        """Resolve and validate a user-supplied file path."""
        raw_path = self.validate_text(str(value), field_name=field_name, max_length=self.max_path_length).strip()
        if not raw_path:
            raise InvalidInputSecurityError(f"{field_name} is required.")

        candidate = Path(raw_path).expanduser()
        if base_dir is not None and not candidate.is_absolute():
            candidate = Path(base_dir).expanduser() / candidate

        resolved = candidate.resolve(strict=False)
        if base_dir is not None:
            base_path = Path(base_dir).expanduser().resolve(strict=False)
            if not resolved.is_relative_to(base_path):
                raise PathTraversalSecurityError(f"{field_name} must stay within {base_path}.")
        if must_exist and not resolved.exists():
            raise InvalidInputSecurityError(f"{field_name} not found: {resolved}")
        return resolved


__all__ = [
    "DEFAULT_MAX_PATH_LENGTH",
    "DEFAULT_MAX_TEXT_LENGTH",
    "InputValidator",
    "InvalidInputSecurityError",
    "PathTraversalSecurityError",
    "SecurityError",
]
