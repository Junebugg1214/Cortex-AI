"""
Cross-Platform Context Writer — Write Cortex identity to AI tool config files.

Supports: Claude Code, Cursor, GitHub Copilot, Windsurf, Gemini CLI.
Uses non-destructive section markers to coexist with user content.
"""

from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cortex.hooks import generate_compact_context, HookConfig, _load_graph
from cortex.upai.disclosure import BUILTIN_POLICIES


# ---------------------------------------------------------------------------
# Section markers for non-destructive writes
# ---------------------------------------------------------------------------

CORTEX_START = "<!-- CORTEX:START -->"
CORTEX_END = "<!-- CORTEX:END -->"


# ---------------------------------------------------------------------------
# Platform formatting functions
# ---------------------------------------------------------------------------

def _format_plain(content: str) -> str:
    """Wrap content with Cortex section markers. Used by most platforms."""
    return f"{CORTEX_START}\n{content}\n{CORTEX_END}\n"


def _format_cursor_mdc(content: str) -> str:
    """Format as Cursor .mdc file with YAML frontmatter + markers."""
    return (
        "---\n"
        "description: Cortex identity context (auto-generated)\n"
        "globs:\n"
        "alwaysApply: true\n"
        "---\n\n"
        f"{CORTEX_START}\n{content}\n{CORTEX_END}\n"
    )


# ---------------------------------------------------------------------------
# Platform target registry
# ---------------------------------------------------------------------------

@dataclass
class PlatformTarget:
    name: str                          # "claude-code", "cursor", etc.
    file_path: str                     # Path template: {home}, {project}
    scope: str                         # "global" or "project"
    default_policy: str                # Default disclosure policy name
    format_fn: Callable[[str], str]    # Platform-specific formatter
    description: str                   # Human-readable description


CONTEXT_TARGETS: dict[str, PlatformTarget] = {
    "claude-code": PlatformTarget(
        name="claude-code",
        file_path="{home}/.claude/MEMORY.md",
        scope="global",
        default_policy="technical",
        format_fn=_format_plain,
        description="Claude Code global memory",
    ),
    "claude-code-project": PlatformTarget(
        name="claude-code-project",
        file_path="{project}/.claude/MEMORY.md",
        scope="project",
        default_policy="technical",
        format_fn=_format_plain,
        description="Claude Code per-project memory",
    ),
    "cursor": PlatformTarget(
        name="cursor",
        file_path="{project}/.cursor/rules/cortex.mdc",
        scope="project",
        default_policy="technical",
        format_fn=_format_cursor_mdc,
        description="Cursor IDE rules",
    ),
    "copilot": PlatformTarget(
        name="copilot",
        file_path="{project}/.github/copilot-instructions.md",
        scope="project",
        default_policy="technical",
        format_fn=_format_plain,
        description="GitHub Copilot instructions",
    ),
    "windsurf": PlatformTarget(
        name="windsurf",
        file_path="{project}/.windsurfrules",
        scope="project",
        default_policy="technical",
        format_fn=_format_plain,
        description="Windsurf rules",
    ),
    "gemini-cli": PlatformTarget(
        name="gemini-cli",
        file_path="{project}/GEMINI.md",
        scope="project",
        default_policy="technical",
        format_fn=_format_plain,
        description="Gemini CLI context",
    ),
}


# ---------------------------------------------------------------------------
# Non-destructive file writer
# ---------------------------------------------------------------------------

def _write_non_destructive(path: Path, content: str, dry_run: bool = False) -> str:
    """Write content between CORTEX section markers.

    - File has markers → replace content between them
    - File exists, no markers → append marked section
    - File doesn't exist → create with marked section

    Returns status: "created", "updated", or "dry-run".
    """
    if dry_run:
        return "dry-run"

    if path.exists():
        existing = path.read_text(encoding="utf-8")

        if CORTEX_START in existing and CORTEX_END in existing:
            # Replace between markers
            start_idx = existing.index(CORTEX_START)
            end_idx = existing.index(CORTEX_END) + len(CORTEX_END)
            # Consume trailing newline if present
            if end_idx < len(existing) and existing[end_idx] == "\n":
                end_idx += 1
            new_content = existing[:start_idx] + content + existing[end_idx:]
            path.write_text(new_content, encoding="utf-8")
            return "updated"
        else:
            # Append marked section
            separator = "" if existing.endswith("\n\n") else (
                "\n" if existing.endswith("\n") else "\n\n"
            )
            path.write_text(existing + separator + content, encoding="utf-8")
            return "updated"
    else:
        # Create new file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return "created"


