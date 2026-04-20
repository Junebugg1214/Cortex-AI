from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:  # pragma: no cover - Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib

from cortex.graph.graph import CortexGraph, Node, make_node_id_with_tag
from cortex.import_memory import NormalizedContext
from cortex.portability.context import CONTEXT_TARGETS, CORTEX_END, CORTEX_START, _resolve_path
from cortex.portability.portability import PORTABLE_DIRECT_TARGETS, PORTABLE_TARGET_ALIASES, PORTABLE_TARGET_ORDER
from cortex.portability.portable_graphs import merge_graphs

if TYPE_CHECKING:
    from cortex.extraction.extract_memory import AggressiveExtractor, PIIRedactor


def collect_bulk_texts(*args, **kwargs):
    from cortex.extraction import collect_bulk_texts as impl

    return impl(*args, **kwargs)


def get_bulk_backend():
    from cortex.extraction import get_bulk_backend as impl

    return impl()


def merged_v4_from_results(*args, **kwargs):
    from cortex.extraction import merged_v4_from_results as impl

    return impl(*args, **kwargs)


DEFAULT_DIRECT_TARGETS = ["claude-code", "codex", "cursor", "copilot", "windsurf", "gemini"]
ALL_PORTABLE_TARGETS = list(PORTABLE_TARGET_ORDER)

TOOL_DISPLAY_NAMES = {
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "claude-code": "Claude Code",
    "codex": "Codex",
    "cursor": "Cursor",
    "copilot": "Copilot",
    "gemini": "Gemini",
    "grok": "Grok",
    "hermes": "Hermes",
    "windsurf": "Windsurf",
}

ARTIFACT_TARGET_PATHS = {
    "claude": ("claude/claude_preferences.txt", "claude/claude_memories.json"),
    "chatgpt": ("chatgpt/custom_instructions.md", "chatgpt/custom_instructions.json"),
    "grok": ("grok/context_prompt.md", "grok/context_prompt.json"),
}

EXPORT_DISCOVERY_PATTERNS = {
    "chatgpt": (
        "*chatgpt*.zip",
        "*conversations*.json",
        "*chat.html",
        "custom_instructions.json",
        "custom_instructions.md",
    ),
    "claude": (
        "*claude*memories*.json",
        "*claude*preferences*.txt",
        "claude_memories.json",
        "claude_preferences.txt",
    ),
    "grok": (
        "*grok*context*.json",
        "*grok*context*.md",
        "context_prompt.json",
        "context_prompt.md",
    ),
    "hermes": (
        "USER.md",
        "MEMORY.md",
        "config.yaml",
    ),
}
DISCOVERY_MAX_DEPTH = 4


@dataclass(frozen=True, slots=True)
class MCPDiscoverySpec:
    path_templates: tuple[str, ...]
    schema: str


@dataclass(frozen=True, slots=True)
class CompatibilityEntry:
    target: str
    content_templates: tuple[str, ...] = ()
    export_patterns: tuple[str, ...] = ()
    mcp_specs: tuple[MCPDiscoverySpec, ...] = ()


