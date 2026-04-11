from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cortex.embeddings import get_embedding_provider, hybrid_search_documents
from cortex.storage.filesystem_versions import FilesystemVersionBackend


@dataclass(slots=True)
class FilesystemIndexBackend:
    versions: FilesystemVersionBackend

    def status(self, *, ref: str = "HEAD") -> dict[str, Any]:
        resolved_ref = self.versions.resolve_ref(ref)
        if resolved_ref is None:
            raise ValueError(f"Unknown ref: {ref}")
        graph = self.versions.checkout(resolved_ref)
        provider = get_embedding_provider()
        return {
            "status": "ok",
            "backend": "filesystem",
            "persistent": False,
            "supported": False,
            "ref": ref,
            "resolved_ref": resolved_ref,
            "last_indexed_commit": None,
            "doc_count": len(graph.nodes),
            "stale": False,
            "updated_at": None,
            "lag_commits": 0,
            "embedding_provider": provider.name,
            "embedding_enabled": provider.enabled,
        }

    def rebuild(self, *, ref: str = "HEAD", all_refs: bool = False) -> dict[str, Any]:
        if all_refs:
            indexed_versions = sorted({branch.head for branch in self.versions.list_branches() if branch.head})
        else:
            resolved_ref = self.versions.resolve_ref(ref)
            if resolved_ref is None:
                raise ValueError(f"Unknown ref: {ref}")
            indexed_versions = [resolved_ref]
        return {
            "status": "ok",
            "backend": "filesystem",
            "persistent": False,
            "supported": False,
            "ref": ref,
            "all_refs": all_refs,
            "rebuilt": 0,
            "indexed_versions": indexed_versions,
            "last_indexed_commit": None,
            "message": "Persistent lexical indexing is only available for sqlite-backed stores.",
            "embedding_provider": get_embedding_provider().name,
        }

    def search(
        self,
        *,
        query: str,
        ref: str = "HEAD",
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        resolved_ref = self.versions.resolve_ref(ref)
        if resolved_ref is None:
            raise ValueError(f"Unknown ref: {ref}")
        graph = self.versions.checkout(resolved_ref)
        results, _ = hybrid_search_documents(
            [node.to_dict() for node in graph.nodes.values()],
            query,
            limit=limit,
            min_score=min_score,
            provider=get_embedding_provider(),
        )
        return results


@dataclass(slots=True)
class FilesystemMaintenanceBackend:
    store_dir: Path
    audit_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.store_dir = Path(self.store_dir)
        self.audit_path = self.store_dir / "maintenance_audit.json"

    def _merge_artifacts(self) -> list[Path]:
        return [self.store_dir / "merge_state.json", self.store_dir / "merge_working.json"]

    def _load_audit(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        return list(json.loads(self.audit_path.read_text(encoding="utf-8")))

    def _write_audit(self, entries: list[dict[str, Any]]) -> None:
        self.audit_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    def status(self, *, retention_days: int = 7) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(retention_days, 0))
        stale_merge_artifacts: list[str] = []
        for path in self._merge_artifacts():
            if not path.exists():
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified <= cutoff:
                stale_merge_artifacts.append(str(path))
        return {
            "status": "ok",
            "backend": "filesystem",
            "retention_days": retention_days,
            "stale_merge_artifacts": stale_merge_artifacts,
            "orphan_lexical_indices": 0,
            "orphan_embedding_indices": 0,
            "stale_total": len(stale_merge_artifacts),
        }

    def prune(self, *, dry_run: bool = True, retention_days: int = 7) -> dict[str, Any]:
        status = self.status(retention_days=retention_days)
        removed_merge_artifacts: list[str] = []
        if not dry_run:
            for raw_path in status["stale_merge_artifacts"]:
                path = Path(raw_path)
                if path.exists():
                    path.unlink()
                    removed_merge_artifacts.append(raw_path)
            audit_entries = self._load_audit()
            audit_entries.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action": "prune",
                    "dry_run": False,
                    "retention_days": retention_days,
                    "removed_merge_artifacts": removed_merge_artifacts,
                }
            )
            self._write_audit(audit_entries[-100:])
        return {
            "status": "ok",
            "backend": "filesystem",
            "dry_run": dry_run,
            "retention_days": retention_days,
            "removed_merge_artifacts": removed_merge_artifacts,
            "stale_merge_artifacts": status["stale_merge_artifacts"],
            "orphan_lexical_indices": 0,
            "orphan_embedding_indices": 0,
        }

    def audit_log(self, *, limit: int = 50) -> list[dict[str, Any]]:
        entries = self._load_audit()
        return list(reversed(entries[-limit:]))
