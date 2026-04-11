from __future__ import annotations

import json
import secrets
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from cortex.atomic_io import atomic_write_json, locked_path
from cortex.graph import CortexGraph
from cortex.minds import (
    DEFAULT_CATEGORIES,
    MIND_LAYOUT_DIRECTORIES,
    MIND_LAYOUT_FILES,
    SUPPORTED_MIND_MOUNT_TARGETS,
    MindManifest,
    _attachment_details,
    _default_openclaw_store_dir,
    _iso_now,
    _load_attachments,
    _load_branches,
    _load_mounts,
    _load_openclaw_mind_mount_registry,
    _load_policies,
    _minds_root,
    _read_json,
    _refresh_mind_mounts,
    _replace_manifest,
    _require_mind_namespace,
    _resolve_core_graph,
    _store_lock_path,
    _write_mounts,
    _write_openclaw_mind_mount_registry,
    adopt_graph_into_mind,
    load_mind_core_graph,
    load_mind_manifest,
    mind_attachments_path,
    mind_branch_ref,
    mind_branches_path,
    mind_core_state_path,
    mind_mounts_path,
    mind_openclaw_mount_registry_path,
    mind_path,
    mind_policies_path,
    mind_proposal_path,
    mind_proposals_dir,
    resolve_default_mind,
)
from cortex.namespaces import resource_namespace_matches


def ingest_detected_sources_into_mind(
    store_dir: Path,
    mind_id: str,
    *,
    targets: list[str],
    project_dir: Path,
    extra_roots: list[Path] | None = None,
    include_config_metadata: bool = False,
    include_unmanaged_text: bool = False,
    redactor: Any | None = None,
    message: str = "",
    namespace: str | None = None,
) -> dict[str, Any]:
    from cortex.portable_runtime import extract_graph_from_detected_sources

    detected_payload = extract_graph_from_detected_sources(
        targets=targets,
        store_dir=store_dir,
        project_dir=project_dir,
        extra_roots=extra_roots,
        include_config_metadata=include_config_metadata,
        include_unmanaged_text=include_unmanaged_text,
        redactor=redactor,
    )
    selected_sources = list(detected_payload["selected_sources"])
    if not selected_sources:
        skipped = detected_payload["skipped_sources"]
        metadata_hint = (
            " Add `--include-config-metadata` if you want MCP setup metadata too."
            if any(item.get("reason") == "metadata_only" for item in skipped)
            else ""
        )
        unmanaged_hint = (
            " Add `--include-unmanaged-text` if you want to ingest text outside Cortex markers from instruction files."
            if any(item.get("reason") == "unmanaged_only" for item in skipped)
            else ""
        )
        raise ValueError(
            "No detected sources were approved for Mind ingest.\n"
            f"Hint: Run `cortex scan` first and select an adoptable target.{metadata_hint}{unmanaged_hint}"
        )

    manifest = load_mind_manifest(store_dir, mind_id)
    _require_mind_namespace(manifest, namespace)
    proposal_id = f"proposal-{secrets.token_hex(8)}"
    proposal_path = mind_proposal_path(store_dir, manifest.id, proposal_id)
    proposal_payload = {
        "proposal_id": proposal_id,
        "mind": manifest.id,
        "created_at": _iso_now(),
        "status": "pending_review",
        "review_required": True,
        "trust_level": "unverified",
        "source": "mind.ingest_detected",
        "message": message.strip() or f"Review detected local context for Mind `{manifest.id}`",
        "namespace": manifest.namespace,
        "project_dir": str(project_dir),
        "graph": detected_payload["graph"].export_v5(),
        "graph_node_count": len(detected_payload["graph"].nodes),
        "graph_edge_count": len(detected_payload["graph"].edges),
        "selected_sources": selected_sources,
        "skipped_sources": detected_payload["skipped_sources"],
        "detected_source_count": len(detected_payload["detected_sources"]),
        "proposed_source_count": len(selected_sources),
    }
    with locked_path(_store_lock_path(store_dir)):
        atomic_write_json(proposal_path, proposal_payload)
        _replace_manifest(store_dir, manifest.id, updated_at=_iso_now())
    return {
        "status": "pending_review",
        "pending_review": True,
        "review_required": True,
        "mind": manifest.id,
        "proposal_id": proposal_id,
        "proposal_path": str(proposal_path),
        "selected_sources": selected_sources,
        "skipped_sources": detected_payload["skipped_sources"],
        "detected_source_count": len(detected_payload["detected_sources"]),
        "proposed_source_count": len(selected_sources),
        "ingested_source_count": 0,
        "graph_node_count": len(detected_payload["graph"].nodes),
        "graph_edge_count": len(detected_payload["graph"].edges),
    }


