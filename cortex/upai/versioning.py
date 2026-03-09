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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from cortex.graph import CortexGraph

if TYPE_CHECKING:
    from cortex.upai.identity import UPAIIdentity


@dataclass
class ContextVersion:
    version_id: str  # SHA-256 of serialized graph
    parent_id: str | None  # previous version (None for initial)
    timestamp: str  # ISO-8601
    source: str  # "extraction", "merge", "manual"
    message: str  # commit message
    graph_hash: str  # SHA-256 integrity hash
    node_count: int
    edge_count: int
    signature: str | None  # Ed25519/HMAC signature of graph_hash (if identity available)

    def to_dict(self) -> dict:
        return {
            "version_id": self.version_id,
            "parent_id": self.parent_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "message": self.message,
            "graph_hash": self.graph_hash,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ContextVersion:
        return cls(
            version_id=d["version_id"],
            parent_id=d.get("parent_id"),
            timestamp=d["timestamp"],
            source=d["source"],
            message=d["message"],
            graph_hash=d["graph_hash"],
            node_count=d["node_count"],
            edge_count=d["edge_count"],
            signature=d.get("signature"),
        )


class VersionStore:
    """Git-like version store for CortexGraph snapshots."""

    def __init__(self, store_dir: Path) -> None:
        self.store_dir = store_dir
        self.versions_dir = store_dir / "versions"
        self.history_path = store_dir / "history.json"

    def _ensure_dirs(self) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    def _load_history(self) -> list[dict]:
        if self.history_path.exists():
            return json.loads(self.history_path.read_text())
        return []

    def _save_history(self, history: list[dict]) -> None:
        self._ensure_dirs()
        self.history_path.write_text(json.dumps(history, indent=2))

    def commit(
        self,
        graph: CortexGraph,
        message: str,
        source: str = "manual",
        identity: UPAIIdentity | None = None,
    ) -> ContextVersion:
        """Serialize graph, hash, optionally sign, save snapshot, append to history."""
        self._ensure_dirs()

        # Serialize graph
        graph_data = graph.export_v5()
        graph_json = json.dumps(graph_data, sort_keys=True, ensure_ascii=False)
        graph_bytes = graph_json.encode("utf-8")

        # Hash
        graph_hash = hashlib.sha256(graph_bytes).hexdigest()
        version_id = graph_hash[:32]

        # Determine parent
        history = self._load_history()
        parent_id = history[-1]["version_id"] if history else None

        # Sign if identity available
        signature = None
        if identity is not None:
            signature = identity.sign(graph_hash.encode("utf-8"))

        # Save snapshot
        snapshot_path = self.versions_dir / f"{version_id}.json"
        snapshot_path.write_text(json.dumps(graph_data, indent=2))

        # Create version record
        version = ContextVersion(
            version_id=version_id,
            parent_id=parent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            source=source,
            message=message,
            graph_hash=graph_hash,
            node_count=len(graph.nodes),
            edge_count=len(graph.edges),
            signature=signature,
        )

        # Append to history
        history.append(version.to_dict())
        self._save_history(history)

        return version

    def log(self, limit: int = 10) -> list[ContextVersion]:
        """Return recent versions from history.json, newest first."""
        history = self._load_history()
        recent = history[-limit:] if limit > 0 else history
        recent.reverse()
        return [ContextVersion.from_dict(d) for d in recent]

    def diff(self, version_id_a: str, version_id_b: str) -> dict:
        """Compare two versions: added/removed/modified nodes, confidence/tag changes."""
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
            if changes:
                modified.append({"node_id": nid, "changes": changes})

        return {
            "added": sorted(added),
            "removed": sorted(removed),
            "modified": modified,
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

    def head(self) -> ContextVersion | None:
        """Return the latest version, or None if no history."""
        history = self._load_history()
        if not history:
            return None
        return ContextVersion.from_dict(history[-1])
