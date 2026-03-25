"""Storage backend selection for Cortex."""

from __future__ import annotations

from pathlib import Path

from cortex.storage.base import (
    DEFAULT_NAMESPACE,
    DEFAULT_TENANT_ID,
    ClaimBackend,
    GovernanceBackend,
    RemoteBackend,
    StorageBackend,
    VersionBackend,
)
from cortex.storage.filesystem import FilesystemStorageBackend, build_filesystem_backend


def get_storage_backend(
    store_dir: str | Path,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> StorageBackend:
    return build_filesystem_backend(store_dir, tenant_id=tenant_id)


__all__ = [
    "DEFAULT_NAMESPACE",
    "DEFAULT_TENANT_ID",
    "ClaimBackend",
    "FilesystemStorageBackend",
    "GovernanceBackend",
    "RemoteBackend",
    "StorageBackend",
    "VersionBackend",
    "build_filesystem_backend",
    "get_storage_backend",
]
