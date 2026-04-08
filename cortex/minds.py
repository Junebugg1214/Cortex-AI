from __future__ import annotations

import json
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cortex.graph import CortexGraph

MINDS_DIRNAME = "minds"
MIND_KINDS = ("person", "agent", "project", "team")
DEFAULT_BRANCH = "main"
DEFAULT_POLICY = "professional"
ATTACHMENT_MODE = "attached"
ATTACHMENT_SCOPE = "specialist"
DEFAULT_CATEGORIES = (
    "identity",
    "professional_context",
    "business_context",
    "active_priorities",
    "technical_expertise",
    "domain_knowledge",
    "relationships",
    "constraints",
    "values",
    "user_preferences",
    "communication_preferences",
)
MIND_LAYOUT_FILES = (
    "manifest.json",
    "core_state.json",
    "attachments.json",
    "branches.json",
    "policies.json",
    "mounts.json",
)


@dataclass(frozen=True, slots=True)
class MindManifest:
    id: str
    label: str
    kind: str
    owner: str
    created_at: str
    updated_at: str
    default_branch: str = DEFAULT_BRANCH
    current_branch: str = DEFAULT_BRANCH
    default_policy: str = DEFAULT_POLICY


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _minds_root(store_dir: Path) -> Path:
    return Path(store_dir) / MINDS_DIRNAME


def _validate_mind_id(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Mind id is required.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,63}", cleaned):
        raise ValueError("Mind ids must use letters, numbers, '.', '-', or '_' and start with an alphanumeric.")
    return cleaned


def _validate_kind(kind: str) -> str:
    cleaned = kind.strip().lower()
    if cleaned not in MIND_KINDS:
        raise ValueError(f"Mind kind must be one of: {', '.join(MIND_KINDS)}.")
    return cleaned


def _default_label(mind_id: str) -> str:
    parts = [part for part in re.split(r"[-_.]+", mind_id.strip()) if part]
    return " ".join(part.capitalize() for part in parts) or mind_id


