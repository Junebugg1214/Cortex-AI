from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cortex.atomic_io import atomic_write_json, atomic_write_text, locked_path
from cortex.graph import CortexGraph
from cortex.namespaces import describe_resource_namespace, normalize_resource_namespace, resource_namespace_matches

MINDS_DIRNAME = "minds"
MIND_KINDS = ("person", "agent", "project", "team")
DEFAULT_BRANCH = "main"
DEFAULT_POLICY = "professional"
ATTACHMENT_MODE = "attached"
ATTACHMENT_SCOPE = "specialist"
OPENCLAW_MIND_MOUNTS_FILE = "minds.mounted.json"
DEFAULT_MIND_CONFIG_FILE = "default.json"
MIND_PROPOSALS_DIRNAME = "proposals"
SUPPORTED_MIND_MOUNT_TARGETS = (
    "claude-code",
    "codex",
    "cursor",
    "hermes",
    "openclaw",
)
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
MIND_LAYOUT_DIRECTORIES = ("compositions", MIND_PROPOSALS_DIRNAME, "refs")


@dataclass(frozen=True, slots=True)
class MindManifest:
    id: str
    label: str
    kind: str
    owner: str
    namespace: str | None
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


def _require_mind_namespace(manifest: MindManifest, namespace: str | None) -> None:
    if resource_namespace_matches(manifest.namespace, namespace):
        return
    raise PermissionError(f"Mind '{manifest.id}' is outside namespace '{describe_resource_namespace(namespace)}'.")


def _read_json(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)


def _store_lock_path(store_dir: Path) -> Path:
    return Path(store_dir)


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


def mind_branch_name(mind_id: str, branch: str = DEFAULT_BRANCH) -> str:
    return f"minds/{_validate_mind_id(mind_id)}/{branch.strip() or DEFAULT_BRANCH}"


def mind_branch_ref(mind_id: str, branch: str = DEFAULT_BRANCH) -> str:
    return f"refs/minds/{_validate_mind_id(mind_id)}/branches/{branch.strip() or DEFAULT_BRANCH}"


def _branch_from_mind_ref(mind_id: str, ref: str) -> str | None:
    prefix = f"refs/minds/{_validate_mind_id(mind_id)}/branches/"
    if ref.startswith(prefix):
        return ref[len(prefix) :] or DEFAULT_BRANCH
    return None


def _default_openclaw_store_dir() -> Path:
    return Path.home() / ".openclaw" / "cortex"


def mind_openclaw_mount_registry_path(openclaw_store_dir: Path | None = None) -> Path:
    root = Path(openclaw_store_dir) if openclaw_store_dir is not None else _default_openclaw_store_dir()
    return root / OPENCLAW_MIND_MOUNTS_FILE


def default_mind_config_path(store_dir: Path) -> Path:
    return _minds_root(store_dir) / DEFAULT_MIND_CONFIG_FILE


def mind_proposals_dir(store_dir: Path, mind_id: str) -> Path:
    return mind_path(store_dir, mind_id) / MIND_PROPOSALS_DIRNAME


def mind_proposal_path(store_dir: Path, mind_id: str, proposal_id: str) -> Path:
    return mind_proposals_dir(store_dir, mind_id) / f"{proposal_id}.json"


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
        namespace=normalize_resource_namespace(payload.get("namespace")),
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
        namespace=manifest.namespace,
        created_at=manifest.created_at,
        updated_at=updated_at,
        default_branch=manifest.default_branch,
        current_branch=manifest.current_branch,
        default_policy=manifest.default_policy,
    )
    _write_manifest(store_dir, updated)
    return updated


