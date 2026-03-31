from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from cortex.context import _format_plain, _resolve_path, _write_non_destructive
from cortex.import_memory import NormalizedContext, TopicDetail
from cortex.portability import build_instruction_pack

HERMES_CONFIG_START = "# CORTEX:HERMES:START"
HERMES_CONFIG_END = "# CORTEX:HERMES:END"


@dataclass(frozen=True, slots=True)
class HermesInstallResult:
    paths: tuple[Path, ...]
    status: str
    note: str


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = " ".join(item.split()).strip(" .;")
        if not cleaned:
            continue
        lowered = cleaned.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(cleaned)
    return result


def _topic_strings(topics: list[TopicDetail] | None, *, limit: int = 5, prefer_brief: bool = True) -> list[str]:
    if not topics:
        return []
    values: list[str] = []
    for topic in topics[:limit]:
        if prefer_brief:
            candidate = topic.brief or topic.topic
        else:
            candidate = topic.topic or topic.brief
        values.append(candidate)
    return _dedupe_preserve(values)


def _markdown_section(
    title: str, topics: list[TopicDetail] | None, *, limit: int = 5, prefer_brief: bool = True
) -> str:
    values = _topic_strings(topics, limit=limit, prefer_brief=prefer_brief)
    if not values:
        return ""
    body = "\n".join(f"- {value}" for value in values)
    return f"## {title}\n{body}"


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    shortened = text[: max(limit - 3, 0)].rstrip()
    for separator in ("\n## ", "\n- ", ". ", "; "):
        if separator in shortened:
            candidate = shortened.rsplit(separator, 1)[0].strip()
            if candidate:
                return candidate + "..."
    return shortened + "..."


def build_hermes_documents(
    ctx: NormalizedContext, *, max_chars: int = 1500, min_confidence: float = 0.6
) -> dict[str, str]:
    topics = ctx.get_topics_by_confidence(min_confidence)
    pack = build_instruction_pack(ctx, min_confidence=min_confidence)

    user_sections = [
        "# USER.md",
        "",
        "Persistent user profile managed by Cortex for Hermes.",
        "",
        _markdown_section("Identity", topics.get("identity"), limit=4, prefer_brief=False),
        _markdown_section("Professional Context", topics.get("professional_context"), limit=5, prefer_brief=False),
        _markdown_section(
            "Communication Preferences", topics.get("communication_preferences"), limit=6, prefer_brief=False
        ),
        _markdown_section("Working Preferences", topics.get("user_preferences"), limit=6, prefer_brief=False),
        _markdown_section("Values", topics.get("values"), limit=5, prefer_brief=False),
    ]
    memory_sections = [
        "# MEMORY.md",
        "",
        "Persistent durable context managed by Cortex for Hermes.",
        "",
        _markdown_section("Active Priorities", topics.get("active_priorities"), limit=6, prefer_brief=False),
        _markdown_section("Technical Context", topics.get("technical_expertise"), limit=8, prefer_brief=False),
        _markdown_section("Domain Knowledge", topics.get("domain_knowledge"), limit=6, prefer_brief=False),
        _markdown_section("Business Context", topics.get("business_context"), limit=5, prefer_brief=False),
        _markdown_section("Relationships", topics.get("relationships"), limit=5, prefer_brief=False),
        _markdown_section("Constraints", topics.get("constraints"), limit=5, prefer_brief=False),
        _markdown_section("Corrections", topics.get("correction_history"), limit=5, prefer_brief=False),
    ]
    agents_sections = ["# AGENTS.md", "", "Optional project context for Hermes.", "", pack.combined]

    user_text = _truncate("\n".join(section for section in user_sections if section).strip(), max_chars)
    memory_text = _truncate("\n".join(section for section in memory_sections if section).strip(), max_chars)
    agents_text = _truncate("\n".join(section for section in agents_sections if section).strip(), max_chars)
    return {
        "user": user_text,
        "memory": memory_text,
        "agents": agents_text,
    }


