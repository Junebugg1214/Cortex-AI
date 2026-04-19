"""Stable source registry and lineage helpers for Cortex."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from cortex.atomic_io import atomic_write_json, locked_path
from cortex.graph.graph import CortexGraph


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_source_label(label: str) -> str:
    """Normalize a human source label for case-insensitive matching."""
    return " ".join(str(label).strip().lower().split())


def normalize_source_content(data: bytes) -> bytes:
    """Normalize text-like content before hashing while preserving binary data."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    normalized_lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    normalized_text = "\n".join(normalized_lines).strip()
    return normalized_text.encode("utf-8")


def stable_source_id_for_bytes(data: bytes) -> str:
    """Return the canonical content-addressed source id."""
    return hashlib.sha256(normalize_source_content(data)).hexdigest()


def source_registry_path(store_dir: Path) -> Path:
    """Return the global source registry path for a Cortex store."""
    return Path(store_dir) / "sources.json"


class SourceRegistryError(RuntimeError):
    """Base class for source registry failures."""


class DuplicateSourceError(SourceRegistryError):
    """Raised when content is already known and re-ingest was not forced."""


class AmbiguousSourceLabelError(SourceRegistryError):
    """Raised when a human label resolves to multiple stable source ids."""


class SourceResolutionError(SourceRegistryError):
    """Raised when a source identifier cannot be resolved."""


@dataclass(slots=True)
class SourceRecord:
    """Persisted source registry record."""

    stable_id: str
    labels: list[str] = field(default_factory=list)
    content_sha256: str = ""
    first_seen_at: str = field(default_factory=_iso_now)
    updated_at: str = field(default_factory=_iso_now)
    ingest_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SourceRecord":
        return cls(
            stable_id=str(payload.get("stable_id") or ""),
            labels=[str(item) for item in payload.get("labels", []) if str(item).strip()],
            content_sha256=str(payload.get("content_sha256") or ""),
            first_seen_at=str(payload.get("first_seen_at") or _iso_now()),
            updated_at=str(payload.get("updated_at") or _iso_now()),
            ingest_count=int(payload.get("ingest_count", 0) or 0),
            metadata=dict(payload.get("metadata") or {}),
        )


