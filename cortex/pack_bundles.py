from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from cortex.namespaces import normalize_resource_namespace
from cortex.packs import (
    BRAINPACK_BUNDLE_FORMAT_VERSION,
    BRAINPACK_BUNDLE_MANIFEST,
    BRAINPACK_BUNDLE_PREFIX,
    SKIP_NAMES,
    BrainpackManifest,
    _iso_now,
    _load_manifest_from_root,
    _read_json,
    _require_pack_namespace,
    _safe_stem,
    _sha256_bytes,
    _sha256_file,
    _unique_destination,
    _validate_pack_name,
    _write_json,
    _write_manifest,
    load_manifest,
    pack_path,
)


def _iter_pack_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in SKIP_NAMES or path.name.endswith(".lock"):
            continue
        paths.append(path)
    return paths


def _rewrite_pack_name_metadata(root: Path, *, target_name: str) -> None:
    manifest = _load_manifest_from_root(root)
    renamed_manifest = BrainpackManifest(
        name=target_name,
        description=manifest.description,
        owner=manifest.owner,
        namespace=manifest.namespace,
        created_at=manifest.created_at,
        updated_at=_iso_now(),
        default_policy=manifest.default_policy,
        auto_backlink=manifest.auto_backlink,
        auto_promote_claims=manifest.auto_promote_claims,
        store_outputs=manifest.store_outputs,
        max_summary_chars=manifest.max_summary_chars,
        suggest_questions=manifest.suggest_questions,
        source_glob=manifest.source_glob,
        default_tags=manifest.default_tags,
    )
    _write_manifest(root / "manifest.toml", renamed_manifest)
    for relative in (
        Path("indexes") / "sources.json",
        Path("indexes") / "compile.json",
        Path("indexes") / "source_index.json",
        Path("claims") / "claims.json",
        Path("unknowns") / "open_questions.json",
        Path("indexes") / "lint.json",
    ):
        path = root / relative
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "pack" in payload:
            payload["pack"] = target_name
            _write_json(path, payload)


