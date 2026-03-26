"""Storage backend selection for Cortex."""

from __future__ import annotations

import os
from pathlib import Path

from cortex.storage.base import (
    DEFAULT_NAMESPACE,
    DEFAULT_TENANT_ID,
    ClaimBackend,
    GovernanceBackend,
    IndexBackend,
    MaintenanceBackend,
    RemoteBackend,
    StorageBackend,
    VersionBackend,
)
from cortex.storage.filesystem import FilesystemStorageBackend, build_filesystem_backend
from cortex.storage.sqlite import SQLiteStorageBackend, build_sqlite_backend, sqlite_db_path

BACKEND_ALIASES = {
    "filesystem": "filesystem",
    "fs": "filesystem",
    "sqlite": "sqlite",
    "sqlite3": "sqlite",
}


def _normalize_backend_type(backend_type: str | None) -> str | None:
    if backend_type is None:
        return None
    raw = backend_type.strip().lower()
    if not raw:
        return None
    normalized = BACKEND_ALIASES.get(raw)
    if normalized is None:
        raise ValueError(f"Unknown storage backend: {backend_type}")
    return normalized


def _auto_backend_type(store_dir: Path) -> str:
    if (store_dir / "history.json").exists() or (store_dir / "versions").exists():
        return "filesystem"
    if sqlite_db_path(store_dir).exists():
        return "sqlite"
    return "filesystem"


def get_storage_backend(
    store_dir: str | Path,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    backend_type: str | None = None,
) -> StorageBackend:
    store_path = Path(store_dir)
    selected = _normalize_backend_type(backend_type)
    if selected is None:
        selected = _normalize_backend_type(os.getenv("CORTEX_STORAGE_BACKEND"))
    if selected is None:
        selected = _auto_backend_type(store_path)
    if selected == "sqlite":
        return build_sqlite_backend(store_path, tenant_id=tenant_id)
    return build_filesystem_backend(store_path, tenant_id=tenant_id)


__all__ = [
    "DEFAULT_NAMESPACE",
    "DEFAULT_TENANT_ID",
    "ClaimBackend",
    "FilesystemStorageBackend",
    "GovernanceBackend",
    "IndexBackend",
    "MaintenanceBackend",
    "RemoteBackend",
    "SQLiteStorageBackend",
    "StorageBackend",
    "VersionBackend",
    "build_filesystem_backend",
    "build_sqlite_backend",
    "get_storage_backend",
]