def remember_on_mind(
    store_dir: Path,
    mind_id: str,
    *,
    statement: str,
    message: str = "",
    namespace: str | None = None,
) -> dict[str, Any]:
    from cortex.portable_runtime import extract_graph_from_statement

    cleaned = " ".join(str(statement).split()).strip()
    if not cleaned:
        raise ValueError("Statement is required.")

    manifest = load_mind_manifest(store_dir, mind_id)
    _require_mind_namespace(manifest, namespace)
    adopted = adopt_graph_into_mind(
        store_dir,
        manifest.id,
        extract_graph_from_statement(cleaned),
        message=message.strip() or f"Remember on Mind `{manifest.id}`",
        source="mind.remember",
    )
    refresh_payload = _refresh_mind_mounts(store_dir, manifest.id)
    return {
        **adopted,
        "statement": cleaned,
        "mount_count": refresh_payload["mount_count"],
        "refreshed_mount_count": refresh_payload["refreshed_count"],
        "stale_mount_count": refresh_payload["stale_mount_count"],
        "stale_mounts": refresh_payload["stale_mounts"],
        "refresh_error_count": refresh_payload["refresh_error_count"],
        "refresh_errors": refresh_payload["refresh_errors"],
        "targets": refresh_payload["targets"],
    }


def _resolve_effective_policy(
    policies: dict[str, Any],
    manifest: MindManifest,
    *,
    target: str,
    policy_name: str,
) -> str:
    return (
        policy_name.strip()
        or str((policies.get("target_overrides") or {}).get(target) or "").strip()
        or str(policies.get("default_disclosure") or manifest.default_policy)
    )


def _evaluate_attachment_match(record: dict[str, Any], *, target: str, task: str) -> tuple[bool, str]:
    activation = dict(record.get("activation") or {})
    always_on = bool(activation.get("always_on", False))
    raw_targets = [str(item).strip() for item in activation.get("targets", [])]
    raw_terms = [str(item).strip().lower() for item in activation.get("task_terms", []) if str(item).strip()]
    if always_on:
        return True, "always_on"

    target_matches = not raw_targets or target in raw_targets
    task_lower = task.lower().strip()
    task_matches = not raw_terms or any(term in task_lower for term in raw_terms)

    if target_matches and task_matches:
        if raw_targets and raw_terms:
            return True, "target_and_task_match"
        if raw_targets:
            return True, "target_match"
        if raw_terms:
            return True, "task_match"
        return True, "default_attached"
    if not target_matches:
        return False, "target_mismatch"
    return False, "task_mismatch"