def _materialize_referenced_sources(bundle_root: Path) -> tuple[int, list[str]]:
    sources_index = bundle_root / "indexes" / "sources.json"
    compiled_index = bundle_root / "indexes" / "source_index.json"
    if not sources_index.exists():
        return 0, []

    ingest_payload = json.loads(sources_index.read_text(encoding="utf-8"))
    compiled_payload = (
        json.loads(compiled_index.read_text(encoding="utf-8")) if compiled_index.exists() else {"sources": []}
    )
    compiled_by_source = {
        str(item.get("source_path") or ""): dict(item)
        for item in compiled_payload.get("sources", [])
        if item.get("source_path")
    }
    materialized = 0
    missing: list[str] = []
    raw_root = bundle_root / "raw" / "bundled-references"
    raw_root.mkdir(parents=True, exist_ok=True)

    for record in ingest_payload.get("sources", []):
        if str(record.get("stored_path") or "").strip():
            continue
        source_path_value = str(record.get("source_path") or "").strip()
        if not source_path_value:
            continue
        source_path = Path(source_path_value)
        if not source_path.exists() or not source_path.is_file():
            missing.append(source_path_value)
            continue
        destination = _unique_destination(
            raw_root,
            Path(_safe_stem(source_path.parent)) / source_path.name,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        relative = destination.relative_to(bundle_root)
        record["stored_path"] = str(relative)
        record["mode"] = "copy"
        compiled_record = compiled_by_source.get(source_path_value)
        if compiled_record is not None:
            compiled_record["stored_path"] = str(relative)
            compiled_record["mode"] = "copy"
        materialized += 1

    _write_json(sources_index, ingest_payload)
    if compiled_index.exists():
        rewritten_sources = []
        for item in compiled_payload.get("sources", []):
            source_path_value = str(item.get("source_path") or "")
            rewritten_sources.append(compiled_by_source.get(source_path_value, item))
        compiled_payload["sources"] = rewritten_sources
        _write_json(compiled_index, compiled_payload)
    return materialized, missing


def _bundle_manifest_for_pack(bundle_root: Path, *, verification_warnings: list[str]) -> dict[str, Any]:
    manifest = _load_manifest_from_root(bundle_root)
    compile_meta = _read_json(
        bundle_root / "indexes" / "compile.json",
        default={
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
    files = _iter_pack_files(bundle_root)
    return {
        "format_version": BRAINPACK_BUNDLE_FORMAT_VERSION,
        "created_at": _iso_now(),
        "pack_name": manifest.name,
        "manifest": {
            "name": manifest.name,
            "description": manifest.description,
            "owner": manifest.owner,
            "default_policy": manifest.default_policy,
            "created_at": manifest.created_at,
            "updated_at": manifest.updated_at,
        },
        "compile_status": str(compile_meta.get("compile_status") or "idle"),
        "compiled_at": str(compile_meta.get("compiled_at") or ""),
        "file_count": len(files),
        "verification_warnings": verification_warnings,
        "files": [
            {
                "path": str(path.relative_to(bundle_root)),
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
            for path in files
        ],
    }


def _read_pack_bundle_manifest(archive_path: str | Path) -> dict[str, Any]:
    path = Path(archive_path)
    if not path.exists():
        raise FileNotFoundError(f"Brainpack bundle not found: {path}")
    with ZipFile(path, "r") as archive:
        try:
            payload = json.loads(archive.read(BRAINPACK_BUNDLE_MANIFEST).decode("utf-8"))
        except KeyError as exc:
            raise ValueError(f"Brainpack bundle is missing {BRAINPACK_BUNDLE_MANIFEST}: {path}") from exc
    if str(payload.get("format_version") or "") != BRAINPACK_BUNDLE_FORMAT_VERSION:
        raise ValueError(
            f"Unsupported Brainpack bundle format: {payload.get('format_version') or 'unknown'} for {path}"
        )
    if not str(payload.get("pack_name") or "").strip():
        raise ValueError(f"Brainpack bundle is missing a pack_name: {path}")
    return payload


def _safe_bundle_members(archive: ZipFile) -> list[tuple[str, PurePosixPath]]:
    members: list[tuple[str, PurePosixPath]] = []
    for info in archive.infolist():
        name = info.filename
        if name == BRAINPACK_BUNDLE_MANIFEST:
            continue
        if not name.startswith(BRAINPACK_BUNDLE_PREFIX):
            raise ValueError(f"Brainpack bundle contains unexpected entry outside '{BRAINPACK_BUNDLE_PREFIX}': {name}")
        if info.is_dir():
            continue
        relative = PurePosixPath(name[len(BRAINPACK_BUNDLE_PREFIX) :])
        parts = [part for part in relative.parts if part not in ("", ".")]
        if not parts:
            continue
        if any(part == ".." for part in parts):
            raise ValueError(f"Brainpack bundle contains unsafe path traversal entry: {name}")
        members.append((name, PurePosixPath(*parts)))
    return members


def verify_pack_bundle(archive_path: str | Path) -> dict[str, Any]:
    path = Path(archive_path)
    manifest = _read_pack_bundle_manifest(path)
    with ZipFile(path, "r") as archive:
        members = _safe_bundle_members(archive)
        mismatches: list[dict[str, Any]] = []
        actual_paths = {str(relative_path.as_posix()) for _, relative_path in members}
        expected_paths = {str(item["path"]) for item in manifest.get("files", [])}
        for missing in sorted(expected_paths - actual_paths):
            mismatches.append({"path": missing, "reason": "missing"})
        for extra in sorted(actual_paths - expected_paths):
            mismatches.append({"path": extra, "reason": "unexpected"})
        for item in manifest.get("files", []):
            if str(item["path"]) not in actual_paths:
                continue
            archive_name = f"{BRAINPACK_BUNDLE_PREFIX}{item['path']}"
            try:
                payload = archive.read(archive_name)
            except KeyError:
                mismatches.append({"path": item["path"], "reason": "missing"})
                continue
            actual_hash = _sha256_bytes(payload)
            if actual_hash != item["sha256"]:
                mismatches.append(
                    {
                        "path": item["path"],
                        "reason": "sha256_mismatch",
                        "expected": item["sha256"],
                        "actual": actual_hash,
                    }
                )
            if len(payload) != int(item["size"]):
                mismatches.append(
                    {
                        "path": item["path"],
                        "reason": "size_mismatch",
                        "expected": int(item["size"]),
                        "actual": len(payload),
                    }
                )
    return {
        "status": "ok",
        "archive": str(path),
        "valid": not mismatches,
        "pack": str(manifest.get("pack_name") or ""),
        "file_count": int(manifest.get("file_count") or len(manifest.get("files", []))),
        "mismatches": mismatches,
        "warnings": list(manifest.get("verification_warnings") or []),
    }


def export_pack_bundle(
    store_dir: Path,
    name: str,
    output_path: str | Path,
    *,
    verify: bool = True,
    namespace: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
    source_root = pack_path(store_dir, name)
    destination = Path(output_path)
    if destination.exists() and destination.is_dir():
        destination = destination / f"{manifest.name}.brainpack.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="cortex_brainpack_export_") as tmp_dir:
        bundle_root = Path(tmp_dir) / manifest.name
        shutil.copytree(source_root, bundle_root)
        materialized_reference_sources, missing_reference_sources = _materialize_referenced_sources(bundle_root)
        bundle_manifest = _bundle_manifest_for_pack(
            bundle_root,
            verification_warnings=missing_reference_sources,
        )
        with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr(BRAINPACK_BUNDLE_MANIFEST, json.dumps(bundle_manifest, indent=2, ensure_ascii=False))
            for item in bundle_manifest["files"]:
                archive.write(bundle_root / item["path"], arcname=f"{BRAINPACK_BUNDLE_PREFIX}{item['path']}")

    verification = verify_pack_bundle(destination) if verify else None
    if verification is not None and not verification["valid"]:
        raise ValueError(f"Brainpack bundle verification failed for {destination}")
    return {
        "status": "ok",
        "pack": manifest.name,
        "archive": str(destination),
        "file_count": int(bundle_manifest["file_count"]),
        "materialized_reference_sources": materialized_reference_sources,
        "missing_reference_sources": missing_reference_sources,
        "verified": verification["valid"] if verification is not None else False,
        "verification": verification,
    }


def import_pack_bundle(
    archive_path: str | Path,
    store_dir: Path,
    *,
    as_name: str = "",
    namespace: str | None = None,
) -> dict[str, Any]:
    archive = Path(archive_path)
    manifest = _read_pack_bundle_manifest(archive)
    verification = verify_pack_bundle(archive)
    if not verification["valid"]:
        raise ValueError(f"Brainpack bundle verification failed for {archive}")

    bundle_name = _validate_pack_name(str(manifest.get("pack_name") or ""))
    target_name = _validate_pack_name(as_name) if as_name else bundle_name
    destination = pack_path(store_dir, target_name)
    if destination.exists():
        raise FileExistsError(
            f"Brainpack '{target_name}' already exists. Choose a different name with `--as` or remove the existing pack."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="cortex_brainpack_import_") as tmp_dir:
        tmp_root = Path(tmp_dir) / bundle_name
        with ZipFile(archive, "r") as zip_archive:
            members = _safe_bundle_members(zip_archive)
            for archive_name, relative_path in members:
                target = tmp_root / Path(relative_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zip_archive.read(archive_name))
        if not (tmp_root / "manifest.toml").exists():
            raise ValueError(f"Brainpack bundle is missing manifest.toml content: {archive}")
        if target_name != bundle_name:
            renamed_root = tmp_root.parent / target_name
            tmp_root.rename(renamed_root)
            tmp_root = renamed_root
            _rewrite_pack_name_metadata(tmp_root, target_name=target_name)
        if namespace:
            manifest_payload = _load_manifest_from_root(tmp_root)
            namespaced_manifest = BrainpackManifest(
                name=manifest_payload.name,
                description=manifest_payload.description,
                owner=manifest_payload.owner,
                namespace=normalize_resource_namespace(namespace),
                created_at=manifest_payload.created_at,
                updated_at=_iso_now(),
                default_policy=manifest_payload.default_policy,
                auto_backlink=manifest_payload.auto_backlink,
                auto_promote_claims=manifest_payload.auto_promote_claims,
                store_outputs=manifest_payload.store_outputs,
                max_summary_chars=manifest_payload.max_summary_chars,
                suggest_questions=manifest_payload.suggest_questions,
                source_glob=manifest_payload.source_glob,
                default_tags=manifest_payload.default_tags,
            )
            _write_manifest(tmp_root / "manifest.toml", namespaced_manifest)
        shutil.copytree(tmp_root, destination)

    from cortex.packs import pack_status

    status = pack_status(store_dir, target_name, namespace=namespace)
    return {
        "status": "ok",
        "archive": str(archive),
        "pack": target_name,
        "original_pack": bundle_name,
        "path": str(destination),
        "verified": verification["valid"],
        "verification": verification,
        "source_count": status["source_count"],
        "artifact_count": status["artifact_count"],
        "compile_status": status["compile_status"],
    }
