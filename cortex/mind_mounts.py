from __future__ import annotations

from pathlib import Path
from typing import Any

import cortex.minds as minds_module


def _load_mounts(store_dir: Path, mind_id: str) -> dict[str, Any]:
    return minds_module._read_json(
        minds_module.mind_mounts_path(store_dir, mind_id),
        default={"mind": mind_id, "mounts": []},
    )


def _write_mounts(store_dir: Path, mind_id: str, mounts: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "status": "ok",
        "mind": mind_id,
        "mount_count": len(mounts),
        "mounts": mounts,
    }
    minds_module._write_json(minds_module.mind_mounts_path(store_dir, mind_id), payload)
    return payload


def _load_openclaw_mind_mount_registry(openclaw_store_dir: Path) -> dict[str, Any]:
    return minds_module._read_json(
        minds_module.mind_openclaw_mount_registry_path(openclaw_store_dir),
        default={"status": "ok", "mount_count": 0, "mounts": []},
    )


def _write_openclaw_mind_mount_registry(openclaw_store_dir: Path, payload: dict[str, Any]) -> Path:
    path = minds_module.mind_openclaw_mount_registry_path(openclaw_store_dir)
    with minds_module.locked_path(path):
        minds_module._write_json(path, payload)
    return path


def _refresh_mind_mounts(store_dir: Path, mind_id: str) -> dict[str, Any]:
    from cortex.portable_runtime import canonical_target_name

    with minds_module.locked_path(minds_module._store_lock_path(store_dir)):
        persisted = [dict(item) for item in minds_module._load_mounts(store_dir, mind_id).get("mounts", [])]
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
            if canonical_target not in minds_module.SUPPORTED_MIND_MOUNT_TARGETS:
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
            minds_module._write_mounts(store_dir, mind_id, retained_mounts)

    refreshed_targets: list[dict[str, Any]] = []
    refresh_errors: list[dict[str, Any]] = []
    for item in retained_mounts:
        target = str(item.get("target") or "").strip()
        try:
            payload = minds_module.mount_mind(
                store_dir,
                mind_id,
                targets=[target],
                task=str(item.get("task") or ""),
                project_dir=str(item.get("project_dir") or ""),
                smart=minds_module._coerce_bool(item.get("smart"), default=str(item.get("mode") or "smart") == "smart"),
                policy_name=str(item.get("policy") or ""),
                max_chars=minds_module._coerce_positive_int(item.get("max_chars"), default=1500),
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