# ---------------------------------------------------------------------------
# Resolve path templates
# ---------------------------------------------------------------------------

def _resolve_path(template: str, project_dir: str | None = None) -> Path:
    """Expand {home} and {project} in path templates."""
    resolved = template.replace("{home}", str(Path.home()))
    project = project_dir or os.getcwd()
    resolved = resolved.replace("{project}", project)
    return Path(resolved)


# ---------------------------------------------------------------------------
# Main write function
# ---------------------------------------------------------------------------

def write_context(
    graph_path: str,
    platforms: list[str],
    project_dir: str | None = None,
    policy: str | None = None,
    max_chars: int = 1500,
    dry_run: bool = False,
) -> list[tuple[str, Path, str]]:
    """Write context files for the specified platforms.

    Args:
        graph_path: Path to Cortex graph JSON
        platforms: List of platform names, or ["all"]
        project_dir: Project directory for per-project targets (default: cwd)
        policy: Override disclosure policy for all platforms (None = use defaults)
        max_chars: Max chars per context file
        dry_run: Preview without writing

    Returns:
        List of (platform_name, file_path, status) tuples.
        Status: "created", "updated", "skipped", "dry-run", "error".
    """
    # Resolve "all"
    if "all" in platforms:
        platforms = list(CONTEXT_TARGETS.keys())

    results: list[tuple[str, Path, str]] = []

    for platform_name in platforms:
        target = CONTEXT_TARGETS.get(platform_name)
        if target is None:
            results.append((platform_name, Path(""), "skipped"))
            continue

        # Determine policy
        use_policy = policy or target.default_policy

        # Generate compact context
        config = HookConfig(
            graph_path=graph_path,
            policy=use_policy,
            max_chars=max_chars,
        )
        context = generate_compact_context(config)

        if not context:
            results.append((platform_name, Path(""), "skipped"))
            continue

        # Format for platform
        formatted = target.format_fn(context)

        # Resolve file path
        file_path = _resolve_path(target.file_path, project_dir)

        # Write
        try:
            status = _write_non_destructive(file_path, formatted, dry_run=dry_run)
            results.append((platform_name, file_path, status))
        except (OSError, PermissionError) as e:
            results.append((platform_name, file_path, "error"))

    return results


# ---------------------------------------------------------------------------
# Watch and auto-refresh
# ---------------------------------------------------------------------------

def watch_and_refresh(
    graph_path: str,
    platforms: list[str],
    project_dir: str | None = None,
    policy: str | None = None,
    max_chars: int = 1500,
    interval: int = 30,
) -> None:
    """Poll graph file and re-write context when it changes.

    Blocks until interrupted (KeyboardInterrupt).
    """
    path = Path(graph_path)
    if not path.exists():
        return

    last_mtime = path.stat().st_mtime
    stop_event = threading.Event()

    # Initial write
    write_context(graph_path, platforms, project_dir, policy, max_chars)
    print(f"Watching {graph_path} (interval: {interval}s)...")

    try:
        while not stop_event.is_set():
            stop_event.wait(interval)
            if stop_event.is_set():
                break

            try:
                current_mtime = path.stat().st_mtime
            except OSError:
                continue

            if current_mtime != last_mtime:
                last_mtime = current_mtime
                results = write_context(
                    graph_path, platforms, project_dir, policy, max_chars,
                )
                for name, fpath, status in results:
                    if status in ("created", "updated"):
                        print(f"  {name}: {status} ({fpath})")
    except KeyboardInterrupt:
        print("\nStopped watching.")
