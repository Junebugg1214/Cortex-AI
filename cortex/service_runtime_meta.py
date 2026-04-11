from __future__ import annotations

from cortex.embeddings import get_embedding_provider
from cortex.openapi import build_openapi_spec
from cortex.release import build_release_metadata
from cortex.service_runtime_common import _backend_name, _safe_head_ref, _safe_index_status


class MemoryRuntimeMetaMixin:
    def health(self) -> dict[str, object]:
        index_status = _safe_index_status(self)
        return {
            "status": "ok",
            "backend": _backend_name(self.backend),
            "store_dir": str(self.store_dir.resolve()),
            "current_branch": self.backend.versions.current_branch(),
            "head": _safe_head_ref(self),
            "index": index_status,
            "release": self.release(),
        }

    def openapi(self, *, server_url: str | None = None) -> dict[str, object]:
        return build_openapi_spec(server_url=server_url)

    def release(self) -> dict[str, object]:
        return build_release_metadata(self.openapi())

    def meta(self) -> dict[str, object]:
        provider = get_embedding_provider()
        return {
            "status": "ok",
            "store_dir": str(self.store_dir.resolve()),
            "context_file": str(self.context_file) if self.context_file else "",
            "backend": _backend_name(self.backend),
            "current_branch": self.backend.versions.current_branch(),
            "head": _safe_head_ref(self),
            "embedding_provider": provider.name,
            "embedding_enabled": provider.enabled,
            "log_path": str(self.observability.log_path),
            "index": _safe_index_status(self),
            "release": self.release(),
        }

    def metrics(self, *, namespace: str | None = None) -> dict[str, object]:
        self._enforce_namespace(namespace, ref="HEAD")
        metrics = self.observability.metrics(
            index_status=_safe_index_status(self),
            backend=_backend_name(self.backend),
            current_branch=self.backend.versions.current_branch(),
        )
        metrics["release"] = self.release()
        return metrics

    def prune_status(self, *, retention_days: int = 7) -> dict[str, object]:
        return self.backend.maintenance.status(retention_days=retention_days)

    def prune(self, *, dry_run: bool = True, retention_days: int = 7) -> dict[str, object]:
        return self.backend.maintenance.prune(dry_run=dry_run, retention_days=retention_days)

    def prune_audit(self, *, limit: int = 50) -> dict[str, object]:
        return {"status": "ok", "entries": self.backend.maintenance.audit_log(limit=limit)}


__all__ = ["MemoryRuntimeMetaMixin"]
