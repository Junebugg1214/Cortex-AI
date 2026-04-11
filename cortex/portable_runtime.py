from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib

from cortex.atomic_io import atomic_write_text, locked_path
from cortex.compat import upgrade_v4_to_v5
from cortex.context import CONTEXT_TARGETS, CORTEX_END, CORTEX_START, _resolve_path, write_context
from cortex.extract_memory import AggressiveExtractor, PIIRedactor, load_file
from cortex.graph import CortexGraph, Node, make_node_id_with_tag
from cortex.hermes_integration import build_hermes_documents, install_hermes_context
from cortex.hooks import HookConfig, generate_compact_context
from cortex.hooks import _load_graph as load_graph_optional
from cortex.import_memory import NormalizedContext, export_claude_memories, export_claude_preferences
from cortex.portability import (
    PORTABLE_DIRECT_TARGETS,
    PORTABLE_TARGET_ALIASES,
    PORTABLE_TARGET_ORDER,
    build_instruction_pack,
    export_artifact_targets,
)
from cortex.portable_builders import (
    build_git_history_graph,
    build_github_graph,
    build_project_graph,
    build_resume_graph,
)
from cortex.portable_graphs import extract_graph_from_statement, merge_graphs
from cortex.upai.disclosure import BUILTIN_POLICIES, DisclosurePolicy, apply_disclosure

STATE_VERSION = "1.0"
DEFAULT_STALE_DAYS = 30
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

SMART_ROUTE_TAGS = {
    "claude": [
        "identity",
        "professional_context",
        "technical_expertise",
        "domain_knowledge",
        "active_priorities",
        "communication_preferences",
        "user_preferences",
    ],
    "claude-code": [
        "technical_expertise",
        "domain_knowledge",
        "active_priorities",
        "professional_context",
        "communication_preferences",
        "user_preferences",
    ],
    "chatgpt": [
        "identity",
        "professional_context",
        "business_context",
        "active_priorities",
        "technical_expertise",
        "domain_knowledge",
        "relationships",
        "values",
        "constraints",
        "user_preferences",
        "communication_preferences",
    ],
    "codex": [
        "technical_expertise",
        "domain_knowledge",
        "active_priorities",
        "communication_preferences",
        "user_preferences",
        "constraints",
    ],
    "cursor": [
        "technical_expertise",
        "active_priorities",
        "communication_preferences",
        "user_preferences",
        "domain_knowledge",
    ],
    "copilot": [
        "technical_expertise",
        "communication_preferences",
        "user_preferences",
        "constraints",
    ],
    "gemini": [
        "domain_knowledge",
        "professional_context",
        "business_context",
        "active_priorities",
        "technical_expertise",
        "communication_preferences",
    ],
    "grok": [
        "identity",
        "professional_context",
        "business_context",
        "active_priorities",
        "domain_knowledge",
        "values",
        "communication_preferences",
    ],
    "hermes": [
        "identity",
        "professional_context",
        "business_context",
        "active_priorities",
        "technical_expertise",
        "domain_knowledge",
        "relationships",
        "constraints",
        "communication_preferences",
        "user_preferences",
        "values",
    ],
    "windsurf": [
        "technical_expertise",
        "active_priorities",
        "communication_preferences",
        "user_preferences",
        "domain_knowledge",
    ],
}


@dataclass(slots=True)
class TargetState:
    target: str
    mode: str = "full"
    policy: str = "technical"
    route_tags: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    fingerprints: dict[str, str] = field(default_factory=dict)
    fact_ids: list[str] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = ""
    snapshot_path: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetState:
        return cls(
            target=str(data.get("target", "")),
            mode=str(data.get("mode", "full")),
            policy=str(data.get("policy", "technical")),
            route_tags=[str(tag) for tag in data.get("route_tags", [])],
            paths=[str(path) for path in data.get("paths", [])],
            fingerprints={str(key): str(value) for key, value in data.get("fingerprints", {}).items()},
            fact_ids=[str(value) for value in data.get("fact_ids", [])],
            facts=[dict(item) for item in data.get("facts", [])],
            updated_at=str(data.get("updated_at", "")),
            snapshot_path=str(data.get("snapshot_path", "")),
            note=str(data.get("note", "")),
        )


