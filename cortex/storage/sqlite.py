from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cortex.claims import ClaimEvent
from cortex.governance import GovernanceRule
from cortex.graph import CortexGraph, Node, _normalize_label, diff_graphs
from cortex.remotes import _normalize_store_path
from cortex.schemas.memory_v1 import (
    DEFAULT_NAMESPACE,
    DEFAULT_TENANT_ID,
    BranchRecord,
    ClaimRecord,
    CommitRecord,
    GovernanceDecisionRecord,
    GovernanceRuleRecord,
    RemoteRecord,
)
from cortex.semantic_diff import semantic_diff_graphs

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
                        f"SELECT version_id, graph_json FROM snapshots WHERE version_id IN ({','.join('?' * len(version_ids))})",
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
        return copied


@dataclass(slots=True)
class SQLiteClaimBackend:
    versions: SQLiteVersionBackend
    tenant_id: str = DEFAULT_TENANT_ID

    def _connect(self) -> sqlite3.Connection:
        return self.versions._connect()

    def append(self, event: Any) -> None:
        claim_event = event if isinstance(event, ClaimEvent) else ClaimEvent.from_dict(event.to_dict())
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO claims(event_id, payload) VALUES(?, ?)",
                (claim_event.event_id, json.dumps(claim_event.to_dict(), ensure_ascii=False)),
            )

    def _load_all(self) -> list[ClaimEvent]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM claims ORDER BY seq ASC").fetchall()
        return [ClaimEvent.from_dict(json.loads(row["payload"])) for row in rows]

    def list_events(
        self,
        *,
        claim_id: str = "",
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
        source: str = "",
        version_ref: str = "",
        op: str = "",
        limit: int = 50,
    ) -> list[ClaimRecord]:
        events = self._load_all()
        label_norm = _normalize_label(label) if label else ""
        filtered: list[ClaimEvent] = []
        for event in reversed(events):
            if claim_id and event.claim_id != claim_id:
                continue
            if node_id and event.node_id != node_id:
                continue
            if canonical_id and event.canonical_id != canonical_id:
                continue
            if label_norm:
                event_terms = {_normalize_label(event.label), *(_normalize_label(alias) for alias in event.aliases)}
                if label_norm not in event_terms:
                    continue
            if source and event.source != source:
                continue
            if version_ref and not event.version_id.startswith(version_ref):
                continue
            if op and event.op != op:
                continue
            filtered.append(event)
            if len(filtered) >= limit:
                break
        namespace = self.versions.current_branch()
        return [
            ClaimRecord.from_claim_event(event, tenant_id=self.tenant_id, namespace=namespace) for event in filtered
        ]

    def get_claim(self, claim_id: str) -> list[ClaimRecord]:
        namespace = self.versions.current_branch()
        return [
            ClaimRecord.from_claim_event(event, tenant_id=self.tenant_id, namespace=namespace)
            for event in self._load_all()
            if event.claim_id == claim_id
        ]

    def latest_event(self, claim_id: str) -> ClaimRecord | None:
        claims = self.get_claim(claim_id)
        return claims[-1] if claims else None

    def lineage_for_node(
        self,
        node: Node,
        limit: int = 50,
        *,
        source: str = "",
        version_ref: str = "",
    ) -> dict[str, Any]:
        events = [
            ClaimEvent.from_dict(item.to_dict())
            for item in self.list_events(
                node_id=node.id,
                canonical_id=node.canonical_id or node.id,
                label=node.label,
                source=source,
                version_ref=version_ref,
                limit=limit,
            )
        ]
        if not events and node.aliases:
            combined: list[ClaimEvent] = []
            seen: set[str] = set()
            for alias in node.aliases:
                for item in self.list_events(label=alias, source=source, version_ref=version_ref, limit=limit):
                    event = ClaimEvent.from_dict(item.to_dict())
                    if event.event_id in seen:
                        continue
                    seen.add(event.event_id)
                    combined.append(event)
            combined.sort(key=lambda event: event.timestamp, reverse=True)
            events = combined[:limit]
        if not events:
            return {
                "event_count": 0,
                "claim_count": 0,
                "assert_count": 0,
                "retract_count": 0,
                "sources": [],
                "claim_ids": [],
                "introduced_at": None,
                "latest_event": None,
                "events": [],
            }
        chronological = list(reversed(events))
        claim_ids = sorted({event.claim_id for event in events})
        sources = sorted({event.source for event in events if event.source})
        assert_count = sum(1 for event in events if event.op == "assert")
        retract_count = sum(1 for event in events if event.op == "retract")
        introduced = chronological[0]
        latest = events[0]
        return {
            "event_count": len(events),
            "claim_count": len(claim_ids),
            "assert_count": assert_count,
            "retract_count": retract_count,
            "sources": sources,
            "claim_ids": claim_ids,
            "introduced_at": {
                "timestamp": introduced.timestamp,
                "source": introduced.source,
                "method": introduced.method,
                "claim_id": introduced.claim_id,
                "version_id": introduced.version_id,
            },
            "latest_event": {
                "timestamp": latest.timestamp,
                "op": latest.op,
                "source": latest.source,
                "method": latest.method,
                "claim_id": latest.claim_id,
                "version_id": latest.version_id,
            },
            "events": [event.to_dict() for event in events],
        }


