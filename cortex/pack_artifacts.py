from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cortex.graph.graph import make_node_id
from cortex.packs import (
    _artifacts_root,
    _compact_summary,
    _iso_now,
    _read_json,
    _read_text_if_possible,
    _replace_manifest,
    _require_pack_namespace,
    _write_json,
    compile_meta_path,
    load_manifest,
    pack_path,
)


def _list_artifact_records(store_dir: Path, name: str) -> list[dict[str, Any]]:
    root = _artifacts_root(store_dir, name)
    records: list[dict[str, Any]] = []
    if not root.exists():
        return records
    pack_root = pack_path(store_dir, name)
    for item in sorted(root.rglob("*")):
        if not item.is_file():
            continue
        text, readable = _read_text_if_possible(item)
        relative_path = item.relative_to(pack_root)
        preview = _compact_summary(text, limit=280) if readable and text.strip() else ""
        records.append(
            {
                "id": make_node_id(f"{name}:artifact:{relative_path.as_posix()}"),
                "path": str(relative_path),
                "title": item.stem.replace("-", " ").replace("_", " ").title(),
                "preview": preview,
                "readable": readable,
                "size_bytes": item.stat().st_size,
                "updated_at": datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return records


def _refresh_artifact_count(store_dir: Path, name: str) -> int:
    count = sum(1 for path in _artifacts_root(store_dir, name).rglob("*") if path.is_file())
    meta = _read_json(
        compile_meta_path(store_dir, name),
        default={
            "pack": name,
            "compile_status": "idle",
            "compiled_at": "",
            "source_count": 0,
            "text_source_count": 0,
            "graph_nodes": 0,
            "graph_edges": 0,
            "article_count": 0,
            "claim_count": 0,
            "unknown_count": 0,
            "artifact_count": 0,
        },
    )
    meta["artifact_count"] = count
    _write_json(compile_meta_path(store_dir, name), meta)
    _replace_manifest(store_dir, name, updated_at=_iso_now())
    return count


def pack_artifacts(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
    artifacts = _list_artifact_records(store_dir, name)
    return {
        "status": "ok",
        "pack": manifest.name,
        "namespace": manifest.namespace,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }
