from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cortex.graph.graph import CortexGraph, Node, _normalize_label, diff_graphs
from cortex.graph.semantic_diff import semantic_diff_graphs
from cortex.schemas.memory_v1 import DEFAULT_NAMESPACE, DEFAULT_TENANT_ID, BranchRecord, CommitRecord

DEFAULT_SQLITE_FILENAME = "cortex.db"


def sqlite_db_path(store_dir: str | Path) -> Path:
    return Path(store_dir) / DEFAULT_SQLITE_FILENAME


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _parse_timestamp(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


@dataclass(slots=True)
class SQLiteVersionBackend:
    store_dir: Path
    tenant_id: str = DEFAULT_TENANT_ID
    db_path: Path = field(init=False)
    index_backend: Any | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.store_dir = Path(self.store_dir)
        self.db_path = sqlite_db_path(self.store_dir)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    version_id TEXT PRIMARY KEY,
                    graph_hash TEXT NOT NULL,
                    graph_json TEXT NOT NULL,
                    node_count INTEGER NOT NULL,
                    edge_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS version_history (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_id TEXT NOT NULL,
                    parent_id TEXT,
                    merge_parent_ids TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    source TEXT NOT NULL,
                    message TEXT NOT NULL,
                    signature TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_version_history_version_id ON version_history(version_id);
                CREATE TABLE IF NOT EXISTS refs (
                    name TEXT PRIMARY KEY,
                    version_id TEXT
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS claims (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS governance_rules (
                    name TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS remotes (
                    name TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lexical_indices (
                    version_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    doc_count INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_lexical_indices_indexed_at ON lexical_indices(indexed_at DESC);
                CREATE TABLE IF NOT EXISTS embedding_indices (
                    version_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    doc_count INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_embedding_indices_indexed_at ON embedding_indices(indexed_at DESC);
                CREATE TABLE IF NOT EXISTS maintenance_audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )
            current = conn.execute("SELECT value FROM meta WHERE key = 'head_ref'").fetchone()
            if current is None:
                conn.execute("INSERT INTO meta(key, value) VALUES('head_ref', ?)", (DEFAULT_NAMESPACE,))
            branch = conn.execute("SELECT 1 FROM refs WHERE name = ?", (DEFAULT_NAMESPACE,)).fetchone()
            if branch is None:
                conn.execute("INSERT INTO refs(name, version_id) VALUES(?, NULL)", (DEFAULT_NAMESPACE,))

    def _snapshot_row(self, version_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT version_id, graph_hash, graph_json, node_count, edge_count FROM snapshots WHERE version_id = ?",
                (version_id,),
            ).fetchone()

    def _latest_history_row(self, version_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT h.seq, h.version_id, h.parent_id, h.merge_parent_ids, h.timestamp, h.branch, h.source,
                       h.message, h.signature, s.graph_hash, s.node_count, s.edge_count
                FROM version_history h
                JOIN snapshots s ON s.version_id = h.version_id
                WHERE h.version_id = ?
                ORDER BY h.seq DESC
                LIMIT 1
                """,
                (version_id,),
            ).fetchone()

    def _row_to_commit(self, row: sqlite3.Row) -> CommitRecord:
        return CommitRecord(
            tenant_id=self.tenant_id,
            namespace=row["branch"],
            version_id=row["version_id"],
            parent_id=row["parent_id"],
            merge_parent_ids=list(json.loads(row["merge_parent_ids"] or "[]")),
            timestamp=row["timestamp"],
            source=row["source"],
            message=row["message"],
            graph_hash=row["graph_hash"],
            node_count=int(row["node_count"]),
            edge_count=int(row["edge_count"]),
            signature=row["signature"],
        )

    def _read_ref(self, branch: str) -> str | None:
        self._ensure_schema()
        with self._connect() as conn:
            row = conn.execute("SELECT version_id FROM refs WHERE name = ?", (branch,)).fetchone()
        if row is None:
            return None
        return row["version_id"]

    def _write_ref(self, branch: str, version_id: str | None) -> None:
        self._ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO refs(name, version_id) VALUES(?, ?)
                ON CONFLICT(name) DO UPDATE SET version_id = excluded.version_id
                """,
                (branch, version_id),
            )

    def current_branch(self) -> str:
        self._ensure_schema()
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'head_ref'").fetchone()
        return row["value"] if row else DEFAULT_NAMESPACE

    def resolve_version_id(self, prefix: str) -> str | None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT version_id FROM snapshots WHERE version_id LIKE ? ORDER BY version_id",
                (f"{prefix}%",),
            ).fetchall()
        matches = [row["version_id"] for row in rows]
        if prefix in matches:
            return prefix
        return matches[0] if len(matches) == 1 else None

    def resolve_ref(self, ref: str) -> str | None:
        self._ensure_schema()
        if ref == "HEAD":
            return self._read_ref(self.current_branch())
        if ref.startswith("refs/heads/"):
            return self._read_ref(ref[len("refs/heads/") :])
        branch_match = self._read_ref(ref)
        if branch_match is not None or self._branch_exists(ref):
            return branch_match
        return self.resolve_version_id(ref)

    def _branch_exists(self, branch: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM refs WHERE name = ?", (branch,)).fetchone()
        return row is not None

    def resolve_at(self, timestamp: str, ref: str | None = None) -> str | None:
        try:
            target = _parse_timestamp(timestamp)
        except ValueError:
            return None
        records = self.lineage_records(ref) if ref else self._all_history_records()
        best: dict[str, Any] | None = None
        for record in records:
            try:
                record_ts = _parse_timestamp(record["timestamp"])
            except ValueError:
                continue
            if record_ts <= target and (best is None or record_ts > _parse_timestamp(best["timestamp"])):
                best = record
        return best["version_id"] if best else None

    def is_ancestor(self, ancestor_ref: str, descendant_ref: str) -> bool:
        ancestor = self.resolve_ref(ancestor_ref)
        descendant = self.resolve_ref(descendant_ref)
        if ancestor is None or descendant is None:
            return False
        if ancestor == descendant:
            return True
        return ancestor in self._ancestry_ids(descendant)

    def merge_base(self, ref_a: str, ref_b: str) -> str | None:
        start_a = self.resolve_ref(ref_a)
        start_b = self.resolve_ref(ref_b)
        if not start_a or not start_b:
            return None
        if start_a == start_b:
            return start_a

        history_by_id = {item["version_id"]: item for item in self._all_history_records()}

        def _ancestor_distances(start: str) -> dict[str, int]:
            distances: dict[str, int] = {}
            queue: list[tuple[str, int]] = [(start, 0)]
            while queue:
                version_id, distance = queue.pop(0)
                if version_id in distances and distances[version_id] <= distance:
                    continue
                distances[version_id] = distance
                record = history_by_id.get(version_id)
                if record is None:
                    continue
                parents = []
                if record.get("parent_id"):
                    parents.append(record["parent_id"])
                parents.extend(record.get("merge_parent_ids", []))
                for parent in parents:
                    queue.append((parent, distance + 1))
            return distances

        distances_a = _ancestor_distances(start_a)
        distances_b = _ancestor_distances(start_b)
        shared = set(distances_a) & set(distances_b)
        if not shared:
            return None
        return min(
            shared,
            key=lambda version_id: (
                distances_a[version_id] + distances_b[version_id],
                max(distances_a[version_id], distances_b[version_id]),
            ),
        )

    def checkout(self, version_id: str, verify: bool = True) -> CortexGraph:
        row = self._snapshot_row(version_id)
        if row is None:
            raise FileNotFoundError(f"Version {version_id} not found")
        raw_text = row["graph_json"]
        data = json.loads(raw_text)
        if verify:
            actual_hash = hashlib.sha256(_json_dumps(data).encode("utf-8")).hexdigest()
            if actual_hash != row["graph_hash"]:
                raise ValueError(
                    f"Integrity check failed for version {version_id}: "
                    f"expected {row['graph_hash'][:16]}..., got {actual_hash[:16]}..."
                )
        return CortexGraph.from_v5_json(data)

    def diff(self, version_id_a: str, version_id_b: str) -> dict[str, Any]:
        graph_a = self.checkout(version_id_a)
        graph_b = self.checkout(version_id_b)
        structural = diff_graphs(graph_a, graph_b)
        semantic = semantic_diff_graphs(graph_a, graph_b)
        return {
            "added": sorted(item["id"] for item in structural["added_nodes"]),
            "removed": sorted(item["id"] for item in structural["removed_nodes"]),
            "modified": [{"node_id": item["id"], "changes": item["changes"]} for item in structural["modified_nodes"]],
            "semantic_changes": semantic["changes"],
            "semantic_summary": semantic["summary"],
        }

    def commit(
        self,
        graph: CortexGraph,
        message: str,
        source: str = "manual",
        identity: Any | None = None,
        *,
        parent_id: str | None = None,
        branch: str | None = None,
        merge_parent_ids: list[str] | None = None,
    ) -> CommitRecord:
        self._ensure_schema()
        graph_data = graph.export_v5()
        graph_json = _json_dumps(graph_data)
        graph_hash = hashlib.sha256(graph_json.encode("utf-8")).hexdigest()
        version_id = graph_hash[:32]
        branch = branch or self.current_branch()
        resolved_parent = parent_id if parent_id is not None else self._read_ref(branch)
        signature = identity.sign(graph_hash.encode("utf-8")) if identity is not None else None

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO snapshots(version_id, graph_hash, graph_json, node_count, edge_count)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    graph_hash,
                    json.dumps(graph_data, indent=2, ensure_ascii=False),
                    len(graph.nodes),
                    len(graph.edges),
                ),
            )
            conn.execute(
                """
                INSERT INTO version_history(
                    version_id, parent_id, merge_parent_ids, timestamp, branch, source, message, signature
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    resolved_parent,
                    json.dumps(list(merge_parent_ids or []), ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                    branch,
                    source,
                    message,
                    signature,
                ),
            )
            conn.execute(
                """
                INSERT INTO refs(name, version_id) VALUES(?, ?)
                ON CONFLICT(name) DO UPDATE SET version_id = excluded.version_id
                """,
                (branch, version_id),
            )

        if self.index_backend is not None:
            self.index_backend.upsert_version_index(version_id, graph=graph)

        row = self._latest_history_row(version_id)
        assert row is not None
        return self._row_to_commit(row)

    def head(self, ref: str = "HEAD") -> CommitRecord | None:
        resolved = self.resolve_ref(ref)
        if resolved is None:
            return None
        row = self._latest_history_row(resolved)
        return None if row is None else self._row_to_commit(row)

    def _all_history_records(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT h.seq, h.version_id, h.parent_id, h.merge_parent_ids, h.timestamp, h.branch, h.source,
                       h.message, h.signature, s.graph_hash, s.node_count, s.edge_count
                FROM version_history h
                JOIN snapshots s ON s.version_id = h.version_id
                ORDER BY h.seq ASC
                """
            ).fetchall()
        return [
            {
                "version_id": row["version_id"],
                "parent_id": row["parent_id"],
                "merge_parent_ids": list(json.loads(row["merge_parent_ids"] or "[]")),
                "timestamp": row["timestamp"],
                "branch": row["branch"],
                "source": row["source"],
                "message": row["message"],
                "graph_hash": row["graph_hash"],
                "node_count": int(row["node_count"]),
                "edge_count": int(row["edge_count"]),
                "signature": row["signature"],
            }
            for row in rows
        ]

    def log(self, limit: int = 10, ref: str | None = None) -> list[CommitRecord]:
        if ref:
            current = self.resolve_ref(ref)
            seen: set[str] = set()
            records: list[CommitRecord] = []
            while current and current not in seen:
                seen.add(current)
                row = self._latest_history_row(current)
                if row is None:
                    break
                records.append(self._row_to_commit(row))
                current = row["parent_id"]
                if limit > 0 and len(records) >= limit:
                    break
            return records

        with self._connect() as conn:
            query = """
                SELECT h.seq, h.version_id, h.parent_id, h.merge_parent_ids, h.timestamp, h.branch, h.source,
                       h.message, h.signature, s.graph_hash, s.node_count, s.edge_count
                FROM version_history h
                JOIN snapshots s ON s.version_id = h.version_id
                ORDER BY h.seq DESC
            """
            if limit > 0:
                query += " LIMIT ?"
                rows = conn.execute(query, (limit,)).fetchall()
            else:
                rows = conn.execute(query).fetchall()
        return [self._row_to_commit(row) for row in rows]

    def list_branches(self) -> list[BranchRecord]:
        current = self.current_branch()
        with self._connect() as conn:
            rows = conn.execute("SELECT name, version_id FROM refs ORDER BY name").fetchall()
        return [
            BranchRecord(
                tenant_id=self.tenant_id,
                name=row["name"],
                head=row["version_id"],
                current=row["name"] == current,
            )
            for row in rows
        ]

    def create_branch(self, branch_name: str, from_ref: str = "HEAD", switch: bool = False) -> str | None:
        if self._branch_exists(branch_name):
            raise ValueError(f"Branch already exists: {branch_name}")
        start = self.resolve_ref(from_ref)
        self._write_ref(branch_name, start)
        if switch:
            self.switch_branch(branch_name)
        return start

    def switch_branch(self, branch_name: str) -> str | None:
        if not self._branch_exists(branch_name):
            raise ValueError(f"Branch not found: {branch_name}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO meta(key, value) VALUES('head_ref', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (branch_name,),
            )
        return self._read_ref(branch_name)

    def _ancestry_ids(self, start_version: str | None) -> list[str]:
        if not start_version:
            return []
        history_by_id = {item["version_id"]: item for item in self._all_history_records()}
        seen: set[str] = set()
        queue: list[str] = [start_version]
        while queue:
            version_id = queue.pop(0)
            if version_id in seen:
                continue
            seen.add(version_id)
            record = history_by_id.get(version_id)
            if record is None:
                continue
            parents = []
            if record.get("parent_id"):
                parents.append(record["parent_id"])
            parents.extend(record.get("merge_parent_ids", []))
            queue.extend(parent for parent in parents if parent and parent not in seen)
        return [item["version_id"] for item in self._all_history_records() if item["version_id"] in seen]

    def lineage_records(self, ref: str | None) -> list[dict[str, Any]]:
        resolved = self.resolve_ref(ref or "HEAD")
        if resolved is None:
            return []
        needed = set(self._ancestry_ids(resolved))
        return [item for item in self._all_history_records() if item["version_id"] in needed]

    def _match_historical_node(
        self,
        graph: CortexGraph,
        *,
        node_id: str = "",
        label: str = "",
        aliases: list[str] | None = None,
        canonical_id: str = "",
    ) -> Node | None:
        aliases = aliases or []
        if node_id and node_id in graph.nodes:
            return graph.nodes[node_id]
        if canonical_id:
            for node in graph.nodes.values():
                if node.canonical_id == canonical_id:
                    return node
        search_terms = {_normalize_label(term) for term in [label, *aliases] if term}
        if not search_terms:
            return None
        for node in graph.nodes.values():
            node_terms = {_normalize_label(node.label), *(_normalize_label(alias) for alias in node.aliases)}
            if search_terms & node_terms:
                return node
        return None

    def blame_node(
        self,
        *,
        node_id: str = "",
        label: str = "",
        aliases: list[str] | None = None,
        canonical_id: str = "",
        ref: str = "HEAD",
        source: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        aliases = aliases or []
        history = list(reversed(self.log(limit=limit, ref=ref)))
        occurrences: list[dict[str, Any]] = []
        previous_signature: str | None = None
        source_norm = source.strip().lower()

        for version in history:
            graph = self.checkout(version.version_id)
            matched = self._match_historical_node(
                graph,
                node_id=node_id,
                label=label,
                aliases=aliases,
                canonical_id=canonical_id,
            )
            if matched is None:
                continue
            provenance_sources = sorted(
                {
                    str(item.get("source", "")).strip()
                    for item in matched.provenance
                    if str(item.get("source", "")).strip()
                }
            )
            snapshot_sources = sorted(
                {
                    str(item.get("source", "")).strip()
                    for item in matched.snapshots
                    if str(item.get("source", "")).strip()
                }
            )
            if source_norm:
                event_sources = {value.lower() for value in provenance_sources + snapshot_sources}
                if source_norm not in event_sources:
                    continue

            signature = _json_dumps(
                {
                    "label": matched.label,
                    "aliases": sorted(matched.aliases),
                    "tags": sorted(matched.tags),
                    "confidence": round(matched.confidence, 4),
                    "status": matched.status,
                    "valid_from": matched.valid_from,
                    "valid_to": matched.valid_to,
                    "sources": sorted({*provenance_sources, *snapshot_sources}),
                }
            )
            changed = previous_signature is None or signature != previous_signature
            previous_signature = signature
            occurrences.append(
                {
                    "version_id": version.version_id,
                    "timestamp": version.timestamp,
                    "message": version.message,
                    "source": version.source,
                    "changed": changed,
                    "node": {
                        "id": matched.id,
                        "canonical_id": matched.canonical_id,
                        "label": matched.label,
                        "aliases": list(matched.aliases),
                        "tags": list(matched.tags),
                        "confidence": matched.confidence,
                        "status": matched.status,
                        "valid_from": matched.valid_from,
                        "valid_to": matched.valid_to,
                        "provenance_sources": provenance_sources,
                        "snapshot_sources": snapshot_sources,
                    },
                }
            )

        introduced_in = occurrences[0] if occurrences else None
        last_seen_in = occurrences[-1] if occurrences else None
        changed_in = [item for item in occurrences if item["changed"]]
        return {
            "versions_scanned": len(history),
            "versions_seen": len(occurrences),
            "versions_changed": len(changed_in),
            "introduced_in": introduced_in,
            "last_seen_in": last_seen_in,
            "changed_in": changed_in,
            "history": occurrences,
        }

    def _export_bundle(self, ref: str) -> dict[str, Any]:
        resolved = self.resolve_ref(ref)
        if resolved is None:
            raise ValueError(f"Unknown ref: {ref}")
        records = self.lineage_records(ref)
        version_ids = {item["version_id"] for item in records}
        with self._connect() as conn:
            snapshots = (
                {
                    row["version_id"]: row["graph_json"]
                    for row in conn.execute(
                        # Safe: dynamic fragment only expands parameter placeholders.
                        f"SELECT version_id, graph_json FROM snapshots WHERE version_id IN ({','.join('?' * len(version_ids))})",  # nosec B608
                        tuple(sorted(version_ids)),
                    ).fetchall()
                }
                if version_ids
                else {}
            )
        return {"head": resolved, "records": records, "snapshots": snapshots}

    def _import_bundle(self, bundle: dict[str, Any]) -> int:
        self._ensure_schema()
        copied = 0
        snapshots_to_index: list[tuple[str, dict[str, Any]]] = []
        with self._connect() as conn:
            existing_snapshots = {
                row["version_id"] for row in conn.execute("SELECT version_id FROM snapshots").fetchall()
            }
            existing_history = {
                row["version_id"] for row in conn.execute("SELECT DISTINCT version_id FROM version_history").fetchall()
            }
            for version_id, graph_json in bundle.get("snapshots", {}).items():
                if version_id in existing_snapshots:
                    continue
                payload = json.loads(graph_json)
                graph_hash = hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()
                meta = payload.get("meta", {})
                conn.execute(
                    """
                    INSERT INTO snapshots(version_id, graph_hash, graph_json, node_count, edge_count)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        graph_hash,
                        graph_json,
                        int(meta.get("node_count", 0)),
                        int(meta.get("edge_count", 0)),
                    ),
                )
                existing_snapshots.add(version_id)
                snapshots_to_index.append((version_id, payload))
            for record in bundle.get("records", []):
                version_id = record["version_id"]
                if version_id in existing_history:
                    continue
                conn.execute(
                    """
                    INSERT INTO version_history(
                        version_id, parent_id, merge_parent_ids, timestamp, branch, source, message, signature
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        record.get("parent_id"),
                        json.dumps(list(record.get("merge_parent_ids", [])), ensure_ascii=False),
                        record["timestamp"],
                        record.get("branch", DEFAULT_NAMESPACE),
                        record.get("source", "manual"),
                        record.get("message", ""),
                        record.get("signature"),
                    ),
                )
                existing_history.add(version_id)
                copied += 1
        if self.index_backend is not None:
            for version_id, payload in snapshots_to_index:
                self.index_backend.upsert_version_index(version_id, snapshot_payload=payload)
        return copied


__all__ = [
    "DEFAULT_SQLITE_FILENAME",
    "SQLiteVersionBackend",
    "_json_dumps",
    "_parse_timestamp",
    "sqlite_db_path",
]
