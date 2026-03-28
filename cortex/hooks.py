"""
Cortex Hook — Auto-inject identity context into Claude Code sessions.

Provides a SessionStart hook that loads your Cortex graph, applies a
disclosure policy, and returns compact markdown for injection as a
system message.
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from cortex.compat import upgrade_v4_to_v5
from cortex.graph import CortexGraph
from cortex.upai.disclosure import BUILTIN_POLICIES, apply_disclosure

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_DIR = Path.home() / ".cortex"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "hook-config.json"
logger = logging.getLogger(__name__)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_FOCUS_STOP_WORDS = {
    "app",
    "code",
    "codes",
    "desktop",
    "dev",
    "home",
    "private",
    "project",
    "projects",
    "repo",
    "repos",
    "src",
    "tmp",
    "user",
    "users",
    "var",
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class HookConfig:
    graph_path: str = ""  # Path to Cortex graph JSON
    policy: str = "technical"  # Disclosure policy name
    max_chars: int = 1500  # Cap injection size
    include_project: bool = True  # Include project-specific context


@dataclass(frozen=True)
class GraphLoadResult:
    graph: CortexGraph | None
    status: str
    message: str = ""
    path: str = ""


@dataclass(frozen=True)
class ContextGenerationResult:
    context: str
    status: str
    reason: str
    warnings: tuple[str, ...] = ()


def load_hook_config(config_path: Path | None = None) -> HookConfig:
    """Load hook configuration from JSON file. Returns defaults if missing."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return HookConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return HookConfig(
            graph_path=data.get("graph_path", ""),
            policy=data.get("policy", "technical"),
            max_chars=data.get("max_chars", 1500),
            include_project=data.get("include_project", True),
        )
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load hook config from %s: %s", path, exc)
        return HookConfig()


def save_hook_config(config: HookConfig, config_path: Path | None = None) -> Path:
    """Write hook configuration to JSON file. Creates parent dirs."""
    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(config), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------


def _load_graph_result(graph_path: str) -> GraphLoadResult:
    """Load a v4, v5, or v6 graph from a JSON file with diagnostics."""
    path = Path(graph_path)
    if not path.exists():
        return GraphLoadResult(None, status="missing_file", path=str(path))
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return GraphLoadResult(None, status="read_error", message=str(exc), path=str(path))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return GraphLoadResult(None, status="invalid_json", message=str(exc), path=str(path))
    if not isinstance(data, dict) or (
        "graph" not in data and "categories" not in data and "nodes" not in data and "edges" not in data
    ):
        return GraphLoadResult(
            None, status="invalid_graph", message="JSON does not look like a Cortex graph.", path=str(path)
        )
    try:
        version = data.get("schema_version", "")
        if version.startswith(("5", "6")) and "graph" in data:
            graph = CortexGraph.from_v5_json(data)
        else:
            graph = upgrade_v4_to_v5(data)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return GraphLoadResult(None, status="invalid_graph", message=str(exc), path=str(path))
    return GraphLoadResult(graph, status="ok", path=str(path))


def _load_graph(graph_path: str) -> CortexGraph | None:
    """Load a v4, v5, or v6 graph from a JSON file. Returns None on error."""
    return _load_graph_result(graph_path).graph


# ---------------------------------------------------------------------------
# Compact markdown formatting
# ---------------------------------------------------------------------------

# Tag categories grouped for compact display
_TAG_SECTIONS = [
    ("Tech Stack", ["technical_expertise"]),
    ("Projects", ["active_priorities"]),
    ("Domain", ["domain_knowledge"]),
    ("Professional", ["identity", "professional_context", "business_context"]),
    ("Preferences", ["user_preferences", "communication_preferences"]),
    ("Values", ["values", "constraints"]),
    ("Relationships", ["relationships"]),
]