def default_mind_status(store_dir: Path) -> dict[str, Any]:
    env_value = os.getenv("CORTEX_DEFAULT_MIND", "").strip()
    if env_value:
        normalized = _validate_mind_id(env_value)
        load_mind_manifest(store_dir, normalized)
        return {
            "status": "ok",
            "configured": True,
            "mind": normalized,
            "source": "env",
            "path": "",
        }

    path = default_mind_config_path(store_dir)
    payload = _read_json(path, default={"mind": "", "configured_at": ""})
    configured_mind = str(payload.get("mind") or "").strip()
    if not configured_mind:
        return {
            "status": "ok",
            "configured": False,
            "mind": "",
            "source": "config",
            "path": str(path),
        }
    normalized = _validate_mind_id(configured_mind)
    load_mind_manifest(store_dir, normalized)
    return {
        "status": "ok",
        "configured": True,
        "mind": normalized,
        "source": "config",
        "path": str(path),
    }


def resolve_default_mind(store_dir: Path) -> str | None:
    payload = default_mind_status(store_dir)
    if not payload["configured"]:
        return None
    return str(payload["mind"])


def set_default_mind(store_dir: Path, mind_id: str) -> dict[str, Any]:
    manifest = load_mind_manifest(store_dir, mind_id)
    path = default_mind_config_path(store_dir)
    payload = {
        "mind": manifest.id,
        "configured_at": _iso_now(),
    }
    with locked_path(_store_lock_path(store_dir)):
        _write_json(path, payload)
    return {
        "status": "ok",
        "configured": True,
        "mind": manifest.id,
        "source": "config",
        "path": str(path),
    }


def clear_default_mind(store_dir: Path) -> dict[str, Any]:
    path = default_mind_config_path(store_dir)
    with locked_path(_store_lock_path(store_dir)):
        existed = path.exists()
        if existed:
            path.unlink()
    return {
        "status": "ok",
        "configured": False,
        "cleared": existed,
        "mind": "",
        "source": "config",
        "path": str(path),
    }


