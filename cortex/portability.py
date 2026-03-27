"""
Portability helpers for moving Cortex context across AI tools.

The portability layer is intentionally honest about how each target works:

- direct-write targets install context into local instruction files
- artifact targets generate import-ready or copy-paste-ready files
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from cortex.adapters import ADAPTERS
from cortex.import_memory import NormalizedContext, TopicDetail
from cortex.upai.disclosure import BUILTIN_POLICIES

if TYPE_CHECKING:
    from cortex.graph import CortexGraph
    from cortex.upai.identity import UPAIIdentity


PORTABLE_TARGET_ORDER = [
    "claude",
    "claude-code",
    "chatgpt",
    "codex",
    "copilot",
    "gemini",
    "grok",
    "windsurf",
    "cursor",
]

PORTABLE_TARGET_ALIASES: dict[str, str] = {
    "gemini-cli": "gemini",
}

PORTABLE_DIRECT_TARGETS: dict[str, tuple[str, ...]] = {
    "claude-code": ("claude-code", "claude-code-project"),
    "codex": ("codex",),
    "copilot": ("copilot",),
    "cursor": ("cursor",),
    "gemini": ("gemini-cli",),
    "windsurf": ("windsurf",),
}


@dataclass(frozen=True, slots=True)
class InstructionPack:
    about: str
    respond: str
    combined: str


@dataclass(frozen=True, slots=True)
class ArtifactResult:
    target: str
    status: str
    paths: tuple[Path, ...]
    note: str = ""


def resolve_portable_targets(targets: list[str]) -> list[str]:
    """Resolve aliases and expand ``all`` into the portability target set."""
    if "all" in targets:
        return list(PORTABLE_TARGET_ORDER)

    resolved: list[str] = []
    for target in targets:
        canonical = PORTABLE_TARGET_ALIASES.get(target, target)
        if canonical not in PORTABLE_TARGET_ORDER:
            raise ValueError(f"Unknown target: {target}")
        if canonical not in resolved:
            resolved.append(canonical)
    return resolved


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = " ".join(item.split()).strip(" .;")
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(cleaned)
    return result


def _topic_strings(
    topics: list[TopicDetail] | None,
    *,
    limit: int = 5,
    prefer_brief: bool = True,
) -> list[str]:
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


def _line(prefix: str, topics: list[TopicDetail] | None, *, limit: int = 5, prefer_brief: bool = True) -> str:
    values = _topic_strings(topics, limit=limit, prefer_brief=prefer_brief)
    if not values:
        return ""
    return f"{prefix}: {'; '.join(values)}."


def _truncate_block(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text

    truncated = text[: max(limit - 3, 0)].rstrip()
    for separator in (". ", "; ", "\n"):
        if separator in truncated:
            candidate = truncated.rsplit(separator, 1)[0].strip()
            if candidate:
                return candidate.rstrip(".;") + "..."
    return truncated + "..."


def build_instruction_pack(ctx: NormalizedContext, min_confidence: float = 0.6) -> InstructionPack:
    """Build compact profile-style instructions for chat-based tools."""
    topics = ctx.get_topics_by_confidence(min_confidence)

    about_lines = [
        _line("Identity", topics.get("identity"), limit=3, prefer_brief=False),
        _line("Role", topics.get("professional_context"), limit=3),
        _line("Business", topics.get("business_context"), limit=3),
        _line("Current priorities", topics.get("active_priorities"), limit=5),
        _line("Tech stack", topics.get("technical_expertise"), limit=8),
        _line("Domain context", topics.get("domain_knowledge"), limit=5),
        _line("Relationships", topics.get("relationships"), limit=4),
    ]
    about = _truncate_block("\n".join(line for line in about_lines if line), 1400)

    respond_lines = [
        _line("Communication preferences", topics.get("communication_preferences"), limit=6, prefer_brief=False),
        _line("Working preferences", topics.get("user_preferences"), limit=6, prefer_brief=False),
        _line("Constraints to respect", topics.get("constraints"), limit=5),
        _line("Values to honor", topics.get("values"), limit=5, prefer_brief=False),
        _line("Avoid", topics.get("negations"), limit=5, prefer_brief=False),
    ]

    if topics.get("correction_history"):
        respond_lines.append("If prior context conflicts, ask which version is current before assuming.")

    respond = _truncate_block("\n".join(line for line in respond_lines if line), 1200)
    combined = "\n\n".join(block for block in (about, respond) if block)
    return InstructionPack(about=about, respond=respond, combined=combined)


def _write_text(path: Path, text: str, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, data: dict, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def export_chatgpt_artifacts(
    ctx: NormalizedContext,
    output_dir: Path,
    *,
    min_confidence: float = 0.6,
    dry_run: bool = False,
) -> ArtifactResult:
    pack = build_instruction_pack(ctx, min_confidence=min_confidence)
    target_dir = output_dir / "chatgpt"
    md_path = target_dir / "custom_instructions.md"
    json_path = target_dir / "custom_instructions.json"

    markdown = (
        "# ChatGPT Custom Instructions\n\n"
        "Paste these into ChatGPT's custom instructions fields.\n\n"
        "## What ChatGPT should know about you\n\n"
        f"{pack.about}\n\n"
        "## How ChatGPT should respond\n\n"
        f"{pack.respond}\n"
    )
    payload = {
        "what_chatgpt_should_know_about_you": pack.about,
        "how_chatgpt_should_respond": pack.respond,
    }

    _write_text(md_path, markdown, dry_run=dry_run)
    _write_json(json_path, payload, dry_run=dry_run)
    return ArtifactResult(
        target="chatgpt",
        status="dry-run" if dry_run else "created",
        paths=(md_path, json_path),
        note="Generated as a paste-ready custom instructions pack.",
    )


def export_grok_artifacts(
    ctx: NormalizedContext,
    output_dir: Path,
    *,
    min_confidence: float = 0.6,
    dry_run: bool = False,
) -> ArtifactResult:
    pack = build_instruction_pack(ctx, min_confidence=min_confidence)
    target_dir = output_dir / "grok"
    md_path = target_dir / "context_prompt.md"
    json_path = target_dir / "context_prompt.json"

    markdown = (
        "# Grok Context Prompt\n\n"
        "Use this as a pinned workspace prompt or paste it into a fresh Grok chat.\n\n"
        "## Context Grok should know\n\n"
        f"{pack.about}\n\n"
        "## How Grok should respond\n\n"
        f"{pack.respond}\n"
    )
    payload = {
        "context_for_grok": pack.about,
        "response_preferences": pack.respond,
    }

    _write_text(md_path, markdown, dry_run=dry_run)
    _write_json(json_path, payload, dry_run=dry_run)
    return ArtifactResult(
        target="grok",
        status="dry-run" if dry_run else "created",
        paths=(md_path, json_path),
        note="Generated as a prompt pack because Grok is not wired through a local file target here.",
    )


def export_claude_artifacts(
    graph: CortexGraph,
    output_dir: Path,
    *,
    policy_name: str = "technical",
    identity: UPAIIdentity | None = None,
    dry_run: bool = False,
) -> ArtifactResult:
    target_dir = output_dir / "claude"
    prefs_path = target_dir / "claude_preferences.txt"
    mem_path = target_dir / "claude_memories.json"

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
        policy = BUILTIN_POLICIES[policy_name]
        ADAPTERS["claude"].push(graph, policy, identity=identity, output_dir=target_dir)

    return ArtifactResult(
        target="claude",
        status="dry-run" if dry_run else "created",
        paths=(prefs_path, mem_path),
        note="Generated as Claude profile and memory import artifacts.",
    )


def export_artifact_targets(
    graph: CortexGraph,
    ctx: NormalizedContext,
    targets: list[str],
    output_dir: Path,
    *,
    policy_name: str = "technical",
    min_confidence: float = 0.6,
    identity: UPAIIdentity | None = None,
    dry_run: bool = False,
) -> list[ArtifactResult]:
    results: list[ArtifactResult] = []
    for target in targets:
        if target == "claude":
            results.append(
                export_claude_artifacts(
                    graph,
                    output_dir,
                    policy_name=policy_name,
                    identity=identity,
                    dry_run=dry_run,
                )
            )
        elif target == "chatgpt":
            results.append(
                export_chatgpt_artifacts(
                    ctx,
                    output_dir,
                    min_confidence=min_confidence,
                    dry_run=dry_run,
                )
            )
        elif target == "grok":
            results.append(
                export_grok_artifacts(
                    ctx,
                    output_dir,
                    min_confidence=min_confidence,
                    dry_run=dry_run,
                )
            )
    return results