def _format_compact_markdown(graph: CortexGraph, max_chars: int, focus_terms: set[str] | None = None) -> str:
    """Render a filtered graph as tight markdown grouped by tag category.

    Output format:
        ## Your Cortex Context

        **Tech Stack:** Python (0.9), Git (0.9)
        **Projects:** Cortex — Own your AI memory
        **Preferences:** Plans before coding, writes tests
    """
    # Group nodes by their primary tag section
    section_nodes: dict[str, list] = {label: [] for label, _ in _TAG_SECTIONS}
    uncategorized: list = []

    for node in sorted(graph.nodes.values(), key=lambda n: _context_rank(n, focus_terms), reverse=True):
        placed = False
        for section_label, section_tags in _TAG_SECTIONS:
            if any(t in section_tags for t in node.tags):
                section_nodes[section_label].append(node)
                placed = True
                break
        if not placed:
            uncategorized.append(node)

    lines = ["## Shared AI Context", ""]

    for section_label, _ in _TAG_SECTIONS:
        nodes = section_nodes[section_label]
        if not nodes:
            continue

        if section_label == "Projects":
            # Show project name + description
            parts = []
            for n in nodes:
                desc = n.brief or n.label
                # Strip "Active project: " prefix if present
                if desc.startswith("Active project: "):
                    desc = desc[len("Active project: ") :]
                parts.append(desc)
            lines.append(f"**{section_label}:** {'; '.join(parts)}")
        elif section_label == "Domain":
            # Show domain topics
            parts = [n.brief or n.label for n in nodes]
            lines.append(f"**{section_label}:** {', '.join(parts)}")
        else:
            # Show label (confidence) for tech, or just label for others
            parts = []
            for n in nodes:
                if section_label == "Tech Stack":
                    parts.append(f"{n.label} ({n.confidence:.1f})")
                else:
                    parts.append(n.brief or n.label)
            lines.append(f"**{section_label}:** {', '.join(parts)}")

    result = "\n".join(lines).strip()

    # Truncate to max_chars
    if len(result) > max_chars:
        result = result[: max_chars - 3].rsplit("\n", 1)[0] + "..."

    return result


def _focus_terms(cwd: str | None) -> set[str]:
    if not cwd:
        return set()
    parts: set[str] = set()
    for part in Path(cwd).parts:
        if not part or part in {"/", "."}:
            continue
        parts.update(_tokenize(part))
    return parts


def _context_rank(node, focus_terms: set[str] | None = None) -> tuple[float, float, int, str]:
    focus_terms = focus_terms or set()
    text_parts = [node.label, node.brief, node.full_description, *getattr(node, "aliases", [])]
    text = " ".join(part.lower() for part in text_parts if part)
    text_tokens = _tokenize(text)

    focus_boost = 0.0
    if focus_terms and focus_terms.intersection(text_tokens):
        focus_boost += 1.0

    tag_boost = 0.0
    if "active_priorities" in node.tags:
        tag_boost += 1.0
    if "communication_preferences" in node.tags or "user_preferences" in node.tags:
        tag_boost += 0.8
    if "technical_expertise" in node.tags:
        tag_boost += 0.5
    if getattr(node, "status", "") == "active":
        tag_boost += 0.3
    if getattr(node, "status", "") == "planned":
        tag_boost -= 0.1

    recency_boost = 0.0
    timestamp = getattr(node, "last_seen", "") or getattr(node, "first_seen", "") or getattr(node, "valid_from", "")
    if timestamp:
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age_days = max((datetime.now(timezone.utc) - parsed).days, 0)
            recency_boost = max(0.0, 0.4 - min(age_days / 365.0, 0.4))
        except ValueError:
            recency_boost = 0.0

    score = round(node.confidence + focus_boost + tag_boost + recency_boost, 4)
    return (score, node.confidence, node.mention_count, node.label.lower())


def _tokenize(value: str) -> set[str]:
    tokens = set()
    for match in _TOKEN_RE.findall(value.lower()):
        if len(match) < 3 or match in _FOCUS_STOP_WORDS:
            continue
        tokens.add(match)
    return tokens


