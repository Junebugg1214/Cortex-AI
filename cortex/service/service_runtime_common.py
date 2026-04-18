from __future__ import annotations

from typing import Any

from cortex.embeddings import get_embedding_provider
from cortex.storage.base import StorageBackend


def _backend_name(backend: StorageBackend) -> str:
    module_name = type(backend).__module__
    if module_name.endswith(".sqlite"):
        return "sqlite"
    return "filesystem"


def _safe_head_ref(service: Any) -> str:
    try:
        return service.backend.versions.resolve_ref("HEAD")
    except (FileNotFoundError, ValueError):
        return ""


def _safe_index_status(service: Any) -> dict[str, Any]:
    try:
        return service.backend.indexing.status(ref="HEAD")
    except (FileNotFoundError, ValueError):
        provider = get_embedding_provider()
        backend_name = _backend_name(service.backend)
        return {
            "status": "missing",
            "backend": backend_name,
            "persistent": backend_name == "sqlite",
            "supported": provider.enabled,
            "ref": "HEAD",
            "resolved_ref": "",
            "last_indexed_commit": None,
            "doc_count": 0,
            "stale": False,
            "updated_at": None,
            "lag_commits": 0,
            "embedding_provider": provider.name,
            "embedding_enabled": provider.enabled,
        }


__all__ = ["_backend_name", "_safe_head_ref", "_safe_index_status"]
