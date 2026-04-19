from __future__ import annotations

from pathlib import Path
from typing import Any

from cortex.pack_runtime import _load_compiled_graph
from cortex.packs import (
    OPENCLAW_MOUNT_TARGET,
    SUPPORTED_PACK_MOUNT_TARGETS,
    _default_openclaw_store_dir,
    _iso_now,
    _read_json,
    _require_pack_namespace,
    _write_json,
    compile_meta_path,
    graph_path,
    load_manifest,
    openclaw_mount_registry_path,
    pack_mounts_path,
)
from cortex.portability.portable_runtime import canonical_target_name, default_output_dir, sync_targets


def pack_mounts(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
    payload = _read_json(pack_mounts_path(store_dir, name), default={})
    if payload:
        return payload
    return {
        "status": "ok",
        "pack": name,
        "mount_count": 0,
        "mounts": [],
    }


def _load_openclaw_mount_registry(openclaw_store_dir: Path) -> dict[str, Any]:
    return _read_json(
        openclaw_mount_registry_path(openclaw_store_dir),
        default={"status": "ok", "mount_count": 0, "mounts": []},
    )


def _write_openclaw_mount_registry(openclaw_store_dir: Path, payload: dict[str, Any]) -> Path:
    path = openclaw_mount_registry_path(openclaw_store_dir)
    _write_json(path, payload)
    return path


def _record_pack_mounts(store_dir: Path, name: str, mounts: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "status": "ok",
        "pack": name,
        "mount_count": len(mounts),
        "mounts": mounts,
    }
    _write_json(pack_mounts_path(store_dir, name), payload)
    return payload


def mount_pack(
    store_dir: Path,
    name: str,
    *,
    targets: list[str],
    project_dir: str = "",
    smart: bool = True,
    policy_name: str = "technical",
    max_chars: int = 1500,
    openclaw_store_dir: str = "",
    namespace: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
    graph = _load_compiled_graph(store_dir, name)
    if not targets:
        raise ValueError("Specify at least one mount target.")
    compile_meta = _read_json(compile_meta_path(store_dir, name), default={"compile_mode": "distribution"})
    compile_mode = str(compile_meta.get("compile_mode") or "distribution")
    provenance_available = bool(compile_meta.get("provenance_available", compile_mode == "full"))

    resolved: list[str] = []
    for raw_target in targets:
        lowered = raw_target.strip().lower()
        target = lowered if lowered == OPENCLAW_MOUNT_TARGET else canonical_target_name(lowered)
        if target not in SUPPORTED_PACK_MOUNT_TARGETS:
            raise ValueError(f"Unsupported Brainpack mount target: {raw_target}")
        if target not in resolved:
            resolved.append(target)

    project_path = str(Path(project_dir).resolve()) if project_dir else ""
    output_dir = default_output_dir(store_dir) / "packs" / manifest.name
    graph_file = graph_path(store_dir, name)
    mount_results: list[dict[str, Any]] = []

    file_targets = [target for target in resolved if target != OPENCLAW_MOUNT_TARGET]
    if file_targets:
        sync_payload = sync_targets(
            graph,
            targets=file_targets,
            store_dir=store_dir,
            project_dir=project_path,
            output_dir=output_dir,
            graph_path=graph_file,
            policy_name=policy_name,
            smart=smart,
            max_chars=max_chars,
            persist_state=False,
        )
        mount_results.extend(
            {
                "target": str(item["target"]),
                "status": str(item["status"]),
                "paths": list(item.get("paths", [])),
                "note": str(item.get("note", "")),
                "mode": str(item.get("mode", "smart" if smart else "full")),
                "route_tags": list(item.get("route_tags", [])),
                "compile_mode": compile_mode,
                "provenance_available": provenance_available,
                "mounted_at": _iso_now(),
            }
            for item in sync_payload.get("targets", [])
        )

    if OPENCLAW_MOUNT_TARGET in resolved:
        openclaw_root = (
            Path(openclaw_store_dir).expanduser().resolve()
            if openclaw_store_dir
            else _default_openclaw_store_dir().resolve()
        )
        registry = _load_openclaw_mount_registry(openclaw_root)
        mounts = [
            dict(item)
            for item in registry.get("mounts", [])
            if str(item.get("name") or "").strip() and str(item.get("name")) != manifest.name
        ]
        pack_entry = {
            "name": manifest.name,
            "smart": smart,
            "policy": policy_name,
            "max_chars": max_chars,
            "project_dir": project_path,
            "source_graph_path": str(graph_file),
            "mounted_at": _iso_now(),
            "enabled": True,
        }
        mounts.append(pack_entry)
        registry_payload = {
            "status": "ok",
            "mount_count": len(mounts),
            "mounts": mounts,
        }
        registry_path = _write_openclaw_mount_registry(openclaw_root, registry_payload)
        mount_results.append(
            {
                "target": OPENCLAW_MOUNT_TARGET,
                "status": "ok",
                "paths": [str(registry_path)],
                "note": f"Registered Brainpack `{manifest.name}` for OpenClaw plugin runtime injection.",
                "mode": "smart" if smart else "full",
                "route_tags": [],
                "compile_mode": compile_mode,
                "provenance_available": provenance_available,
                "mounted_at": pack_entry["mounted_at"],
            }
        )

    mounts_payload = _record_pack_mounts(store_dir, name, mount_results)
    return {
        "status": "ok",
        "pack": manifest.name,
        "targets": mount_results,
        "mount_count": len(mount_results),
        "mounts_path": str(pack_mounts_path(store_dir, name)),
        "mounts": mounts_payload["mounts"],
    }