def _log_generation_result(result: ContextGenerationResult, *, cwd: str | None = None) -> None:
    extra = {"cwd": cwd or ""}
    if result.status == "ok":
        if result.warnings:
            logger.warning("Generated hook context with warnings: %s", "; ".join(result.warnings), extra=extra)
        return
    message = f"Hook context generation {result.status}: {result.reason}"
    if result.status in {"error", "noop"}:
        logger.warning(message, extra=extra)
    else:
        logger.info(message, extra=extra)


# ---------------------------------------------------------------------------
# Context generation pipeline
# ---------------------------------------------------------------------------


def generate_compact_context_result(config: HookConfig, cwd: str | None = None) -> ContextGenerationResult:
    """Load graph, apply disclosure policy, and return compact markdown plus diagnostics."""
    if not config.graph_path:
        result = ContextGenerationResult("", status="noop", reason="missing_graph_path")
        _log_generation_result(result, cwd=cwd)
        return result

    load_result = _load_graph_result(config.graph_path)
    if load_result.graph is None:
        reason = load_result.status if not load_result.message else f"{load_result.status}: {load_result.message}"
        result = ContextGenerationResult("", status="error", reason=reason)
        _log_generation_result(result, cwd=cwd)
        return result

    graph = load_result.graph
    if not graph.nodes:
        result = ContextGenerationResult("", status="empty", reason="empty_graph")
        _log_generation_result(result, cwd=cwd)
        return result

    # Apply disclosure policy
    policy = BUILTIN_POLICIES.get(config.policy)
    warnings: list[str] = []
    if policy is None:
        policy = BUILTIN_POLICIES["technical"]
        warnings.append(f"Unknown policy '{config.policy}', using 'technical'")

    # If include_project and cwd provided, try to load project-specific graph
    if config.include_project and cwd:
        project_graph_path = Path(cwd) / ".cortex" / "graph.json"
        if project_graph_path.exists():
            project_result = _load_graph_result(str(project_graph_path))
            if project_result.graph and project_result.graph.nodes:
                # Merge project nodes into main graph for context
                for node in project_result.graph.nodes.values():
                    if node.id not in graph.nodes:
                        graph.nodes[node.id] = node
            elif project_result.graph is None:
                warnings.append(f"Project graph ignored: {project_result.status}")

    filtered = apply_disclosure(graph, policy)
    if not filtered.nodes:
        result = ContextGenerationResult("", status="empty", reason="filtered_empty", warnings=tuple(warnings))
        _log_generation_result(result, cwd=cwd)
        return result

    result = ContextGenerationResult(
        _format_compact_markdown(filtered, config.max_chars, focus_terms=_focus_terms(cwd)),
        status="ok",
        reason="generated",
        warnings=tuple(warnings),
    )
    _log_generation_result(result, cwd=cwd)
    return result


def generate_compact_context(config: HookConfig, cwd: str | None = None) -> str:
    """Load graph, apply disclosure policy, format as compact markdown."""
    return generate_compact_context_result(config, cwd=cwd).context


# ---------------------------------------------------------------------------
# Hook handler
# ---------------------------------------------------------------------------


def handle_session_start(input_json: dict, config: HookConfig) -> dict:
    """Process a Claude Code SessionStart hook event.

    Args:
        input_json: Parsed stdin from Claude Code
            (keys: session_id, cwd, transcript_path, etc.)
        config: Hook configuration

    Returns:
        Hook output dict with additionalContext for injection.
    """
    cwd = input_json.get("cwd")
    result = generate_compact_context_result(config, cwd=cwd)

    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": result.context,
        }
    }


# ---------------------------------------------------------------------------
# Install / uninstall helpers
# ---------------------------------------------------------------------------