def _select_brainpacks_for_compose(
    store_dir: Path,
    mind_id: str,
    *,
    target: str,
    task: str,
    namespace: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from cortex.portable_runtime import canonical_target_name

    attachments = _load_attachments(store_dir, mind_id)
    attachment_details, _ = _attachment_details(
        store_dir,
        [dict(item) for item in attachments.get("brainpacks", [])],
        namespace=namespace,
    )
    canonical_target = canonical_target_name(target)
    included: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in attachment_details:
        evaluated = dict(item)
        evaluated["activation"]["targets"] = [
            canonical_target_name(name) for name in evaluated["activation"].get("targets", [])
        ]
        include, reason = _evaluate_attachment_match(evaluated, target=canonical_target, task=task)
        evaluated["selection_reason"] = reason
        if not evaluated.get("pack_exists", False):
            evaluated["selection_reason"] = "pack_missing"
            skipped.append(evaluated)
            continue
        if str(evaluated.get("compile_status") or "") != "compiled":
            evaluated["selection_reason"] = "pack_not_compiled"
            skipped.append(evaluated)
            continue
        if include:
            included.append(evaluated)
        else:
            skipped.append(evaluated)
    included.sort(key=lambda item: (-int(item.get("priority", 0)), str(item.get("pack") or "").lower()))
    return included, skipped


def _compose_graph_for_target(
    store_dir: Path,
    mind_id: str,
    *,
    target: str,
    task: str,
    policy_name: str,
    activation_target: str = "",
    namespace: str | None = None,
) -> dict[str, Any]:
    from cortex.packs import graph_path as pack_graph_path
    from cortex.portable_runtime import canonical_target_name, merge_graphs

    manifest = load_mind_manifest(store_dir, mind_id)
    _require_mind_namespace(manifest, namespace)
    policies = _load_policies(store_dir, mind_id, manifest)
    canonical_target = canonical_target_name(target)
    canonical_activation_target = canonical_target_name(activation_target.strip()) if activation_target.strip() else ""
    selection_target = canonical_activation_target or canonical_target
    effective_policy = _resolve_effective_policy(
        policies,
        manifest,
        target=canonical_target,
        policy_name=policy_name,
    )

    base_graph, base_graph_ref, base_graph_source = _resolve_core_graph(store_dir, mind_id)
    included_brainpacks, skipped_brainpacks = _select_brainpacks_for_compose(
        store_dir,
        mind_id,
        target=selection_target,
        task=task,
        namespace=namespace,
    )

    composed_graph = CortexGraph.from_v5_json(base_graph.export_v5())
    realized_brainpacks: list[dict[str, Any]] = []
    for item in included_brainpacks:
        pack_graph_file = pack_graph_path(store_dir, item["pack"])
        if not pack_graph_file.exists():
            skipped_item = dict(item)
            skipped_item["selection_reason"] = "pack_graph_missing"
            skipped_brainpacks.append(skipped_item)
            continue
        pack_graph = CortexGraph.from_v5_json(json.loads(pack_graph_file.read_text(encoding="utf-8")))
        composed_graph = merge_graphs(composed_graph, pack_graph)
        realized_brainpacks.append(item)

    return {
        "manifest": manifest,
        "policies": policies,
        "target": canonical_target,
        "activation_target": selection_target,
        "effective_policy": effective_policy,
        "task": task,
        "base_graph": base_graph,
        "base_graph_ref": base_graph_ref,
        "base_graph_source": base_graph_source,
        "included_brainpacks": realized_brainpacks,
        "skipped_brainpacks": skipped_brainpacks,
        "composed_graph": composed_graph,
    }


def _render_graph_for_target(
    graph: CortexGraph,
    *,
    target: str,
    smart: bool,
    policy_name: str,
    max_chars: int,
    project_dir: str = "",
) -> dict[str, Any]:
    from cortex.hermes_integration import build_hermes_documents
    from cortex.hooks import HookConfig, generate_compact_context
    from cortex.import_memory import NormalizedContext, export_claude_memories, export_claude_preferences
    from cortex.portability import PORTABLE_DIRECT_TARGETS, build_instruction_pack
    from cortex.portable_runtime import _policy_for_target, canonical_target_name, display_name
    from cortex.upai.disclosure import apply_disclosure

    canonical_target = canonical_target_name(target)
    policy, route_tags = _policy_for_target(canonical_target, smart=smart, policy_name=policy_name)
    filtered = apply_disclosure(graph, policy)
    ctx = NormalizedContext.from_v5(filtered.export_v5())
    facts = [
        {"id": node.id, "label": node.label, "tags": list(node.tags), "confidence": round(node.confidence, 2)}
        for node in sorted(filtered.nodes.values(), key=lambda item: (-item.confidence, item.label.lower()))
    ]
    resolved_project_dir = Path(project_dir).resolve() if project_dir else None

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
                filtered_path.write_text(
                    json.dumps(filtered.export_v5(), indent=2, ensure_ascii=False), encoding="utf-8"
                )
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
        "target": canonical_target,
        "name": display_name(canonical_target),
        "mode": "smart" if smart else "full",
        "policy": policy_name,
        "route_tags": route_tags,
        "fact_count": len(facts),
        "labels": [item["label"] for item in facts],
        "facts": facts,
        "project_dir": str(resolved_project_dir) if resolved_project_dir is not None else "",
        "context_markdown": context_markdown,
        "consume_as": consume_as,
        "target_payload": target_payload,
        "graph": filtered.export_v5(),
        "message": "" if facts else "This Mind did not yield routed facts for this target.",
    }


