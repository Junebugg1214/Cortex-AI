from __future__ import annotations

from pathlib import Path
from typing import Any

from cortex.remote_trust import perform_remote_handshake, require_remote_namespace, write_remote_sync_receipt
from cortex.remotes import _normalize_store_path
from cortex.schemas.memory_v1 import RemoteRecord
from cortex.storage.filesystem import FilesystemStorageBackend
from cortex.storage.sqlite import SQLiteStorageBackend, sqlite_db_path


def _backend_name(backend: Any) -> str:
    if isinstance(backend, SQLiteStorageBackend):
        return "sqlite"
    return "filesystem"


def _resolve_remote_store_path(remote: RemoteRecord) -> Path:
    return Path(remote.resolved_store_path) if remote.resolved_store_path else _normalize_store_path(remote.path)


def _open_remote_backend(remote: RemoteRecord, *, fallback_backend_type: str) -> Any:
    from cortex.storage import get_storage_backend

    store_path = _resolve_remote_store_path(remote)
    has_filesystem_store = (store_path / "history.json").exists() or (store_path / "versions").exists()
    has_sqlite_store = sqlite_db_path(store_path).exists()
    backend_type = None if (has_filesystem_store or has_sqlite_store) else fallback_backend_type
    return get_storage_backend(store_path, backend_type=backend_type)


def _backend_store_dir(backend: Any) -> Path:
    if isinstance(backend, SQLiteStorageBackend):
        return backend.store_dir
    if isinstance(backend, FilesystemStorageBackend):
        return backend.store_dir
    raise TypeError(f"Unsupported storage backend for sync: {type(backend)!r}")


def _export_bundle(backend: Any, ref: str) -> dict[str, Any]:
    if isinstance(backend, SQLiteStorageBackend):
        return backend.versions._export_bundle(ref)

    if isinstance(backend, FilesystemStorageBackend):
        store = backend.versions.store
        resolved = store.resolve_ref(ref)
        if resolved is None:
            raise ValueError(f"Unknown ref: {ref}")
        records = store.lineage_records(ref)
        if not records:
            raise ValueError(f"No history found for ref: {ref}")
        version_ids = {item["version_id"] for item in records}
        snapshots: dict[str, str] = {}
        for version_id in sorted(version_ids):
            snapshot_path = store.versions_dir / f"{version_id}.json"
            if snapshot_path.exists():
                snapshots[version_id] = snapshot_path.read_text(encoding="utf-8")
        return {"head": resolved, "records": records, "snapshots": snapshots}

    raise TypeError(f"Unsupported storage backend for export: {type(backend)!r}")


def _import_bundle(backend: Any, bundle: dict[str, Any]) -> int:
    if isinstance(backend, SQLiteStorageBackend):
        return backend.versions._import_bundle(bundle)

    if isinstance(backend, FilesystemStorageBackend):
        store = backend.versions.store
        store._ensure_dirs()
        history = store._load_history()
        existing_ids = {item["version_id"] for item in history}
        copied = 0

        for version_id, graph_json in bundle.get("snapshots", {}).items():
            snapshot_path = store.versions_dir / f"{version_id}.json"
            if snapshot_path.exists():
                continue
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(graph_json, encoding="utf-8")

        for record in bundle.get("records", []):
            version_id = record["version_id"]
            if version_id in existing_ids:
                continue
            history.append(dict(record))
            existing_ids.add(version_id)
            copied += 1

        if copied:
            store._save_history(history)
        return copied

    raise TypeError(f"Unsupported storage backend for import: {type(backend)!r}")


def _set_branch_head(backend: Any, branch: str, version_id: str | None) -> None:
    if isinstance(backend, SQLiteStorageBackend):
        backend.versions._write_ref(branch, version_id)
        return
    if isinstance(backend, FilesystemStorageBackend):
        backend.versions.store._write_ref(branch, version_id)
        return
    raise TypeError(f"Unsupported storage backend for ref update: {type(backend)!r}")