def install_hook(
    graph_path: str,
    policy: str = "technical",
    max_chars: int = 1500,
    config_path: Path | None = None,
    settings_path: Path | None = None,
) -> tuple[Path, Path]:
    """Install the Cortex SessionStart hook.

    1. Writes hook config to ~/.cortex/hook-config.json
    2. Adds hook entry to ~/.claude/settings.json

    Returns (config_path, settings_path).
    """
    # Resolve the absolute path to the hook script
    hook_script = Path(__file__).resolve().parent.parent / "cortex-hook.py"

    # Save hook config
    config = HookConfig(
        graph_path=str(Path(graph_path).resolve()),
        policy=policy,
        max_chars=max_chars,
    )
    cfg_path = save_hook_config(config, config_path)

    # Update Claude Code settings
    settings = settings_path or (Path.home() / ".claude" / "settings.json")
    existing = {}
    if settings.exists():
        try:
            existing = json.loads(settings.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read existing Claude settings from %s: %s", settings, exc)
            existing = {}

    hooks = existing.setdefault("hooks", {})
    session_start = hooks.setdefault("SessionStart", [])

    # Build the hook command
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(hook_script))}"

    # Check if already installed (avoid duplicates — match by script name
    # to handle different quoting styles or python executables)
    already = any(
        any("cortex-hook.py" in h.get("command", "") for h in entry.get("hooks", [])) for entry in session_start
    )

    if not already:
        session_start.append(
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                    }
                ],
            }
        )

    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(existing, indent=2) + "\n",
        encoding="utf-8",
    )

    return cfg_path, settings


def uninstall_hook(
    config_path: Path | None = None,
    settings_path: Path | None = None,
) -> bool:
    """Remove the Cortex SessionStart hook.

    1. Deletes ~/.cortex/hook-config.json
    2. Removes hook entry from ~/.claude/settings.json

    Returns True if anything was removed.
    """
    removed = False

    # Remove config
    cfg_path = config_path or DEFAULT_CONFIG_PATH
    if cfg_path.exists():
        cfg_path.unlink()
        removed = True

    # Remove from Claude Code settings
    settings = settings_path or (Path.home() / ".claude" / "settings.json")
    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
            hooks = data.get("hooks", {})
            session_start = hooks.get("SessionStart", [])

            # Filter out cortex hook entries (match by cortex-hook.py in command,
            # not exact string, to handle quoting/executable differences)
            new_entries = []
            for entry in session_start:
                new_hooks = [h for h in entry.get("hooks", []) if "cortex-hook.py" not in h.get("command", "")]
                if new_hooks:
                    entry["hooks"] = new_hooks
                    new_entries.append(entry)
                else:
                    removed = True

            if new_entries:
                hooks["SessionStart"] = new_entries
            else:
                hooks.pop("SessionStart", None)
                removed = True

            # Clean up empty hooks dict
            if not hooks:
                data.pop("hooks", None)

            settings.write_text(
                json.dumps(data, indent=2) + "\n",
                encoding="utf-8",
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to update Claude settings during hook uninstall from %s: %s", settings, exc)
            pass

    return removed


def hook_status(
    config_path: Path | None = None,
    settings_path: Path | None = None,
) -> dict:
    """Check current hook installation status.

    Returns dict with keys: installed, config, settings_path, config_path.
    """
    cfg_path = config_path or DEFAULT_CONFIG_PATH
    settings = settings_path or (Path.home() / ".claude" / "settings.json")

    config = load_hook_config(cfg_path)
    installed = False

    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
            session_start = data.get("hooks", {}).get("SessionStart", [])
            installed = any(
                any("cortex-hook.py" in h.get("command", "") for h in entry.get("hooks", [])) for entry in session_start
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to inspect Claude settings for hook status from %s: %s", settings, exc)
            pass

    hook_script = Path(__file__).resolve().parent.parent / "cortex-hook.py"
    return {
        "installed": installed,
        "config": asdict(config),
        "config_path": str(cfg_path),
        "settings_path": str(settings),
        "hook_script": str(hook_script),
    }
