from __future__ import annotations

from typing import Any

import cortex.minds as minds_module
from cortex.namespaces import resource_namespace_matches


def _attachment_pack_name(record: dict[str, Any]) -> str:
    pack_name = str(record.get("id") or "").strip()
    if pack_name:
        return pack_name
    pack_ref = str(record.get("pack_ref") or "").strip()
    if pack_ref.startswith("packs/"):
        return pack_ref.split("/", 1)[1]
    return pack_ref


def _load_attachments(store_dir, mind_id: str) -> dict[str, Any]:
    return minds_module._read_json(
        minds_module.mind_attachments_path(store_dir, mind_id),
        default={"mind": mind_id, "brainpacks": []},
    )


def attach_pack_to_mind(
    store_dir,
    mind_id: str,
    pack_name: str,
    *,
    priority: int = 100,
    always_on: bool = False,
    targets: list[str] | None = None,
    task_terms: list[str] | None = None,
    namespace: str | None = None,
) -> dict[str, Any]:
    from cortex.packs import load_manifest as load_pack_manifest
    from cortex.portable_runtime import canonical_target_name

    normalized_mind_id = minds_module._validate_mind_id(mind_id)
    manifest = minds_module.load_mind_manifest(store_dir, normalized_mind_id)
    minds_module._require_mind_namespace(manifest, namespace)

    pack_manifest = load_pack_manifest(store_dir, pack_name)
    if not resource_namespace_matches(pack_manifest.namespace, namespace):
        raise PermissionError(
            f"Brainpack '{pack_manifest.name}' is outside namespace "
            f"'{minds_module.describe_resource_namespace(namespace)}'."
        )
    now = minds_module._iso_now()
    updated = False
    normalized_targets = [canonical_target_name(item) for item in minds_module._clean_strings(targets)]

    with minds_module.locked_path(minds_module._store_lock_path(store_dir)):
        attachments_payload = minds_module._load_attachments(store_dir, normalized_mind_id)
        records = [dict(item) for item in attachments_payload.get("brainpacks", [])]
        attachment_record = {
            "id": pack_manifest.name,
            "pack_ref": f"packs/{pack_manifest.name}",
            "mode": minds_module.ATTACHMENT_MODE,
            "scope": minds_module.ATTACHMENT_SCOPE,
            "priority": int(priority),
            "activation": {
                "targets": normalized_targets,
                "task_terms": minds_module._clean_strings(task_terms),
                "always_on": bool(always_on),
            },
            "attached_at": now,
            "updated_at": now,
        }

        for index, existing in enumerate(records):
            if minds_module._attachment_pack_name(existing) != pack_manifest.name:
                continue
            attachment_record["attached_at"] = str(existing.get("attached_at") or now)
            records[index] = attachment_record
            updated = True
            break
        else:
            records.append(attachment_record)

        records.sort(key=lambda item: (-int(item.get("priority", 0)), minds_module._attachment_pack_name(item).lower()))
        attachments_payload["mind"] = normalized_mind_id
        attachments_payload["brainpacks"] = records
        minds_module._write_json(minds_module.mind_attachments_path(store_dir, normalized_mind_id), attachments_payload)
        minds_module._replace_manifest(store_dir, normalized_mind_id, updated_at=now)

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
    store_dir,
    mind_id: str,
    pack_name: str,
    *,
    namespace: str | None = None,
) -> dict[str, Any]:
    normalized_mind_id = minds_module._validate_mind_id(mind_id)
    manifest = minds_module.load_mind_manifest(store_dir, normalized_mind_id)
    minds_module._require_mind_namespace(manifest, namespace)

    target = str(pack_name).strip()
    if not target:
        raise ValueError("Pack name is required.")

    with minds_module.locked_path(minds_module._store_lock_path(store_dir)):
        attachments_payload = minds_module._load_attachments(store_dir, normalized_mind_id)
        records = [dict(item) for item in attachments_payload.get("brainpacks", [])]
        remaining = [item for item in records if minds_module._attachment_pack_name(item) != target]
        if len(remaining) == len(records):
            raise ValueError(f"Brainpack '{target}' is not attached to Mind '{normalized_mind_id}'.")

        attachments_payload["mind"] = normalized_mind_id
        attachments_payload["brainpacks"] = remaining
        minds_module._write_json(minds_module.mind_attachments_path(store_dir, normalized_mind_id), attachments_payload)
        minds_module._replace_manifest(store_dir, normalized_mind_id, updated_at=minds_module._iso_now())
    return {
        "status": "ok",
        "mind": normalized_mind_id,
        "pack": target,
        "detached": True,
        "attachment_count": len(remaining),
    }


def _attachment_details(
    store_dir,
    records: list[dict[str, Any]],
    *,
    namespace: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    from cortex.packs import pack_status

    details: list[dict[str, Any]] = []
    aggregate_targets: set[str] = set()
    for record in records:
        pack_name = minds_module._attachment_pack_name(record)
        activation = dict(record.get("activation") or {})
        detail = {
            "id": str(record.get("id") or pack_name),
            "pack": pack_name,
            "pack_ref": str(record.get("pack_ref") or f"packs/{pack_name}"),
            "mode": str(record.get("mode") or minds_module.ATTACHMENT_MODE),
            "scope": str(record.get("scope") or minds_module.ATTACHMENT_SCOPE),
            "priority": int(record.get("priority") or 0),
            "activation": {
                "targets": minds_module._clean_strings(list(activation.get("targets") or [])),
                "task_terms": minds_module._clean_strings(list(activation.get("task_terms") or [])),
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
