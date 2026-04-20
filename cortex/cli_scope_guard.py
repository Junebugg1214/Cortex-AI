"""Shared CLI guardrails for commands that write target-specific files."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _iter_candidate_paths(payload: dict[str, Any] | Iterable[str | Path]) -> Iterable[str | Path]:
    if not isinstance(payload, dict):
        yield from payload
        return

    yield from payload.get("paths", [])
    for target in payload.get("targets", []):
        if isinstance(target, dict):
            yield from target.get("paths", [])


def outside_project_paths(payload: dict[str, Any] | Iterable[str | Path], project_dir: str | Path) -> list[Path]:
    outside: list[Path] = []
    seen: set[Path] = set()
    project_root = Path(project_dir)
    for raw_path in _iter_candidate_paths(payload):
        if not raw_path:
            continue
        path = Path(str(raw_path)).expanduser().resolve()
        if _is_within(path, project_root):
            continue
        if path not in seen:
            outside.append(path)
            seen.add(path)
    return outside


def global_scope_error(paths: Iterable[Path], *, error: Callable[[str], int] | None = None) -> str | int:
    rendered_paths = "\n".join(f"  - {path}" for path in paths)
    message = (
        "The following paths are outside --project and will be written:\n"
        f"{rendered_paths}\n"
        "Re-run with --global to confirm, or use --to PROJECT_TARGET to narrow."
    )
    if error is not None:
        return error(message)
    return message