class SourceRegistry:
    """Content-addressed source registry with human label aliases."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @classmethod
    def for_store(cls, store_dir: Path) -> "SourceRegistry":
        """Create a registry rooted in *store_dir*."""
        return cls(source_registry_path(store_dir))

    def _load_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"records": {}, "labels": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save_payload(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with locked_path(self.path):
            atomic_write_json(self.path, payload)

    def list_records(self, *, stable_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """List registry records, optionally filtered to specific stable ids."""
        payload = self._load_payload()
        allowed = {str(item) for item in stable_ids} if stable_ids is not None else None
        records: list[dict[str, Any]] = []
        for stable_id, raw in sorted(payload.get("records", {}).items()):
            if allowed is not None and stable_id not in allowed:
                continue
            record = SourceRecord.from_dict(raw)
            records.append(record.to_dict())
        return records

    def register_bytes(
        self,
        data: bytes,
        *,
        label: str,
        metadata: dict[str, Any] | None = None,
        force_reingest: bool = False,
    ) -> dict[str, Any]:
        """Register source content and return the canonical record."""
        cleaned_label = str(label).strip()
        if not cleaned_label:
            raise SourceRegistryError("Source label is required.")
        stable_id = stable_source_id_for_bytes(data)
        norm_label = normalize_source_label(cleaned_label)
        payload = self._load_payload()
        records = dict(payload.get("records") or {})
        labels = {str(key): [str(item) for item in value] for key, value in (payload.get("labels") or {}).items()}
        now = _iso_now()
        existing = records.get(stable_id)
        duplicate = existing is not None

        if existing is None:
            record = SourceRecord(
                stable_id=stable_id,
                labels=[cleaned_label],
                content_sha256=stable_id,
                first_seen_at=now,
                updated_at=now,
                ingest_count=1,
                metadata=dict(metadata or {}),
            )
        else:
            record = SourceRecord.from_dict(existing)
            if not force_reingest:
                existing_labels = ", ".join(record.labels)
                raise DuplicateSourceError(
                    f"Source content already exists as {stable_id} under label(s): {existing_labels}. "
                    "Re-run with force_reingest=True to record a duplicate ingest intentionally."
                )
            if cleaned_label not in record.labels:
                record.labels.append(cleaned_label)
            record.updated_at = now
            record.ingest_count += 1
            merged_metadata = dict(record.metadata)
            merged_metadata.update(dict(metadata or {}))
            record.metadata = merged_metadata

        label_ids = list(dict.fromkeys(labels.get(norm_label, []) + [stable_id]))
        labels[norm_label] = label_ids
        records[stable_id] = record.to_dict()
        self._save_payload({"records": records, "labels": labels})

        return {
            "stable_id": stable_id,
            "labels": list(record.labels),
            "duplicate": duplicate,
            "forced": bool(force_reingest),
            "record": record.to_dict(),
        }

    def register_path(
        self,
        path: Path,
        *,
        label: str = "",
        metadata: dict[str, Any] | None = None,
        force_reingest: bool = False,
    ) -> dict[str, Any]:
        """Register a file path as a source."""
        source_path = Path(path)
        return self.register_bytes(
            source_path.read_bytes(),
            label=label or source_path.name,
            metadata={"path": str(source_path), **dict(metadata or {})},
            force_reingest=force_reingest,
        )

    def resolve(
        self,
        identifier: str,
        *,
        allowed_ids: set[str] | None = None,
    ) -> SourceRecord:
        """Resolve a stable id or human label to a single canonical record."""
        cleaned = str(identifier).strip()
        if not cleaned:
            raise SourceResolutionError("Source identifier is required.")
        payload = self._load_payload()
        records = dict(payload.get("records") or {})
        if cleaned in records:
            return SourceRecord.from_dict(records[cleaned])

        label_ids = list((payload.get("labels") or {}).get(normalize_source_label(cleaned), []))
        if allowed_ids is not None:
            label_ids = [stable_id for stable_id in label_ids if stable_id in allowed_ids]
        if not label_ids:
            raise SourceResolutionError(f"Unknown source identifier: {cleaned}")
        unique_ids = sorted(dict.fromkeys(label_ids))
        if len(unique_ids) > 1:
            raise AmbiguousSourceLabelError(
                f"Source label '{cleaned}' is ambiguous; matching stable ids: {', '.join(unique_ids)}"
            )
        stable_id = unique_ids[0]
        raw = records.get(stable_id)
        if raw is None:
            raise SourceResolutionError(f"Source id '{stable_id}' is missing from the registry.")
        return SourceRecord.from_dict(raw)


def graph_source_ids(graph: CortexGraph) -> set[str]:
    """Return the set of canonical source ids referenced in a graph."""
    source_ids: set[str] = set()
    for node in graph.nodes.values():
        for item in list(node.provenance) + list(node.snapshots):
            source_id = str(item.get("source_id") or item.get("source") or "").strip()
            if source_id:
                source_ids.add(source_id)
    for edge in graph.edges.values():
        for item in edge.provenance:
            source_id = str(item.get("source_id") or item.get("source") or "").strip()
            if source_id:
                source_ids.add(source_id)
    return source_ids


def attach_stable_source(
    entries: list[dict[str, Any]],
    *,
    stable_id: str,
    label: str,
    method: str,
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Append a canonical lineage entry unless it already exists."""
    payload = {
        "source": stable_id,
        "source_id": stable_id,
        "source_label": label,
        "method": method,
        **dict(extra or {}),
    }
    if payload not in entries:
        entries.append(payload)
    return entries


__all__ = [
    "AmbiguousSourceLabelError",
    "DuplicateSourceError",
    "SourceRecord",
    "SourceRegistry",
    "SourceRegistryError",
    "SourceResolutionError",
    "attach_stable_source",
    "graph_source_ids",
    "normalize_source_content",
    "normalize_source_label",
    "source_registry_path",
    "stable_source_id_for_bytes",
]
