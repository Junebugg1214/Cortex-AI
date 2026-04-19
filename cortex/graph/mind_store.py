from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import cortex.graph.minds as minds_module
from cortex.namespaces import normalize_resource_namespace


def mind_proposals_dir(store_dir: Path, mind_id: str) -> Path:
    return minds_module.mind_path(store_dir, mind_id) / minds_module.MIND_PROPOSALS_DIRNAME


def mind_proposal_path(store_dir: Path, mind_id: str, proposal_id: str) -> Path:
    return mind_proposals_dir(store_dir, mind_id) / f"{proposal_id}.json"


def load_mind_manifest(store_dir: Path, mind_id: str) -> minds_module.MindManifest:
    path = minds_module.mind_manifest_path(store_dir, mind_id)
    if not path.exists():
        raise FileNotFoundError(f"Mind '{mind_id}' does not exist.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return minds_module.MindManifest(
        id=str(payload["id"]),
        label=str(payload["label"]),
        kind=str(payload["kind"]),
        owner=str(payload.get("owner") or ""),
        namespace=normalize_resource_namespace(payload.get("namespace")),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
        default_branch=str(payload.get("default_branch") or minds_module.DEFAULT_BRANCH),
        current_branch=str(payload.get("current_branch") or minds_module.DEFAULT_BRANCH),
        default_policy=str(payload.get("default_policy") or minds_module.DEFAULT_POLICY),
    )


def _replace_manifest(store_dir: Path, mind_id: str, *, updated_at: str) -> minds_module.MindManifest:
    manifest = load_mind_manifest(store_dir, mind_id)
    updated = minds_module.MindManifest(
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
    minds_module._write_manifest(store_dir, updated)
    return updated


def default_mind_status(store_dir: Path) -> dict[str, Any]:
    env_value = os.getenv("CORTEX_DEFAULT_MIND", "").strip()
    if env_value:
        normalized = minds_module._validate_mind_id(env_value)
        load_mind_manifest(store_dir, normalized)
        return {
            "status": "ok",
            "configured": True,
            "mind": normalized,
            "source": "env",
            "path": "",
        }

    path = minds_module.default_mind_config_path(store_dir)
    payload = minds_module._read_json(path, default={"mind": "", "configured_at": ""})
    configured_mind = str(payload.get("mind") or "").strip()
    if not configured_mind:
        return {
            "status": "ok",
            "configured": False,
            "mind": "",
            "source": "config",
            "path": str(path),
        }
    normalized = minds_module._validate_mind_id(configured_mind)
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
    path = minds_module.default_mind_config_path(store_dir)
    payload = {
        "mind": manifest.id,
        "configured_at": minds_module._iso_now(),
    }
    with minds_module.locked_path(minds_module._store_lock_path(store_dir)):
        minds_module._write_json(path, payload)
    return {
        "status": "ok",
        "configured": True,
        "mind": manifest.id,
        "source": "config",
        "path": str(path),
    }


def clear_default_mind(store_dir: Path) -> dict[str, Any]:
    path = minds_module.default_mind_config_path(store_dir)
    with minds_module.locked_path(minds_module._store_lock_path(store_dir)):
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
    default_policy: str = minds_module.DEFAULT_POLICY,
) -> dict[str, Any]:
    normalized_id = minds_module._validate_mind_id(mind_id)
    normalized_kind = minds_module._validate_kind(kind)
    root = minds_module.mind_path(store_dir, normalized_id)
    if root.exists():
        raise FileExistsError(f"Mind '{normalized_id}' already exists.")

    created_at = minds_module._iso_now()
    manifest = minds_module.MindManifest(
        id=normalized_id,
        label=label.strip() or minds_module._default_label(normalized_id),
        kind=normalized_kind,
        owner=owner.strip(),
        namespace=normalize_resource_namespace(namespace),
        created_at=created_at,
        updated_at=created_at,
        default_policy=default_policy.strip() or minds_module.DEFAULT_POLICY,
    )
    with minds_module.locked_path(minds_module._store_lock_path(store_dir)):
        root.mkdir(parents=True, exist_ok=False)
        for directory in minds_module.MIND_LAYOUT_DIRECTORIES:
            (root / directory).mkdir(parents=True, exist_ok=True)
        minds_module._write_json(minds_module.mind_manifest_path(store_dir, normalized_id), asdict(manifest))
        minds_module._write_json(
            minds_module.mind_core_state_path(store_dir, normalized_id),
            {
                "mind": normalized_id,
                "graph_ref": f"refs/minds/{normalized_id}/branches/{manifest.default_branch}",
                "categories": list(minds_module.DEFAULT_CATEGORIES),
            },
        )
        minds_module._write_json(
            minds_module.mind_attachments_path(store_dir, normalized_id),
            {
                "mind": normalized_id,
                "brainpacks": [],
            },
        )
        minds_module._write_json(
            minds_module.mind_branches_path(store_dir, normalized_id),
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
        minds_module._write_json(
            minds_module.mind_policies_path(store_dir, normalized_id),
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
        minds_module._write_json(
            minds_module.mind_mounts_path(store_dir, normalized_id),
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
        "manifest": str(minds_module.mind_manifest_path(store_dir, normalized_id)),
    }