def push_remote_backend(
    local_backend: Any,
    remote: RemoteRecord,
    branch: str,
    target_branch: str | None,
    force: bool,
) -> dict[str, Any]:
    local_store_dir = _backend_store_dir(local_backend)
    local_branch = branch if branch != "HEAD" else local_backend.versions.current_branch()
    remote_branch = target_branch or local_branch
    require_remote_namespace(remote, remote_branch)
    handshake = perform_remote_handshake(
        local_store_dir,
        remote,
        direction="push",
        branch=local_branch,
        remote_branch=remote_branch,
    )
    remote_backend = _open_remote_backend(remote, fallback_backend_type=_backend_name(local_backend))
    local_head = local_backend.versions.resolve_ref(branch)
    if local_head is None:
        raise ValueError(f"Unknown ref: {branch}")
    bundle = _export_bundle(local_backend, branch)
    copied = _import_bundle(remote_backend, bundle)
    remote_head = remote_backend.versions.resolve_ref(remote_branch)

    if remote_head and remote_head != local_head and not remote_backend.versions.is_ancestor(remote_head, local_head):
        if not force:
            raise ValueError(f"Push would not be a fast-forward on remote branch '{remote_branch}'.")

    _set_branch_head(remote_backend, remote_branch, local_head)
    receipt_path = write_remote_sync_receipt(
        local_store_dir,
        {
            "direction": "push",
            "remote": remote.name,
            "branch": local_branch,
            "remote_branch": remote_branch,
            "head": local_head,
            "versions_copied": copied,
            "force": force,
            **handshake,
        },
    )
    return {
        "status": "ok",
        "remote": remote.name,
        "remote_path": str(_resolve_remote_store_path(remote)),
        "branch": local_branch,
        "remote_branch": remote_branch,
        "head": local_head,
        "versions_copied": copied,
        "force": force,
        "trusted_remote_did": handshake["remote_did"],
        "local_did": handshake["local_did"],
        "allowed_namespaces": list(handshake["allowed_namespaces"]),
        "receipt_path": receipt_path,
    }


def pull_remote_backend(
    local_backend: Any,
    remote: RemoteRecord,
    branch: str,
    into_branch: str | None,
    force: bool,
    switch: bool,
) -> dict[str, Any]:
    local_store_dir = _backend_store_dir(local_backend)
    require_remote_namespace(remote, branch)
    handshake = perform_remote_handshake(
        local_store_dir,
        remote,
        direction="pull",
        branch=branch,
        remote_branch=branch,
    )
    remote_backend = _open_remote_backend(remote, fallback_backend_type=_backend_name(local_backend))
    remote_head = remote_backend.versions.resolve_ref(branch)
    if remote_head is None:
        raise ValueError(f"Unknown ref: {branch}")
    bundle = _export_bundle(remote_backend, branch)
    copied = _import_bundle(local_backend, bundle)
    local_branch = into_branch or f"remotes/{remote.name}/{branch}"
    current_head = local_backend.versions.resolve_ref(local_branch)

    if (
        current_head
        and current_head != remote_head
        and not local_backend.versions.is_ancestor(current_head, remote_head)
    ):
        if not force:
            raise ValueError(f"Pull would not be a fast-forward on local branch '{local_branch}'.")

    _set_branch_head(local_backend, local_branch, remote_head)
    if switch:
        local_backend.versions.switch_branch(local_branch)
    receipt_path = write_remote_sync_receipt(
        local_store_dir,
        {
            "direction": "pull",
            "remote": remote.name,
            "branch": local_branch,
            "remote_branch": branch,
            "head": remote_head,
            "versions_copied": copied,
            "switched": switch,
            "force": force,
            **handshake,
        },
    )

    return {
        "status": "ok",
        "remote": remote.name,
        "remote_path": str(_resolve_remote_store_path(remote)),
        "remote_branch": branch,
        "branch": local_branch,
        "head": remote_head,
        "versions_copied": copied,
        "switched": switch,
        "force": force,
        "trusted_remote_did": handshake["remote_did"],
        "local_did": handshake["local_did"],
        "allowed_namespaces": list(handshake["allowed_namespaces"]),
        "receipt_path": receipt_path,
    }


def fork_remote_backend(
    local_backend: Any,
    remote: RemoteRecord,
    remote_branch: str,
    local_branch: str,
    switch: bool,
) -> dict[str, Any]:
    payload = pull_remote_backend(
        local_backend,
        remote,
        branch=remote_branch,
        into_branch=local_branch,
        force=False,
        switch=switch,
    )
    payload["forked"] = True
    return payload
