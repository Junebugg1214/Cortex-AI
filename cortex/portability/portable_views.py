from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cortex.compat import upgrade_v4_to_v5
from cortex.extract_memory import AggressiveExtractor, load_file
from cortex.graph import CortexGraph
from cortex.hermes_integration import build_hermes_documents
from cortex.hooks import HookConfig, generate_compact_context
from cortex.import_memory import NormalizedContext, export_claude_memories, export_claude_preferences
from cortex.portability import PORTABLE_DIRECT_TARGETS, build_instruction_pack
from cortex.portable_sources import (
    ALL_PORTABLE_TARGETS,
    candidate_content_paths,
    canonical_target_name,
    dedupe_labels,
    discover_mcp_configs,
    discover_portability_sources,
    display_name,
    expected_tool_paths,
    find_export_file,
    human_age,
    label_map,
    mcp_note,
    parse_target_file,
    run_extraction_data,
    sanitize_detected_source,
    sanitized_mcp_note,
    search_roots,
)
from cortex.portable_state import (
    PortabilityState,
    TargetState,
    default_output_dir,
    file_fingerprint,
    graph_fact_rows,
    load_canonical_graph,
    load_portability_state,
    write_graph,
)
from cortex.upai.disclosure import BUILTIN_POLICIES, DisclosurePolicy, apply_disclosure

DEFAULT_STALE_DAYS = 30

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


def policy_for_target(target: str, *, smart: bool, policy_name: str) -> tuple[DisclosurePolicy, list[str]]:
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


def tool_labels(state: PortabilityState, target: str, paths: list[Path], export_path: Path | None = None) -> list[str]:
    target_state = state.targets.get(target)
    existing_paths = [path for path in paths if path.exists()]
    if _stored_fingerprints_match(target_state, paths):
        return _stored_labels(target_state)

    labels: list[str] = []
    for path in existing_paths:
        labels.extend(parse_target_file(target, path))
    if not existing_paths and export_path is not None:
        if export_path.suffix.lower() == ".zip":
            try:
                data, fmt = load_file(export_path)
                extractor = AggressiveExtractor()
                extracted = upgrade_v4_to_v5(run_extraction_data(extractor, data, fmt))
                labels.extend([node.label for node in extracted.nodes.values()])
            except Exception:
                pass
        else:
            labels.extend(parse_target_file(target, export_path))
    return dedupe_labels(labels)


def policy_from_target_state(target_state: TargetState) -> DisclosurePolicy:
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
    policy, route_tags = policy_for_target(canonical_target, smart=effective_smart, policy_name=effective_policy)
    filtered = apply_disclosure(graph, policy)
    ctx = NormalizedContext.from_v5(filtered.export_v5())
    facts = graph_fact_rows(filtered)
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
                write_graph(filtered_path, filtered)
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
    filtered = apply_disclosure(graph, policy_from_target_state(target_state))
    return {node.label for node in filtered.nodes.values()}


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
    roots = search_roots(project_dir, extra_roots)
    now = datetime.now(timezone.utc)

    total_facts = len(graph.nodes)
    expected_map = label_map([node.label for node in graph.nodes.values()])
    expected_keys = set(expected_map)
    known_union: set[str] = set()
    detected_sources = discover_portability_sources(project_dir=project_dir, output_dir=output_dir, roots=roots)
    sources_by_target: dict[str, list[dict[str, Any]]] = {}
    for source in detected_sources:
        entry = sanitize_detected_source(source) if metadata_only else dict(source)
        sources_by_target.setdefault(str(source["target"]), []).append(entry)
    tools: list[dict[str, Any]] = []

    for target in ALL_PORTABLE_TARGETS:
        target_state = state.targets.get(target)
        compatibility_paths = candidate_content_paths(target, project_dir=project_dir, output_dir=output_dir)
        state_paths = _target_paths(state, target, project_dir=project_dir, output_dir=output_dir)
        paths = compatibility_paths if compatibility_paths else state_paths
        mcp_configs = discover_mcp_configs(target, project_dir=project_dir, output_dir=output_dir)
        export_path = None
        if not any(path.exists() for path in paths) and target_state is None:
            export_path = find_export_file(target, roots)
        labels = [] if metadata_only else tool_labels(state, target, paths, export_path)
        actual_map = label_map(labels)
        matched_keys = expected_keys & set(actual_map)
        known_union.update(matched_keys)

        existing_paths = [path for path in paths if path.exists()]
        age_days = None
        if existing_paths:
            age_days = min(
                (human_age(path, now=now)[0] for path in existing_paths if human_age(path, now=now)[0] is not None),
                default=None,
            )
        elif export_path is not None:
            age_days = human_age(export_path, now=now)[0]

        note = "not configured"
        if metadata_only:
            parts: list[str] = []
            if existing_paths:
                parts.append("local files detected")
            elif export_path is not None:
                parts.append("export detected")
            compact_note = sanitized_mcp_note(mcp_configs)
            if compact_note:
                parts.append(compact_note)
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
                config_note = mcp_note(mcp_configs)
                if config_note:
                    note = f"{note}; {config_note}"
            elif mcp_configs:
                note = mcp_note(mcp_configs)
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
        "adoptable_sources": [sanitize_detected_source(source) for source in detected_sources]
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
        actual = set(tool_labels(state, target, paths))
        expected_map = label_map(list(expected))
        actual_map = label_map(list(actual))
        missing_labels = sorted(expected_map[key] for key in expected_map.keys() - actual_map.keys())
        unexpected_labels = sorted(actual_map[key] for key in actual_map.keys() - expected_map.keys())
        missing_paths = [str(path) for path in paths if not path.exists()]
        age_days = None
        existing = [path for path in paths if path.exists()]
        if existing:
            age_days = min((human_age(path)[0] for path in existing if human_age(path)[0] is not None), default=None)
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
        actual = set(tool_labels(state, target, paths))
        expected = _expected_labels(graph, target_state)
        actual_by_target[target] = label_map(list(actual))
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

        expected_map = label_map(list(expected))
        actual_map = label_map(list(actual))
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


def bar(coverage: float, width: int = 20) -> str:
    coverage = max(0.0, min(1.0, coverage))
    filled = int(round(coverage * width))
    return "█" * filled + "░" * (width - filled)


__all__ = [
    "SMART_ROUTE_TAGS",
    "audit_portability",
    "bar",
    "policy_for_target",
    "render_portability_context",
    "scan_portability",
    "status_portability",
]