def _escape_yaml_double_quoted(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _render_cortex_mcp_block(config_path: Path, *, indent: str = "  ") -> list[str]:
    escaped = _escape_yaml_double_quoted(str(config_path))
    return [
        f"{indent}{HERMES_CONFIG_START}",
        f"{indent}cortex:",
        f'{indent}  command: "cortex-mcp"',
        f"{indent}  args:",
        f'{indent}    - "--config"',
        f'{indent}    - "{escaped}"',
        f"{indent}{HERMES_CONFIG_END}",
    ]


def _find_existing_marker(lines: list[str], marker: str) -> int | None:
    for index, line in enumerate(lines):
        if marker in line:
            return index
    return None


def _top_level_key(line: str) -> str | None:
    if line.startswith(" ") or line.startswith("\t"):
        return None
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    match = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(?:#.*)?$", stripped)
    if not match:
        return None
    return match.group(1)


def _section_end(lines: list[str], start_index: int) -> int:
    for index in range(start_index + 1, len(lines)):
        if _top_level_key(lines[index]) is not None:
            return index
    return len(lines)


def _child_block_end(lines: list[str], start_index: int, *, section_end: int, sibling_indent: int) -> int:
    for index in range(start_index + 1, section_end):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(lines[index]) - len(lines[index].lstrip(" "))
        if indent <= sibling_indent:
            return index
    return section_end


def _replace_slice(lines: list[str], start_index: int, end_index: int, replacement: list[str]) -> list[str]:
    return lines[:start_index] + replacement + lines[end_index:]


def update_hermes_config(config_path: Path, *, cortex_config_path: Path, dry_run: bool = False) -> str:
    block = _render_cortex_mcp_block(cortex_config_path)
    if not config_path.exists():
        content = [
            "mcp_servers:",
            *block,
            "",
            "memory:",
            "  memory_enabled: true",
            "  user_profile_enabled: true",
            "  memory_char_limit: 2200",
            "  user_char_limit: 1375",
            "",
        ]
        if not dry_run:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("\n".join(content), encoding="utf-8")
        return "created"

    original = config_path.read_text(encoding="utf-8")
    lines = original.splitlines()

    marker_start = _find_existing_marker(lines, HERMES_CONFIG_START)
    marker_end = _find_existing_marker(lines, HERMES_CONFIG_END)
    if marker_start is not None and marker_end is not None and marker_end >= marker_start:
        indent = re.match(r"^(\s*)", lines[marker_start]).group(1)
        replacement = _render_cortex_mcp_block(cortex_config_path, indent=indent)
        updated_lines = _replace_slice(lines, marker_start, marker_end + 1, replacement)
    else:
        mcp_start = None
        for index, line in enumerate(lines):
            if _top_level_key(line) == "mcp_servers":
                mcp_start = index
                break
        if mcp_start is None:
            updated_lines = list(lines)
            if updated_lines and updated_lines[-1].strip():
                updated_lines.append("")
            updated_lines.extend(["mcp_servers:", *block])
        else:
            section_end = _section_end(lines, mcp_start)
            cortex_start = None
            for index in range(mcp_start + 1, section_end):
                if re.match(r"^\s{2}cortex\s*:\s*(?:#.*)?$", lines[index]):
                    cortex_start = index
                    break
            updated_lines = list(lines)
            if cortex_start is not None:
                cortex_end = _child_block_end(lines, cortex_start, section_end=section_end, sibling_indent=2)
                updated_lines = _replace_slice(updated_lines, cortex_start, cortex_end, block)
            else:
                insert_at = mcp_start + 1
                updated_lines = _replace_slice(updated_lines, insert_at, insert_at, block)

    updated = "\n".join(updated_lines).rstrip() + "\n"
    if updated == original:
        return "updated"
    if not dry_run:
        config_path.write_text(updated, encoding="utf-8")
    return "updated"


def ensure_cortex_mcp_config(store_dir: Path, *, dry_run: bool = False) -> Path:
    config_path = store_dir / "config.toml"
    if config_path.exists():
        return config_path
    if not dry_run:
        escaped_store_dir = str(store_dir).replace("\\", "\\\\").replace('"', '\\"')
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            "\n".join(
                [
                    "[runtime]",
                    f'store_dir = "{escaped_store_dir}"',
                    "",
                    "[mcp]",
                    'namespace = ""',
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return config_path


def install_hermes_context(
    ctx: NormalizedContext,
    *,
    project_dir: str | None,
    store_dir: Path,
    max_chars: int = 1500,
    min_confidence: float = 0.6,
    dry_run: bool = False,
) -> HermesInstallResult:
    documents = build_hermes_documents(ctx, max_chars=max_chars, min_confidence=min_confidence)
    user_path = _resolve_path("{home}/.hermes/memories/USER.md", project_dir)
    memory_path = _resolve_path("{home}/.hermes/memories/MEMORY.md", project_dir)
    hermes_config_path = _resolve_path("{home}/.hermes/config.yaml", project_dir)
    cortex_config_path = ensure_cortex_mcp_config(store_dir, dry_run=dry_run)

    user_status = _write_non_destructive(user_path, _format_plain(documents["user"]), dry_run=dry_run)
    memory_status = _write_non_destructive(memory_path, _format_plain(documents["memory"]), dry_run=dry_run)
    config_status = update_hermes_config(hermes_config_path, cortex_config_path=cortex_config_path, dry_run=dry_run)

    paths = (user_path, memory_path, hermes_config_path)
    statuses = {user_status, memory_status, config_status}
    status = "dry-run" if dry_run else ("ok" if {"created", "updated"} & statuses else "skipped")
    note = "Updated Hermes USER.md, MEMORY.md, and MCP config."
    return HermesInstallResult(paths=paths, status=status, note=note)