def compose_mind(
    store_dir: Path,
    mind_id: str,
    *,
    target: str,
    task: str = "",
    project_dir: str = "",
    smart: bool = True,
    policy_name: str = "",
    max_chars: int = 1500,
    activation_target: str = "",
    namespace: str | None = None,
) -> dict[str, Any]:
    composed = _compose_graph_for_target(
        store_dir,
        mind_id,
        target=target,
        task=task,
        policy_name=policy_name,
        activation_target=activation_target,
        namespace=namespace,
    )

    render_payload = _render_graph_for_target(
        composed["composed_graph"],
        target=composed["target"],
        smart=smart,
        policy_name=composed["effective_policy"],
        max_chars=max_chars,
        project_dir=project_dir,
    )
    return {
        "status": "ok",
        "mind": composed["manifest"].id,
        "branch": composed["manifest"].current_branch,
        "task": task,
        "activation_target": composed["activation_target"],
        "base_graph_ref": composed["base_graph_ref"],
        "base_graph_source": composed["base_graph_source"],
        "base_graph_node_count": len(composed["base_graph"].nodes),
        "base_graph_edge_count": len(composed["base_graph"].edges),
        "included_brainpacks": composed["included_brainpacks"],
        "skipped_brainpacks": composed["skipped_brainpacks"],
        "included_brainpack_count": len(composed["included_brainpacks"]),
        "composed_graph_node_count": len(composed["composed_graph"].nodes),
        "composed_graph_edge_count": len(composed["composed_graph"].edges),
        **render_payload,
    }


