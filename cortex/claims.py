from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cortex.graph import CortexGraph, Node, _normalize_label


def make_claim_id(
    *,
    canonical_id: str,
    label: str,
    tags: list[str],
    source: str,
    status: str,
    valid_from: str,
    valid_to: str,
) -> str:
    payload = json.dumps(
        {
            "canonical_id": canonical_id,
            "label": _normalize_label(label),
            "tags": sorted(tags),
            "source": source.strip(),
            "status": status.strip(),
            "valid_from": valid_from.strip(),
            "valid_to": valid_to.strip(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def make_claim_event_id(claim_id: str, op: str, timestamp: str, version_id: str) -> str:
    payload = f"{claim_id}:{op}:{timestamp}:{version_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class ClaimEvent:
    event_id: str
    claim_id: str
    op: str
    node_id: str
    canonical_id: str
    label: str
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    status: str = ""
    valid_from: str = ""
    valid_to: str = ""
    source: str = ""
    method: str = ""
    timestamp: str = ""
    version_id: str = ""
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "claim_id": self.claim_id,
            "op": self.op,
            "node_id": self.node_id,
            "canonical_id": self.canonical_id,
            "label": self.label,
            "aliases": list(self.aliases),
            "tags": list(self.tags),
            "confidence": self.confidence,
            "status": self.status,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "source": self.source,
            "method": self.method,
            "timestamp": self.timestamp,
            "version_id": self.version_id,
            "message": self.message,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClaimEvent:
        return cls(
            event_id=data["event_id"],
            claim_id=data["claim_id"],
            op=data["op"],
            node_id=data["node_id"],
            canonical_id=data.get("canonical_id", ""),
            label=data["label"],
            aliases=list(data.get("aliases", [])),
            tags=list(data.get("tags", [])),
            confidence=float(data.get("confidence", 0.0)),
            status=data.get("status", ""),
            valid_from=data.get("valid_from", ""),
            valid_to=data.get("valid_to", ""),
            source=data.get("source", ""),
            method=data.get("method", ""),
            timestamp=data.get("timestamp", ""),
            version_id=data.get("version_id", ""),
            message=data.get("message", ""),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def from_node(
        cls,
        node: Node,
        *,
        op: str,
        source: str,
        method: str,
        version_id: str = "",
        message: str = "",
        metadata: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> ClaimEvent:
        canonical_id = node.canonical_id or node.id
        claim_id = make_claim_id(
            canonical_id=canonical_id,
            label=node.label,
            tags=list(node.tags),
            source=source,
            status=node.status,
            valid_from=node.valid_from,
            valid_to=node.valid_to,
        )
        timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        return cls(
            event_id=make_claim_event_id(claim_id, op, timestamp, version_id),
            claim_id=claim_id,
            op=op,
            node_id=node.id,
            canonical_id=canonical_id,
            label=node.label,
            aliases=list(node.aliases),
            tags=list(node.tags),
            confidence=node.confidence,
            status=node.status,
            valid_from=node.valid_from,
            valid_to=node.valid_to,
            source=source,
            method=method,
            timestamp=timestamp,
            version_id=version_id,
            message=message,
            metadata=dict(metadata or {}),
        )


class ClaimLedger:
    def __init__(self, store_dir: Path) -> None:
        self.store_dir = store_dir
        self.path = store_dir / "claims.jsonl"

    def _ensure_dir(self) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def append(self, event: ClaimEvent) -> None:
        self._ensure_dir()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def list_events(
        self,
        *,
        claim_id: str = "",
        node_id: str = "",
        label: str = "",
        source: str = "",
        op: str = "",
        limit: int = 50,
    ) -> list[ClaimEvent]:
        events = self._load_all()
        label_norm = _normalize_label(label) if label else ""
        filtered: list[ClaimEvent] = []
        for event in reversed(events):
            if claim_id and event.claim_id != claim_id:
                continue
            if node_id and event.node_id != node_id:
                continue
            if label_norm:
                event_terms = {_normalize_label(event.label), *(_normalize_label(alias) for alias in event.aliases)}
                if label_norm not in event_terms:
                    continue
            if source and event.source != source:
                continue
            if op and event.op != op:
                continue
            filtered.append(event)
            if len(filtered) >= limit:
                break
        return filtered

    def get_claim(self, claim_id: str) -> list[ClaimEvent]:
        return [event for event in self._load_all() if event.claim_id == claim_id]

    def _load_all(self) -> list[ClaimEvent]:
        if not self.path.exists():
            return []
        events: list[ClaimEvent] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                events.append(ClaimEvent.from_dict(json.loads(raw)))
        return events


def extraction_source_label(input_path: Path) -> str:
    return f"extract:{input_path.name}"


def stamp_graph_provenance(
    graph: CortexGraph,
    *,
    source: str,
    method: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    metadata = dict(metadata or {})
    stamped = 0
    for node in graph.nodes.values():
        entry = {"source": source, "method": method, **metadata}
        if entry not in node.provenance:
            node.provenance.append(entry)
            stamped += 1
    return stamped


def record_graph_claims(
    graph: CortexGraph,
    ledger: ClaimLedger,
    *,
    op: str,
    source: str,
    method: str,
    version_id: str = "",
    message: str = "",
    metadata: dict[str, Any] | None = None,
) -> list[ClaimEvent]:
    events: list[ClaimEvent] = []
    for node in graph.nodes.values():
        event = ClaimEvent.from_node(
            node,
            op=op,
            source=source,
            method=method,
            version_id=version_id,
            message=message,
            metadata=metadata,
        )
        ledger.append(event)
        events.append(event)
    return events
