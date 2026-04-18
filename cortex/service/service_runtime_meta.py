from __future__ import annotations

from time import monotonic

from cortex.embeddings import get_embedding_provider
from cortex.integrity import check_store_integrity
from cortex.openapi import build_openapi_spec
from cortex.release import build_release_metadata
from cortex.service_runtime_common import _backend_name, _safe_head_ref, _safe_index_status


class MemoryRuntimeMetaMixin:
    def health(self) -> dict[str, object]:
        index_status = _safe_index_status(self)
        integrity = check_store_integrity(self.store_dir)
        agent = self.agent_status()
        health_status = "error" if integrity["status"] == "error" else "ok"
        return {
            "status": health_status,
            "backend": _backend_name(self.backend),
            "store_dir": str(self.store_dir.resolve()),
            "current_branch": self.backend.versions.current_branch(),
            "head": _safe_head_ref(self),
            "index": index_status,
            "graph_integrity": integrity["status"],
            "uptime_seconds": int(monotonic() - getattr(self, "started_at", monotonic())),
            "pending_conflicts": int(agent.get("pending_count", 0)),
            "scheduled_tasks": int(agent.get("scheduled_count", 0)),
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