def mount_mind(
    store_dir: Path,
    mind_id: str,
    *,
    targets: list[str],
    task: str = "",
    project_dir: str = "",
    smart: bool = True,
    policy_name: str = "",
    max_chars: int = 1500,
    openclaw_store_dir: str = "",
    namespace: str | None = None,
) -> dict[str, Any]:
    from cortex.packs import default_output_dir
    from cortex.portable_runtime import canonical_target_name, sync_targets

    manifest = load_mind_manifest(store_dir, mind_id)
    _require_mind_namespace(manifest, namespace)
    policies = _load_policies(store_dir, manifest.id, manifest)
    if not targets:
        raise ValueError("Specify at least one mount target.")

    resolved_targets: list[str] = []
    for raw_target in targets:
        canonical = canonical_target_name(str(raw_target).strip().lower())
        if canonical not in SUPPORTED_MIND_MOUNT_TARGETS:
            raise ValueError(f"Unsupported Mind mount target: {raw_target}")
        if canonical not in resolved_targets:
            resolved_targets.append(canonical)

    project_path = str(Path(project_dir).resolve()) if project_dir else ""
    output_dir = default_output_dir(store_dir) / "minds" / manifest.id
    mount_results: list[dict[str, Any]] = []

    for target in resolved_targets:
        mounted_at = _iso_now()
        effective_policy = _resolve_effective_policy(policies, manifest, target=target, policy_name=policy_name)
        if target == "openclaw":
            openclaw_root = (
                Path(openclaw_store_dir).expanduser().resolve()
                if openclaw_store_dir
                else _default_openclaw_store_dir().resolve()
            )
            registry_path = mind_openclaw_mount_registry_path(openclaw_root)
            with locked_path(registry_path):
                registry = _load_openclaw_mind_mount_registry(openclaw_root)
                mounts = [
                    dict(item)
                    for item in registry.get("mounts", [])
                    if str(item.get("name") or "").strip() and str(item.get("name")) != manifest.id
                ]
                entry = {
                    "name": manifest.id,
                    "smart": smart,
                    "policy": policy_name,
                    "effective_policy": effective_policy,
                    "max_chars": max_chars,
                    "task": task,
                    "project_dir": project_path,
                    "activation_target": "openclaw",
                    "mounted_at": mounted_at,
                    "enabled": True,
                }
                mounts.append(entry)
                registry_payload = {
                    "status": "ok",
                    "mount_count": len(mounts),
                    "mounts": mounts,
                }
                registry_path = _write_openclaw_mind_mount_registry(openclaw_root, registry_payload)
            mount_results.append(
                {
                    "target": "openclaw",
                    "status": "ok",
                    "paths": [str(registry_path)],
                    "note": f"Registered Mind `{manifest.id}` for OpenClaw runtime composition.",
                    "mode": "smart" if smart else "full",
                    "route_tags": [],
                    "consume_as": "runtime_compose",
                    "project_dir": project_path,
                    "task": task,
                    "activation_target": "openclaw",
                    "smart": smart,
                    "policy": policy_name,
                    "effective_policy": effective_policy,
                    "max_chars": max_chars,
                    "openclaw_store_dir": str(openclaw_root),
                    "mounted_at": mounted_at,
                }
            )
            continue

        composed = compose_mind(
            store_dir,
            manifest.id,
            target=target,
            task=task,
            project_dir=project_path,
            smart=smart,
            policy_name=policy_name,
            max_chars=max_chars,
            namespace=namespace,
        )
        graph = CortexGraph.from_v5_json(dict(composed["graph"]))
        sync_payload = sync_targets(
            graph,
            targets=[target],
            store_dir=store_dir,
            project_dir=project_path,
            output_dir=output_dir,
            graph_path=mind_core_state_path(store_dir, manifest.id),
            policy_name="full",
            smart=False,
            max_chars=max_chars,
            persist_state=False,
        )
        target_result = dict(sync_payload.get("targets", [{}])[0])
        mount_results.append(
            {
                "target": target,
                "status": str(target_result.get("status") or "ok"),
                "paths": list(target_result.get("paths", [])),
                "note": str(target_result.get("note") or composed.get("message") or ""),
                "mode": str(composed.get("mode") or ("smart" if smart else "full")),
                "route_tags": list(composed.get("route_tags", [])),
                "fact_count": int(composed.get("fact_count") or 0),
                "consume_as": str(composed.get("consume_as") or ""),
                "project_dir": project_path,
                "task": task,
                "activation_target": str(composed.get("activation_target") or target),
                "smart": smart,
                "policy": policy_name,
                "effective_policy": str(composed.get("policy") or effective_policy),
                "max_chars": max_chars,
                "mounted_at": mounted_at,
            }
        )

    with locked_path(_store_lock_path(store_dir)):
        persisted = [
            dict(item)
            for item in _load_mounts(store_dir, manifest.id).get("mounts", [])
            if str(item.get("target") or "").strip() not in set(resolved_targets)
        ]
        persisted.extend(mount_results)
        persisted.sort(key=lambda item: str(item.get("target") or "").lower())
        mounts_payload = _write_mounts(store_dir, manifest.id, persisted)
        _replace_manifest(store_dir, manifest.id, updated_at=_iso_now())
    return {
        "status": "ok",
        "mind": manifest.id,
        "mounted_count": len(mount_results),
        "mount_count": mounts_payload["mount_count"],
        "targets": mount_results,
        "mounts": mounts_payload["mounts"],
        "mounts_path": str(mind_mounts_path(store_dir, manifest.id)),
    }


def list_mind_mounts(store_dir: Path, mind_id: str, *, namespace: str | None = None) -> dict[str, Any]:
    manifest = load_mind_manifest(store_dir, mind_id)
    _require_mind_namespace(manifest, namespace)
    payload = _load_mounts(store_dir, mind_id)
    mounts = [dict(item) for item in payload.get("mounts", [])]
    mounts.sort(key=lambda item: str(item.get("target") or "").lower())
    return {
        "status": "ok",
        "mind": mind_id,
        "mount_count": len(mounts),
        "mounted_targets": [str(item.get("target") or "") for item in mounts if str(item.get("target") or "").strip()],
        "mounts": mounts,
        "mounts_path": str(mind_mounts_path(store_dir, mind_id)),
    }