def _read_json(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_manifest(store_dir: Path, manifest: MindManifest) -> None:
    _write_json(mind_manifest_path(store_dir, manifest.id), asdict(manifest))


def mind_path(store_dir: Path, mind_id: str) -> Path:
    return _minds_root(store_dir) / _validate_mind_id(mind_id)


def mind_manifest_path(store_dir: Path, mind_id: str) -> Path:
    return mind_path(store_dir, mind_id) / "manifest.json"


def mind_core_state_path(store_dir: Path, mind_id: str) -> Path:
    return mind_path(store_dir, mind_id) / "core_state.json"


def mind_attachments_path(store_dir: Path, mind_id: str) -> Path:
    return mind_path(store_dir, mind_id) / "attachments.json"


def mind_branches_path(store_dir: Path, mind_id: str) -> Path:
    return mind_path(store_dir, mind_id) / "branches.json"


def mind_policies_path(store_dir: Path, mind_id: str) -> Path:
    return mind_path(store_dir, mind_id) / "policies.json"


def mind_mounts_path(store_dir: Path, mind_id: str) -> Path:
    return mind_path(store_dir, mind_id) / "mounts.json"


def load_mind_manifest(store_dir: Path, mind_id: str) -> MindManifest:
    path = mind_manifest_path(store_dir, mind_id)
    if not path.exists():
        raise FileNotFoundError(f"Mind '{mind_id}' does not exist.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return MindManifest(
        id=str(payload["id"]),
        label=str(payload["label"]),
        kind=str(payload["kind"]),
        owner=str(payload.get("owner") or ""),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
        default_branch=str(payload.get("default_branch") or DEFAULT_BRANCH),
        current_branch=str(payload.get("current_branch") or DEFAULT_BRANCH),
        default_policy=str(payload.get("default_policy") or DEFAULT_POLICY),
    )


def _replace_manifest(store_dir: Path, mind_id: str, *, updated_at: str) -> MindManifest:
    manifest = load_mind_manifest(store_dir, mind_id)
    updated = MindManifest(
        id=manifest.id,
        label=manifest.label,
        kind=manifest.kind,
        owner=manifest.owner,
        created_at=manifest.created_at,
        updated_at=updated_at,
        default_branch=manifest.default_branch,
        current_branch=manifest.current_branch,
        default_policy=manifest.default_policy,
    )
    _write_manifest(store_dir, updated)
    return updated


def init_mind(
    store_dir: Path,
    mind_id: str,
    *,
    kind: str = "person",
    label: str = "",
    owner: str = "",
    default_policy: str = DEFAULT_POLICY,
) -> dict[str, Any]:
    normalized_id = _validate_mind_id(mind_id)
    normalized_kind = _validate_kind(kind)
    root = mind_path(store_dir, normalized_id)
    if root.exists():
        raise FileExistsError(f"Mind '{normalized_id}' already exists.")

    created_at = _iso_now()
    manifest = MindManifest(
        id=normalized_id,
        label=label.strip() or _default_label(normalized_id),
        kind=normalized_kind,
        owner=owner.strip(),
        created_at=created_at,
        updated_at=created_at,
        default_policy=default_policy.strip() or DEFAULT_POLICY,
    )
    root.mkdir(parents=True, exist_ok=False)
    (root / "compositions").mkdir(parents=True, exist_ok=True)
    (root / "refs").mkdir(parents=True, exist_ok=True)
    _write_manifest(store_dir, manifest)
    _write_json(
        mind_core_state_path(store_dir, normalized_id),
        {
            "mind": normalized_id,
            "graph_ref": f"refs/minds/{normalized_id}/branches/{manifest.default_branch}",
            "categories": list(DEFAULT_CATEGORIES),
        },
    )
    _write_json(
        mind_attachments_path(store_dir, normalized_id),
        {
            "mind": normalized_id,
            "brainpacks": [],
        },
    )
    _write_json(
        mind_branches_path(store_dir, normalized_id),
        {
            "mind": normalized_id,
            "branches": {
                manifest.default_branch: {
                    "head": "",
                    "created_at": created_at,
                }
            },
        },
    )
    _write_json(
        mind_policies_path(store_dir, normalized_id),
        {
            "mind": normalized_id,
            "default_disclosure": manifest.default_policy,
            "target_overrides": {},
            "approval_rules": {
                "merge_to_main_requires_review": True,
                "external_mount_requires_explicit_approval": True,
            },
        },
    )
    _write_json(
        mind_mounts_path(store_dir, normalized_id),
        {
            "mind": normalized_id,
            "mounts": [],
        },
    )
    return {
        "status": "ok",
        "created": True,
        "mind": normalized_id,
        "path": str(root),
        "manifest": str(mind_manifest_path(store_dir, normalized_id)),
    }


def _clean_strings(values: list[str] | tuple[str, ...] | None) -> list[str]:
    if not values:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


def _attachment_pack_name(record: dict[str, Any]) -> str:
    pack_name = str(record.get("id") or "").strip()
    if pack_name:
        return pack_name
    pack_ref = str(record.get("pack_ref") or "").strip()
    if pack_ref.startswith("packs/"):
        return pack_ref.split("/", 1)[1]
    return pack_ref


def _load_attachments(store_dir: Path, mind_id: str) -> dict[str, Any]:
    return _read_json(mind_attachments_path(store_dir, mind_id), default={"mind": mind_id, "brainpacks": []})


def attach_pack_to_mind(
    store_dir: Path,
    mind_id: str,
    pack_name: str,
    *,
    priority: int = 100,
    always_on: bool = False,
    targets: list[str] | None = None,
    task_terms: list[str] | None = None,
) -> dict[str, Any]:
    from cortex.portable_runtime import canonical_target_name

    normalized_mind_id = _validate_mind_id(mind_id)
    load_mind_manifest(store_dir, normalized_mind_id)

    from cortex.packs import load_manifest as load_pack_manifest

    pack_manifest = load_pack_manifest(store_dir, pack_name)
    attachments_payload = _load_attachments(store_dir, normalized_mind_id)
    records = [dict(item) for item in attachments_payload.get("brainpacks", [])]
    now = _iso_now()
    updated = False
    normalized_targets = [canonical_target_name(item) for item in _clean_strings(targets)]

    attachment_record = {
        "id": pack_manifest.name,
        "pack_ref": f"packs/{pack_manifest.name}",
        "mode": ATTACHMENT_MODE,
        "scope": ATTACHMENT_SCOPE,
        "priority": int(priority),
        "activation": {
            "targets": normalized_targets,
            "task_terms": _clean_strings(task_terms),
            "always_on": bool(always_on),
        },
        "attached_at": now,
        "updated_at": now,
    }

    for index, existing in enumerate(records):
        if _attachment_pack_name(existing) != pack_manifest.name:
            continue
        attachment_record["attached_at"] = str(existing.get("attached_at") or now)
        records[index] = attachment_record
        updated = True
        break
    else:
        records.append(attachment_record)

    records.sort(key=lambda item: (-int(item.get("priority", 0)), _attachment_pack_name(item).lower()))
    attachments_payload["mind"] = normalized_mind_id
    attachments_payload["brainpacks"] = records
    _write_json(mind_attachments_path(store_dir, normalized_mind_id), attachments_payload)
    _replace_manifest(store_dir, normalized_mind_id, updated_at=now)

    return {
        "status": "ok",
        "mind": normalized_mind_id,
        "pack": pack_manifest.name,
        "attached": not updated,
        "updated": updated,
        "attachment_count": len(records),
        "attachment": attachment_record,
    }


def detach_pack_from_mind(store_dir: Path, mind_id: str, pack_name: str) -> dict[str, Any]:
    normalized_mind_id = _validate_mind_id(mind_id)
    load_mind_manifest(store_dir, normalized_mind_id)

    target = str(pack_name).strip()
    if not target:
        raise ValueError("Pack name is required.")

    attachments_payload = _load_attachments(store_dir, normalized_mind_id)
    records = [dict(item) for item in attachments_payload.get("brainpacks", [])]
    remaining = [item for item in records if _attachment_pack_name(item) != target]
    if len(remaining) == len(records):
        raise ValueError(f"Brainpack '{target}' is not attached to Mind '{normalized_mind_id}'.")

    attachments_payload["mind"] = normalized_mind_id
    attachments_payload["brainpacks"] = remaining
    _write_json(mind_attachments_path(store_dir, normalized_mind_id), attachments_payload)
    _replace_manifest(store_dir, normalized_mind_id, updated_at=_iso_now())
    return {
        "status": "ok",
        "mind": normalized_mind_id,
        "pack": target,
        "detached": True,
        "attachment_count": len(remaining),
    }


def _attachment_details(store_dir: Path, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    from cortex.packs import pack_status

    details: list[dict[str, Any]] = []
    aggregate_targets: set[str] = set()
    for record in records:
        pack_name = _attachment_pack_name(record)
        activation = dict(record.get("activation") or {})
        detail = {
            "id": str(record.get("id") or pack_name),
            "pack": pack_name,
            "pack_ref": str(record.get("pack_ref") or f"packs/{pack_name}"),
            "mode": str(record.get("mode") or ATTACHMENT_MODE),
            "scope": str(record.get("scope") or ATTACHMENT_SCOPE),
            "priority": int(record.get("priority") or 0),
            "activation": {
                "targets": _clean_strings(list(activation.get("targets") or [])),
                "task_terms": _clean_strings(list(activation.get("task_terms") or [])),
                "always_on": bool(activation.get("always_on", False)),
            },
            "attached_at": str(record.get("attached_at") or ""),
            "updated_at": str(record.get("updated_at") or ""),
            "pack_exists": False,
            "pack_description": "",
            "pack_owner": "",
            "compile_status": "missing",
            "pack_mount_count": 0,
            "mounted_targets": [],
        }
        try:
            status = pack_status(store_dir, pack_name)
        except FileNotFoundError:
            status = None
        if status is not None:
            detail["pack_exists"] = True
            detail["pack_description"] = str(status["manifest"].get("description") or "")
            detail["pack_owner"] = str(status["manifest"].get("owner") or "")
            detail["compile_status"] = str(status.get("compile_status") or "idle")
            detail["pack_mount_count"] = int(status.get("mount_count") or 0)
            detail["mounted_targets"] = [str(item) for item in status.get("mounted_targets", []) if str(item).strip()]
            aggregate_targets.update(detail["mounted_targets"])
        details.append(detail)
    return details, sorted(aggregate_targets)


def _load_policies(store_dir: Path, mind_id: str, manifest: MindManifest) -> dict[str, Any]:
    return _read_json(
        mind_policies_path(store_dir, mind_id),
        default={"default_disclosure": manifest.default_policy, "target_overrides": {}, "approval_rules": {}},
    )


def _resolve_core_graph(store_dir: Path, mind_id: str) -> tuple[CortexGraph, str, str]:
    from cortex.portable_runtime import load_canonical_graph, load_portability_state
    from cortex.storage import get_storage_backend

    core_state = _read_json(
        mind_core_state_path(store_dir, mind_id),
        default={"graph_ref": "", "categories": list(DEFAULT_CATEGORIES)},
    )
    declared_ref = str(core_state.get("graph_ref") or "").strip()
    backend = get_storage_backend(store_dir)
    if declared_ref:
        resolved = backend.versions.resolve_ref(declared_ref)
        if resolved is not None:
            return backend.versions.checkout(resolved), declared_ref, "version_ref"

    portability_state = load_portability_state(store_dir)
    canonical_graph, canonical_path = load_canonical_graph(store_dir, portability_state)
    if canonical_graph.nodes:
        return canonical_graph, str(canonical_path), "portable_canonical_graph"

    head = backend.versions.resolve_ref("HEAD")
    if head is not None:
        return backend.versions.checkout(head), "HEAD", "version_head"

    return CortexGraph(), declared_ref, "empty_graph"


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
    store_dir: Path, mind_id: str, *, target: str, task: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from cortex.portable_runtime import canonical_target_name

    attachments = _load_attachments(store_dir, mind_id)
    attachment_details, _ = _attachment_details(store_dir, [dict(item) for item in attachments.get("brainpacks", [])])
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
) -> dict[str, Any]:
    from cortex.packs import graph_path as pack_graph_path
    from cortex.portable_runtime import canonical_target_name, merge_graphs

    manifest = load_mind_manifest(store_dir, mind_id)
    policies = _load_policies(store_dir, mind_id, manifest)
    canonical_target = canonical_target_name(target)
    effective_policy = (
        policy_name.strip()
        or str((policies.get("target_overrides") or {}).get(canonical_target) or "").strip()
        or str(policies.get("default_disclosure") or manifest.default_policy)
    )

    base_graph, base_graph_ref, base_graph_source = _resolve_core_graph(store_dir, mind_id)
    included_brainpacks, skipped_brainpacks = _select_brainpacks_for_compose(
        store_dir,
        mind_id,
        target=canonical_target,
        task=task,
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

    render_payload = _render_graph_for_target(
        composed_graph,
        target=canonical_target,
        smart=smart,
        policy_name=effective_policy,
        max_chars=max_chars,
        project_dir=project_dir,
    )
    return {
        "status": "ok",
        "mind": manifest.id,
        "branch": manifest.current_branch,
        "task": task,
        "base_graph_ref": base_graph_ref,
        "base_graph_source": base_graph_source,
        "base_graph_node_count": len(base_graph.nodes),
        "base_graph_edge_count": len(base_graph.edges),
        "included_brainpacks": realized_brainpacks,
        "skipped_brainpacks": skipped_brainpacks,
        "included_brainpack_count": len(realized_brainpacks),
        "composed_graph_node_count": len(composed_graph.nodes),
        "composed_graph_edge_count": len(composed_graph.edges),
        **render_payload,
    }


def _mind_summary(store_dir: Path, manifest: MindManifest) -> dict[str, Any]:
    core_state = _read_json(
        mind_core_state_path(store_dir, manifest.id),
        default={"graph_ref": "", "categories": list(DEFAULT_CATEGORIES)},
    )
    attachments = _read_json(mind_attachments_path(store_dir, manifest.id), default={"brainpacks": []})
    attachment_records = [dict(item) for item in attachments.get("brainpacks", [])]
    attachment_details, attached_targets = _attachment_details(store_dir, attachment_records)
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
        "path": str(mind_path(store_dir, manifest.id)),
        "graph_ref": str(core_state.get("graph_ref") or ""),
        "categories": [str(item) for item in core_state.get("categories", [])],
        "attachment_count": len(attachment_records),
        "attached_brainpacks": attachment_details,
        "attached_mount_count": sum(int(item.get("pack_mount_count") or 0) for item in attachment_details),
        "attached_mounted_targets": attached_targets,
        "branch_count": len(branches.get("branches", {})),
        "mount_count": len(mounts.get("mounts", [])),
        "mounts": [dict(item) for item in mounts.get("mounts", [])],
        "default_disclosure": str(policies.get("default_disclosure") or manifest.default_policy),
    }


def list_minds(store_dir: Path) -> dict[str, Any]:
    root = _minds_root(store_dir)
    if not root.exists():
        return {"status": "ok", "count": 0, "minds": []}

    minds: list[dict[str, Any]] = []
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
        summary = _mind_summary(store_dir, manifest)
        minds.append(
            {
                "mind": summary["mind"],
                "label": summary["manifest"]["label"],
                "kind": summary["manifest"]["kind"],
                "owner": summary["manifest"]["owner"],
                "current_branch": summary["manifest"]["current_branch"],
                "default_policy": summary["manifest"]["default_policy"],
                "graph_ref": summary["graph_ref"],
                "attachment_count": summary["attachment_count"],
                "mount_count": summary["mount_count"],
                "updated_at": summary["manifest"]["updated_at"],
            }
        )
    return {"status": "ok", "count": len(minds), "minds": minds}


def mind_status(store_dir: Path, mind_id: str) -> dict[str, Any]:
    manifest = load_mind_manifest(store_dir, mind_id)
    payload = _mind_summary(store_dir, manifest)
    payload["layout"] = {
        "files": list(MIND_LAYOUT_FILES),
        "directories": ["compositions", "refs"],
    }
    return {"status": "ok", **payload}