def _governance_rule_model(record: GovernanceRuleRecord) -> GovernanceRule:
    return GovernanceRule.from_dict(record.to_dict())


@dataclass(slots=True)
class SQLiteGovernanceBackend:
    versions: SQLiteVersionBackend
    tenant_id: str = DEFAULT_TENANT_ID

    def _connect(self) -> sqlite3.Connection:
        return self.versions._connect()

    def list_rules(self) -> list[GovernanceRuleRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM governance_rules ORDER BY name").fetchall()
        return [
            GovernanceRuleRecord.from_governance_rule(json.loads(row["payload"]), tenant_id=self.tenant_id)
            for row in rows
        ]

    def upsert_rule(self, rule: GovernanceRuleRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO governance_rules(name, payload) VALUES(?, ?)
                ON CONFLICT(name) DO UPDATE SET payload = excluded.payload
                """,
                (rule.name, json.dumps(rule.to_dict(), ensure_ascii=False)),
            )

    def remove_rule(self, name: str) -> bool:
        with self._connect() as conn:
            before = conn.total_changes
            conn.execute("DELETE FROM governance_rules WHERE name = ?", (name,))
            return conn.total_changes > before

    def _approval_reasons(
        self,
        rule: GovernanceRule,
        *,
        current_graph: CortexGraph | None,
        baseline_graph: CortexGraph | None,
    ) -> list[str]:
        if current_graph is None:
            return []
        reasons: list[str] = []
        changed_nodes = list(current_graph.nodes.values())
        semantic_changes: list[dict[str, Any]] = []
        if baseline_graph is not None:
            structural = diff_graphs(baseline_graph, current_graph)
            touched_ids = (
                {item["id"] for item in structural.get("added_nodes", [])}
                | {item["id"] for item in structural.get("modified_nodes", [])}
                | {item["id"] for item in structural.get("removed_nodes", [])}
            )
            changed_nodes = [current_graph.nodes[node_id] for node_id in touched_ids if node_id in current_graph.nodes]
            semantic_changes = semantic_diff_graphs(baseline_graph, current_graph)["changes"]
        if rule.approval_below_confidence is not None:
            risky = sorted(
                [node for node in changed_nodes if node.confidence < float(rule.approval_below_confidence)],
                key=lambda node: node.confidence,
            )
            if risky:
                preview = ", ".join(f"{node.label} ({node.confidence:.2f})" for node in risky[:5])
                reasons.append(f"Low-confidence changes below {float(rule.approval_below_confidence):.2f}: {preview}")
        if rule.approval_tags:
            matched = [node.label for node in changed_nodes if any(tag in set(node.tags) for tag in rule.approval_tags)]
            if matched:
                reasons.append("Protected tag changes: " + ", ".join(sorted(dict.fromkeys(matched))[:10]))
        if rule.approval_change_types and semantic_changes:
            matched = [change for change in semantic_changes if change.get("type") in set(rule.approval_change_types)]
            if matched:
                preview = ", ".join(sorted(dict.fromkeys(change["type"] for change in matched)))
                reasons.append(f"Semantic changes requiring review: {preview}")
        return reasons

    def authorize(
        self,
        actor: str,
        action: str,
        namespace: str,
        *,
        current_graph: CortexGraph | None = None,
        baseline_graph: CortexGraph | None = None,
    ) -> GovernanceDecisionRecord:
        rules = [_governance_rule_model(rule) for rule in self.list_rules()]
        if not rules:
            return GovernanceDecisionRecord(
                tenant_id=self.tenant_id,
                namespace=namespace,
                allowed=True,
                require_approval=False,
                actor=actor,
                action=action,
            )
        matching = [rule for rule in rules if rule.matches(actor, action, namespace)]
        if not matching:
            return GovernanceDecisionRecord(
                tenant_id=self.tenant_id,
                namespace=namespace,
                allowed=False,
                require_approval=False,
                actor=actor,
                action=action,
                reasons=["No matching governance rule allows this action."],
            )
        deny_rules = [rule for rule in matching if rule.effect == "deny"]
        if deny_rules:
            return GovernanceDecisionRecord(
                tenant_id=self.tenant_id,
                namespace=namespace,
                allowed=False,
                require_approval=False,
                actor=actor,
                action=action,
                reasons=[f"Blocked by governance rule '{rule.name}'." for rule in deny_rules],
                matched_rules=[rule.name for rule in matching],
            )
        allow_rules = [rule for rule in matching if rule.effect == "allow"]
        require_approval = False
        reasons: list[str] = []
        for rule in allow_rules:
            if rule.require_approval:
                require_approval = True
                reasons.append(f"Rule '{rule.name}' requires explicit approval.")
            reasons.extend(self._approval_reasons(rule, current_graph=current_graph, baseline_graph=baseline_graph))
        if reasons:
            require_approval = True
        return GovernanceDecisionRecord(
            tenant_id=self.tenant_id,
            namespace=namespace,
            allowed=True,
            require_approval=require_approval,
            actor=actor,
            action=action,
            reasons=reasons,
            matched_rules=[rule.name for rule in matching],
        )


@dataclass(slots=True)
class SQLiteRemoteBackend:
    versions: SQLiteVersionBackend
    tenant_id: str = DEFAULT_TENANT_ID

    def _connect(self) -> sqlite3.Connection:
        return self.versions._connect()

    def list_remotes(self) -> list[RemoteRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM remotes ORDER BY name").fetchall()
        remotes: list[RemoteRecord] = []
        for row in rows:
            payload = json.loads(row["payload"])
            record = RemoteRecord.from_memory_remote(payload, tenant_id=self.tenant_id)
            if not record.resolved_store_path:
                record = RemoteRecord(
                    tenant_id=record.tenant_id,
                    name=record.name,
                    path=record.path,
                    resolved_store_path=str(_normalize_store_path(record.path)),
                    default_branch=record.default_branch,
                )
            remotes.append(record)
        return remotes

    def add_remote(self, remote: RemoteRecord) -> None:
        resolved_store_path = remote.resolved_store_path or str(_normalize_store_path(remote.path))
        stored_remote = RemoteRecord(
            tenant_id=remote.tenant_id,
            name=remote.name,
            path=remote.path,
            resolved_store_path=resolved_store_path,
            default_branch=remote.default_branch,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO remotes(name, payload) VALUES(?, ?)
                ON CONFLICT(name) DO UPDATE SET payload = excluded.payload
                """,
                (stored_remote.name, json.dumps(stored_remote.to_dict(), ensure_ascii=False)),
            )

    def remove_remote(self, name: str) -> bool:
        with self._connect() as conn:
            before = conn.total_changes
            conn.execute("DELETE FROM remotes WHERE name = ?", (name,))
            return conn.total_changes > before

    def _require_remote(self, name: str) -> RemoteRecord:
        for remote in self.list_remotes():
            if remote.name == name:
                return remote
        raise ValueError(f"Unknown remote: {name}")

    def push_remote(
        self,
        name: str,
        *,
        branch: str,
        target_branch: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        from cortex.storage.remote_sync import push_remote_backend

        return push_remote_backend(self.storage_backend, self._require_remote(name), branch, target_branch, force)

    def pull_remote(
        self,
        name: str,
        *,
        branch: str,
        into_branch: str | None = None,
        force: bool = False,
        switch: bool = False,
    ) -> dict[str, Any]:
        from cortex.storage.remote_sync import pull_remote_backend

        return pull_remote_backend(self.storage_backend, self._require_remote(name), branch, into_branch, force, switch)

    def fork_remote(
        self,
        name: str,
        *,
        remote_branch: str,
        local_branch: str,
        switch: bool = False,
    ) -> dict[str, Any]:
        from cortex.storage.remote_sync import fork_remote_backend

        return fork_remote_backend(
            self.storage_backend, self._require_remote(name), remote_branch, local_branch, switch
        )

    @property
    def storage_backend(self) -> "SQLiteStorageBackend":
        return SQLiteStorageBackend(self.versions.store_dir, tenant_id=self.tenant_id)


@dataclass(slots=True)
class SQLiteStorageBackend:
    store_dir: Path
    tenant_id: str = DEFAULT_TENANT_ID
    versions: SQLiteVersionBackend = field(init=False)
    claims: SQLiteClaimBackend = field(init=False)
    governance: SQLiteGovernanceBackend = field(init=False)
    remotes: SQLiteRemoteBackend = field(init=False)

    def __post_init__(self) -> None:
        self.store_dir = Path(self.store_dir)
        versions = SQLiteVersionBackend(self.store_dir, tenant_id=self.tenant_id)
        self.versions = versions
        self.claims = SQLiteClaimBackend(versions, tenant_id=self.tenant_id)
        self.governance = SQLiteGovernanceBackend(versions, tenant_id=self.tenant_id)
        self.remotes = SQLiteRemoteBackend(versions, tenant_id=self.tenant_id)


def build_sqlite_backend(
    store_dir: str | Path,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> SQLiteStorageBackend:
    return SQLiteStorageBackend(Path(store_dir), tenant_id=tenant_id)


__all__ = [
    "DEFAULT_SQLITE_FILENAME",
    "SQLiteClaimBackend",
    "SQLiteGovernanceBackend",
    "SQLiteRemoteBackend",
    "SQLiteStorageBackend",
    "SQLiteVersionBackend",
    "build_sqlite_backend",
    "sqlite_db_path",
]