def _mind_summary(store_dir: Path, manifest: MindManifest) -> dict[str, Any]:
    configured_default = None
    try:
        configured_default = resolve_default_mind(store_dir)
    except (FileNotFoundError, ValueError):
        configured_default = None
    core_state = _read_json(
        mind_core_state_path(store_dir, manifest.id),
        default={"graph_ref": "", "categories": list(DEFAULT_CATEGORIES)},
    )
    attachments = _read_json(mind_attachments_path(store_dir, manifest.id), default={"brainpacks": []})
    attachment_records = [dict(item) for item in attachments.get("brainpacks", [])]
    attachment_details, attached_targets = _attachment_details(
        store_dir,
        attachment_records,
        namespace=manifest.namespace or None,
    )
    proposals = list_mind_proposals(store_dir, manifest.id, namespace=manifest.namespace)
    branches = _read_json(
        mind_branches_path(store_dir, manifest.id),
        default={"branches": {manifest.default_branch: {"head": "", "created_at": manifest.created_at}}},
    )
    mounts = _read_json(mind_mounts_path(store_dir, manifest.id), default={"mounts": []})
    policies = _read_json(
        mind_policies_path(store_dir, manifest.id),
        default={"default_disclosure": manifest.default_policy, "target_overrides": {}, "approval_rules": {}},
    )
    return {
        "mind": manifest.id,
        "manifest": asdict(manifest),
        "namespace": manifest.namespace,
        "path": str(mind_path(store_dir, manifest.id)),
        "graph_ref": str(core_state.get("graph_ref") or ""),
        "categories": [str(item) for item in core_state.get("categories", [])],
        "attachment_count": len(attachment_records),
        "attached_brainpacks": attachment_details,
        "attached_mount_count": sum(int(item.get("pack_mount_count") or 0) for item in attachment_details),
        "attached_mounted_targets": attached_targets,
        "branch_count": len(branches.get("branches", {})),
        "mount_count": len(mounts.get("mounts", [])),
        "proposal_count": int(proposals.get("proposal_count") or 0),
        "pending_proposal_count": int(proposals.get("pending_proposal_count") or 0),
        "mounts": [dict(item) for item in mounts.get("mounts", [])],
        "mounted_targets": [
            str(item.get("target") or "") for item in mounts.get("mounts", []) if str(item.get("target") or "").strip()
        ],
        "default_disclosure": str(policies.get("default_disclosure") or manifest.default_policy),
        "is_default": manifest.id == configured_default,
    }


def _mind_list_item(store_dir: Path, manifest: MindManifest, *, configured_default: str | None) -> dict[str, Any]:
    core_state = _read_json(
        mind_core_state_path(store_dir, manifest.id),
        default={"graph_ref": mind_branch_ref(manifest.id, manifest.current_branch)},
    )
    attachments = _read_json(mind_attachments_path(store_dir, manifest.id), default={"brainpacks": []})
    mounts = _read_json(mind_mounts_path(store_dir, manifest.id), default={"mounts": []})
    proposals = list_mind_proposals(store_dir, manifest.id, namespace=manifest.namespace)
    return {
        "mind": manifest.id,
        "namespace": manifest.namespace,
        "label": manifest.label,
        "kind": manifest.kind,
        "owner": manifest.owner,
        "current_branch": manifest.current_branch,
        "default_policy": manifest.default_policy,
        "graph_ref": str(core_state.get("graph_ref") or ""),
        "attachment_count": len(attachments.get("brainpacks", [])),
        "mount_count": len(mounts.get("mounts", [])),
        "proposal_count": int(proposals.get("proposal_count") or 0),
        "pending_proposal_count": int(proposals.get("pending_proposal_count") or 0),
        "updated_at": manifest.updated_at,
        "is_default": manifest.id == configured_default,
    }


def list_minds(store_dir: Path, *, namespace: str | None = None) -> dict[str, Any]:
    root = _minds_root(store_dir)
    if not root.exists():
        return {"status": "ok", "count": 0, "minds": []}

    minds: list[dict[str, Any]] = []
    try:
        configured_default = resolve_default_mind(store_dir)
    except (FileNotFoundError, ValueError):
        configured_default = None
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir():
            continue
        manifest_file = child / "manifest.json"
        if not manifest_file.exists():
            continue
        try:
            manifest = load_mind_manifest(store_dir, child.name)
        except (FileNotFoundError, KeyError, json.JSONDecodeError):
            continue
        if not resource_namespace_matches(manifest.namespace, namespace):
            continue
        minds.append(_mind_list_item(store_dir, manifest, configured_default=configured_default))
    return {"status": "ok", "count": len(minds), "minds": minds}


