"""
Cortex Hook — Auto-inject identity context into Claude Code sessions.

Provides a SessionStart hook that loads your Cortex graph, applies a
disclosure policy, and returns compact markdown for injection as a
system message.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cortex.graph import CortexGraph, CATEGORY_ORDER
from cortex.compat import upgrade_v4_to_v5
from cortex.upai.disclosure import BUILTIN_POLICIES, DisclosurePolicy, apply_disclosure


# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_DIR = Path.home() / ".cortex"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "hook-config.json"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class HookConfig:
    graph_path: str = ""            # Path to Cortex graph JSON
    policy: str = "technical"       # Disclosure policy name
    max_chars: int = 1500           # Cap injection size
    include_project: bool = True    # Include project-specific context


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
    except (json.JSONDecodeError, OSError):
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

def _load_graph(graph_path: str) -> CortexGraph | None:
    """Load a v4, v5, or v6 graph from a JSON file. Returns None on error."""
    path = Path(graph_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        version = data.get("schema_version", "")
        if version.startswith(("5", "6")) and "graph" in data:
            return CortexGraph.from_v5_json(data)
        return upgrade_v4_to_v5(data)
    except (json.JSONDecodeError, OSError, KeyError):
        return None


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


def _format_compact_markdown(graph: CortexGraph, max_chars: int) -> str:
    """Render a filtered graph as tight markdown grouped by tag category.

    Output format:
        ## Your Cortex Context

        **Tech Stack:** Python (0.9), Git (0.9)
        **Projects:** chatbot-memory-skills — Own your AI memory
        **Preferences:** Plans before coding, writes tests
    """
    # Group nodes by their primary tag section
    section_nodes: dict[str, list] = {label: [] for label, _ in _TAG_SECTIONS}
    uncategorized: list = []

    for node in sorted(graph.nodes.values(), key=lambda n: n.confidence, reverse=True):
        placed = False
        for section_label, section_tags in _TAG_SECTIONS:
            if any(t in section_tags for t in node.tags):
                section_nodes[section_label].append(node)
                placed = True
                break
        if not placed:
            uncategorized.append(node)

    lines = ["## Your Cortex Context", ""]

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
                    desc = desc[len("Active project: "):]
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
        result = result[:max_chars - 3].rsplit("\n", 1)[0] + "..."

    return result


# ---------------------------------------------------------------------------
# Context generation pipeline
# ---------------------------------------------------------------------------

def generate_compact_context(config: HookConfig, cwd: str | None = None) -> str:
    """Load graph, apply disclosure policy, format as compact markdown.

    Returns empty string if graph can't be loaded or is empty.
    """
    if not config.graph_path:
        return ""

    graph = _load_graph(config.graph_path)
    if graph is None or not graph.nodes:
        return ""

    # Apply disclosure policy
    policy = BUILTIN_POLICIES.get(config.policy)
    if policy is None:
        policy = BUILTIN_POLICIES["technical"]

    filtered = apply_disclosure(graph, policy)
    if not filtered.nodes:
        return ""

    return _format_compact_markdown(filtered, config.max_chars)


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
    context = generate_compact_context(config, cwd=cwd)

    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
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
        except (json.JSONDecodeError, OSError):
            existing = {}

    hooks = existing.setdefault("hooks", {})
    session_start = hooks.setdefault("SessionStart", [])

    # Build the hook command
    command = f"python3 {hook_script}"

    # Check if already installed (avoid duplicates)
    already = any(
        any(h.get("command") == command for h in entry.get("hooks", []))
        for entry in session_start
    )

    if not already:
        session_start.append({
            "matcher": "*",
            "hooks": [{
                "type": "command",
                "command": command,
            }],
        })

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
    hook_script = Path(__file__).resolve().parent.parent / "cortex-hook.py"
    command = f"python3 {hook_script}"

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

            # Filter out cortex hook entries
            new_entries = []
            for entry in session_start:
                new_hooks = [
                    h for h in entry.get("hooks", [])
                    if h.get("command") != command
                ]
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
        except (json.JSONDecodeError, OSError):
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
    hook_script = Path(__file__).resolve().parent.parent / "cortex-hook.py"
    command = f"python3 {hook_script}"

    config = load_hook_config(cfg_path)
    installed = False

    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
            session_start = data.get("hooks", {}).get("SessionStart", [])
            installed = any(
                any(h.get("command") == command for h in entry.get("hooks", []))
                for entry in session_start
            )
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "installed": installed,
        "config": asdict(config),
        "config_path": str(cfg_path),
        "settings_path": str(settings),
        "hook_script": str(hook_script),
    }
