from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path
from typing import Any

from cortex.extraction.sources import DuplicateSourceError, SourceRegistry
from cortex.graph.graph import make_node_id
from cortex.packs import (
    _iso_now,
    _read_json,
    _read_text_if_possible,
    _replace_manifest,
    _safe_stem,
    _unique_destination,
    _validate_pack_name,
    _write_json,
    pack_path,
    source_index_path,
)
from cortex.security.secrets import CortexIgnore
from cortex.security.validate import InputValidator

_INPUT_VALIDATOR = InputValidator()


def _iter_source_files(path: Path, *, recurse: bool) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(path)
    if recurse:
        return sorted(item for item in path.rglob("*") if item.is_file())
    return sorted(item for item in path.iterdir() if item.is_file())


def _source_type_for(path: Path, override: str) -> str:
    if override != "auto":
        return override
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        return "image"
    if suffix in {".csv", ".tsv", ".parquet"}:
        return "dataset"
    if suffix in {".md", ".txt", ".rst"}:
        return "note"
    if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs"}:
        return "repo"
    return "article"


def ingest_pack(
    store_dir: Path,
    name: str,
    paths: list[str],
    *,
    mode: str = "copy",
    source_type: str = "auto",
    recurse: bool = False,
    force_reingest: bool = False,
) -> dict[str, Any]:
    pack_name = _validate_pack_name(name)
    root = pack_path(store_dir, pack_name)
    if not root.exists():
        raise FileNotFoundError(f"Brainpack '{pack_name}' does not exist.")
    raw_root = root / "raw"
    registry = SourceRegistry.for_store(store_dir)
    ignore = CortexIgnore.discover()
    index_payload = _read_json(source_index_path(store_dir, pack_name), default={"pack": pack_name, "sources": []})
    existing = {str(item["source_path"]): dict(item) for item in index_payload.get("sources", [])}
    ingested: list[dict[str, Any]] = []
    ignored: list[str] = []
    for raw_input in paths:
        source = _INPUT_VALIDATOR.validate_path(raw_input, field_name="ingest source path")
        input_root = source if source.is_dir() else source.parent
        for item in _iter_source_files(source, recurse=recurse):
            if ignore.matches(item):
                ignored.append(str(item))
                continue
            stored_path = ""
            if mode == "copy":
                relative = item.relative_to(input_root) if source.is_dir() else Path(item.name)
                if source.is_dir():
                    relative = Path(_safe_stem(source)) / relative
                destination = _unique_destination(raw_root, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, destination)
                stored_path = str(destination.relative_to(root))
            try:
                registry_payload = registry.register_path(
                    item,
                    label=item.name,
                    metadata={"pack": pack_name, "path": str(item)},
                    force_reingest=True if mode == "copy" else force_reingest,
                )
            except DuplicateSourceError as exc:
                raise ValueError(str(exc)) from exc
            text_preview, text_eligible = _read_text_if_possible(item)
            record = {
                "id": make_node_id(f"{pack_name}:{item}"),
                "source_path": str(item),
                "stored_path": stored_path,
                "source_id": registry_payload["stable_id"],
                "source_labels": list(registry_payload["labels"]),
                "mode": mode,
                "type": _source_type_for(item, source_type),
                "mime_type": mimetypes.guess_type(item.name)[0] or "",
                "size_bytes": item.stat().st_size,
                "ingested_at": _iso_now(),
                "text_eligible": text_eligible,
                "preview": " ".join(text_preview.strip().split())[:240] if text_preview else "",
                "duplicate": bool(registry_payload["duplicate"]),
            }
            existing[str(item)] = record
            ingested.append(record)

    payload = {"pack": pack_name, "sources": sorted(existing.values(), key=lambda item: item["source_path"])}
    _write_json(source_index_path(store_dir, pack_name), payload)
    _replace_manifest(store_dir, pack_name, updated_at=_iso_now())
    return {
        "status": "ok",
        "pack": pack_name,
        "mode": mode,
        "ingested": ingested,
        "ignored": ignored,
        "ingested_count": len(ingested),
        "source_count": len(payload["sources"]),
    }
