"""
Version Control — Git-like version history for graph snapshots.

Full snapshots per commit (~50-100KB). Delta optimization deferred to v6.0.

Store layout:
    .cortex/
    +-- identity.json
    +-- identity.key
    +-- history.json
    +-- versions/
        +-- <hash1>.json
        +-- <hash2>.json
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cortex.atomic_io import atomic_write_text, locked_path
from cortex.graph import CortexGraph, Node, _normalize_label
from cortex.semantic_diff import semantic_diff_graphs

if TYPE_CHECKING:
    from cortex.upai.identity import UPAIIdentity


CHAIN_HASH_VERSION = 2
LEGACY_CHAIN_HASH_VERSION = 1
logger = logging.getLogger(__name__)


@dataclass
class ContextVersion:
    version_id: str  # SHA-256 of canonical chain envelope
    parent_id: str | None  # previous version (None for initial)
    merge_parent_ids: list[str]  # optional additional parents for merge commits
    timestamp: str  # ISO-8601
    branch: str  # branch ref name
    source: str  # "extraction", "merge", "manual"
    message: str  # commit message
    graph_hash: str  # SHA-256 integrity hash
    node_count: int
    edge_count: int
    signature: str | None  # Ed25519/HMAC signature of graph_hash (if identity available)
    chain_hash_version: int = CHAIN_HASH_VERSION

    def to_dict(self) -> dict:
        return {
            "version_id": self.version_id,
            "parent_id": self.parent_id,
            "merge_parent_ids": list(self.merge_parent_ids),
            "timestamp": self.timestamp,
            "branch": self.branch,
            "source": self.source,
            "message": self.message,
            "graph_hash": self.graph_hash,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "signature": self.signature,
            "chain_hash_version": self.chain_hash_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ContextVersion:
        return cls(
            version_id=d["version_id"],
            parent_id=d.get("parent_id"),
            merge_parent_ids=list(d.get("merge_parent_ids", [])),
            timestamp=d["timestamp"],
            branch=d.get("branch", "main"),
            source=d["source"],
            message=d["message"],
            graph_hash=d["graph_hash"],
            node_count=d["node_count"],
            edge_count=d["edge_count"],
            signature=d.get("signature"),
            chain_hash_version=int(d.get("chain_hash_version") or LEGACY_CHAIN_HASH_VERSION),
        )


class VersionStore:
    """Git-like version store for CortexGraph snapshots."""

    def __init__(self, store_dir: Path) -> None:
        self.store_dir = store_dir
        self.versions_dir = store_dir / "versions"
        self.history_path = store_dir / "history.json"
        self.refs_dir = store_dir / "refs"
        self.heads_dir = self.refs_dir / "heads"
        self.head_path = store_dir / "HEAD"
        self.migrations_dir = store_dir / "migrations"
        self._warned_legacy_unchained = False

    def _ensure_dirs(self) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.heads_dir.mkdir(parents=True, exist_ok=True)

    def _branch_path(self, branch: str) -> Path:
        return self.heads_dir / branch

    def _bootstrap_refs(self) -> None:
        self._ensure_dirs()
        with locked_path(self.store_dir):
            if self.head_path.exists():
                return

            history = self._load_history()
            branch = "main"
            branch_path = self._branch_path(branch)
            branch_path.parent.mkdir(parents=True, exist_ok=True)
            if history:
                atomic_write_text(branch_path, history[-1]["version_id"])
            elif not branch_path.exists():
                atomic_write_text(branch_path, "")
            atomic_write_text(self.head_path, f"ref: refs/heads/{branch}")

    def _current_ref(self) -> str:
        self._bootstrap_refs()
        raw = self.head_path.read_text().strip()
        if raw.startswith("ref: "):
            return raw[5:]
        return raw or "refs/heads/main"

    def _read_ref(self, branch: str) -> str | None:
        self._bootstrap_refs()
        path = self._branch_path(branch)
        if not path.exists():
            return None
        value = path.read_text().strip()
        return value or None

    def _write_ref(self, branch: str, version_id: str | None) -> None:
        self._ensure_dirs()
        path = self._branch_path(branch)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, version_id or "")

    def current_branch(self) -> str:
        ref = self._current_ref()
        if ref.startswith("refs/heads/"):
            return ref[len("refs/heads/") :]
        return ref

    @staticmethod
    def _chain_payload(
        *,
        graph_hash: str,
        parent_id: str | None,
        merge_parent_ids: list[str] | None,
        branch: str,
        timestamp: str,
        source: str,
        message: str,
    ) -> dict[str, Any]:
        return {
            "graph_hash": graph_hash,
            "parent_id": parent_id or "",
            "merge_parent_ids": sorted(merge_parent_ids or []),
            "branch": branch,
            "timestamp": timestamp,
            "source": source,
            "message": message,
        }

    @classmethod
    def derive_version_id(
        cls,
        *,
        graph_hash: str,
        parent_id: str | None,
        merge_parent_ids: list[str] | None,
        branch: str,
        timestamp: str,
        source: str,
        message: str,
    ) -> str:
        payload = cls._chain_payload(
            graph_hash=graph_hash,
            parent_id=parent_id,
            merge_parent_ids=merge_parent_ids,
            branch=branch,
            timestamp=timestamp,
            source=source,
            message=message,
        )
        canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]

    def _warn_legacy_unchained(self) -> None:
        if self._warned_legacy_unchained:
            return
        logger.warning(
            "Cortex store %s uses legacy unchained version IDs; run `cortex integrity rehash --confirm --store-dir %s` to migrate.",
            self.store_dir,
            self.store_dir,
        )
        self._warned_legacy_unchained = True

    def _write_history_envelope(self, envelope: dict[str, Any]) -> None:
        self._ensure_dirs()
        atomic_write_text(self.history_path, json.dumps(envelope, indent=2))

    def _load_history_envelope(self) -> dict[str, Any]:
        if self.history_path.exists():
            raw = json.loads(self.history_path.read_text())
            if isinstance(raw, list):
                envelope = {
                    "chain_hash_version": LEGACY_CHAIN_HASH_VERSION,
                    "meta": {"legacy_unchained": True},
                    "history": raw,
                }
                self._warn_legacy_unchained()
                self._write_history_envelope(envelope)
                return envelope
            if not isinstance(raw, dict):
                raise ValueError(f"Invalid history format in {self.history_path}")

            chain_hash_version = int(raw.get("chain_hash_version") or LEGACY_CHAIN_HASH_VERSION)
            meta = dict(raw.get("meta") or {})
            history = list(raw.get("history") or [])
            envelope = {
                "chain_hash_version": chain_hash_version,
                "meta": meta,
                "history": history,
            }
            if chain_hash_version <= LEGACY_CHAIN_HASH_VERSION:
                was_marked = bool(meta.get("legacy_unchained"))
                envelope["meta"]["legacy_unchained"] = True
                self._warn_legacy_unchained()
                if not was_marked or "meta" not in raw:
                    self._write_history_envelope(envelope)
            return envelope
        return {"chain_hash_version": CHAIN_HASH_VERSION, "meta": {}, "history": []}

    def _load_history(self) -> list[dict]:
        return list(self._load_history_envelope().get("history", []))

    def _save_history(
        self,
        history: list[dict],
        *,
        meta: dict[str, Any] | None = None,
        chain_hash_version: int = CHAIN_HASH_VERSION,
    ) -> None:
        existing = self._load_history_envelope() if self.history_path.exists() else {}
        envelope = {
            "chain_hash_version": chain_hash_version,
            "meta": dict(existing.get("meta", {})) if meta is None else dict(meta),
            "history": history,
        }
        self._write_history_envelope(envelope)

    def _topological_history(self, history: list[dict]) -> list[dict]:
        records_by_id = {item["version_id"]: item for item in history}
        remaining = list(history)
        ordered: list[dict] = []
        seen: set[str] = set()
        while remaining:
            progressed = False
            next_remaining: list[dict] = []
            for item in remaining:
                parents = []
                if item.get("parent_id"):
                    parents.append(item["parent_id"])
                parents.extend(item.get("merge_parent_ids", []))
                if all(parent not in records_by_id or parent in seen for parent in parents):
                    ordered.append(item)
                    seen.add(item["version_id"])
                    progressed = True
                else:
                    next_remaining.append(item)
            if not progressed:
                ordered.extend(next_remaining)
                break
            remaining = next_remaining
        return ordered

    def verify_chain_integrity(self) -> dict[str, Any]:
        envelope = self._load_history_envelope()
        history = list(envelope.get("history", []))
        root_chain_hash_version = int(envelope.get("chain_hash_version") or LEGACY_CHAIN_HASH_VERSION)
        meta = dict(envelope.get("meta") or {})
        legacy_versions: list[str] = []
        chain_issues: list[dict[str, str]] = []

        for item in history:
            version_id = item["version_id"]
            record_chain_hash_version = int(item.get("chain_hash_version") or LEGACY_CHAIN_HASH_VERSION)
            if record_chain_hash_version < CHAIN_HASH_VERSION:
                legacy_versions.append(version_id)
                continue
            expected = self.derive_version_id(
                graph_hash=item["graph_hash"],
                parent_id=item.get("parent_id"),
                merge_parent_ids=list(item.get("merge_parent_ids", [])),
                branch=item.get("branch", "main"),
                timestamp=item["timestamp"],
                source=item["source"],
                message=item["message"],
            )
            if expected != version_id:
                chain_issues.append(
                    {
                        "version_id": version_id,
                        "expected_version_id": expected,
                        "message": "Version ID does not match its canonical chain envelope.",
                    }
                )

        legacy_unchained = (
            bool(meta.get("legacy_unchained")) or bool(legacy_versions) or root_chain_hash_version < CHAIN_HASH_VERSION
        )
        status = "ok"
        if chain_issues:
            status = "error"
        elif legacy_unchained:
            status = "warning"
        return {
            "status": status,
            "chain_hash_version": root_chain_hash_version,
            "legacy_unchained": legacy_unchained,
            "legacy_versions": legacy_versions,
            "chain_issues": chain_issues,
        }

    def rehash_chain_v2(self, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise ValueError("Refusing to rewrite version history without confirm=True")

        self._ensure_dirs()
        with locked_path(self.store_dir):
            envelope = self._load_history_envelope()
            history = list(envelope.get("history", []))
            ordered = self._topological_history(history)
            meta = dict(envelope.get("meta") or {})
            migrated_at = datetime.now(timezone.utc).isoformat()

            rewritten: list[dict[str, Any]] = []
            old_to_new: dict[str, str] = {}
            for item in ordered:
                old_version_id = item["version_id"]
                new_parent_id = old_to_new.get(item.get("parent_id"), item.get("parent_id"))
                new_merge_parent_ids = [old_to_new.get(parent, parent) for parent in item.get("merge_parent_ids", [])]
                new_version_id = self.derive_version_id(
                    graph_hash=item["graph_hash"],
                    parent_id=new_parent_id,
                    merge_parent_ids=new_merge_parent_ids,
                    branch=item.get("branch", "main"),
                    timestamp=item["timestamp"],
                    source=item["source"],
                    message=item["message"],
                )
                old_to_new[old_version_id] = new_version_id
                new_item = dict(item)
                new_item["version_id"] = new_version_id
                new_item["parent_id"] = new_parent_id
                new_item["merge_parent_ids"] = new_merge_parent_ids
                new_item["chain_hash_version"] = CHAIN_HASH_VERSION
                rewritten.append(new_item)

            new_ids = list(old_to_new.values())
            if len(set(new_ids)) != len(new_ids):
                raise ValueError("Cannot rehash store: duplicate v2 version IDs would be produced")

            self._rewrite_version_files(old_to_new)
            updated_refs = self._rewrite_refs(old_to_new)

            meta.pop("legacy_unchained", None)
            meta["rehash_v2"] = {
                "migrated_at": migrated_at,
                "version_count": len(rewritten),
            }
            self._save_history(rewritten, meta=meta, chain_hash_version=CHAIN_HASH_VERSION)

            self.migrations_dir.mkdir(parents=True, exist_ok=True)
            log_path = self.migrations_dir / "rehash-v2.log"
            log_lines = [
                f"rehash-v2 migrated_at={migrated_at}",
                f"versions={len(rewritten)}",
                "mapping:",
            ]
            for old_id, new_id in old_to_new.items():
                marker = "unchanged" if old_id == new_id else "rewritten"
                log_lines.append(f"{old_id} -> {new_id} {marker}")
            if updated_refs:
                log_lines.append("refs:")
                for name, value in sorted(updated_refs.items()):
                    log_lines.append(f"{name} -> {value}")
            atomic_write_text(log_path, "\n".join(log_lines) + "\n")

            return {
                "status": "ok",
                "migrated": len(rewritten),
                "mapping": old_to_new,
                "refs": updated_refs,
                "log_path": str(log_path),
            }

    def _rewrite_version_files(self, old_to_new: dict[str, str]) -> None:
        old_ids = set(old_to_new)
        for old_id, new_id in old_to_new.items():
            source = self.versions_dir / f"{old_id}.json"
            if not source.exists():
                raise FileNotFoundError(f"Cannot rehash store: missing snapshot {source}")
            if old_id == new_id:
                continue
            destination = self.versions_dir / f"{new_id}.json"
            if destination.exists() and new_id not in old_ids:
                raise FileExistsError(f"Cannot rehash store: destination snapshot already exists: {destination}")

        temp_paths: dict[str, Path] = {}
        for old_id, new_id in old_to_new.items():
            if old_id == new_id:
                continue
            source = self.versions_dir / f"{old_id}.json"
            temp = self.versions_dir / f".rehash-v2-{old_id}.json.tmp"
            if temp.exists():
                temp.unlink()
            source.replace(temp)
            temp_paths[old_id] = temp

        for old_id, temp in temp_paths.items():
            destination = self.versions_dir / f"{old_to_new[old_id]}.json"
            temp.replace(destination)

    def _rewrite_refs(self, old_to_new: dict[str, str]) -> dict[str, str]:
        updated: dict[str, str] = {}
        if self.heads_dir.exists():
            for path in sorted(self.heads_dir.rglob("*")):
                if not path.is_file():
                    continue
                value = path.read_text().strip()
                if value in old_to_new:
                    new_value = old_to_new[value]
                    atomic_write_text(path, new_value)
                    updated[f"refs/heads/{path.relative_to(self.heads_dir).as_posix()}"] = new_value

        if self.head_path.exists():
            value = self.head_path.read_text().strip()
            if value and not value.startswith("ref: ") and value in old_to_new:
                new_value = old_to_new[value]
                atomic_write_text(self.head_path, new_value)
                updated["HEAD"] = new_value
        return updated

    def _ancestry_ids(self, start_version: str | None) -> list[str]:
        if not start_version:
            return []
        history_by_id = {item["version_id"]: item for item in self._load_history()}
        seen: set[str] = set()
        queue: deque[str] = deque([start_version])
        while queue:
            version_id = queue.popleft()
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
        return [item["version_id"] for item in self._load_history() if item["version_id"] in seen]

    def commit(
        self,
        graph: CortexGraph,
        message: str,
        source: str = "manual",
        identity: UPAIIdentity | None = None,
        *,
        parent_id: str | None = None,
        branch: str | None = None,
        merge_parent_ids: list[str] | None = None,
    ) -> ContextVersion:
        """Serialize graph, hash, optionally sign, save snapshot, append to history."""
        self._ensure_dirs()
        self._bootstrap_refs()

        # Serialize graph
        graph_data = graph.export_v5()
        graph_json = json.dumps(graph_data, sort_keys=True, ensure_ascii=False)
        graph_bytes = graph_json.encode("utf-8")

        # Hash graph content independently from the chain envelope.
        graph_hash = hashlib.sha256(graph_bytes).hexdigest()

        # Sign if identity available
        signature = None
        if identity is not None:
            signature = identity.sign(graph_hash.encode("utf-8"))

        with locked_path(self.store_dir):
            history = self._load_history()
            resolved_branch = branch or self.current_branch()
            resolved_parent = parent_id if parent_id is not None else self._read_ref(resolved_branch)
            timestamp = datetime.now(timezone.utc).isoformat()
            resolved_merge_parents = list(merge_parent_ids or [])
            version_id = self.derive_version_id(
                graph_hash=graph_hash,
                parent_id=resolved_parent,
                merge_parent_ids=resolved_merge_parents,
                branch=resolved_branch,
                timestamp=timestamp,
                source=source,
                message=message,
            )

            # Save snapshot
            snapshot_path = self.versions_dir / f"{version_id}.json"
            atomic_write_text(snapshot_path, json.dumps(graph_data, indent=2))

            # Create version record
            version = ContextVersion(
                version_id=version_id,
                parent_id=resolved_parent,
                merge_parent_ids=resolved_merge_parents,
                timestamp=timestamp,
                branch=resolved_branch,
                source=source,
                message=message,
                graph_hash=graph_hash,
                node_count=len(graph.nodes),
                edge_count=len(graph.edges),
                signature=signature,
                chain_hash_version=CHAIN_HASH_VERSION,
            )

            # Append to history
            history.append(version.to_dict())
            self._save_history(history)
            self._write_ref(resolved_branch, version_id)

        return version

    def _record_for_version(self, version_id: str) -> dict[str, Any] | None:
        history = self._load_history()
        return next((item for item in reversed(history) if item["version_id"] == version_id), None)

    def log(self, limit: int = 10, ref: str | None = None) -> list[ContextVersion]:
        """Return recent versions from history.json, newest first."""
        history = self._load_history()
        if ref:
            version_id = self.resolve_ref(ref)
            if version_id is None:
                return []
            history_by_id = {item["version_id"]: item for item in history}
            recent: list[dict] = []
            seen: set[str] = set()
            current = version_id
            while current and current not in seen:
                seen.add(current)
                record = history_by_id.get(current)
                if record is None:
                    break
                recent.append(record)
                current = record.get("parent_id")
            if limit > 0:
                recent = recent[:limit]
            return [ContextVersion.from_dict(d) for d in recent]

        recent = history[-limit:] if limit > 0 else history
        recent.reverse()
        return [ContextVersion.from_dict(d) for d in recent]

    def diff(self, version_id_a: str, version_id_b: str) -> dict:
        """Compare two versions: added/removed/modified nodes, including temporal fields."""
        graph_a = self.checkout(version_id_a)
        graph_b = self.checkout(version_id_b)

        ids_a = set(graph_a.nodes.keys())
        ids_b = set(graph_b.nodes.keys())

        added = ids_b - ids_a
        removed = ids_a - ids_b
        shared = ids_a & ids_b

        modified = []
        for nid in shared:
            node_a = graph_a.nodes[nid]
            node_b = graph_b.nodes[nid]
            changes = {}
            if node_a.confidence != node_b.confidence:
                changes["confidence"] = {
                    "from": node_a.confidence,
                    "to": node_b.confidence,
                }
            if sorted(node_a.tags) != sorted(node_b.tags):
                changes["tags"] = {
                    "from": sorted(node_a.tags),
                    "to": sorted(node_b.tags),
                }
            if node_a.label != node_b.label:
                changes["label"] = {"from": node_a.label, "to": node_b.label}
            if getattr(node_a, "status", "") != getattr(node_b, "status", ""):
                changes["status"] = {"from": getattr(node_a, "status", ""), "to": getattr(node_b, "status", "")}
            if getattr(node_a, "valid_from", "") != getattr(node_b, "valid_from", ""):
                changes["valid_from"] = {
                    "from": getattr(node_a, "valid_from", ""),
                    "to": getattr(node_b, "valid_from", ""),
                }
            if getattr(node_a, "valid_to", "") != getattr(node_b, "valid_to", ""):
                changes["valid_to"] = {"from": getattr(node_a, "valid_to", ""), "to": getattr(node_b, "valid_to", "")}
            if changes:
                modified.append({"node_id": nid, "changes": changes})

        semantic = semantic_diff_graphs(graph_a, graph_b)
        return {
            "added": sorted(added),
            "removed": sorted(removed),
            "modified": modified,
            "semantic_changes": semantic["changes"],
            "semantic_summary": semantic["summary"],
        }

    def checkout(self, version_id: str, verify: bool = True) -> CortexGraph:
        """Load a specific version's graph snapshot.

        If verify=True, checks the integrity hash from history against the
        loaded data. Raises ValueError on mismatch.
        """
        snapshot_path = self.versions_dir / f"{version_id}.json"
        if not snapshot_path.exists():
            raise FileNotFoundError(f"Version {version_id} not found")
        raw_text = snapshot_path.read_text()
        data = json.loads(raw_text)

        # Verify integrity hash against history record (#6)
        if verify:
            history = self._load_history()
            record = next((h for h in history if h["version_id"] == version_id), None)
            if record and record.get("graph_hash"):
                graph_json = json.dumps(data, sort_keys=True, ensure_ascii=False)
                actual_hash = hashlib.sha256(graph_json.encode("utf-8")).hexdigest()
                if actual_hash != record["graph_hash"]:
                    raise ValueError(
                        f"Integrity check failed for version {version_id}: "
                        f"expected {record['graph_hash'][:16]}..., "
                        f"got {actual_hash[:16]}..."
                    )

        return CortexGraph.from_v5_json(data)

    def head(self, ref: str = "HEAD") -> ContextVersion | None:
        """Return the latest version for a ref, or None if no history."""
        resolved = self.resolve_ref(ref)
        if resolved is None:
            return None
        record = self._record_for_version(resolved)
        if record is None:
            return None
        return ContextVersion.from_dict(record)

    def list_branches(self) -> list[dict[str, Any]]:
        self._bootstrap_refs()
        current = self.current_branch()
        branches: list[dict[str, Any]] = []
        for path in sorted(self.heads_dir.rglob("*")):
            if not path.is_file():
                continue
            name = path.relative_to(self.heads_dir).as_posix()
            head = path.read_text().strip() or None
            branches.append({"name": name, "head": head, "current": name == current})
        return branches

    def create_branch(self, branch: str, from_ref: str = "HEAD", switch: bool = False) -> str | None:
        self._bootstrap_refs()
        with locked_path(self.store_dir):
            path = self._branch_path(branch)
            if path.exists():
                raise ValueError(f"Branch already exists: {branch}")
            start = self.resolve_ref(from_ref)
            self._write_ref(branch, start)
            if switch:
                self.switch_branch(branch)
            return start

    def switch_branch(self, branch: str) -> str | None:
        self._bootstrap_refs()
        path = self._branch_path(branch)
        if not path.exists():
            raise ValueError(f"Branch not found: {branch}")
        with locked_path(self.store_dir):
            atomic_write_text(self.head_path, f"ref: refs/heads/{branch}")
        return self._read_ref(branch)

    def resolve_version_id(self, prefix: str) -> str | None:
        """Resolve a full or unique-prefix version ID from history."""
        history = self._load_history()
        matches = [item["version_id"] for item in history if item.get("version_id", "").startswith(prefix)]
        if len(matches) == 1:
            return matches[0]
        if prefix in matches:
            return prefix
        return None

    def resolve_ref(self, ref: str) -> str | None:
        self._bootstrap_refs()
        if ref == "HEAD":
            return self._read_ref(self.current_branch())
        if ref.startswith("refs/heads/"):
            return self._read_ref(ref[len("refs/heads/") :])
        branch_match = self._read_ref(ref)
        if branch_match is not None:
            return branch_match
        return self.resolve_version_id(ref)

    def resolve_at(self, timestamp: str, ref: str | None = None) -> str | None:
        """Resolve the latest version at or before an ISO timestamp."""
        try:
            target = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None

        if ref:
            records = [ContextVersion.from_dict(item) for item in self.lineage_records(ref)]
        else:
            records = [ContextVersion.from_dict(item) for item in self._load_history()]

        best: ContextVersion | None = None
        for record in records:
            try:
                record_ts = datetime.fromisoformat(record.timestamp.replace("Z", "+00:00"))
            except ValueError:
                continue
            if record_ts <= target and (
                best is None or record_ts > datetime.fromisoformat(best.timestamp.replace("Z", "+00:00"))
            ):
                best = record
        return best.version_id if best is not None else None

    def is_ancestor(self, ancestor_ref: str, descendant_ref: str) -> bool:
        ancestor = self.resolve_ref(ancestor_ref)
        descendant = self.resolve_ref(descendant_ref)
        if ancestor is None or descendant is None:
            return False
        if ancestor == descendant:
            return True
        return ancestor in self._ancestry_ids(descendant)

    def lineage_records(self, ref: str) -> list[dict[str, Any]]:
        resolved = self.resolve_ref(ref)
        if resolved is None:
            return []
        needed = set(self._ancestry_ids(resolved))
        return [dict(item) for item in self._load_history() if item["version_id"] in needed]

    def merge_base(self, ref_a: str, ref_b: str) -> str | None:
        """Return the nearest shared ancestor version id for two refs."""
        start_a = self.resolve_ref(ref_a)
        start_b = self.resolve_ref(ref_b)
        if not start_a or not start_b:
            return None
        if start_a == start_b:
            return start_a

        def _ancestor_distances(start: str) -> dict[str, int]:
            distances: dict[str, int] = {}
            queue: deque[tuple[str, int]] = deque([(start, 0)])
            while queue:
                version_id, distance = queue.popleft()
                if version_id in distances and distances[version_id] <= distance:
                    continue
                distances[version_id] = distance
                record = self._record_for_version(version_id)
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
        """Trace where a node appeared and changed across stored versions."""
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

            signature = json.dumps(
                {
                    "label": matched.label,
                    "aliases": sorted(matched.aliases),
                    "tags": sorted(matched.tags),
                    "confidence": round(matched.confidence, 4),
                    "status": matched.status,
                    "valid_from": matched.valid_from,
                    "valid_to": matched.valid_to,
                    "sources": sorted({*provenance_sources, *snapshot_sources}),
                },
                sort_keys=True,
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
                if getattr(node, "canonical_id", "") == canonical_id:
                    return node

        search_terms = {_normalize_label(term) for term in [label, *aliases] if term}
        if not search_terms:
            return None

        for node in graph.nodes.values():
            node_terms = {_normalize_label(node.label), *(_normalize_label(alias) for alias in node.aliases)}
            if search_terms & node_terms:
                return node
        return None