def init_mind(
    store_dir: Path,
    mind_id: str,
    *,
    kind: str = "person",
    label: str = "",
    owner: str = "",
    namespace: str | None = None,
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
        namespace=normalize_resource_namespace(namespace),
        created_at=created_at,
        updated_at=created_at,
        default_policy=default_policy.strip() or DEFAULT_POLICY,
    )
    with locked_path(_store_lock_path(store_dir)):
        root.mkdir(parents=True, exist_ok=False)
        (root / "compositions").mkdir(parents=True, exist_ok=True)
        (root / MIND_PROPOSALS_DIRNAME).mkdir(parents=True, exist_ok=True)
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


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    cleaned = str(value).strip().lower()
    if not cleaned:
        return default
    if cleaned in {"1", "true", "yes", "on"}:
        return True
    if cleaned in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_positive_int(value: Any, *, default: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return default
    return coerced if coerced > 0 else default


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


def _load_mounts(store_dir: Path, mind_id: str) -> dict[str, Any]:
    return _read_json(mind_mounts_path(store_dir, mind_id), default={"mind": mind_id, "mounts": []})


def _load_core_state(store_dir: Path, mind_id: str) -> dict[str, Any]:
    return _read_json(
        mind_core_state_path(store_dir, mind_id),
        default={"mind": mind_id, "graph_ref": "", "categories": list(DEFAULT_CATEGORIES)},
    )


def _load_branches(store_dir: Path, mind_id: str, manifest: MindManifest) -> dict[str, Any]:
    return _read_json(
        mind_branches_path(store_dir, mind_id),
        default={
            "mind": mind_id,
            "branches": {manifest.default_branch: {"head": "", "created_at": manifest.created_at}},
        },
    )


def _graph_categories(graph: CortexGraph) -> list[str]:
    categories = graph.export_v4().get("categories", {})
    names = [str(name) for name, items in categories.items() if items]
    return names or list(DEFAULT_CATEGORIES)


def _write_mounts(store_dir: Path, mind_id: str, mounts: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "status": "ok",
        "mind": mind_id,
        "mount_count": len(mounts),
        "mounts": mounts,
    }
    _write_json(mind_mounts_path(store_dir, mind_id), payload)
    return payload


def _load_openclaw_mind_mount_registry(openclaw_store_dir: Path) -> dict[str, Any]:
    return _read_json(
        mind_openclaw_mount_registry_path(openclaw_store_dir),
        default={"status": "ok", "mount_count": 0, "mounts": []},
    )


def _write_openclaw_mind_mount_registry(openclaw_store_dir: Path, payload: dict[str, Any]) -> Path:
    path = mind_openclaw_mount_registry_path(openclaw_store_dir)
    with locked_path(path):
        _write_json(path, payload)
    return path


def attach_pack_to_mind(
    store_dir: Path,
    mind_id: str,
    pack_name: str,
    *,
    priority: int = 100,
    always_on: bool = False,
    targets: list[str] | None = None,
    task_terms: list[str] | None = None,
    namespace: str | None = None,
) -> dict[str, Any]:
    from cortex.portable_runtime import canonical_target_name

    normalized_mind_id = _validate_mind_id(mind_id)
    manifest = load_mind_manifest(store_dir, normalized_mind_id)
    _require_mind_namespace(manifest, namespace)

    from cortex.packs import load_manifest as load_pack_manifest

    pack_manifest = load_pack_manifest(store_dir, pack_name)
    if not resource_namespace_matches(pack_manifest.namespace, namespace):
        raise PermissionError(
            f"Brainpack '{pack_manifest.name}' is outside namespace '{describe_resource_namespace(namespace)}'."
        )
    now = _iso_now()
    updated = False
    normalized_targets = [canonical_target_name(item) for item in _clean_strings(targets)]

    with locked_path(_store_lock_path(store_dir)):
        attachments_payload = _load_attachments(store_dir, normalized_mind_id)
        records = [dict(item) for item in attachments_payload.get("brainpacks", [])]
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


def detach_pack_from_mind(
    store_dir: Path,
    mind_id: str,
    pack_name: str,
    *,
    namespace: str | None = None,
) -> dict[str, Any]:
    normalized_mind_id = _validate_mind_id(mind_id)
    manifest = load_mind_manifest(store_dir, normalized_mind_id)
    _require_mind_namespace(manifest, namespace)

    target = str(pack_name).strip()
    if not target:
        raise ValueError("Pack name is required.")

    with locked_path(_store_lock_path(store_dir)):
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


def _attachment_details(
    store_dir: Path,
    records: list[dict[str, Any]],
    *,
    namespace: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
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
            status = pack_status(store_dir, pack_name, namespace=namespace)
        except (FileNotFoundError, PermissionError):
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

    manifest = load_mind_manifest(store_dir, mind_id)
    core_state = _load_core_state(store_dir, mind_id)
    declared_ref = str(core_state.get("graph_ref") or "").strip()
    backend = get_storage_backend(store_dir)
    if declared_ref:
        resolved = backend.versions.resolve_ref(declared_ref)
        if resolved is not None:
            return backend.versions.checkout(resolved), declared_ref, "version_ref"
        branch = _branch_from_mind_ref(mind_id, declared_ref)
        if branch is not None:
            branch_name = mind_branch_name(mind_id, branch)
            resolved = backend.versions.resolve_ref(branch_name)
            if resolved is not None:
                return backend.versions.checkout(resolved), declared_ref, "mind_branch_ref"
    branch_name = mind_branch_name(mind_id, manifest.current_branch)
    branch_head = backend.versions.resolve_ref(branch_name)
    if branch_head is not None:
        return backend.versions.checkout(branch_head), mind_branch_ref(mind_id, manifest.current_branch), "mind_branch"

    portability_state = load_portability_state(store_dir)
    canonical_graph, canonical_path = load_canonical_graph(store_dir, portability_state)
    if canonical_graph.nodes:
        return canonical_graph, str(canonical_path), "portable_canonical_graph"

    head = backend.versions.resolve_ref("HEAD")
    if head is not None:
        return backend.versions.checkout(head), "HEAD", "version_head"

    return CortexGraph(), declared_ref, "empty_graph"


def load_mind_core_graph(store_dir: Path, mind_id: str) -> dict[str, Any]:
    manifest = load_mind_manifest(store_dir, mind_id)
    graph, graph_ref, graph_source = _resolve_core_graph(store_dir, mind_id)
    return {
        "status": "ok",
        "mind": manifest.id,
        "graph": graph,
        "graph_ref": graph_ref,
        "graph_source": graph_source,
        "fact_count": len(graph.nodes),
    }


def mind_graph_snapshot_path(store_dir: Path, mind_id: str) -> Path:
    return mind_path(store_dir, mind_id) / "refs" / "current.graph.json"


def _persist_mind_core_graph(
    store_dir: Path,
    mind_id: str,
    graph: CortexGraph,
    *,
    message: str,
    source: str,
    acquire_lock: bool = True,
) -> dict[str, Any]:
    from cortex.storage import get_storage_backend
    from cortex.upai.identity import UPAIIdentity

    manifest = load_mind_manifest(store_dir, mind_id)
    backend = get_storage_backend(store_dir)
    branch = manifest.current_branch or manifest.default_branch
    branch_name = mind_branch_name(mind_id, branch)
    identity_path = store_dir / "identity.json"
    identity = UPAIIdentity.load(store_dir) if identity_path.exists() else None

    def _persist() -> dict[str, Any]:
        commit = backend.versions.commit(graph, message, source=source, identity=identity, branch=branch_name)

        branches_payload = _load_branches(store_dir, mind_id, manifest)
        branch_record = dict(branches_payload.get("branches", {}).get(branch) or {})
        branch_record["head"] = commit.version_id
        branch_record["created_at"] = str(branch_record.get("created_at") or manifest.created_at)
        branches_payload["mind"] = mind_id
        branches_payload.setdefault("branches", {})
        branches_payload["branches"][branch] = branch_record
        _write_json(mind_branches_path(store_dir, mind_id), branches_payload)

        core_state = _load_core_state(store_dir, mind_id)
        core_state["mind"] = mind_id
        core_state["graph_ref"] = mind_branch_ref(mind_id, branch)
        core_state["categories"] = _graph_categories(graph)
        _write_json(mind_core_state_path(store_dir, mind_id), core_state)
        _replace_manifest(store_dir, mind_id, updated_at=_iso_now())
        return {
            "branch": branch,
            "branch_name": branch_name,
            "graph_ref": core_state["graph_ref"],
            "version_id": commit.version_id,
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
        }

    if acquire_lock:
        with locked_path(_store_lock_path(store_dir)):
            return _persist()
    return _persist()


def adopt_graph_into_mind(
    store_dir: Path,
    mind_id: str,
    graph: CortexGraph,
    *,
    message: str = "",
    source: str = "mind.adopt_graph",
) -> dict[str, Any]:
    from cortex.portable_runtime import merge_graphs

    with locked_path(_store_lock_path(store_dir)):
        manifest = load_mind_manifest(store_dir, mind_id)
        base_graph, base_graph_ref, base_graph_source = _resolve_core_graph(store_dir, mind_id)
        merged_graph = merge_graphs(base_graph, graph)
        persisted = _persist_mind_core_graph(
            store_dir,
            mind_id,
            merged_graph,
            message=message.strip() or f"Adopt context into Mind `{manifest.id}`",
            source=source,
            acquire_lock=False,
        )
    return {
        "status": "ok",
        "mind": manifest.id,
        "base_graph_ref": base_graph_ref,
        "base_graph_source": base_graph_source,
        "branch": persisted["branch"],
        "branch_name": persisted["branch_name"],
        "graph_ref": persisted["graph_ref"],
        "version_id": persisted["version_id"],
        "graph_node_count": persisted["node_count"],
        "graph_edge_count": persisted["edge_count"],
        "categories": _graph_categories(merged_graph),
    }


def sync_mind_compatibility_targets(
    store_dir: Path,
    mind_id: str,
    *,
    targets: list[str],
    project_dir: Path,
    smart: bool,
    policy_name: str,
    max_chars: int,
    output_dir: Path | None = None,
    persist_state: bool = True,
    graph: CortexGraph | None = None,
    graph_ref: str = "",
    graph_source: str = "",
) -> dict[str, Any]:
    from cortex.portable_runtime import canonical_target_name, default_output_dir, load_portability_state, sync_targets
    from cortex.upai.identity import UPAIIdentity

    manifest = load_mind_manifest(store_dir, mind_id)
    resolved_targets = [canonical_target_name(target) for target in targets if str(target).strip()]
    if not resolved_targets:
        raise ValueError("Specify at least one compatibility target.")

    if graph is None:
        resolved_graph, resolved_graph_ref, resolved_graph_source = _resolve_core_graph(store_dir, mind_id)
    else:
        resolved_graph = graph
        resolved_graph_ref = graph_ref or mind_branch_ref(manifest.id, manifest.current_branch)
        resolved_graph_source = graph_source or "mind_branch"
    state = load_portability_state(store_dir)
    chosen_output_dir = output_dir or (Path(state.output_dir) if state.output_dir else default_output_dir(store_dir))
    snapshot_path = mind_graph_snapshot_path(store_dir, manifest.id)
    atomic_write_text(snapshot_path, json.dumps(resolved_graph.export_v5(), indent=2, ensure_ascii=False))
    identity_path = store_dir / "identity.json"
    identity = UPAIIdentity.load(store_dir) if identity_path.exists() else None
    sync_payload = sync_targets(
        resolved_graph,
        targets=resolved_targets,
        store_dir=store_dir,
        project_dir=str(project_dir),
        output_dir=chosen_output_dir,
        graph_path=snapshot_path,
        policy_name=policy_name,
        smart=smart,
        max_chars=max_chars,
        state=state,
        identity=identity,
        persist_state=persist_state,
    )
    return {
        "status": "ok",
        "mind": manifest.id,
        "graph_ref": resolved_graph_ref,
        "graph_source": resolved_graph_source,
        "graph_path": str(snapshot_path),
        "fact_count": len(resolved_graph.nodes),
        "compatibility_mode": "default_mind",
        **sync_payload,
    }


def remember_and_sync_default_mind(
    store_dir: Path,
    mind_id: str,
    *,
    statement: str,
    project_dir: Path,
    targets: list[str],
    smart: bool,
    policy_name: str,
    max_chars: int,
    message: str = "",
) -> dict[str, Any]:
    remembered = remember_on_mind(store_dir, mind_id, statement=statement, message=message)
    sync_payload = sync_mind_compatibility_targets(
        store_dir,
        mind_id,
        targets=targets,
        project_dir=project_dir,
        smart=smart,
        policy_name=policy_name,
        max_chars=max_chars,
    )
    return {
        **sync_payload,
        "statement": remembered["statement"],
        "version_id": remembered["version_id"],
        "branch": remembered["branch"],
        "branch_name": remembered["branch_name"],
        "mount_count": remembered["mount_count"],
        "refreshed_mount_count": remembered["refreshed_mount_count"],
        "stale_mount_count": remembered["stale_mount_count"],
        "stale_mounts": remembered["stale_mounts"],
        "refresh_error_count": remembered["refresh_error_count"],
        "refresh_errors": remembered["refresh_errors"],
        "mount_targets": remembered["targets"],
    }


def _refresh_mind_mounts(store_dir: Path, mind_id: str) -> dict[str, Any]:
    from cortex.portable_runtime import canonical_target_name

    with locked_path(_store_lock_path(store_dir)):
        persisted = [dict(item) for item in _load_mounts(store_dir, mind_id).get("mounts", [])]
        if not persisted:
            return {
                "mount_count": 0,
                "refreshed_count": 0,
                "targets": [],
                "stale_mount_count": 0,
                "stale_mounts": [],
                "refresh_error_count": 0,
                "refresh_errors": [],
            }

        retained_mounts: list[dict[str, Any]] = []
        stale_mounts: list[dict[str, Any]] = []
        seen_targets: set[str] = set()
        for item in persisted:
            raw_target = str(item.get("target") or "").strip()
            if not raw_target:
                stale_mounts.append({"target": "", "reason": "missing_target"})
                continue
            canonical_target = canonical_target_name(raw_target.lower())
            if canonical_target not in SUPPORTED_MIND_MOUNT_TARGETS:
                stale_mounts.append({"target": raw_target, "reason": "unsupported_target"})
                continue
            if canonical_target in seen_targets:
                stale_mounts.append({"target": raw_target, "reason": "duplicate_target"})
                continue
            normalized = dict(item)
            normalized["target"] = canonical_target
            retained_mounts.append(normalized)
            seen_targets.add(canonical_target)

        if len(retained_mounts) != len(persisted):
            _write_mounts(store_dir, mind_id, retained_mounts)

    refreshed_targets: list[dict[str, Any]] = []
    refresh_errors: list[dict[str, Any]] = []
    for item in retained_mounts:
        target = str(item.get("target") or "").strip()
        try:
            payload = mount_mind(
                store_dir,
                mind_id,
                targets=[target],
                task=str(item.get("task") or ""),
                project_dir=str(item.get("project_dir") or ""),
                smart=_coerce_bool(item.get("smart"), default=str(item.get("mode") or "smart") == "smart"),
                policy_name=str(item.get("policy") or ""),
                max_chars=_coerce_positive_int(item.get("max_chars"), default=1500),
                openclaw_store_dir=str(item.get("openclaw_store_dir") or ""),
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            refresh_errors.append({"target": target, "error": str(exc)})
            continue
        refreshed_targets.extend(dict(target_payload) for target_payload in payload.get("targets", []))

    refreshed_targets.sort(key=lambda item: str(item.get("target") or "").lower())
    return {
        "mount_count": len(retained_mounts),
        "refreshed_count": len(refreshed_targets),
        "targets": refreshed_targets,
        "stale_mount_count": len(stale_mounts),
        "stale_mounts": stale_mounts,
        "refresh_error_count": len(refresh_errors),
        "refresh_errors": refresh_errors,
    }


def _mind_runtime_module():
    from cortex import mind_runtime

    return mind_runtime


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
    return _mind_runtime_module().ingest_detected_sources_into_mind(
        store_dir,
        mind_id,
        targets=targets,
        project_dir=project_dir,
        extra_roots=extra_roots,
        include_config_metadata=include_config_metadata,
        include_unmanaged_text=include_unmanaged_text,
        redactor=redactor,
        message=message,
        namespace=namespace,
    )


def remember_on_mind(
    store_dir: Path,
    mind_id: str,
    *,
    statement: str,
    message: str = "",
    namespace: str | None = None,
) -> dict[str, Any]:
    return _mind_runtime_module().remember_on_mind(
        store_dir,
        mind_id,
        statement=statement,
        message=message,
        namespace=namespace,
    )


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
    return _mind_runtime_module().compose_mind(
        store_dir,
        mind_id,
        target=target,
        task=task,
        project_dir=project_dir,
        smart=smart,
        policy_name=policy_name,
        max_chars=max_chars,
        activation_target=activation_target,
        namespace=namespace,
    )


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
    return _mind_runtime_module().mount_mind(
        store_dir,
        mind_id,
        targets=targets,
        task=task,
        project_dir=project_dir,
        smart=smart,
        policy_name=policy_name,
        max_chars=max_chars,
        openclaw_store_dir=openclaw_store_dir,
        namespace=namespace,
    )


def list_mind_mounts(store_dir: Path, mind_id: str, *, namespace: str | None = None) -> dict[str, Any]:
    return _mind_runtime_module().list_mind_mounts(store_dir, mind_id, namespace=namespace)


def list_minds(store_dir: Path, *, namespace: str | None = None) -> dict[str, Any]:
    return _mind_runtime_module().list_minds(store_dir, namespace=namespace)


def list_mind_proposals(store_dir: Path, mind_id: str, *, namespace: str | None = None) -> dict[str, Any]:
    return _mind_runtime_module().list_mind_proposals(store_dir, mind_id, namespace=namespace)


def mind_status(store_dir: Path, mind_id: str, *, namespace: str | None = None) -> dict[str, Any]:
    return _mind_runtime_module().mind_status(store_dir, mind_id, namespace=namespace)