COMPATIBILITY_MATRIX = {
    "chatgpt": CompatibilityEntry(
        target="chatgpt",
        export_patterns=EXPORT_DISCOVERY_PATTERNS["chatgpt"],
    ),
    "claude": CompatibilityEntry(
        target="claude",
        content_templates=(
            "{output_dir}/claude/claude_preferences.txt",
            "{output_dir}/claude/claude_memories.json",
        ),
        export_patterns=EXPORT_DISCOVERY_PATTERNS["claude"],
        mcp_specs=(
            MCPDiscoverySpec(
                path_templates=(
                    "{home}/Library/Application Support/Claude/claude_desktop_config.json",
                    "{xdg_config_home}/Claude/claude_desktop_config.json",
                    "{appdata}/Claude/claude_desktop_config.json",
                ),
                schema="mcpServers",
            ),
        ),
    ),
    "claude-code": CompatibilityEntry(
        target="claude-code",
        content_templates=(
            "{home}/.claude/CLAUDE.md",
            "{project}/CLAUDE.md",
        ),
        mcp_specs=(
            MCPDiscoverySpec(
                path_templates=("{project}/.mcp.json",),
                schema="mcpServers",
            ),
        ),
    ),
    "codex": CompatibilityEntry(
        target="codex",
        content_templates=("{project}/AGENTS.md",),
        mcp_specs=(
            MCPDiscoverySpec(
                path_templates=("{home}/.codex/config.toml",),
                schema="mcp_servers",
            ),
        ),
    ),
    "cursor": CompatibilityEntry(
        target="cursor",
        content_templates=(
            "{project}/.cursor/rules/*.mdc",
            "{project}/.cursor/rules/cortex.mdc",
        ),
        mcp_specs=(
            MCPDiscoverySpec(
                path_templates=(
                    "{home}/.cursor/mcp.json",
                    "{project}/.cursor/mcp.json",
                ),
                schema="mcpServers",
            ),
        ),
    ),
    "copilot": CompatibilityEntry(
        target="copilot",
        content_templates=("{project}/.github/copilot-instructions.md",),
        mcp_specs=(
            MCPDiscoverySpec(
                path_templates=("{project}/.vscode/mcp.json",),
                schema="servers",
            ),
        ),
    ),
    "gemini": CompatibilityEntry(
        target="gemini",
        content_templates=("{project}/GEMINI.md",),
        mcp_specs=(
            MCPDiscoverySpec(
                path_templates=(
                    "{home}/.gemini/settings.json",
                    "{project}/.gemini/settings.json",
                ),
                schema="mcpServers",
            ),
        ),
    ),
    "grok": CompatibilityEntry(
        target="grok",
        content_templates=(
            "{output_dir}/grok/context_prompt.md",
            "{output_dir}/grok/context_prompt.json",
        ),
        export_patterns=EXPORT_DISCOVERY_PATTERNS["grok"],
    ),
    "hermes": CompatibilityEntry(
        target="hermes",
        content_templates=(
            "{home}/.hermes/memories/USER.md",
            "{home}/.hermes/memories/MEMORY.md",
        ),
        mcp_specs=(
            MCPDiscoverySpec(
                path_templates=("{home}/.hermes/config.yaml",),
                schema="mcp_servers",
            ),
        ),
    ),
    "windsurf": CompatibilityEntry(
        target="windsurf",
        content_templates=("{project}/.windsurfrules",),
        mcp_specs=(
            MCPDiscoverySpec(
                path_templates=("{home}/.codeium/windsurf/mcp_config.json",),
                schema="mcpServers",
            ),
        ),
    ),
}

HERMES_SECTION_TAGS = {
    "identity": "identity",
    "professional context": "professional_context",
    "communication preferences": "communication_preferences",
    "working preferences": "user_preferences",
    "values": "values",
    "active priorities": "active_priorities",
    "technical context": "technical_expertise",
    "domain knowledge": "domain_knowledge",
    "business context": "business_context",
    "relationships": "relationships",
    "constraints": "constraints",
    "corrections": "correction_history",
}


def canonical_target_name(target: str) -> str:
    if target in PORTABLE_TARGET_ORDER:
        return target
    return PORTABLE_TARGET_ALIASES.get(target, target)


def resolve_requested_targets(targets: list[str]) -> list[str]:
    resolved: list[str] = []
    for raw_target in targets:
        canonical = canonical_target_name(raw_target)
        if canonical == "all":
            for target in ALL_PORTABLE_TARGETS:
                if target not in resolved:
                    resolved.append(target)
            continue
        if canonical not in resolved:
            resolved.append(canonical)
    return resolved


def display_name(target: str) -> str:
    return TOOL_DISPLAY_NAMES.get(target, target.replace("-", " ").title())


def _direct_target_paths(target: str, project_dir: str | None = None) -> list[Path]:
    paths: list[Path] = []
    for platform_name in PORTABLE_DIRECT_TARGETS.get(target, ()):
        target_config = CONTEXT_TARGETS.get(platform_name)
        if target_config is None:
            continue
        try:
            paths.append(_resolve_path(target_config.file_path, project_dir))
        except ValueError:
            continue
    return paths


def _artifact_target_paths(target: str, output_dir: Path) -> list[Path]:
    rel_paths = ARTIFACT_TARGET_PATHS.get(target, ())
    return [output_dir / rel_path for rel_path in rel_paths]


