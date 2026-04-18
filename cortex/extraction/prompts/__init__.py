from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

_PROMPT_FILE_RE = re.compile(r"^(?P<name>[a-z][a-z0-9_]*?)\.(?P<version>v[0-9]+)\.md$")
_REQUIRED_FRONT_MATTER = {"version", "schema_ref", "inputs", "outputs", "test_fixture"}


class PromptLibraryError(RuntimeError):
    """Raised when prompt files are missing or malformed."""


class PromptNotFoundError(PromptLibraryError):
    """Raised when a stage references a missing prompt version."""


class _StrictRenderValues(dict[str, Any]):
    def __missing__(self, key: str) -> Any:
        raise PromptLibraryError(f"Missing render value for prompt placeholder {key!r}.")


@dataclass(frozen=True)
class Prompt:
    """Versioned prompt loaded from Markdown front matter."""

    name: str
    version: str
    schema_ref: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    test_fixture: str
    content: str
    path: str
    metadata: dict[str, Any]

    @property
    def reference(self) -> tuple[str, str]:
        return (self.name, self.version)

    def render(self, **values: Any) -> str:
        return self.content.format_map(_StrictRenderValues(values))


def _parse_scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_front_matter(front_matter: list[str], *, path: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    current_list_key = ""
    for raw_line in front_matter:
        if not raw_line.strip():
            continue
        stripped = raw_line.strip()
        if stripped.startswith("- "):
            if not current_list_key:
                raise PromptLibraryError(f"{path}: list item without a key in YAML front matter.")
            metadata.setdefault(current_list_key, []).append(_parse_scalar(stripped[2:]))
            continue
        if ":" not in raw_line:
            raise PromptLibraryError(f"{path}: malformed YAML front matter line: {raw_line!r}.")
        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        if not key:
            raise PromptLibraryError(f"{path}: empty YAML front matter key.")
        value = raw_value.strip()
        if value:
            metadata[key] = _parse_scalar(value)
            current_list_key = ""
        else:
            metadata[key] = []
            current_list_key = key
    missing = sorted(_REQUIRED_FRONT_MATTER - set(metadata))
    if missing:
        raise PromptLibraryError(f"{path}: missing required YAML front matter keys: {', '.join(missing)}.")
    return metadata


def _split_markdown_prompt(raw_text: str, *, path: str) -> tuple[dict[str, Any], str]:
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise PromptLibraryError(f"{path}: prompt file must start with YAML front matter.")
    end_index = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"), -1)
    if end_index < 0:
        raise PromptLibraryError(f"{path}: prompt file has unterminated YAML front matter.")
    metadata = _parse_front_matter(lines[1:end_index], path=path)
    content = "\n".join(lines[end_index + 1 :]).strip()
    if not content:
        raise PromptLibraryError(f"{path}: prompt body is empty.")
    return metadata, content


def _as_tuple(value: Any, *, path: str, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise PromptLibraryError(f"{path}: YAML front matter key {key!r} must be a non-empty string list.")
    return tuple(item.strip() for item in value)


def _prompt_from_file(filename: str, raw_text: str) -> Prompt:
    match = _PROMPT_FILE_RE.match(filename)
    if match is None:
        raise PromptLibraryError(f"{filename}: prompt file names must look like name.v1.md.")
    name = match.group("name")
    version = match.group("version")
    metadata, content = _split_markdown_prompt(raw_text, path=filename)
    metadata_version = str(metadata["version"]).strip()
    if metadata_version != version:
        raise PromptLibraryError(
            f"{filename}: front matter version {metadata_version!r} does not match file version {version!r}."
        )
    return Prompt(
        name=name,
        version=version,
        schema_ref=str(metadata["schema_ref"]).strip(),
        inputs=_as_tuple(metadata["inputs"], path=filename, key="inputs"),
        outputs=_as_tuple(metadata["outputs"], path=filename, key="outputs"),
        test_fixture=str(metadata["test_fixture"]).strip(),
        content=content,
        path=filename,
        metadata=dict(metadata),
    )


def _load_all_prompts() -> dict[tuple[str, str], Prompt]:
    prompts: dict[tuple[str, str], Prompt] = {}
    package_files = resources.files(__package__)
    for entry in package_files.iterdir():
        if not entry.name.endswith(".md"):
            continue
        prompt = _prompt_from_file(entry.name, entry.read_text(encoding="utf-8"))
        key = prompt.reference
        if key in prompts:
            raise PromptLibraryError(f"Duplicate prompt reference {prompt.name}.{prompt.version}.")
        prompts[key] = prompt
    return prompts


_PROMPTS = _load_all_prompts()


def load_prompt(name: str, version: str) -> Prompt:
    """Load a versioned extraction prompt."""

    key = (name, version)
    try:
        return _PROMPTS[key]
    except KeyError as exc:
        available = ", ".join(f"{prompt_name}.{prompt_version}" for prompt_name, prompt_version in sorted(_PROMPTS))
        raise PromptNotFoundError(
            f"Missing extraction prompt {name}.{version}. Available prompts: {available or 'none'}."
        ) from exc


def available_prompts() -> tuple[tuple[str, str], ...]:
    """Return prompt references loaded at import time."""

    return tuple(sorted(_PROMPTS))


__all__ = [
    "Prompt",
    "PromptLibraryError",
    "PromptNotFoundError",
    "available_prompts",
    "load_prompt",
]
