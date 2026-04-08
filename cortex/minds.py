from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MINDS_DIRNAME = "minds"
MIND_KINDS = ("person", "agent", "project", "team")
DEFAULT_BRANCH = "main"
DEFAULT_POLICY = "professional"
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
    _write_json(mind_manifest_path(store_dir, normalized_id), asdict(manifest))
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


def _mind_summary(store_dir: Path, manifest: MindManifest) -> dict[str, Any]:
    core_state = _read_json(
        mind_core_state_path(store_dir, manifest.id),
        default={"graph_ref": "", "categories": list(DEFAULT_CATEGORIES)},
    )
    attachments = _read_json(mind_attachments_path(store_dir, manifest.id), default={"brainpacks": []})
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
        "attachment_count": len(attachments.get("brainpacks", [])),
        "branch_count": len(branches.get("branches", {})),
        "mount_count": len(mounts.get("mounts", [])),
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