def expected_tool_paths(target: str, *, project_dir: str | None, output_dir: Path) -> list[Path]:
    if target == "hermes":
        return _expand_compatibility_templates(
            COMPATIBILITY_MATRIX["hermes"].content_templates,
            project_dir=Path(project_dir) if project_dir else None,
            output_dir=output_dir,
        )
    if target in PORTABLE_DIRECT_TARGETS:
        return _direct_target_paths(target, project_dir)
    return _artifact_target_paths(target, output_dir)


def _compatibility_tokens(project_dir: Path | None, output_dir: Path) -> dict[str, str]:
    home = Path.home()
    xdg_config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return {
        "home": str(home),
        "project": str(project_dir or Path.cwd()),
        "output_dir": str(output_dir),
        "appdata": os.environ.get("APPDATA", ""),
        "localappdata": os.environ.get("LOCALAPPDATA", ""),
        "xdg_config_home": str(xdg_config_home),
    }


def _expand_compatibility_templates(
    templates: tuple[str, ...],
    *,
    project_dir: Path | None,
    output_dir: Path,
) -> list[Path]:
    tokens = _compatibility_tokens(project_dir, output_dir)
    expanded: list[Path] = []
    seen: set[str] = set()
    for template in templates:
        try:
            rendered = template.format(**tokens)
        except KeyError:
            continue
        if not rendered:
            continue
        candidate = Path(rendered).expanduser()
        matches = (
            [path for path in candidate.parent.glob(candidate.name)]
            if any(char in candidate.name for char in "*?[")
            else [candidate]
        )
        for match in matches:
            key = str(match)
            if key in seen:
                continue
            seen.add(key)
            expanded.append(match)
    return expanded


def candidate_content_paths(target: str, *, project_dir: Path | None, output_dir: Path) -> list[Path]:
    entry = COMPATIBILITY_MATRIX.get(target)
    if entry is None:
        return expected_tool_paths(target, project_dir=str(project_dir) if project_dir else None, output_dir=output_dir)
    paths = _expand_compatibility_templates(entry.content_templates, project_dir=project_dir, output_dir=output_dir)
    if paths:
        return paths
    return expected_tool_paths(target, project_dir=str(project_dir) if project_dir else None, output_dir=output_dir)


