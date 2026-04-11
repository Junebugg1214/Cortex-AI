from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cortex.embeddings import build_document_embeddings, get_embedding_provider, hybrid_search_documents
from cortex.graph import CortexGraph
from cortex.search import TFIDFIndex
from cortex.storage.sqlite_versions import SQLiteVersionBackend


@dataclass(slots=True)
class SQLiteIndexBackend:
    versions: SQLiteVersionBackend

    def _connect(self) -> sqlite3.Connection:
        return self.versions._connect()

    def _snapshot_payload(self, version_id: str) -> dict[str, Any]:
        row = self.versions._snapshot_row(version_id)
        if row is None:
            raise FileNotFoundError(f"Version {version_id} not found")
        return json.loads(row["graph_json"])

    def _node_documents(
        self, *, graph: CortexGraph | None = None, snapshot_payload: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        if graph is not None:
            return [node.to_dict() for node in graph.nodes.values()]
        if snapshot_payload is not None:
            nodes = snapshot_payload.get("graph", {}).get("nodes", {})
            return [dict(node) for node in nodes.values()]
        raise ValueError("graph or snapshot_payload is required to build an index")

    def _latest_row(self) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT version_id, doc_count, indexed_at
                FROM lexical_indices
                ORDER BY indexed_at DESC, version_id DESC
                LIMIT 1
                """
            ).fetchone()

    def _index_row(self, version_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT version_id, payload, doc_count, indexed_at
                FROM lexical_indices
                WHERE version_id = ?
                """,
                (version_id,),
            ).fetchone()

    def _embedding_row(self, version_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT version_id, provider, payload, doc_count, indexed_at
                FROM embedding_indices
                WHERE version_id = ?
                """,
                (version_id,),
            ).fetchone()

    def _nearest_index_details(self, ref: str) -> dict[str, Any] | None:
        for lag, commit in enumerate(self.versions.log(limit=0, ref=ref)):
            row = self._index_row(commit.version_id)
            if row is None:
                continue
            return {
                "version_id": row["version_id"],
                "doc_count": int(row["doc_count"]),
                "indexed_at": row["indexed_at"],
                "lag_commits": lag,
            }
        return None

    def upsert_version_index(
        self,
        version_id: str,
        *,
        graph: CortexGraph | None = None,
        snapshot_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        documents = self._node_documents(graph=graph, snapshot_payload=snapshot_payload)
        index = TFIDFIndex()
        index.build(documents)
        embedding_provider = get_embedding_provider()
        embedding_payload = build_document_embeddings(documents, embedding_provider)
        indexed_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO lexical_indices(version_id, payload, doc_count, indexed_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(version_id) DO UPDATE
                SET payload = excluded.payload,
                    doc_count = excluded.doc_count,
                    indexed_at = excluded.indexed_at
                """,
                (version_id, json.dumps(index.to_dict(), ensure_ascii=False), index.doc_count, indexed_at),
            )
            if embedding_provider.enabled:
                conn.execute(
                    """
                    INSERT INTO embedding_indices(version_id, provider, payload, doc_count, indexed_at)
                    VALUES(?, ?, ?, ?, ?)
                    ON CONFLICT(version_id) DO UPDATE
                    SET provider = excluded.provider,
                        payload = excluded.payload,
                        doc_count = excluded.doc_count,
                        indexed_at = excluded.indexed_at
                    """,
                    (
                        version_id,
                        embedding_provider.name,
                        json.dumps(embedding_payload, ensure_ascii=False),
                        len(embedding_payload),
                        indexed_at,
                    ),
                )
            else:
                conn.execute("DELETE FROM embedding_indices WHERE version_id = ?", (version_id,))
        return {
            "version_id": version_id,
            "doc_count": index.doc_count,
            "indexed_at": indexed_at,
            "embedding_enabled": embedding_provider.enabled,
            "embedding_provider": embedding_provider.name,
        }

    def _ensure_index(self, version_id: str) -> tuple[TFIDFIndex, dict[str, Any]]:
        row = self._index_row(version_id)
        if row is None:
            details = self.upsert_version_index(version_id, snapshot_payload=self._snapshot_payload(version_id))
            row = self._index_row(version_id)
            assert row is not None
            return TFIDFIndex.from_dict(json.loads(row["payload"])), details
        return TFIDFIndex.from_dict(json.loads(row["payload"])), {
            "version_id": row["version_id"],
            "doc_count": int(row["doc_count"]),
            "indexed_at": row["indexed_at"],
        }

    def status(self, *, ref: str = "HEAD") -> dict[str, Any]:
        resolved_ref = self.versions.resolve_ref(ref)
        if resolved_ref is None:
            raise ValueError(f"Unknown ref: {ref}")
        current_row = self._index_row(resolved_ref)
        nearest = self._nearest_index_details(ref)
        snapshot = self.versions._snapshot_row(resolved_ref)
        embedding_provider = get_embedding_provider()
        current_embedding_row = self._embedding_row(resolved_ref)
        snapshot_doc_count = int(snapshot["node_count"]) if snapshot is not None else 0
        return {
            "status": "ok",
            "backend": "sqlite",
            "persistent": True,
            "supported": True,
            "ref": ref,
            "resolved_ref": resolved_ref,
            "indexed": current_row is not None,
            "stale": current_row is None,
            "doc_count": int(current_row["doc_count"]) if current_row is not None else snapshot_doc_count,
            "updated_at": current_row["indexed_at"]
            if current_row is not None
            else nearest["indexed_at"]
            if nearest
            else None,
            "last_indexed_commit": nearest["version_id"] if nearest is not None else None,
            "last_indexed_at": nearest["indexed_at"] if nearest is not None else None,
            "lag_commits": int(nearest["lag_commits"])
            if nearest is not None
            else len(self.versions.log(limit=0, ref=ref)),
            "embedding_provider": embedding_provider.name,
            "embedding_enabled": embedding_provider.enabled,
            "embedding_indexed": current_embedding_row is not None if embedding_provider.enabled else False,
        }

    def rebuild(self, *, ref: str = "HEAD", all_refs: bool = False) -> dict[str, Any]:
        if all_refs:
            version_ids = list(dict.fromkeys(item["version_id"] for item in self.versions._all_history_records()))
        else:
            resolved_ref = self.versions.resolve_ref(ref)
            if resolved_ref is None:
                raise ValueError(f"Unknown ref: {ref}")
            version_ids = [resolved_ref]

        rebuilt: list[dict[str, Any]] = []
        for version_id in version_ids:
            rebuilt.append(self.upsert_version_index(version_id, snapshot_payload=self._snapshot_payload(version_id)))

        latest = rebuilt[-1] if rebuilt else None
        return {
            "status": "ok",
            "backend": "sqlite",
            "persistent": True,
            "supported": True,
            "ref": ref,
            "all_refs": all_refs,
            "rebuilt": len(rebuilt),
            "indexed_versions": [item["version_id"] for item in rebuilt],
            "doc_count": latest["doc_count"] if latest is not None else 0,
            "updated_at": latest["indexed_at"] if latest is not None else None,
            "last_indexed_commit": latest["version_id"] if latest is not None else None,
            "embedding_provider": get_embedding_provider().name,
            "embedding_enabled": get_embedding_provider().enabled,
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
        index, _ = self._ensure_index(resolved_ref)
        embedding_provider = get_embedding_provider()
        embedding_row = self._embedding_row(resolved_ref)
        embeddings = json.loads(embedding_row["payload"]) if embedding_row is not None else None
        results, _ = hybrid_search_documents(
            list(index.to_dict().get("docs", {}).values()),
            query,
            limit=limit,
            min_score=min_score,
            lexical_index=index,
            provider=embedding_provider,
            document_embeddings=embeddings,
        )
        return results


@dataclass(slots=True)
class SQLiteMaintenanceBackend:
    versions: SQLiteVersionBackend

    def _connect(self) -> sqlite3.Connection:
        return self.versions._connect()

    def _merge_artifacts(self) -> list[Path]:
        return [self.versions.store_dir / "merge_state.json", self.versions.store_dir / "merge_working.json"]

    def _orphan_count(self, table_name: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {table_name}
                WHERE version_id NOT IN (SELECT version_id FROM snapshots)
                """
            ).fetchone()
        return int(row["total"]) if row is not None else 0

    def _stale_merge_artifacts(self, retention_days: int) -> list[str]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(retention_days, 0))
        stale: list[str] = []
        for path in self._merge_artifacts():
            if not path.exists():
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified <= cutoff:
                stale.append(str(path))
        return stale

    def status(self, *, retention_days: int = 7) -> dict[str, Any]:
        return {
            "status": "ok",
            "backend": "sqlite",
            "retention_days": retention_days,
            "orphan_lexical_indices": self._orphan_count("lexical_indices"),
            "orphan_embedding_indices": self._orphan_count("embedding_indices"),
            "stale_merge_artifacts": self._stale_merge_artifacts(retention_days),
        }

    def prune(self, *, dry_run: bool = True, retention_days: int = 7) -> dict[str, Any]:
        status = self.status(retention_days=retention_days)
        removed_lexical = 0
        removed_embedding = 0
        removed_merge_artifacts: list[str] = []
        if not dry_run:
            with self._connect() as conn:
                removed_lexical = conn.execute(
                    """
                    DELETE FROM lexical_indices
                    WHERE version_id NOT IN (SELECT version_id FROM snapshots)
                    """
                ).rowcount
                removed_embedding = conn.execute(
                    """
                    DELETE FROM embedding_indices
                    WHERE version_id NOT IN (SELECT version_id FROM snapshots)
                    """
                ).rowcount
                payload = {
                    "dry_run": False,
                    "retention_days": retention_days,
                    "removed_lexical_indices": removed_lexical,
                    "removed_embedding_indices": removed_embedding,
                }
                conn.execute(
                    "INSERT INTO maintenance_audit(timestamp, action, payload) VALUES(?, ?, ?)",
                    (
                        datetime.now(timezone.utc).isoformat(),
                        "prune",
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
            for raw_path in status["stale_merge_artifacts"]:
                path = Path(raw_path)
                if path.exists():
                    path.unlink()
                    removed_merge_artifacts.append(raw_path)
        return {
            "status": "ok",
            "backend": "sqlite",
            "dry_run": dry_run,
            "retention_days": retention_days,
            "removed_lexical_indices": removed_lexical,
            "removed_embedding_indices": removed_embedding,
            "removed_merge_artifacts": removed_merge_artifacts,
            **status,
        }

    def audit_log(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, action, payload
                FROM maintenance_audit
                ORDER BY seq DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "timestamp": row["timestamp"],
                "action": row["action"],
                **json.loads(row["payload"]),
            }
            for row in rows
        ]


__all__ = ["SQLiteIndexBackend", "SQLiteMaintenanceBackend"]