@dataclass(slots=True)
class PortabilityState:
    graph_path: str = ""
    output_dir: str = ""
    project_dir: str = ""
    updated_at: str = ""
    targets: dict[str, TargetState] = field(default_factory=dict)
    schema_version: str = STATE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "graph_path": self.graph_path,
            "output_dir": self.output_dir,
            "project_dir": self.project_dir,
            "updated_at": self.updated_at,
            "targets": {name: target.to_dict() for name, target in self.targets.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortabilityState:
        return cls(
            schema_version=str(data.get("schema_version", STATE_VERSION)),
            graph_path=str(data.get("graph_path", "")),
            output_dir=str(data.get("output_dir", "")),
            project_dir=str(data.get("project_dir", "")),
            updated_at=str(data.get("updated_at", "")),
            targets={
                str(name): TargetState.from_dict(payload)
                for name, payload in dict(data.get("targets", {})).items()
                if isinstance(payload, dict)
            },
        )


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def portability_dir(store_dir: Path) -> Path:
    return store_dir / "portable"


def portability_state_path(store_dir: Path) -> Path:
    return portability_dir(store_dir) / "state.json"


def portability_snapshot_dir(store_dir: Path) -> Path:
    return portability_dir(store_dir) / "snapshots"


def default_graph_path(store_dir: Path) -> Path:
    return portability_dir(store_dir) / "context.json"


def default_output_dir(store_dir: Path) -> Path:
    return portability_dir(store_dir) / "artifacts"


def ensure_state_dirs(store_dir: Path) -> None:
    portability_dir(store_dir).mkdir(parents=True, exist_ok=True)
    portability_snapshot_dir(store_dir).mkdir(parents=True, exist_ok=True)


def load_portability_state(store_dir: Path) -> PortabilityState:
    path = portability_state_path(store_dir)
    if not path.exists():
        return PortabilityState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return PortabilityState()
    if not isinstance(data, dict):
        return PortabilityState()
    return PortabilityState.from_dict(data)


def save_portability_state(store_dir: Path, state: PortabilityState) -> Path:
    ensure_state_dirs(store_dir)
    path = portability_state_path(store_dir)
    with locked_path(path):
        atomic_write_text(path, json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_fingerprint(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return ""


def _graph_fact_rows(graph: CortexGraph) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in sorted(graph.nodes.values(), key=lambda item: (item.label.lower(), item.id)):
        rows.append(
            {
                "id": node.id,
                "label": node.label,
                "brief": node.brief,
                "tags": list(node.tags),
                "confidence": round(node.confidence, 2),
            }
        )
    return rows


def _write_graph(path: Path, graph: CortexGraph) -> None:
    with locked_path(path):
        atomic_write_text(path, json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def _load_graph(path: Path) -> CortexGraph | None:
    if not path.exists():
        return None
    return load_graph_optional(str(path))


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


def _candidate_content_paths(target: str, *, project_dir: Path | None, output_dir: Path) -> list[Path]:
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
    current_name = ""
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
            current_name = ""
            current_server = None
            in_mcp_servers = stripped.startswith("mcp_servers:")
            continue
        if not in_mcp_servers:
            continue
        if indent == 2 and stripped.endswith(":"):
            current_name = stripped[:-1].strip()
            current_server = {}
            mcp_servers[current_name] = current_server
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


def _discover_mcp_configs(target: str, *, project_dir: Path | None, output_dir: Path) -> list[dict[str, Any]]:
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


def _mcp_note(configs: list[dict[str, Any]]) -> str:
    if not configs:
        return ""
    cortex_paths = [Path(item["path"]).name for item in configs if item["cortex_configured"]]
    if cortex_paths:
        return f"MCP: cortex in {cortex_paths[0]}"
    total_servers = sum(int(item["server_count"]) for item in configs)
    primary = Path(configs[0]["path"]).name
    return f"MCP: {total_servers} server(s) in {primary}"


def _sanitized_mcp_note(configs: list[dict[str, Any]]) -> str:
    if not configs:
        return ""
    if any(item["cortex_configured"] for item in configs):
        return "MCP: Cortex configured"
    total_servers = sum(int(item["server_count"]) for item in configs)
    return f"MCP: {total_servers} server(s) configured"


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


def detect_portability_sources(
    *,
    store_dir: Path,
    project_dir: Path,
    extra_roots: list[Path] | None = None,
) -> list[dict[str, Any]]:
    state = load_portability_state(store_dir)
    output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(store_dir)
    roots = _search_roots(project_dir, extra_roots)
    detected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for target in ALL_PORTABLE_TARGETS:
        for path in [
            path
            for path in _candidate_content_paths(target, project_dir=project_dir, output_dir=output_dir)
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

        export_path = _find_export_file(target, roots)
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

        for config in _discover_mcp_configs(target, project_dir=project_dir, output_dir=output_dir):
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


def _human_age(path: Path, *, now: datetime | None = None) -> tuple[int | None, str]:
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


def _dedupe_labels(labels: list[str]) -> list[str]:
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


def _label_map(labels: list[str] | set[str]) -> dict[str, str]:
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
    return _dedupe_labels(_split_fact_chunks(text))


def _parse_shared_context_markdown(text: str) -> list[str]:
    labels: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("**") or ":**" not in line:
            continue
        _, _, value = line.partition(":**")
        labels.extend(_parse_section_value_text(value))
    return _dedupe_labels(labels)


def _parse_claude_preferences_text(text: str) -> list[str]:
    labels: list[str] = []
    for line in text.splitlines():
        labels.extend(_parse_section_value_text(line))
    return _dedupe_labels(labels)


def _labels_from_normalized_context(ctx: NormalizedContext) -> list[str]:
    labels: list[str] = []
    for topics in ctx.categories.values():
        for topic in topics:
            labels.append(topic.topic or topic.brief)
    return _dedupe_labels(labels)


def _parse_chat_style_json(payload: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for value in payload.values():
        if isinstance(value, str):
            labels.extend(_parse_section_value_text(value))
    return _dedupe_labels(labels)


def _parse_claude_json_payload(payload: Any) -> list[str]:
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]
    if not isinstance(payload, list):
        return []
    return _labels_from_normalized_context(NormalizedContext.from_claude_memories(payload))


def _parse_target_file(target: str, path: Path) -> list[str]:
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
                return _dedupe_labels([str(item) for item in payload if isinstance(item, str | int | float)])

        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []

    if target in PORTABLE_DIRECT_TARGETS:
        text = _strip_cursor_frontmatter(text)
        cortex_section, outside = _extract_cortex_section(text)
        labels = _parse_shared_context_markdown(cortex_section)
        labels.extend(extract_fact_labels_from_text(outside))
        return _dedupe_labels(labels)
    if target == "hermes":
        return [
            node.label for node in _extract_hermes_graph_from_text(text, include_unmanaged_text=True).nodes.values()
        ]
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
    return _dedupe_labels(labels)


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


def _extract_hermes_graph_from_text(text: str, *, include_unmanaged_text: bool = False) -> CortexGraph:
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
    extractor = AggressiveExtractor()
    payload = extractor.process_plain_text(text)
    return upgrade_v4_to_v5(payload)


def _sanitize_detected_source(source: dict[str, Any]) -> dict[str, Any]:
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


def _graph_from_hermes_paths(paths: list[str]) -> CortexGraph:
    merged = CortexGraph()
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix.lower() != ".md" or not path.exists():
            continue
        merged = merge_graphs(
            merged,
            _extract_hermes_graph_from_text(
                path.read_text(encoding="utf-8", errors="replace"), include_unmanaged_text=True
            ),
        )
    return merged


def extract_graph_from_detected_sources(
    *,
    targets: list[str],
    store_dir: Path,
    project_dir: Path,
    extra_roots: list[Path] | None = None,
    include_config_metadata: bool = False,
    include_unmanaged_text: bool = False,
    redactor: PIIRedactor | None = None,
) -> dict[str, Any]:
    requested = resolve_requested_targets(targets)
    detected = detect_portability_sources(store_dir=store_dir, project_dir=project_dir, extra_roots=extra_roots)
    selected_targets = set(requested)
    selected_sources: list[dict[str, Any]] = []
    skipped_sources: list[dict[str, Any]] = []
    merged = CortexGraph()

    for source in detected:
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
                payload = _run_extraction_data(AggressiveExtractor(redactor=redactor), data, fmt)
                source_graph = upgrade_v4_to_v5(payload)
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
                    source_graph = _extract_hermes_graph_from_text(
                        rendered,
                        include_unmanaged_text=include_unmanaged_text,
                    )
                else:
                    source_graph = _extract_graph_from_text(rendered)
        except Exception:
            skipped_sources.append({**source, "reason": "unreadable"})
            continue

        if not source_graph.nodes:
            skipped_sources.append({**source, "reason": "no_facts"})
            continue
        selected_sources.append({**source, "fact_count": len(source_graph.nodes)})
        merged = merge_graphs(merged, source_graph)

    return {
        "graph": merged,
        "selected_sources": selected_sources,
        "skipped_sources": skipped_sources,
        "detected_sources": detected,
    }


def load_canonical_graph(store_dir: Path, state: PortabilityState | None = None) -> tuple[CortexGraph, Path]:
    state = state or load_portability_state(store_dir)
    graph_path = Path(state.graph_path) if state.graph_path else default_graph_path(store_dir)
    graph = _load_graph(graph_path)
    if graph is None:
        graph = CortexGraph()
    return graph, graph_path


def save_canonical_graph(
    store_dir: Path, graph: CortexGraph, *, state: PortabilityState | None = None, graph_path: Path | None = None
) -> tuple[PortabilityState, Path]:
    state = state or load_portability_state(store_dir)
    ensure_state_dirs(store_dir)
    target_path = graph_path or (Path(state.graph_path) if state.graph_path else default_graph_path(store_dir))
    _write_graph(target_path, graph)
    state.graph_path = str(target_path)
    state.updated_at = iso_now()
    if not state.output_dir:
        state.output_dir = str(default_output_dir(store_dir))
    save_portability_state(store_dir, state)
    return state, target_path


def _policy_for_target(target: str, *, smart: bool, policy_name: str) -> tuple[DisclosurePolicy, list[str]]:
    if smart:
        route_tags = list(SMART_ROUTE_TAGS.get(target, BUILTIN_POLICIES["technical"].include_tags))
        return (
            DisclosurePolicy(
                name=f"smart-{target}",
                include_tags=route_tags,
                exclude_tags=["negations"],
                min_confidence=0.45,
                redact_properties=[],
            ),
            route_tags,
        )
    builtin = BUILTIN_POLICIES.get(policy_name, BUILTIN_POLICIES["technical"])
    return builtin, list(builtin.include_tags)


def sync_targets(
    graph: CortexGraph,
    *,
    targets: list[str],
    store_dir: Path,
    project_dir: str | None,
    output_dir: Path,
    graph_path: Path,
    policy_name: str = "technical",
    smart: bool = False,
    max_chars: int = 1500,
    dry_run: bool = False,
    state: PortabilityState | None = None,
    identity: Any | None = None,
    persist_state: bool = True,
) -> dict[str, Any]:
    state = state or load_portability_state(store_dir)
    results: list[dict[str, Any]] = []
    ensure_state_dirs(store_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for target in resolve_requested_targets(targets):
        policy, route_tags = _policy_for_target(target, smart=smart, policy_name=policy_name)
        filtered = apply_disclosure(graph, policy)
        if target == "hermes":
            install_result = install_hermes_context(
                NormalizedContext.from_v5(filtered.export_v5()),
                project_dir=project_dir,
                store_dir=store_dir,
                max_chars=max_chars,
                min_confidence=policy.min_confidence,
                dry_run=dry_run,
            )
            paths = [str(path) for path in install_result.paths]
            status = install_result.status
            note = install_result.note
        elif target in PORTABLE_DIRECT_TARGETS:
            with tempfile.TemporaryDirectory() as tmp_dir:
                filtered_path = Path(tmp_dir) / f"{target}.json"
                _write_graph(filtered_path, filtered)
                write_results = write_context(
                    graph_path=str(filtered_path),
                    platforms=list(PORTABLE_DIRECT_TARGETS[target]),
                    project_dir=project_dir,
                    policy="full",
                    max_chars=max_chars,
                    dry_run=dry_run,
                )
            paths = [str(path) for _, path, status in write_results if status != "skipped" and str(path)]
            status = "ok" if write_results else "skipped"
            note = f"Updated {len(paths)} file(s)"
        else:
            artifact_results = export_artifact_targets(
                filtered,
                NormalizedContext.from_v5(filtered.export_v5()),
                [target],
                output_dir,
                policy_name="full",
                min_confidence=policy.min_confidence,
                identity=identity,
                dry_run=dry_run,
            )
            artifact = artifact_results[0] if artifact_results else None
            paths = [str(path) for path in (artifact.paths if artifact else ())]
            status = artifact.status if artifact else "skipped"
            note = artifact.note if artifact else ""

        snapshot_path = portability_snapshot_dir(store_dir) / f"{target}.json"
        fingerprints = {path: file_fingerprint(Path(path)) for path in paths if Path(path).exists()}
        facts_graph = _graph_from_hermes_paths(paths) if target == "hermes" else filtered
        facts = _graph_fact_rows(facts_graph)
        results.append(
            {
                "target": target,
                "paths": paths,
                "status": status,
                "note": note,
                "fact_count": len(facts),
                "route_tags": route_tags,
                "mode": "smart" if smart else "full",
            }
        )

        if dry_run or not persist_state:
            continue

        _write_graph(snapshot_path, filtered)
        state.targets[target] = TargetState(
            target=target,
            mode="smart" if smart else "full",
            policy=policy_name,
            route_tags=route_tags,
            paths=paths,
            fingerprints=fingerprints,
            fact_ids=[row["id"] for row in facts],
            facts=facts,
            updated_at=iso_now(),
            snapshot_path=str(snapshot_path),
            note=note,
        )

    if not dry_run and persist_state:
        state.graph_path = str(graph_path)
        state.project_dir = project_dir or state.project_dir or str(Path.cwd())
        state.output_dir = str(output_dir)
        state.updated_at = iso_now()
        save_portability_state(store_dir, state)

    return {
        "graph_path": str(graph_path),
        "output_dir": str(output_dir),
        "targets": results,
        "smart": smart,
    }


def _search_roots(project_dir: Path | None, extra_roots: list[Path] | None) -> list[Path]:
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


def _find_export_file(target: str, roots: list[Path]) -> Path | None:
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


def _load_snapshot_graph(state: PortabilityState, target: str) -> CortexGraph | None:
    target_state = state.targets.get(target)
    if target_state is None or not target_state.snapshot_path:
        return None
    return _load_graph(Path(target_state.snapshot_path))


def _target_paths(
    state: PortabilityState,
    target: str,
    *,
    project_dir: Path,
    output_dir: Path,
) -> list[Path]:
    target_state = state.targets.get(target)
    if target_state and target_state.paths:
        return [Path(path) for path in target_state.paths]
    return expected_tool_paths(target, project_dir=str(project_dir), output_dir=output_dir)


def _stored_labels(target_state: TargetState | None) -> list[str]:
    if target_state is None:
        return []
    return [str(item.get("label", "")) for item in target_state.facts if str(item.get("label", "")).strip()]


def _stored_fingerprints_match(target_state: TargetState | None, paths: list[Path]) -> bool:
    if target_state is None or not target_state.facts or not paths:
        return False
    for path in paths:
        if not path.exists():
            return False
        stored = target_state.fingerprints.get(str(path), "")
        if not stored or stored != file_fingerprint(path):
            return False
    return True


def _tool_labels(state: PortabilityState, target: str, paths: list[Path], export_path: Path | None = None) -> list[str]:
    target_state = state.targets.get(target)
    existing_paths = [path for path in paths if path.exists()]
    if _stored_fingerprints_match(target_state, paths):
        return _stored_labels(target_state)

    labels: list[str] = []
    for path in existing_paths:
        labels.extend(_parse_target_file(target, path))
    if not existing_paths and export_path is not None:
        if export_path.suffix.lower() == ".zip":
            try:
                data, fmt = load_file(export_path)
                extractor = AggressiveExtractor()
                extracted = upgrade_v4_to_v5(_run_extraction_data(extractor, data, fmt))
                labels.extend([node.label for node in extracted.nodes.values()])
            except Exception:
                pass
        else:
            labels.extend(_parse_target_file(target, export_path))
    return _dedupe_labels(labels)


def _policy_from_target_state(target_state: TargetState) -> DisclosurePolicy:
    builtin = BUILTIN_POLICIES.get(target_state.policy, BUILTIN_POLICIES["technical"])
    if target_state.mode == "smart":
        return DisclosurePolicy(
            name=f"smart-{target_state.target}",
            include_tags=list(target_state.route_tags),
            exclude_tags=["negations"],
            min_confidence=0.45,
            redact_properties=[],
        )
    if target_state.route_tags and target_state.route_tags != builtin.include_tags:
        return DisclosurePolicy(
            name=f"portable-{target_state.target}",
            include_tags=list(target_state.route_tags),
            exclude_tags=list(builtin.exclude_tags),
            min_confidence=builtin.min_confidence,
            redact_properties=list(builtin.redact_properties),
            max_nodes=builtin.max_nodes,
        )
    return builtin


def render_portability_context(
    *,
    store_dir: Path,
    target: str,
    project_dir: Path | None = None,
    smart: bool | None = None,
    policy_name: str | None = None,
    max_chars: int = 1500,
) -> dict[str, Any]:
    state = load_portability_state(store_dir)
    graph, graph_path = load_canonical_graph(store_dir, state)
    canonical_target = canonical_target_name(target)
    if canonical_target not in ALL_PORTABLE_TARGETS:
        raise ValueError(f"Unknown portability target: {target}")

    target_state = state.targets.get(canonical_target)
    effective_smart = (
        smart if smart is not None else (target_state.mode == "smart" if target_state is not None else True)
    )
    if effective_smart:
        effective_policy = target_state.policy if target_state is not None else (policy_name or "technical")
    else:
        effective_policy = policy_name or (target_state.policy if target_state is not None else "technical")
    policy, route_tags = _policy_for_target(canonical_target, smart=effective_smart, policy_name=effective_policy)
    filtered = apply_disclosure(graph, policy)
    ctx = NormalizedContext.from_v5(filtered.export_v5())
    facts = _graph_fact_rows(filtered)
    labels = [row["label"] for row in facts]

    resolved_project_dir = project_dir
    if resolved_project_dir is None and state.project_dir:
        resolved_project_dir = Path(state.project_dir)

    context_markdown = ""
    consume_as = "instruction_markdown"
    target_payload: dict[str, Any] = {}

    if filtered.nodes:
        if canonical_target == "hermes":
            documents = build_hermes_documents(ctx, max_chars=max_chars, min_confidence=policy.min_confidence)
            context_markdown = documents["memory"]
            consume_as = "hermes_memory"
            target_payload = {
                "user_text": documents["user"],
                "memory_text": documents["memory"],
                "agents_text": documents["agents"],
            }
        elif canonical_target in PORTABLE_DIRECT_TARGETS:
            with tempfile.TemporaryDirectory() as tmp_dir:
                filtered_path = Path(tmp_dir) / f"{canonical_target}.json"
                _write_graph(filtered_path, filtered)
                context_markdown = generate_compact_context(
                    HookConfig(
                        graph_path=str(filtered_path),
                        policy="full",
                        max_chars=max_chars,
                        include_project=False,
                    ),
                    cwd=str(resolved_project_dir) if resolved_project_dir is not None else None,
                )
        elif canonical_target == "claude":
            preferences_text = export_claude_preferences(ctx, min_confidence=policy.min_confidence)
            memories = export_claude_memories(ctx, min_confidence=policy.min_confidence)
            context_markdown = preferences_text
            consume_as = "claude_profile"
            target_payload = {
                "preferences_text": preferences_text,
                "memories": memories,
            }
        elif canonical_target in {"chatgpt", "grok"}:
            pack = build_instruction_pack(ctx, min_confidence=policy.min_confidence)
            context_markdown = pack.combined
            consume_as = "custom_instructions"
            target_payload = {
                "about": pack.about,
                "respond": pack.respond,
                "combined": pack.combined,
            }

    return {
        "status": "ok",
        "configured": target_state is not None,
        "target": canonical_target,
        "name": display_name(canonical_target),
        "mode": "smart" if effective_smart else "full",
        "policy": effective_policy,
        "route_tags": route_tags,
        "fact_count": len(facts),
        "labels": labels,
        "facts": facts,
        "graph_path": str(graph_path),
        "project_dir": str(resolved_project_dir) if resolved_project_dir is not None else "",
        "updated_at": state.updated_at or (target_state.updated_at if target_state is not None else ""),
        "paths": list(target_state.paths) if target_state is not None else [],
        "context_markdown": context_markdown,
        "consume_as": consume_as,
        "target_payload": target_payload,
        "graph": filtered.export_v5(),
        "message": (
            ""
            if facts
            else "No canonical portability context found. Run `cortex portable`, `cortex build`, or `cortex remember` first."
        ),
    }


def _expected_labels(graph: CortexGraph, target_state: TargetState) -> set[str]:
    filtered = apply_disclosure(graph, _policy_from_target_state(target_state))
    return {node.label for node in filtered.nodes.values()}


def _run_extraction_data(extractor: AggressiveExtractor, data: Any, fmt: str) -> dict[str, Any]:
    if fmt == "openai":
        extractor.process_openai_export(data)
    elif fmt == "gemini":
        extractor.process_gemini_export(data)
    elif fmt == "perplexity":
        extractor.process_perplexity_export(data)
    elif fmt == "grok":
        extractor.process_grok_export(data)
    elif fmt == "cursor":
        extractor.process_cursor_export(data)
    elif fmt == "windsurf":
        extractor.process_windsurf_export(data)
    elif fmt == "copilot":
        extractor.process_copilot_export(data)
    elif fmt in ("jsonl", "claude_code"):
        extractor.process_jsonl_messages(data)
    elif fmt == "api_logs":
        extractor.process_api_logs(data)
    elif fmt == "messages":
        extractor.process_messages_list(data)
    elif fmt == "text":
        extractor.process_plain_text(data)
    else:
        if isinstance(data, list):
            extractor.process_messages_list(data)
        elif isinstance(data, dict) and "messages" in data:
            extractor.process_messages_list(data["messages"])
        else:
            extractor.process_plain_text(json.dumps(data) if not isinstance(data, str) else data)
    extractor.post_process()
    return extractor.context.export()


def scan_portability(
    *,
    store_dir: Path,
    project_dir: Path,
    extra_roots: list[Path] | None = None,
    metadata_only: bool = False,
) -> dict[str, Any]:
    state = load_portability_state(store_dir)
    graph, graph_path = load_canonical_graph(store_dir, state)
    output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(store_dir)
    roots = _search_roots(project_dir, extra_roots)
    now = datetime.now(timezone.utc)

    total_facts = len(graph.nodes)
    expected_map = _label_map([node.label for node in graph.nodes.values()])
    expected_keys = set(expected_map)
    known_union: set[str] = set()
    detected_sources = detect_portability_sources(store_dir=store_dir, project_dir=project_dir, extra_roots=extra_roots)
    sources_by_target: dict[str, list[dict[str, Any]]] = {}
    for source in detected_sources:
        entry = _sanitize_detected_source(source) if metadata_only else dict(source)
        sources_by_target.setdefault(str(source["target"]), []).append(entry)
    tools: list[dict[str, Any]] = []

    for target in ALL_PORTABLE_TARGETS:
        target_state = state.targets.get(target)
        compatibility_paths = _candidate_content_paths(target, project_dir=project_dir, output_dir=output_dir)
        state_paths = _target_paths(state, target, project_dir=project_dir, output_dir=output_dir)
        paths = compatibility_paths if compatibility_paths else state_paths
        mcp_configs = _discover_mcp_configs(target, project_dir=project_dir, output_dir=output_dir)
        export_path = None
        if not any(path.exists() for path in paths) and target_state is None:
            export_path = _find_export_file(target, roots)
        labels = [] if metadata_only else _tool_labels(state, target, paths, export_path)
        actual_map = _label_map(labels)
        matched_keys = expected_keys & set(actual_map)
        known_union.update(matched_keys)

        existing_paths = [path for path in paths if path.exists()]
        age_days = None
        if existing_paths:
            age_days = min(
                (_human_age(path, now=now)[0] for path in existing_paths if _human_age(path, now=now)[0] is not None),
                default=None,
            )
        elif export_path is not None:
            age_days = _human_age(export_path, now=now)[0]

        note = "not configured"
        if metadata_only:
            parts: list[str] = []
            if existing_paths:
                parts.append("local files detected")
            elif export_path is not None:
                parts.append("export detected")
            mcp_note = _sanitized_mcp_note(mcp_configs)
            if mcp_note:
                parts.append(mcp_note)
            if target_state is not None and not parts:
                note = "configured in Cortex state"
            elif parts:
                note = "; ".join(parts)
        else:
            if export_path is not None and not existing_paths:
                note = f"export: {age_days or 0} days old"
            elif existing_paths:
                if age_days is not None and age_days >= DEFAULT_STALE_DAYS:
                    note = f"{existing_paths[0].name}: {age_days} days stale"
                else:
                    note = existing_paths[0].name
                mcp_note = _mcp_note(mcp_configs)
                if mcp_note:
                    note = f"{note}; {mcp_note}"
            elif mcp_configs:
                note = _mcp_note(mcp_configs)
            elif target_state is not None:
                note = "configured, files missing"

        coverage = (len(matched_keys) / total_facts) if total_facts else 0.0
        visible_paths = (
            existing_paths if existing_paths else ([path for path in paths if target_state is not None] or [])
        )
        mcp_paths = [Path(item["path"]) for item in mcp_configs]
        tools.append(
            {
                "target": target,
                "name": display_name(target),
                "fact_count": len(labels),
                "matched_fact_count": len(matched_keys),
                "unexpected_fact_count": max(len(actual_map) - len(matched_keys), 0),
                "labels": labels,
                "coverage": coverage,
                "paths": []
                if metadata_only
                else [str(path) for path in visible_paths] + ([str(export_path)] if export_path else []),
                "detected_paths": [] if metadata_only else [str(path) for path in visible_paths],
                "mcp_paths": [] if metadata_only else [str(path) for path in mcp_paths],
                "mcp_server_count": sum(int(item["server_count"]) for item in mcp_configs),
                "cortex_mcp_configured": any(item["cortex_configured"] for item in mcp_configs),
                "detection_sources": [
                    source
                    for source, enabled in (
                        ("local_files", bool(existing_paths)),
                        ("mcp", bool(mcp_configs)),
                        ("export", export_path is not None),
                        ("state", target_state is not None),
                    )
                    if enabled
                ],
                "adoptable_sources": sources_by_target.get(target, []),
                "stale_days": age_days,
                "note": note,
                "configured": bool(existing_paths or export_path or target_state is not None or mcp_configs),
            }
        )

    known_facts = len(known_union) if total_facts else sum(tool["fact_count"] for tool in tools)
    overall_coverage = (known_facts / total_facts) if total_facts else 0.0

    return {
        "graph_path": "" if metadata_only else str(graph_path),
        "total_facts": total_facts,
        "known_facts": known_facts,
        "coverage": overall_coverage,
        "scan_mode": "metadata_only" if metadata_only else "full",
        "adoptable_sources": [_sanitize_detected_source(source) for source in detected_sources]
        if metadata_only
        else detected_sources,
        "adoptable_targets": sorted({source["target"] for source in detected_sources if source["importable"]}),
        "metadata_only_targets": sorted({source["target"] for source in detected_sources if source["metadata_only"]}),
        "tools": tools,
    }


def status_portability(*, store_dir: Path, project_dir: Path) -> dict[str, Any]:
    state = load_portability_state(store_dir)
    graph, graph_path = load_canonical_graph(store_dir, state)
    output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(store_dir)
    issues: list[dict[str, Any]] = []

    for target, target_state in state.targets.items():
        expected = _expected_labels(graph, target_state)
        paths = _target_paths(state, target, project_dir=project_dir, output_dir=output_dir)
        actual = set(_tool_labels(state, target, paths))
        expected_map = _label_map(list(expected))
        actual_map = _label_map(list(actual))
        missing_labels = sorted(expected_map[key] for key in expected_map.keys() - actual_map.keys())
        unexpected_labels = sorted(actual_map[key] for key in actual_map.keys() - expected_map.keys())
        missing_paths = [str(path) for path in paths if not path.exists()]
        age_days = None
        existing = [path for path in paths if path.exists()]
        if existing:
            age_days = min((_human_age(path)[0] for path in existing if _human_age(path)[0] is not None), default=None)
        stale = bool(
            missing_labels
            or unexpected_labels
            or missing_paths
            or (age_days is not None and age_days >= DEFAULT_STALE_DAYS)
        )
        issues.append(
            {
                "target": target,
                "name": display_name(target),
                "stale": stale,
                "stale_days": age_days,
                "missing_labels": missing_labels[:8],
                "unexpected_labels": unexpected_labels[:8],
                "missing_paths": missing_paths,
                "fact_count": len(actual_map),
                "expected_fact_count": len(expected_map),
                "updated_at": target_state.updated_at,
                "paths": [str(path) for path in paths],
            }
        )

    return {
        "graph_path": str(graph_path),
        "issues": issues,
    }


def audit_portability(*, store_dir: Path, project_dir: Path) -> dict[str, Any]:
    state = load_portability_state(store_dir)
    graph, _ = load_canonical_graph(store_dir, state)
    output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(store_dir)
    issues: list[dict[str, Any]] = []
    actual_by_target: dict[str, dict[str, str]] = {}
    route_group_members: dict[tuple[str, ...], list[str]] = {}

    for target, target_state in state.targets.items():
        paths = _target_paths(state, target, project_dir=project_dir, output_dir=output_dir)
        actual = set(_tool_labels(state, target, paths))
        expected = _expected_labels(graph, target_state)
        actual_by_target[target] = _label_map(list(actual))
        route_key = tuple(target_state.route_tags)
        route_group_members.setdefault(route_key, []).append(target)

        missing_paths = [str(path) for path in paths if not path.exists()]
        if missing_paths:
            issues.append(
                {
                    "type": "missing_files",
                    "tag": "portable",
                    "target": target,
                    "paths": missing_paths,
                    "message": f"{display_name(target)} is configured but missing {len(missing_paths)} expected file(s).",
                }
            )

        expected_map = _label_map(list(expected))
        actual_map = _label_map(list(actual))
        missing_labels = sorted(expected_map[key] for key in expected_map.keys() - actual_map.keys())
        if missing_labels:
            issues.append(
                {
                    "type": "missing_context",
                    "tag": "portable",
                    "target": target,
                    "missing_labels": missing_labels[:8],
                    "message": f"{display_name(target)} is missing expected context such as '{missing_labels[0]}'.",
                }
            )

        unexpected_labels = sorted(actual_map[key] for key in actual_map.keys() - expected_map.keys())
        if unexpected_labels:
            issues.append(
                {
                    "type": "unexpected_context",
                    "tag": "portable",
                    "target": target,
                    "unexpected_labels": unexpected_labels[:8],
                    "message": f"{display_name(target)} contains drifted context such as '{unexpected_labels[0]}'.",
                }
            )

    for route_key, members in route_group_members.items():
        if len(members) < 2:
            continue
        for idx, left in enumerate(sorted(members)):
            left_labels = actual_by_target.get(left, {})
            for right in sorted(members)[idx + 1 :]:
                right_labels = actual_by_target.get(right, {})
                left_only = sorted(left_labels[key] for key in left_labels.keys() - right_labels.keys())
                right_only = sorted(right_labels[key] for key in right_labels.keys() - left_labels.keys())
                if not left_only or not right_only:
                    continue
                issues.append(
                    {
                        "type": "context_divergence",
                        "tag": "portable",
                        "left": left,
                        "right": right,
                        "left_label": left_only[0],
                        "right_label": right_only[0],
                        "message": (
                            f"{display_name(left)} and {display_name(right)} diverged even though they share the same routed context."
                        ),
                    }
                )

    return {
        "issues": issues,
        "targets": sorted(state.targets),
    }


def remember_and_sync(
    statement: str,
    *,
    store_dir: Path,
    project_dir: Path,
    targets: list[str] | None = None,
    smart: bool = False,
    policy_name: str = "full",
    max_chars: int = 1500,
    dry_run: bool = False,
) -> dict[str, Any]:
    state = load_portability_state(store_dir)
    canonical_graph, graph_path = load_canonical_graph(store_dir, state)
    extracted_graph = extract_graph_from_statement(statement)
    merged = merge_graphs(canonical_graph, extracted_graph)
    if not dry_run:
        state, graph_path = save_canonical_graph(store_dir, merged, state=state, graph_path=graph_path)
    output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(store_dir)
    return {
        "statement": statement,
        "graph_path": str(graph_path),
        "targets": sync_targets(
            merged,
            targets=[canonical_target_name(target) for target in (targets or ALL_PORTABLE_TARGETS)],
            store_dir=store_dir,
            project_dir=str(project_dir),
            output_dir=output_dir,
            graph_path=graph_path,
            policy_name=policy_name,
            smart=smart,
            max_chars=max_chars,
            dry_run=dry_run,
            state=state,
        )["targets"],
        "fact_count": len(merged.nodes),
    }


def build_digital_footprint(
    *,
    sources: list[str],
    inputs: list[str],
    store_dir: Path,
    project_dir: Path,
    search_roots: list[Path] | None = None,
    sync_after: bool = False,
    targets: list[str] | None = None,
    smart: bool = False,
    policy_name: str = "technical",
    max_chars: int = 1500,
) -> dict[str, Any]:
    source_iter = iter(inputs)
    built_graph = CortexGraph()
    summaries: list[dict[str, Any]] = []

    roots = _search_roots(project_dir, search_roots)

    for source in sources:
        if source == "github":
            graph, summary = build_github_graph(roots or [project_dir])
        elif source == "resume":
            try:
                resume_input = Path(next(source_iter))
            except StopIteration as exc:
                raise ValueError("build --from resume requires a file path") from exc
            graph, summary = build_resume_graph(resume_input)
        elif source in {"package.json", "project", "manifest"}:
            graph, summary = build_project_graph(project_dir)
        elif source == "git-history":
            graph, summary = build_git_history_graph(project_dir)
        else:
            raise ValueError(f"Unknown build source: {source}")
        built_graph = merge_graphs(built_graph, graph)
        summaries.append({"source": source, **summary})

    state = load_portability_state(store_dir)
    canonical_graph, graph_path = load_canonical_graph(store_dir, state)
    merged = merge_graphs(canonical_graph, built_graph)
    state, graph_path = save_canonical_graph(store_dir, merged, state=state, graph_path=graph_path)

    payload: dict[str, Any] = {
        "graph_path": str(graph_path),
        "sources": summaries,
        "fact_count": len(merged.nodes),
    }
    if sync_after:
        output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(store_dir)
        sync_targets_list = list(targets or DEFAULT_DIRECT_TARGETS)
        if smart and sync_targets_list == DEFAULT_DIRECT_TARGETS:
            sync_targets_list = list(ALL_PORTABLE_TARGETS)
        payload["targets"] = sync_targets(
            merged,
            targets=[canonical_target_name(target) for target in sync_targets_list],
            store_dir=store_dir,
            project_dir=str(project_dir),
            output_dir=output_dir,
            graph_path=graph_path,
            policy_name=policy_name,
            smart=smart,
            max_chars=max_chars,
            state=state,
        )["targets"]
    return payload


def switch_portability(
    input_path: Path,
    *,
    to_target: str,
    store_dir: Path,
    project_dir: Path,
    output_dir: Path,
    input_format: str = "auto",
    policy_name: str = "technical",
    max_chars: int = 1500,
    dry_run: bool = False,
) -> dict[str, Any]:
    graph = load_graph_optional(str(input_path))
    detected_kind = "graph"
    if graph is None:
        data, detected_format = load_file(input_path)
        extractor = AggressiveExtractor()
        fmt = input_format if input_format != "auto" else detected_format
        payload = _run_extraction_data(extractor, data, fmt)
        graph = upgrade_v4_to_v5(payload)
        detected_kind = fmt

    state = load_portability_state(store_dir)
    graph_path = output_dir / "context.json"
    if not dry_run:
        _write_graph(graph_path, graph)

    sync_result = sync_targets(
        graph,
        targets=[canonical_target_name(to_target)],
        store_dir=store_dir,
        project_dir=str(project_dir),
        output_dir=output_dir,
        graph_path=graph_path,
        policy_name=policy_name,
        smart=False,
        max_chars=max_chars,
        dry_run=dry_run,
        state=state,
        persist_state=False,
    )
    return {
        "source": detected_kind,
        "input_path": str(input_path),
        "target": canonical_target_name(to_target),
        "graph_path": str(graph_path),
        "targets": sync_result["targets"],
    }


def bar(coverage: float, width: int = 20) -> str:
    coverage = max(0.0, min(1.0, coverage))
    filled = int(round(coverage * width))
    return "█" * filled + "░" * (width - filled)


__all__ = [
    "ALL_PORTABLE_TARGETS",
    "DEFAULT_DIRECT_TARGETS",
    "PortabilityState",
    "STATE_VERSION",
    "TargetState",
    "audit_portability",
    "bar",
    "build_digital_footprint",
    "canonical_target_name",
    "default_output_dir",
    "display_name",
    "expected_tool_paths",
    "load_canonical_graph",
    "load_portability_state",
    "portability_state_path",
    "remember_and_sync",
    "render_portability_context",
    "save_canonical_graph",
    "save_portability_state",
    "scan_portability",
    "status_portability",
    "switch_portability",
    "sync_targets",
]