def _config_mentions_cortex(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and "cortex" in key.casefold():
                return True
            if _config_mentions_cortex(child):
                return True
        return False
    if isinstance(value, list):
        return any(_config_mentions_cortex(item) for item in value)
    if isinstance(value, str):
        lowered = value.casefold()
        return "cortex-mcp" in lowered or "cortex.mcp" in lowered or ".cortex/config.toml" in lowered
    return False


def _mcp_servers_from_payload(payload: Any, schema: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if schema in {"mcpServers", "servers"}:
        servers = payload.get(schema, {})
        return servers if isinstance(servers, dict) else {}
    if schema == "mcp_servers":
        servers = payload.get("mcp_servers", {})
        return servers if isinstance(servers, dict) else {}
    return {}


def _parse_mcp_config(path: Path, *, schema: str) -> dict[str, Any] | None:
    try:
        if path.suffix.lower() == ".toml":
            payload = tomllib.loads(path.read_text(encoding="utf-8"))
        elif path.suffix.lower() in {".yaml", ".yml"}:
            payload = _parse_yaml_payload(path.read_text(encoding="utf-8"))
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError, tomllib.TOMLDecodeError):
        return None
    servers = _mcp_servers_from_payload(payload, schema)
    if not servers:
        return None
    return {
        "path": str(path),
        "schema": schema,
        "server_count": len(servers),
        "server_names": sorted(str(name) for name in servers),
        "cortex_configured": any(
            _config_mentions_cortex(config) or "cortex" in str(name).casefold() for name, config in servers.items()
        ),
    }


def _parse_yaml_payload(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    payload: dict[str, Any] = {}
    mcp_servers: dict[str, Any] = {}
    payload["mcp_servers"] = mcp_servers

    in_mcp_servers = False
    current_server: dict[str, Any] | None = None
    collecting_list_key = ""

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            collecting_list_key = ""
            current_server = None
            in_mcp_servers = stripped.startswith("mcp_servers:")
            continue
        if not in_mcp_servers:
            continue
        if indent == 2 and stripped.endswith(":"):
            current_server = {}
            mcp_servers[stripped[:-1].strip()] = current_server
            collecting_list_key = ""
            continue
        if current_server is None:
            continue
        if indent == 4 and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                current_server[key] = value
                collecting_list_key = ""
            else:
                current_server[key] = []
                collecting_list_key = key
            continue
        if indent >= 6 and stripped.startswith("- ") and collecting_list_key:
            item = stripped[2:].strip()
            if item.startswith('"') and item.endswith('"'):
                item = item[1:-1]
            current_server.setdefault(collecting_list_key, []).append(item)
    return payload


def discover_mcp_configs(target: str, *, project_dir: Path | None, output_dir: Path) -> list[dict[str, Any]]:
    entry = COMPATIBILITY_MATRIX.get(target)
    if entry is None:
        return []
    configs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for spec in entry.mcp_specs:
        for path in _expand_compatibility_templates(
            spec.path_templates, project_dir=project_dir, output_dir=output_dir
        ):
            if not path.exists() or not path.is_file():
                continue
            parsed = _parse_mcp_config(path, schema=spec.schema)
            if parsed is None or parsed["path"] in seen:
                continue
            seen.add(parsed["path"])
            configs.append(parsed)
    return configs


def mcp_note(configs: list[dict[str, Any]]) -> str:
    if not configs:
        return ""
    cortex_paths = [Path(item["path"]).name for item in configs if item["cortex_configured"]]
    if cortex_paths:
        return f"MCP: cortex in {cortex_paths[0]}"
    total_servers = sum(int(item["server_count"]) for item in configs)
    primary = Path(configs[0]["path"]).name
    return f"MCP: {total_servers} server(s) in {primary}"


def sanitized_mcp_note(configs: list[dict[str, Any]]) -> str:
    if not configs:
        return ""
    if any(item["cortex_configured"] for item in configs):
        return "MCP: Cortex configured"
    total_servers = sum(int(item["server_count"]) for item in configs)
    return f"MCP: {total_servers} server(s) configured"


def search_roots(project_dir: Path | None, extra_roots: list[Path] | None) -> list[Path]:
    roots: list[Path] = []
    for candidate in [
        project_dir,
        Path.home() / "Downloads",
        Path.home() / "Desktop",
        Path.home() / "Documents",
        *(extra_roots or []),
    ]:
        if candidate is None:
            continue
        path = Path(candidate)
        if path.exists():
            roots.append(path)
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root.resolve())
    return deduped


def _iter_discovery_matches(root: Path, pattern: str) -> list[Path]:
    root = root.resolve()
    if root.is_file():
        return [root] if fnmatch.fnmatch(root.name.casefold(), pattern.casefold()) else []

    matches: list[Path] = []
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            depth = 0
        if depth >= DISCOVERY_MAX_DEPTH:
            dirnames[:] = []
        for name in filenames:
            if fnmatch.fnmatch(name.casefold(), pattern.casefold()):
                matches.append((current_path / name).resolve())
    return matches


def find_export_file(target: str, roots: list[Path]) -> Path | None:
    entry = COMPATIBILITY_MATRIX.get(target)
    patterns = entry.export_patterns if entry is not None else ()
    matches: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        for pattern in patterns:
            for match in _iter_discovery_matches(root, pattern):
                if not match.is_file():
                    continue
                key = str(match)
                if key in seen:
                    continue
                seen.add(key)
                matches.append(match)
    if not matches:
        return None
    matches.sort(
        key=lambda path: (
            path.stat().st_mtime if path.exists() else 0.0,
            str(path),
        ),
        reverse=True,
    )
    return matches[0]


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _content_source_kind(path: Path, *, output_dir: Path) -> str:
    return "artifact" if _path_within(path, output_dir) else "local_context"


def _artifact_file_names(target: str) -> set[str]:
    return {Path(path).name for path in ARTIFACT_TARGET_PATHS.get(target, ())}


def _discovered_path_kind(target: str, path: Path, *, output_dir: Path) -> str:
    if _path_within(path, output_dir):
        return "artifact"
    if path.name in _artifact_file_names(target):
        return "artifact"
    return "export"


def discover_portability_sources(
    *,
    project_dir: Path,
    output_dir: Path,
    roots: list[Path],
    targets: list[str] | None = None,
) -> list[dict[str, Any]]:
    detected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for target in targets or ALL_PORTABLE_TARGETS:
        for path in [
            path
            for path in candidate_content_paths(target, project_dir=project_dir, output_dir=output_dir)
            if path.exists()
        ]:
            key = (target, "content", str(path))
            if key in seen:
                continue
            seen.add(key)
            kind = _content_source_kind(path, output_dir=output_dir)
            detected.append(
                {
                    "target": target,
                    "kind": kind,
                    "path": str(path),
                    "importable": True,
                    "permission": "explicit_extract",
                    "metadata_only": False,
                }
            )

        export_path = find_export_file(target, roots)
        if export_path is not None:
            kind = _discovered_path_kind(target, export_path, output_dir=output_dir)
            key = (target, kind, str(export_path))
            if key not in seen:
                seen.add(key)
                detected.append(
                    {
                        "target": target,
                        "kind": kind,
                        "path": str(export_path),
                        "importable": True,
                        "permission": "explicit_extract",
                        "metadata_only": False,
                    }
                )

        for config in discover_mcp_configs(target, project_dir=project_dir, output_dir=output_dir):
            key = (target, "mcp_config", config["path"])
            if key in seen:
                continue
            seen.add(key)
            detected.append(
                {
                    "target": target,
                    "kind": "mcp_config",
                    "path": config["path"],
                    "importable": False,
                    "permission": "explicit_extract",
                    "metadata_only": True,
                    "cortex_mcp_configured": bool(config["cortex_configured"]),
                    "mcp_server_count": int(config["server_count"]),
                    "schema": config["schema"],
                }
            )

    return detected


def human_age(path: Path, *, now: datetime | None = None) -> tuple[int | None, str]:
    if not path.exists():
        return None, ""
    now = now or datetime.now(timezone.utc)
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age_days = max((now - modified).days, 0)
    return age_days, modified.date().isoformat()


def _strip_markdown(text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text


def _label_key(label: str) -> str:
    lowered = label.casefold()
    lowered = lowered.replace("js", " js")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(lowered.split())


def _normalize_fact_label(label: str) -> str:
    cleaned = _strip_markdown(label).strip(" .-*")
    if not cleaned:
        return ""
    cleaned = re.sub(r"\((?:\d+(?:\.\d+)?)\)$", "", cleaned).strip(" .-*")
    cleaned = re.sub(
        r"^(?:Current priorities|Tech stack|Communication preferences|Working preferences|Constraints to respect|Values to honor|Avoid|Identity|Role|Business|Domain context|Relationships|Technical|Domain expertise|Currently focused on|Preferences|Communication|Constraints|How ChatGPT should respond|What ChatGPT should know about you|Context Grok should know|How Grok should respond):\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:User focus|User tech|User domain|User role|User relationship|User prefers|User preference|User is|User's business|Constraint|User avoids|User values|User clarified|Market context|Key metric):\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^Active project:\s*", "", cleaned, flags=re.IGNORECASE)
    if re.match(r"^(?:Most active commit hours|Peak coding hours):", cleaned, flags=re.IGNORECASE):
        return "Peak coding hours"
    if cleaned.casefold() in {
        "shared ai context",
        "chatgpt custom instructions",
        "grok context prompt",
        "paste these into chatgpt's custom instructions fields",
        "use this as a pinned workspace prompt or paste it into a fresh grok chat",
        "description",
        "globs",
        "alwaysapply",
    }:
        return ""
    return cleaned.strip(" .-*")


def dedupe_labels(labels: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        cleaned = _normalize_fact_label(label)
        if not cleaned:
            continue
        key = _label_key(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def label_map(labels: list[str] | set[str]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for label in labels:
        cleaned = _normalize_fact_label(label)
        if not cleaned:
            continue
        key = _label_key(cleaned)
        if key and key not in mapped:
            mapped[key] = cleaned
    return mapped


def _split_fact_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" in line:
            line = line.split(":", 1)[1]
        chunks.extend(re.split(r"[;,]\s*|\.\s+(?=[A-Z])", line))
    return chunks


def _strip_cursor_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        _, _, remainder = text[4:].partition("\n---\n")
        if remainder:
            return remainder
    return text


def _extract_cortex_section(text: str) -> tuple[str, str]:
    if CORTEX_START not in text or CORTEX_END not in text:
        return "", text
    start = text.index(CORTEX_START)
    section_start = start + len(CORTEX_START)
    end = text.index(CORTEX_END, section_start)
    inside = text[section_start:end].strip()
    outside = (text[:start] + text[end + len(CORTEX_END) :]).strip()
    return inside, outside


def _parse_section_value_text(text: str) -> list[str]:
    return dedupe_labels(_split_fact_chunks(text))


def _parse_shared_context_markdown(text: str) -> list[str]:
    labels: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("**") or ":**" not in line:
            continue
        _, _, value = line.partition(":**")
        labels.extend(_parse_section_value_text(value))
    return dedupe_labels(labels)


def _parse_claude_preferences_text(text: str) -> list[str]:
    labels: list[str] = []
    for line in text.splitlines():
        labels.extend(_parse_section_value_text(line))
    return dedupe_labels(labels)


def _labels_from_normalized_context(ctx: NormalizedContext) -> list[str]:
    labels: list[str] = []
    for topics in ctx.categories.values():
        for topic in topics:
            labels.append(topic.topic or topic.brief)
    return dedupe_labels(labels)


def _parse_chat_style_json(payload: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for value in payload.values():
        if isinstance(value, str):
            labels.extend(_parse_section_value_text(value))
    return dedupe_labels(labels)


def _parse_claude_json_payload(payload: Any) -> list[str]:
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]
    if not isinstance(payload, list):
        return []
    return _labels_from_normalized_context(NormalizedContext.from_claude_memories(payload))


def parse_target_file(target: str, path: Path) -> list[str]:
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if target == "claude":
                return _parse_claude_json_payload(payload)
            if target in {"chatgpt", "grok"} and isinstance(payload, dict):
                return _parse_chat_style_json(payload)
            if isinstance(payload, dict):
                return _parse_chat_style_json(payload)
            if isinstance(payload, list):
                return dedupe_labels([str(item) for item in payload if isinstance(item, str | int | float)])

        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []

    if target in PORTABLE_DIRECT_TARGETS:
        text = _strip_cursor_frontmatter(text)
        cortex_section, outside = _extract_cortex_section(text)
        labels = _parse_shared_context_markdown(cortex_section)
        labels.extend(extract_fact_labels_from_text(outside))
        return dedupe_labels(labels)
    if target == "hermes":
        return [node.label for node in extract_hermes_graph_from_text(text, include_unmanaged_text=True).nodes.values()]
    if target in {"chatgpt", "grok"}:
        return _parse_shared_context_markdown(text)
    if target == "claude":
        return _parse_claude_preferences_text(text)
    return extract_fact_labels_from_text(text)


def extract_fact_labels_from_text(text: str) -> list[str]:
    normalized = _strip_markdown(text)
    labels: list[str] = []
    for chunk in _split_fact_chunks(normalized):
        cleaned = re.sub(r"\([^)]*\)", "", chunk).strip(" .-*")
        if not cleaned:
            continue
        if len(cleaned) > 120:
            cleaned = cleaned[:120].rsplit(" ", 1)[0]
        labels.append(cleaned)
    return dedupe_labels(labels)


def _stringify_json_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            lines.extend(_stringify_json_value(item))
        return lines
    if isinstance(value, dict):
        lines: list[str] = []
        for key, child in value.items():
            for entry in _stringify_json_value(child):
                if entry:
                    lines.append(f"{key}: {entry}")
        return lines
    if isinstance(value, int | float):
        return [str(value)]
    return []


def _render_direct_target_text(text: str, *, include_unmanaged_text: bool) -> str:
    text = _strip_cursor_frontmatter(text)
    cortex_section, outside = _extract_cortex_section(text)
    if cortex_section:
        parts = [cortex_section.strip()]
        if include_unmanaged_text and outside.strip():
            parts.append(outside.strip())
        return "\n\n".join(part for part in parts if part).strip()
    if include_unmanaged_text:
        return text.strip()
    return ""


def _render_hermes_target_text(text: str, *, include_unmanaged_text: bool) -> str:
    cortex_section, outside = _extract_cortex_section(text)
    source = cortex_section if cortex_section else (text if include_unmanaged_text else "")
    lines: list[str] = []
    current_heading = ""
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            current_heading = line.lstrip("#").strip()
            continue
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        if current_heading:
            line = f"{current_heading}: {line}"
        if line:
            lines.append(line)
    if include_unmanaged_text and outside.strip():
        lines.append(outside.strip())
    return "\n".join(lines).strip()


def extract_hermes_graph_from_text(text: str, *, include_unmanaged_text: bool = False) -> CortexGraph:
    cortex_section, outside = _extract_cortex_section(text)
    source_parts: list[str] = []
    if cortex_section:
        source_parts.append(cortex_section)
    elif include_unmanaged_text:
        source_parts.append(text)
    if include_unmanaged_text and outside.strip():
        source_parts.append(outside.strip())
    source = "\n".join(part for part in source_parts if part).strip()
    graph = CortexGraph()
    current_heading = ""
    current_tag = ""
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            current_heading = line.lstrip("#").strip()
            current_tag = HERMES_SECTION_TAGS.get(current_heading.casefold(), "")
            continue
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        if not line or not current_tag:
            continue
        label = _normalize_fact_label(line)
        if not label:
            continue
        graph.add_node(
            Node(
                id=make_node_id_with_tag(label, current_tag),
                label=label,
                tags=[current_tag],
                confidence=0.82,
                brief=f"{current_heading}: {label}",
            )
        )
    return graph


def render_detected_source_text(target: str, path: Path, *, include_unmanaged_text: bool = False) -> str:
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if target == "claude":
                return "\n".join(_parse_claude_json_payload(payload))
            if target in {"chatgpt", "grok"} and isinstance(payload, dict):
                lines: list[str] = []
                for value in payload.values():
                    lines.extend(_stringify_json_value(value))
                return "\n".join(lines)
            return "\n".join(_stringify_json_value(payload))
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return ""

    if target in PORTABLE_DIRECT_TARGETS:
        return _render_direct_target_text(text, include_unmanaged_text=include_unmanaged_text)
    if target == "hermes":
        return _render_hermes_target_text(text, include_unmanaged_text=include_unmanaged_text)
    return text.strip()


def _extract_graph_from_text(text: str) -> CortexGraph:
    from cortex.compat import upgrade_v4_to_v5
    from cortex.extraction.extract_memory import AggressiveExtractor

    extractor = AggressiveExtractor()
    payload = extractor.process_plain_text(text)
    graph = upgrade_v4_to_v5(payload)
    if payload.get("resolution_conflicts"):
        graph.meta["resolution_conflicts"] = [dict(item) for item in payload.get("resolution_conflicts", [])]
    return graph


def sanitize_detected_source(source: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "target",
        "kind",
        "importable",
        "permission",
        "metadata_only",
        "cortex_mcp_configured",
        "mcp_server_count",
        "schema",
    }
    return {key: value for key, value in source.items() if key in allowed_keys}


def _mcp_metadata_text(target: str, source: dict[str, Any]) -> str:
    server_count = int(source.get("mcp_server_count", 0))
    if source.get("cortex_mcp_configured"):
        return (
            f"{display_name(target)} is configured to use Cortex MCP. "
            f"{display_name(target)} has {server_count} MCP servers configured."
        )
    return f"{display_name(target)} has {server_count} MCP servers configured."


def graph_from_hermes_paths(paths: list[str]) -> CortexGraph:
    merged = CortexGraph()
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix.lower() != ".md" or not path.exists():
            continue
        merged = merge_graphs(
            merged,
            extract_hermes_graph_from_text(
                path.read_text(encoding="utf-8", errors="replace"), include_unmanaged_text=True
            ),
        )
    return merged


def run_extraction_data(extractor: AggressiveExtractor, data: Any, fmt: str) -> dict[str, Any]:
    backend = get_bulk_backend()
    if backend.__class__.__name__ == "HeuristicBackend":
        return merged_v4_from_results(
            backend.extract_bulk([], context={"extractor": extractor, "data": data, "fmt": fmt})
        )
    texts = collect_bulk_texts(data, fmt)
    return merged_v4_from_results(backend.extract_bulk(texts, context={"data": data, "fmt": fmt}))


def extract_graph_from_detected_sources(
    *,
    targets: list[str],
    store_dir: Path,
    detected_sources: list[dict[str, Any]],
    include_config_metadata: bool = False,
    include_unmanaged_text: bool = False,
    redactor: PIIRedactor | None = None,
) -> dict[str, Any]:
    from cortex.compat import upgrade_v4_to_v5
    from cortex.extraction.extract_memory import AggressiveExtractor, load_file
    from cortex.extraction.sources import SourceRegistry
    from cortex.graph.claims import stamp_graph_provenance
    from cortex.graph.temporal import TEMPORAL_REVIEW_QUEUE_KEY, apply_temporal_review_policy

    requested = resolve_requested_targets(targets)
    selected_targets = set(requested)
    selected_sources: list[dict[str, Any]] = []
    skipped_sources: list[dict[str, Any]] = []
    merged = CortexGraph()
    registry = SourceRegistry.for_store(store_dir)
    resolution_conflicts: list[dict[str, Any]] = []
    temporal_review_queue: list[dict[str, Any]] = []

    for source in detected_sources:
        if source["target"] not in selected_targets:
            continue
        path = Path(source["path"])
        kind = str(source["kind"])

        if kind == "mcp_config" and not include_config_metadata:
            skipped_sources.append({**source, "reason": "metadata_only"})
            continue

        source_graph = CortexGraph()
        try:
            if kind == "export":
                data, fmt = load_file(path)
                payload = run_extraction_data(AggressiveExtractor(redactor=redactor), data, fmt)
                source_graph = upgrade_v4_to_v5(payload)
                resolution_conflicts.extend(list(payload.get("resolution_conflicts", [])))
                source = {**source, "input_format": fmt}
            elif kind == "mcp_config":
                metadata_text = _mcp_metadata_text(source["target"], source)
                source_graph = _extract_graph_from_text(metadata_text)
            else:
                if source["target"] == "hermes":
                    rendered = path.read_text(encoding="utf-8", errors="replace")
                else:
                    rendered = render_detected_source_text(
                        source["target"],
                        path,
                        include_unmanaged_text=include_unmanaged_text,
                    )
                if not rendered.strip():
                    reason = "unmanaged_only" if kind == "local_context" else "empty"
                    skipped_sources.append({**source, "reason": reason})
                    continue
                if redactor is not None:
                    rendered = redactor.redact(rendered)
                if source["target"] == "hermes":
                    source_graph = extract_hermes_graph_from_text(
                        rendered,
                        include_unmanaged_text=include_unmanaged_text,
                    )
                else:
                    source_graph = _extract_graph_from_text(rendered)
            resolution_conflicts.extend(list(source_graph.meta.get("resolution_conflicts", [])))
        except Exception:
            skipped_sources.append({**source, "reason": "unreadable"})
            continue

        registry_payload = registry.register_path(
            path,
            label=path.name,
            metadata={"target": source["target"], "kind": kind},
            force_reingest=True,
        )
        stamp_graph_provenance(
            source_graph,
            source=registry_payload["stable_id"],
            stable_source_id=registry_payload["stable_id"],
            source_label=path.name,
            method="detected_source",
            metadata={"target": source["target"], "kind": kind},
        )
        review_payload = apply_temporal_review_policy(source_graph)
        temporal_review_queue.extend(list(review_payload.get("queue", [])))

        if not source_graph.nodes:
            skipped_sources.append({**source, "reason": "no_facts"})
            continue
        selected_sources.append(
            {
                **source,
                "fact_count": len(source_graph.nodes),
                "source_id": registry_payload["stable_id"],
                "source_labels": list(registry_payload["labels"]),
            }
        )
        merged = merge_graphs(merged, source_graph)

    if resolution_conflicts:
        merged.meta["resolution_conflicts"] = resolution_conflicts
    if temporal_review_queue:
        merged.meta[TEMPORAL_REVIEW_QUEUE_KEY] = temporal_review_queue
    return {
        "graph": merged,
        "selected_sources": selected_sources,
        "skipped_sources": skipped_sources,
        "detected_sources": detected_sources,
        "resolution_conflicts": resolution_conflicts,
    }


__all__ = [
    "ALL_PORTABLE_TARGETS",
    "DEFAULT_DIRECT_TARGETS",
    "MCPDiscoverySpec",
    "CompatibilityEntry",
    "candidate_content_paths",
    "canonical_target_name",
    "dedupe_labels",
    "discover_mcp_configs",
    "discover_portability_sources",
    "display_name",
    "expected_tool_paths",
    "extract_fact_labels_from_text",
    "extract_graph_from_detected_sources",
    "extract_hermes_graph_from_text",
    "find_export_file",
    "graph_from_hermes_paths",
    "human_age",
    "label_map",
    "mcp_note",
    "parse_target_file",
    "render_detected_source_text",
    "resolve_requested_targets",
    "run_extraction_data",
    "sanitized_mcp_note",
    "sanitize_detected_source",
    "search_roots",
]