def _mind_preview_nodes(graph: CortexGraph, *, limit: int = 8) -> list[dict[str, Any]]:
    ranked = sorted(
        graph.nodes.values(),
        key=lambda node: (
            -(float(node.confidence or 0)),
            -(len(node.tags or [])),
            node.label.lower(),
        ),
    )
    preview: list[dict[str, Any]] = []
    for node in ranked[:limit]:
        preview.append(
            {
                "id": node.id,
                "label": node.label,
                "tags": list(node.tags or []),
                "confidence": float(node.confidence or 0),
                "brief": node.brief or "",
            }
        )
    return preview


def list_mind_proposals(store_dir: Path, mind_id: str, *, namespace: str | None = None) -> dict[str, Any]:
    manifest = load_mind_manifest(store_dir, mind_id)
    _require_mind_namespace(manifest, namespace)
    root = mind_proposals_dir(store_dir, manifest.id)
    proposals: list[dict[str, Any]] = []
    if root.exists():
        for child in sorted(root.glob("*.json"), key=lambda item: item.name.lower()):
            try:
                payload = json.loads(child.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            proposal_id = str(payload.get("proposal_id") or child.stem).strip() or child.stem
            proposals.append(
                {
                    "proposal_id": proposal_id,
                    "status": str(payload.get("status") or "pending_review").strip() or "pending_review",
                    "created_at": str(payload.get("created_at") or ""),
                    "trust_level": str(payload.get("trust_level") or "unverified"),
                    "review_required": bool(payload.get("review_required", True)),
                    "proposed_source_count": int(payload.get("proposed_source_count") or 0),
                    "graph_node_count": int(payload.get("graph_node_count") or 0),
                    "graph_edge_count": int(payload.get("graph_edge_count") or 0),
                    "path": str(child),
                }
            )
    pending = [item for item in proposals if item.get("status") == "pending_review"]
    return {
        "status": "ok",
        "mind": manifest.id,
        "proposal_count": len(proposals),
        "pending_proposal_count": len(pending),
        "proposals": proposals,
    }


def mind_status(store_dir: Path, mind_id: str, *, namespace: str | None = None) -> dict[str, Any]:
    manifest = load_mind_manifest(store_dir, mind_id)
    _require_mind_namespace(manifest, namespace)
    payload = _mind_summary(store_dir, manifest)
    core_graph_payload = load_mind_core_graph(store_dir, mind_id)
    core_graph = core_graph_payload["graph"]
    branches_payload = _load_branches(store_dir, mind_id, manifest)
    policies_payload = _load_policies(store_dir, mind_id, manifest)
    proposals_payload = list_mind_proposals(store_dir, mind_id, namespace=manifest.namespace)
    current_branch = manifest.current_branch or manifest.default_branch
    current_branch_record = dict(branches_payload.get("branches", {}).get(current_branch) or {})
    payload["layout"] = {
        "files": list(MIND_LAYOUT_FILES),
        "directories": list(MIND_LAYOUT_DIRECTORIES),
    }
    payload["core_state"] = {
        "graph_ref": payload["graph_ref"],
        "graph_source": str(core_graph_payload.get("graph_source") or ""),
        "fact_count": len(core_graph.nodes),
        "edge_count": len(core_graph.edges),
        "categories": [str(item) for item in payload.get("categories", [])],
        "preview_nodes": _mind_preview_nodes(core_graph),
    }
    payload["branches"] = {
        "current_branch": current_branch,
        "default_branch": manifest.default_branch,
        "current_branch_head": str(current_branch_record.get("head") or ""),
        "branch_records": {
            str(name): {
                "head": str((record or {}).get("head") or ""),
                "created_at": str((record or {}).get("created_at") or ""),
            }
            for name, record in sorted((branches_payload.get("branches") or {}).items())
        },
    }
    payload["policies"] = {
        "default_disclosure": str(policies_payload.get("default_disclosure") or manifest.default_policy),
        "target_overrides": {
            str(name): str(value) for name, value in sorted((policies_payload.get("target_overrides") or {}).items())
        },
        "approval_rules": {
            str(name): bool(value) for name, value in sorted((policies_payload.get("approval_rules") or {}).items())
        },
    }
    payload["proposals"] = {
        "proposal_count": int(proposals_payload.get("proposal_count") or 0),
        "pending_proposal_count": int(proposals_payload.get("pending_proposal_count") or 0),
        "items": [dict(item) for item in proposals_payload.get("proposals", [])],
    }
    return {"status": "ok", **payload}
