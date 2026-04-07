from __future__ import annotations

import json
import mimetypes
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11 fallback
    import tomli as tomllib

from cortex.compat import upgrade_v4_to_v5
from cortex.contradictions import ContradictionEngine
from cortex.dedup import find_duplicates, text_similarity
from cortex.extract_memory import AggressiveExtractor
from cortex.graph import CortexGraph, Edge, Node, make_edge_id, make_node_id
from cortex.hermes_integration import build_hermes_documents
from cortex.hooks import HookConfig, generate_compact_context
from cortex.import_memory import NormalizedContext, export_claude_memories, export_claude_preferences
from cortex.portability import PORTABLE_DIRECT_TARGETS, build_instruction_pack
from cortex.portable_runtime import _policy_for_target, canonical_target_name, display_name
from cortex.upai.disclosure import apply_disclosure

PACKS_DIRNAME = "packs"
BRAINPACK_BUNDLE_FORMAT_VERSION = "1"
BRAINPACK_BUNDLE_MANIFEST = "bundle_manifest.json"
BRAINPACK_BUNDLE_PREFIX = "pack/"
PACK_SUBDIRS = (
    "raw",
    "wiki",
    "graph",
    "claims",
    "unknowns",
    "artifacts",
    "indexes",
)
SKIP_NAMES = {".DS_Store"}
TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cfg",
    ".cpp",
    ".css",
    ".csv",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsonl",
    ".jsx",
    ".md",
    ".mdx",
    ".py",
    ".rb",
    ".rs",
    ".rst",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True, slots=True)
class BrainpackManifest:
    name: str
    description: str
    owner: str
    created_at: str
    updated_at: str
    default_policy: str = "research"
    auto_backlink: bool = True
    auto_promote_claims: bool = False
    store_outputs: bool = True
    max_summary_chars: int = 1200
    suggest_questions: bool = True
    source_glob: tuple[str, ...] = ("raw/**/*",)
    default_tags: tuple[str, ...] = (
        "domain_knowledge",
        "technical_expertise",
        "active_priorities",
        "relationships",
        "constraints",
    )


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _packs_root(store_dir: Path) -> Path:
    return Path(store_dir) / PACKS_DIRNAME


def _validate_pack_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Pack name is required.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,63}", cleaned):
        raise ValueError("Pack names must use letters, numbers, '.', '-', or '_' and start with an alphanumeric.")
    return cleaned


def pack_path(store_dir: Path, name: str) -> Path:
    return _packs_root(store_dir) / _validate_pack_name(name)


def manifest_path(store_dir: Path, name: str) -> Path:
    return pack_path(store_dir, name) / "manifest.toml"


def source_index_path(store_dir: Path, name: str) -> Path:
    return pack_path(store_dir, name) / "indexes" / "sources.json"


def compile_meta_path(store_dir: Path, name: str) -> Path:
    return pack_path(store_dir, name) / "indexes" / "compile.json"


def lint_report_path(store_dir: Path, name: str) -> Path:
    return pack_path(store_dir, name) / "indexes" / "lint.json"


def graph_path(store_dir: Path, name: str) -> Path:
    return pack_path(store_dir, name) / "graph" / "brainpack.graph.json"


def claims_path(store_dir: Path, name: str) -> Path:
    return pack_path(store_dir, name) / "claims" / "claims.json"


def unknowns_path(store_dir: Path, name: str) -> Path:
    return pack_path(store_dir, name) / "unknowns" / "open_questions.json"


def _wiki_root(store_dir: Path, name: str) -> Path:
    return pack_path(store_dir, name) / "wiki"


def _wiki_sources_dir(store_dir: Path, name: str) -> Path:
    return _wiki_root(store_dir, name) / "sources"


def _artifacts_root(store_dir: Path, name: str) -> Path:
    return pack_path(store_dir, name) / "artifacts"


def _artifact_bucket_root(store_dir: Path, name: str, output: str) -> Path:
    bucket = {"note": "notes", "report": "reports", "slides": "slides"}.get(output, f"{output}s")
    return _artifacts_root(store_dir, name) / bucket


def _read_json(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(path: Path, manifest: BrainpackManifest) -> None:
    lines = [
        f"name = {json.dumps(manifest.name)}",
        f"description = {json.dumps(manifest.description)}",
        f"owner = {json.dumps(manifest.owner)}",
        f"default_policy = {json.dumps(manifest.default_policy)}",
        f"auto_backlink = {'true' if manifest.auto_backlink else 'false'}",
        f"auto_promote_claims = {'true' if manifest.auto_promote_claims else 'false'}",
        f"store_outputs = {'true' if manifest.store_outputs else 'false'}",
        f"created_at = {json.dumps(manifest.created_at)}",
        f"updated_at = {json.dumps(manifest.updated_at)}",
        "",
        "[sources]",
        "glob = [",
    ]
    lines.extend(f"  {json.dumps(item)}," for item in manifest.source_glob)
    lines.extend(
        [
            "]",
            "",
            "[compile]",
            f"max_summary_chars = {manifest.max_summary_chars}",
            f"suggest_questions = {'true' if manifest.suggest_questions else 'false'}",
            "",
            "[mount]",
            "default_tags = [",
        ]
    )
    lines.extend(f"  {json.dumps(item)}," for item in manifest.default_tags)
    lines.append("]")
    _write_text(path, "\n".join(lines) + "\n")


def load_manifest(store_dir: Path, name: str) -> BrainpackManifest:
    path = manifest_path(store_dir, name)
    if not path.exists():
        raise FileNotFoundError(f"Brainpack '{name}' does not exist.")
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    return _manifest_from_payload(payload, fallback_name=name)


def _manifest_from_payload(payload: dict[str, Any], *, fallback_name: str) -> BrainpackManifest:
    return BrainpackManifest(
        name=str(payload.get("name") or fallback_name),
        description=str(payload.get("description") or ""),
        owner=str(payload.get("owner") or ""),
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
        default_policy=str(payload.get("default_policy") or "research"),
        auto_backlink=bool(payload.get("auto_backlink", True)),
        auto_promote_claims=bool(payload.get("auto_promote_claims", False)),
        store_outputs=bool(payload.get("store_outputs", True)),
        max_summary_chars=int(payload.get("compile", {}).get("max_summary_chars", 1200)),
        suggest_questions=bool(payload.get("compile", {}).get("suggest_questions", True)),
        source_glob=tuple(str(item) for item in payload.get("sources", {}).get("glob", ["raw/**/*"])),
        default_tags=tuple(str(item) for item in payload.get("mount", {}).get("default_tags", ())),
    )


def _load_manifest_from_root(root: Path) -> BrainpackManifest:
    path = root / "manifest.toml"
    if not path.exists():
        raise FileNotFoundError(f"Brainpack manifest not found: {path}")
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    return _manifest_from_payload(payload, fallback_name=root.name)


def _replace_manifest(store_dir: Path, name: str, *, updated_at: str) -> BrainpackManifest:
    manifest = load_manifest(store_dir, name)
    updated = BrainpackManifest(
        name=manifest.name,
        description=manifest.description,
        owner=manifest.owner,
        created_at=manifest.created_at,
        updated_at=updated_at,
        default_policy=manifest.default_policy,
        auto_backlink=manifest.auto_backlink,
        auto_promote_claims=manifest.auto_promote_claims,
        store_outputs=manifest.store_outputs,
        max_summary_chars=manifest.max_summary_chars,
        suggest_questions=manifest.suggest_questions,
        source_glob=manifest.source_glob,
        default_tags=manifest.default_tags,
    )
    _write_manifest(manifest_path(store_dir, name), updated)
    return updated


def init_pack(
    store_dir: Path,
    name: str,
    *,
    description: str = "",
    owner: str = "",
    default_policy: str = "research",
) -> dict[str, Any]:
    pack_name = _validate_pack_name(name)
    root = pack_path(store_dir, pack_name)
    if root.exists():
        raise FileExistsError(f"Brainpack '{pack_name}' already exists.")
    created_at = _iso_now()
    root.mkdir(parents=True, exist_ok=False)
    for directory in PACK_SUBDIRS:
        (root / directory).mkdir(parents=True, exist_ok=True)
    (_wiki_sources_dir(store_dir, pack_name)).mkdir(parents=True, exist_ok=True)
    manifest = BrainpackManifest(
        name=pack_name,
        description=description.strip(),
        owner=owner.strip(),
        created_at=created_at,
        updated_at=created_at,
        default_policy=default_policy,
    )
    _write_manifest(manifest_path(store_dir, pack_name), manifest)
    _write_json(source_index_path(store_dir, pack_name), {"pack": pack_name, "sources": []})
    _write_json(
        compile_meta_path(store_dir, pack_name),
        {
            "pack": pack_name,
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
    return {
        "status": "ok",
        "created": True,
        "pack": pack_name,
        "path": str(root),
        "manifest": str(manifest_path(store_dir, pack_name)),
    }


def _safe_stem(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-").lower()
    return stem or "source"


def _slugify_text(text: str, *, fallback: str = "artifact") -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text.lower()).strip("-")
    return slug[:64] or fallback


def _unique_destination(base_dir: Path, relative_path: Path) -> Path:
    target = base_dir / relative_path
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    counter = 2
    while True:
        candidate = target.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


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


def _read_text_if_possible(path: Path) -> tuple[str, bool]:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        try:
            return path.read_text(encoding="utf-8"), True
        except (OSError, UnicodeDecodeError):
            return "", False
    mime, _ = mimetypes.guess_type(path.name)
    if mime and mime.startswith("text/"):
        try:
            return path.read_text(encoding="utf-8"), True
        except (OSError, UnicodeDecodeError):
            return "", False
    return "", False


def ingest_pack(
    store_dir: Path,
    name: str,
    paths: list[str],
    *,
    mode: str = "copy",
    source_type: str = "auto",
    recurse: bool = False,
) -> dict[str, Any]:
    pack_name = _validate_pack_name(name)
    root = pack_path(store_dir, pack_name)
    if not root.exists():
        raise FileNotFoundError(f"Brainpack '{pack_name}' does not exist.")
    raw_root = root / "raw"
    index_payload = _read_json(source_index_path(store_dir, pack_name), default={"pack": pack_name, "sources": []})
    existing = {str(item["source_path"]): dict(item) for item in index_payload.get("sources", [])}
    ingested: list[dict[str, Any]] = []
    for raw_input in paths:
        source = Path(raw_input).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(source)
        input_root = source if source.is_dir() else source.parent
        for item in _iter_source_files(source, recurse=recurse):
            stored_path = ""
            if mode == "copy":
                relative = item.relative_to(input_root) if source.is_dir() else Path(item.name)
                if source.is_dir():
                    relative = Path(_safe_stem(source)) / relative
                destination = _unique_destination(raw_root, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, destination)
                stored_path = str(destination.relative_to(root))
            text_preview, text_eligible = _read_text_if_possible(item)
            record = {
                "id": make_node_id(f"{pack_name}:{item}"),
                "source_path": str(item),
                "stored_path": stored_path,
                "mode": mode,
                "type": _source_type_for(item, source_type),
                "mime_type": mimetypes.guess_type(item.name)[0] or "",
                "size_bytes": item.stat().st_size,
                "ingested_at": _iso_now(),
                "text_eligible": text_eligible,
                "preview": " ".join(text_preview.strip().split())[:240] if text_preview else "",
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
        "ingested_count": len(ingested),
        "source_count": len(payload["sources"]),
    }


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
) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
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
        shutil.copytree(tmp_root, destination)

    status = pack_status(store_dir, target_name)
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


def _source_file_path(pack_root: Path, record: dict[str, Any]) -> Path:
    stored_path = str(record.get("stored_path") or "").strip()
    if stored_path:
        return pack_root / stored_path
    return Path(str(record["source_path"]))


def _markdown_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
        return stripped[:120]
    return fallback


def _markdown_headings(text: str, *, limit: int = 8) -> list[str]:
    headings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped.lstrip("#").strip())
        if len(headings) >= limit:
            break
    return headings


def _compact_summary(text: str, *, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    truncated = normalized[: max(limit - 3, 0)].rstrip()
    for separator in (". ", "; ", ": "):
        if separator in truncated:
            candidate = truncated.rsplit(separator, 1)[0].strip()
            if candidate:
                return candidate.rstrip(".;:") + "..."
    return truncated + "..."


def _normalize_query_terms(text: str) -> list[str]:
    return [term for term in re.findall(r"[A-Za-z0-9]+", text.lower()) if len(term) >= 2]


def _score_fields(query: str, terms: list[str], *weighted_fields: tuple[str, float]) -> float:
    normalized_query = " ".join(query.lower().split()).strip()
    if not normalized_query and not terms:
        return 0.0
    score = 0.0
    for text, weight in weighted_fields:
        haystack = " ".join(str(text or "").lower().split())
        if not haystack:
            continue
        if normalized_query and normalized_query in haystack:
            score += 6.0 * weight
        for term in terms:
            if term in haystack:
                score += (1.0 + min(haystack.count(term), 4) * 0.15) * weight
    return round(score, 2)


def _brainpack_root_node(manifest: BrainpackManifest) -> Node:
    return Node(
        id=make_node_id(f"brainpack:{manifest.name}"),
        label=manifest.name.replace("-", " ").replace("_", " ").title(),
        tags=["brainpack", "domain_knowledge"],
        confidence=1.0,
        brief=manifest.description or f"Brainpack for {manifest.name}",
        full_description=manifest.description,
        properties={"brainpack": manifest.name, "owner": manifest.owner},
    )


def _source_node(record: dict[str, Any], *, title: str, summary: str) -> Node:
    return Node(
        id=make_node_id(f"brainpack-source:{record['id']}"),
        label=title,
        tags=["brainpack_source"],
        confidence=0.9,
        brief=summary[:240],
        full_description=summary,
        properties={
            "brainpack_source_id": record["id"],
            "mode": record["mode"],
            "type": record["type"],
            "path": record.get("stored_path") or record["source_path"],
        },
    )


def _claim_payload(graph: CortexGraph) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for node in graph.nodes.values():
        if "brainpack_source" in node.tags or "brainpack" in node.tags:
            continue
        claims.append(
            {
                "id": node.id,
                "label": node.label,
                "tags": list(node.tags),
                "confidence": round(node.confidence, 2),
                "brief": node.brief,
                "source_quotes": list(node.source_quotes[:3]),
                "provenance": list(node.provenance[:3]),
            }
        )
    claims.sort(key=lambda item: (-item["confidence"], item["label"].lower()))
    return claims


def _build_unknowns(
    *,
    manifest: BrainpackManifest,
    source_summaries: list[dict[str, Any]],
    graph: CortexGraph,
    skipped_sources: list[str],
    suggest_questions: bool,
) -> list[dict[str, Any]]:
    unknowns: list[dict[str, Any]] = []
    if not source_summaries:
        unknowns.append(
            {
                "id": "no-readable-sources",
                "question": "Which readable notes, articles, repos, or transcripts should be added to this Brainpack?",
                "reason": "No readable text sources were available to compile.",
                "type": "coverage_gap",
            }
        )
    for skipped in skipped_sources[:10]:
        unknowns.append(
            {
                "id": make_node_id(f"unknown:{skipped}"),
                "question": f"What should Cortex learn from {Path(skipped).name} once it has a readable representation?",
                "reason": "The source was ingested but could not be compiled as text.",
                "type": "unreadable_source",
                "source_path": skipped,
            }
        )
    if suggest_questions and graph.nodes:
        top_tags: list[str] = []
        for node in graph.nodes.values():
            for tag in node.tags:
                if tag not in {"brainpack", "brainpack_source"} and tag not in top_tags:
                    top_tags.append(tag)
        for tag in top_tags[:3]:
            unknowns.append(
                {
                    "id": make_node_id(f"{manifest.name}:{tag}:question"),
                    "question": f"What are the most important unresolved threads in {tag.replace('_', ' ')} for this pack?",
                    "reason": "Suggested follow-up question generated from the compiled graph.",
                    "type": "suggested_question",
                }
            )
    return unknowns


def _wiki_index(markdown_articles: list[dict[str, Any]], manifest: BrainpackManifest) -> str:
    lines = [
        f"# {manifest.name.replace('-', ' ').replace('_', ' ').title()}",
        "",
        manifest.description or "LLM-compiled Brainpack wiki.",
        "",
        "## Sources",
        "",
    ]
    for article in markdown_articles:
        rel_path = article["wiki_path"].replace("\\", "/")
        lines.append(f"- [{article['title']}]({rel_path})")
    lines.append("")
    return "\n".join(lines)


def _wiki_article(record: dict[str, Any], *, title: str, summary: str, headings: list[str], excerpt: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"- Type: {record['type']}",
        f"- Mode: {record['mode']}",
        f"- Source: `{record['source_path']}`",
    ]
    if record.get("stored_path"):
        lines.append(f"- Stored copy: `{record['stored_path']}`")
    lines.extend(["", "## Summary", "", summary or "No summary available.", ""])
    if headings:
        lines.extend(["## Headings", ""])
        lines.extend(f"- {heading}" for heading in headings)
        lines.append("")
    if excerpt:
        lines.extend(["## Excerpt", "", excerpt, ""])
    return "\n".join(lines)


def compile_pack(
    store_dir: Path,
    name: str,
    *,
    incremental: bool = True,
    suggest_questions: bool = True,
    max_summary_chars: int | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    pack_root = pack_path(store_dir, name)
    source_index = _read_json(source_index_path(store_dir, name), default={"pack": name, "sources": []})
    source_records = list(source_index.get("sources", []))
    extractor = AggressiveExtractor()
    readable_sources: list[dict[str, Any]] = []
    skipped_sources: list[str] = []
    wiki_articles: list[dict[str, Any]] = []
    for record in source_records:
        source_file = _source_file_path(pack_root, record)
        if not source_file.exists():
            skipped_sources.append(str(record["source_path"]))
            continue
        text, readable = _read_text_if_possible(source_file)
        if not readable or not text.strip():
            skipped_sources.append(str(record["source_path"]))
            continue
        title = _markdown_title(text, Path(str(record["source_path"])).name)
        headings = _markdown_headings(text)
        summary_limit = max_summary_chars or manifest.max_summary_chars
        summary = _compact_summary(text, limit=summary_limit)
        excerpt = "\n".join(text.splitlines()[:12]).strip()
        article_slug = f"{_safe_stem(Path(str(record['source_path'])))}-{record['id'][:8]}"
        wiki_path = _wiki_sources_dir(store_dir, name) / f"{article_slug}.md"
        wiki_rel = str(wiki_path.relative_to(_wiki_root(store_dir, name)))
        _write_text(wiki_path, _wiki_article(record, title=title, summary=summary, headings=headings, excerpt=excerpt))
        readable_sources.append(
            {
                **record,
                "title": title,
                "summary": summary,
                "headings": headings,
                "wiki_path": wiki_rel,
                "char_count": len(text),
            }
        )
        wiki_articles.append({"title": title, "wiki_path": wiki_rel})
        extractor.extract_from_text(text)
    extractor.post_process()
    graph = upgrade_v4_to_v5(extractor.context.export())

    root_node = _brainpack_root_node(manifest)
    graph.add_node(root_node)
    for record in readable_sources:
        source_node = _source_node(record, title=record["title"], summary=record["summary"])
        graph.add_node(source_node)
        graph.add_edge(
            Edge(
                id=make_edge_id(root_node.id, source_node.id, "contains_source"),
                source_id=root_node.id,
                target_id=source_node.id,
                relation="contains_source",
                confidence=1.0,
            )
        )

    compiled_graph_path = graph_path(store_dir, name)
    _write_json(compiled_graph_path, graph.export_v5())

    claim_items = _claim_payload(graph)
    _write_json(claims_path(store_dir, name), {"pack": name, "claims": claim_items})

    unknown_items = _build_unknowns(
        manifest=manifest,
        source_summaries=readable_sources,
        graph=graph,
        skipped_sources=skipped_sources,
        suggest_questions=suggest_questions and manifest.suggest_questions,
    )
    _write_json(unknowns_path(store_dir, name), {"pack": name, "unknowns": unknown_items})
    _write_json(
        pack_root / "indexes" / "source_index.json",
        {"pack": name, "sources": readable_sources, "skipped_sources": skipped_sources},
    )
    _write_text(_wiki_root(store_dir, name) / "index.md", _wiki_index(wiki_articles, manifest))

    artifact_count = sum(1 for path in _artifacts_root(store_dir, name).rglob("*") if path.is_file())
    compiled_at = _iso_now()
    compile_payload = {
        "pack": name,
        "compile_status": "compiled",
        "compiled_at": compiled_at,
        "source_count": len(source_records),
        "text_source_count": len(readable_sources),
        "graph_nodes": len(graph.nodes),
        "graph_edges": len(graph.edges),
        "article_count": len(wiki_articles) + 1,
        "claim_count": len(claim_items),
        "unknown_count": len(unknown_items),
        "artifact_count": artifact_count,
        "incremental": incremental,
        "skipped_sources": skipped_sources,
    }
    _write_json(compile_meta_path(store_dir, name), compile_payload)
    _replace_manifest(store_dir, name, updated_at=compiled_at)
    return {"status": "ok", **compile_payload, "graph_path": str(compiled_graph_path)}


def _load_compiled_graph(store_dir: Path, name: str) -> CortexGraph:
    graph_payload = _read_json(graph_path(store_dir, name), default={})
    if not graph_payload:
        raise FileNotFoundError(f"Brainpack '{name}' has not been compiled yet.")
    return CortexGraph.from_v5_json(graph_payload)


def _load_claims(store_dir: Path, name: str) -> list[dict[str, Any]]:
    payload = _read_json(claims_path(store_dir, name), default={"pack": name, "claims": []})
    return [dict(item) for item in payload.get("claims", [])]


def _load_unknowns(store_dir: Path, name: str) -> list[dict[str, Any]]:
    payload = _read_json(unknowns_path(store_dir, name), default={"pack": name, "unknowns": []})
    return [dict(item) for item in payload.get("unknowns", [])]


def _load_source_articles(store_dir: Path, name: str) -> list[dict[str, Any]]:
    payload = _read_json(
        pack_path(store_dir, name) / "indexes" / "source_index.json", default={"pack": name, "sources": []}
    )
    return [dict(item) for item in payload.get("sources", [])]


def _pack_knowledge_graph(graph: CortexGraph) -> CortexGraph:
    filtered = CortexGraph()
    keep_ids: set[str] = set()
    for node in graph.nodes.values():
        if "brainpack" in node.tags or "brainpack_source" in node.tags:
            continue
        filtered.add_node(node)
        keep_ids.add(node.id)
    for edge in graph.edges.values():
        if edge.source_id in keep_ids and edge.target_id in keep_ids:
            filtered.add_edge(edge)
    return filtered


def _lint_level(severity: float) -> str:
    if severity >= 0.8:
        return "high"
    if severity >= 0.55:
        return "medium"
    return "low"


def _lint_finding(
    *,
    finding_id: str,
    finding_type: str,
    title: str,
    detail: str,
    severity: float,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "id": finding_id,
        "type": finding_type,
        "title": title,
        "detail": detail,
        "severity": round(severity, 2),
        "level": _lint_level(severity),
    }
    payload.update(extra)
    return payload


def _duplicate_candidates(graph: CortexGraph, *, threshold: float) -> list[tuple[str, str, float]]:
    candidates = list(find_duplicates(graph, threshold=threshold))
    seen = {tuple(sorted((left, right))) for left, right, _ in candidates}
    nodes = list(graph.nodes.values())
    for index, left in enumerate(nodes):
        left_tags = set(left.tags)
        for right in nodes[index + 1 :]:
            if tuple(sorted((left.id, right.id))) in seen:
                continue
            if not left_tags & set(right.tags):
                continue
            similarity = text_similarity(left.label, right.label)
            if similarity < threshold:
                continue
            candidates.append((left.id, right.id, similarity))
            seen.add(tuple(sorted((left.id, right.id))))
    candidates.sort(key=lambda item: item[2], reverse=True)
    return candidates


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


def pack_lint_report(store_dir: Path, name: str) -> dict[str, Any]:
    load_manifest(store_dir, name)
    payload = _read_json(lint_report_path(store_dir, name), default={})
    if payload:
        return payload
    return {
        "status": "pending",
        "pack": name,
        "lint_status": "not_run",
        "linted_at": "",
        "summary": {
            "total_findings": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        },
        "findings": [],
        "suggestions": [],
        "report_path": str(lint_report_path(store_dir, name)),
        "message": "Run `cortex pack lint` to generate the first Brainpack integrity report.",
    }


def pack_sources(store_dir: Path, name: str) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    ingest_index = _read_json(source_index_path(store_dir, name), default={"pack": name, "sources": []})
    compiled_index = _read_json(pack_path(store_dir, name) / "indexes" / "source_index.json", default={"sources": []})
    compiled_by_source = {
        str(item.get("source_path") or ""): dict(item)
        for item in compiled_index.get("sources", [])
        if item.get("source_path")
    }
    skipped = {str(item) for item in compiled_index.get("skipped_sources", [])}
    sources: list[dict[str, Any]] = []
    for item in ingest_index.get("sources", []):
        record = dict(item)
        compiled = compiled_by_source.get(str(record.get("source_path") or ""), {})
        source_path_value = str(record.get("source_path") or "")
        title = str(compiled.get("title") or Path(source_path_value).name or "Source")
        merged = {
            **record,
            "title": title,
            "summary": str(compiled.get("summary") or record.get("preview") or ""),
            "headings": list(compiled.get("headings", [])),
            "wiki_path": str(compiled.get("wiki_path") or ""),
            "char_count": int(compiled.get("char_count", 0)),
            "readable": bool(compiled),
            "compiled": bool(compiled),
            "skipped": source_path_value in skipped,
        }
        sources.append(merged)
    sources.sort(
        key=lambda item: (
            0 if item["readable"] else 1,
            str(item.get("title") or "").lower(),
            str(item.get("source_path") or "").lower(),
        )
    )
    return {
        "status": "ok",
        "pack": manifest.name,
        "source_count": len(sources),
        "readable_count": sum(1 for item in sources if item["readable"]),
        "skipped_count": sum(1 for item in sources if item["skipped"]),
        "sources": sources,
    }


def pack_concepts(store_dir: Path, name: str) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    knowledge_graph = _pack_knowledge_graph(_load_compiled_graph(store_dir, name))
    degree_map: dict[str, int] = {node_id: 0 for node_id in knowledge_graph.nodes}
    for edge in knowledge_graph.edges.values():
        if edge.source_id in degree_map:
            degree_map[edge.source_id] += 1
        if edge.target_id in degree_map:
            degree_map[edge.target_id] += 1
    concepts = [
        {
            "id": node.id,
            "label": node.label,
            "tags": list(node.tags),
            "confidence": round(node.confidence, 2),
            "brief": node.brief or node.full_description or "",
            "degree": degree_map.get(node.id, 0),
            "connected": degree_map.get(node.id, 0) > 0,
            "source_quote_count": len(node.source_quotes),
            "provenance_count": len(node.provenance),
        }
        for node in knowledge_graph.nodes.values()
    ]
    concepts.sort(key=lambda item: (-int(item["degree"]), -float(item["confidence"]), item["label"].lower()))
    return {
        "status": "ok",
        "pack": manifest.name,
        "concept_count": len(concepts),
        "concepts": concepts,
    }


def pack_claims(store_dir: Path, name: str) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    claims = _load_claims(store_dir, name)
    return {
        "status": "ok",
        "pack": manifest.name,
        "claim_count": len(claims),
        "claims": claims,
    }


def pack_unknowns(store_dir: Path, name: str) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    unknowns = _load_unknowns(store_dir, name)
    return {
        "status": "ok",
        "pack": manifest.name,
        "unknown_count": len(unknowns),
        "unknowns": unknowns,
    }


def pack_artifacts(store_dir: Path, name: str) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    artifacts = _list_artifact_records(store_dir, name)
    return {
        "status": "ok",
        "pack": manifest.name,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def query_pack(
    store_dir: Path,
    name: str,
    query: str,
    *,
    limit: int = 8,
    mode: str = "hybrid",
) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    graph = _load_compiled_graph(store_dir, name)
    claims = _load_claims(store_dir, name)
    unknowns = _load_unknowns(store_dir, name)
    source_articles = _load_source_articles(store_dir, name)
    artifacts = _list_artifact_records(store_dir, name)

    terms = _normalize_query_terms(query)

    concept_matches: list[dict[str, Any]] = []
    if mode in {"hybrid", "concepts"}:
        for node in graph.nodes.values():
            if "brainpack_source" in node.tags or "brainpack" in node.tags:
                continue
            score = _score_fields(
                query,
                terms,
                (node.label, 1.8),
                (" ".join(node.tags), 1.0),
                (node.brief or "", 1.2),
                (node.full_description or "", 0.7),
            )
            if score <= 0:
                continue
            concept_matches.append(
                {
                    "kind": "concept",
                    "id": node.id,
                    "title": node.label,
                    "summary": node.brief or node.full_description or "",
                    "score": score,
                    "tags": list(node.tags),
                    "confidence": round(node.confidence, 2),
                }
            )
    concept_matches.sort(key=lambda item: (-item["score"], -item["confidence"], item["title"].lower()))

    claim_matches: list[dict[str, Any]] = []
    if mode in {"hybrid", "claims"}:
        for claim in claims:
            score = _score_fields(
                query,
                terms,
                (claim.get("label", ""), 1.8),
                (" ".join(claim.get("tags", [])), 1.0),
                (claim.get("brief", ""), 1.2),
                (" ".join(claim.get("source_quotes", [])), 0.7),
            )
            if score <= 0:
                continue
            claim_matches.append(
                {
                    "kind": "claim",
                    "id": str(claim.get("id") or ""),
                    "title": str(claim.get("label") or ""),
                    "summary": str(claim.get("brief") or ""),
                    "score": score,
                    "tags": list(claim.get("tags", [])),
                    "confidence": round(float(claim.get("confidence", 0.0)), 2),
                }
            )
    claim_matches.sort(key=lambda item: (-item["score"], -item["confidence"], item["title"].lower()))

    wiki_matches: list[dict[str, Any]] = []
    if mode in {"hybrid", "wiki"}:
        for article in source_articles:
            score = _score_fields(
                query,
                terms,
                (article.get("title", ""), 1.8),
                (" ".join(article.get("headings", [])), 1.0),
                (article.get("summary", ""), 1.2),
                (article.get("preview", ""), 0.6),
            )
            if score <= 0:
                continue
            wiki_matches.append(
                {
                    "kind": "wiki",
                    "id": str(article.get("id") or ""),
                    "title": str(article.get("title") or Path(str(article.get("source_path") or "")).name),
                    "summary": str(article.get("summary") or article.get("preview") or ""),
                    "score": score,
                    "path": str(article.get("wiki_path") or ""),
                    "source_path": str(article.get("source_path") or ""),
                    "type": str(article.get("type") or ""),
                }
            )
    wiki_matches.sort(key=lambda item: (-item["score"], item["title"].lower()))

    unknown_matches: list[dict[str, Any]] = []
    if mode in {"hybrid", "unknowns"}:
        for unknown in unknowns:
            score = _score_fields(
                query,
                terms,
                (unknown.get("question", ""), 1.8),
                (unknown.get("reason", ""), 1.1),
                (unknown.get("type", ""), 0.6),
            )
            if score <= 0:
                continue
            unknown_matches.append(
                {
                    "kind": "unknown",
                    "id": str(unknown.get("id") or ""),
                    "title": str(unknown.get("question") or ""),
                    "summary": str(unknown.get("reason") or ""),
                    "score": score,
                    "type": str(unknown.get("type") or ""),
                }
            )
    unknown_matches.sort(key=lambda item: (-item["score"], item["title"].lower()))

    artifact_matches: list[dict[str, Any]] = []
    if mode in {"hybrid", "artifacts"}:
        for artifact in artifacts:
            score = _score_fields(
                query,
                terms,
                (artifact.get("title", ""), 1.6),
                (artifact.get("preview", ""), 1.0),
                (artifact.get("path", ""), 0.5),
            )
            if score <= 0:
                continue
            artifact_matches.append(
                {
                    "kind": "artifact",
                    "id": str(artifact.get("id") or ""),
                    "title": str(artifact.get("title") or ""),
                    "summary": str(artifact.get("preview") or ""),
                    "score": score,
                    "path": str(artifact.get("path") or ""),
                    "updated_at": str(artifact.get("updated_at") or ""),
                }
            )
    artifact_matches.sort(key=lambda item: (-item["score"], item["title"].lower()))

    combined = sorted(
        concept_matches + claim_matches + wiki_matches + unknown_matches + artifact_matches,
        key=lambda item: (-item["score"], item["kind"], item["title"].lower()),
    )
    top_results = combined[: max(limit, 1)]
    top_unknowns = unknown_matches[: min(max(limit, 1), 5)]

    return {
        "status": "ok",
        "pack": manifest.name,
        "query": query,
        "mode": mode,
        "limit": limit,
        "total_matches": len(combined),
        "results": top_results,
        "concepts": concept_matches[:limit],
        "claims": claim_matches[:limit],
        "wiki": wiki_matches[:limit],
        "unknowns": unknown_matches[:limit],
        "artifacts": artifact_matches[:limit],
        "related_questions": [item["title"] for item in top_unknowns],
        "counts": {
            "concepts": len(concept_matches),
            "claims": len(claim_matches),
            "wiki": len(wiki_matches),
            "unknowns": len(unknown_matches),
            "artifacts": len(artifact_matches),
        },
    }


def _artifact_sections_for_query(question: str, query_payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    claims = list(query_payload.get("claims", []))[:5]
    wiki = list(query_payload.get("wiki", []))[:4]
    unknowns = list(query_payload.get("unknowns", []))[:4]
    concepts = list(query_payload.get("concepts", []))[:4]
    artifacts = list(query_payload.get("artifacts", []))[:3]
    combined = list(query_payload.get("results", []))[:6]
    if not claims and combined:
        claims = [item for item in combined if item.get("kind") in {"concept", "claim"}][:5]
    if not wiki and combined:
        wiki = [item for item in combined if item.get("kind") == "wiki"][:4]
    return {
        "question": question,
        "claims": claims,
        "wiki": wiki,
        "unknowns": unknowns,
        "concepts": concepts,
        "artifacts": artifacts,
        "combined": combined,
    }


def _render_note_artifact(pack: BrainpackManifest, question: str, sections: dict[str, list[dict[str, Any]]]) -> str:
    lines = [
        f"# {question}",
        "",
        f"_Generated from Brainpack `{pack.name}` on {_iso_now()}._",
        "",
        "## Working Answer",
        "",
        f"This note synthesizes the strongest matches Cortex found inside `{pack.name}` for: {question}",
        "",
    ]
    if sections["claims"]:
        lines.extend(["## Key Findings", ""])
        for item in sections["claims"]:
            lines.append(f"- **{item['title']}** — {item.get('summary', '')}".rstrip())
        lines.append("")
    if sections["wiki"]:
        lines.extend(["## Source Pages", ""])
        for item in sections["wiki"]:
            source_label = item.get("path") or item.get("source_path") or ""
            lines.append(f"- **{item['title']}** — {item.get('summary', '')} ({source_label})".rstrip())
        lines.append("")
    if sections["unknowns"]:
        lines.extend(["## Open Questions", ""])
        for item in sections["unknowns"]:
            lines.append(f"- {item['title']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_report_artifact(pack: BrainpackManifest, question: str, sections: dict[str, list[dict[str, Any]]]) -> str:
    lines = [
        f"# {question}",
        "",
        f"_Brainpack_: `{pack.name}`  ",
        f"_Generated_: {_iso_now()}",
        "",
        "## Executive Summary",
        "",
        f"Cortex searched the compiled knowledge inside `{pack.name}` and assembled the most relevant claims, concepts, source pages, and unresolved questions for: {question}",
        "",
    ]
    if sections["concepts"]:
        lines.extend(["## Concepts In Play", ""])
        for item in sections["concepts"]:
            lines.append(f"- **{item['title']}** — tags: {', '.join(item.get('tags', [])) or 'n/a'}")
        lines.append("")
    if sections["claims"]:
        lines.extend(["## Key Claims", ""])
        for item in sections["claims"]:
            lines.append(f"- **{item['title']}** — {item.get('summary', '')}".rstrip())
        lines.append("")
    if sections["wiki"]:
        lines.extend(["## Source Map", ""])
        for item in sections["wiki"]:
            ref = item.get("path") or item.get("source_path") or ""
            lines.append(f"- **{item['title']}** — {item.get('summary', '')} ({ref})".rstrip())
        lines.append("")
    if sections["artifacts"]:
        lines.extend(["## Related Artifacts", ""])
        for item in sections["artifacts"]:
            lines.append(f"- **{item['title']}** — {item.get('path', '')}".rstrip())
        lines.append("")
    if sections["unknowns"]:
        lines.extend(["## Outstanding Questions", ""])
        for item in sections["unknowns"]:
            lines.append(f"- {item['title']}")
        lines.append("")
    lines.extend(
        [
            "## Next Moves",
            "",
            "- Inspect the cited source pages to strengthen or challenge the current claims.",
            "- Turn the open questions into targeted follow-up asks or additional source ingest.",
            "- File refined conclusions back into the Brainpack once the answers are stronger.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_slides_artifact(pack: BrainpackManifest, question: str, sections: dict[str, list[dict[str, Any]]]) -> str:
    findings = sections["claims"][:3] or sections["combined"][:3]
    sources = sections["wiki"][:3]
    unknowns = sections["unknowns"][:3]
    lines = [
        "---",
        "marp: true",
        f"title: {question}",
        "paginate: true",
        "---",
        "",
        f"# {question}",
        "",
        f"Brainpack: `{pack.name}`",
        "",
        "---",
        "",
        "# Key Findings",
    ]
    if findings:
        for item in findings:
            lines.append(f"- **{item['title']}**")
            if item.get("summary"):
                lines.append(f"- {item['summary']}")
    else:
        lines.append("- No strong matches were found yet.")
    lines.extend(["", "---", "", "# Source Pages"])
    if sources:
        for item in sources:
            ref = item.get("path") or item.get("source_path") or ""
            lines.append(f"- **{item['title']}** ({ref})".rstrip())
    else:
        lines.append("- Add or compile more readable sources to strengthen this deck.")
    lines.extend(["", "---", "", "# Open Questions"])
    if unknowns:
        for item in unknowns:
            lines.append(f"- {item['title']}")
    else:
        lines.append("- No unresolved questions were surfaced for this query.")
    lines.append("")
    return "\n".join(lines)


def ask_pack(
    store_dir: Path,
    name: str,
    question: str,
    *,
    output: str = "note",
    limit: int = 8,
    write_back: bool = True,
) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    query_payload = query_pack(store_dir, name, question, limit=limit, mode="hybrid")
    sections = _artifact_sections_for_query(question, query_payload)
    if output == "report":
        artifact_body = _render_report_artifact(manifest, question, sections)
    elif output == "slides":
        artifact_body = _render_slides_artifact(manifest, question, sections)
    else:
        artifact_body = _render_note_artifact(manifest, question, sections)

    artifact_path_value = ""
    if write_back and manifest.store_outputs:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        artifact_name = f"{_slugify_text(question, fallback=output)}-{timestamp}.md"
        artifact_path = _artifact_bucket_root(store_dir, name, output) / artifact_name
        _write_text(artifact_path, artifact_body)
        artifact_path_value = str(artifact_path)
        artifact_count = _refresh_artifact_count(store_dir, name)
    else:
        artifact_count = pack_status(store_dir, name)["artifact_count"]

    summary = (
        f"Built a {output} from {query_payload['total_matches']} ranked Brainpack matches."
        if query_payload["total_matches"]
        else f"No ranked matches were found in `{name}` yet; the artifact captures the current gap."
    )
    return {
        "status": "ok",
        "pack": manifest.name,
        "question": question,
        "output": output,
        "write_back": write_back and manifest.store_outputs,
        "artifact_path": artifact_path_value,
        "artifact_written": bool(artifact_path_value),
        "artifact_count": artifact_count,
        "answer_markdown": artifact_body,
        "summary": summary,
        "results_used": query_payload["results"],
        "related_questions": query_payload["related_questions"],
        "query": query_payload,
        "message": ""
        if artifact_path_value
        else "Artifact write-back is disabled for this pack, so Cortex returned the generated answer without saving it.",
    }


def lint_pack(
    store_dir: Path,
    name: str,
    *,
    stale_days: int = 30,
    duplicate_threshold: float = 0.88,
    weak_claim_confidence: float = 0.65,
    thin_article_chars: int = 220,
) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    graph = _load_compiled_graph(store_dir, name)
    knowledge_graph = _pack_knowledge_graph(graph)
    claims = _load_claims(store_dir, name)
    source_articles = _load_source_articles(store_dir, name)
    artifacts = _list_artifact_records(store_dir, name)
    compile_meta = _read_json(compile_meta_path(store_dir, name), default={"pack": name, "skipped_sources": []})

    health = knowledge_graph.graph_health(stale_days=stale_days)
    contradictions = ContradictionEngine().detect_all(knowledge_graph)
    duplicates = _duplicate_candidates(knowledge_graph, threshold=duplicate_threshold)
    weak_claims = [claim for claim in claims if float(claim.get("confidence", 0.0)) < weak_claim_confidence]
    thin_articles = [
        article
        for article in source_articles
        if int(article.get("char_count", 0)) < thin_article_chars or not article.get("headings")
    ]
    skipped_sources = [str(item) for item in compile_meta.get("skipped_sources", []) if str(item).strip()]

    findings: list[dict[str, Any]] = []
    for contradiction in contradictions:
        findings.append(
            _lint_finding(
                finding_id=f"contradiction:{contradiction.id}",
                finding_type="contradiction",
                title=f"Contradiction: {contradiction.node_label or contradiction.type}",
                detail=contradiction.description,
                severity=float(contradiction.severity),
                node_ids=list(contradiction.node_ids),
                resolution=contradiction.resolution,
                metadata=dict(contradiction.metadata or {}),
            )
        )
    for source_id, target_id, similarity in duplicates:
        source_node = knowledge_graph.get_node(source_id)
        target_node = knowledge_graph.get_node(target_id)
        if source_node is None or target_node is None:
            continue
        findings.append(
            _lint_finding(
                finding_id=f"duplicate:{source_id}:{target_id}",
                finding_type="duplicate_candidate",
                title=f"Possible duplicate: {source_node.label} / {target_node.label}",
                detail=(
                    f"These nodes look similar enough to review for deduplication "
                    f"(similarity {similarity:.2f} >= {duplicate_threshold:.2f})."
                ),
                severity=min(0.95, max(0.55, float(similarity))),
                node_ids=[source_id, target_id],
                similarity=round(float(similarity), 2),
            )
        )
    if int(health.get("total_nodes", 0)) > 1 and int(health.get("total_edges", 0)) == 0:
        findings.append(
            _lint_finding(
                finding_id=f"sparse-graph:{name}",
                finding_type="sparse_graph",
                title="Sparse concept graph",
                detail="The compiled Brainpack has concepts but no relationships between them yet.",
                severity=0.47,
            )
        )
    else:
        for orphan in health.get("orphan_nodes", []):
            findings.append(
                _lint_finding(
                    finding_id=f"orphan:{orphan['id']}",
                    finding_type="orphan_concept",
                    title=f"Orphan concept: {orphan['label']}",
                    detail="This concept is not connected to any other concept in the compiled Brainpack graph.",
                    severity=0.58,
                    node_ids=[orphan["id"]],
                    tags=list(orphan.get("tags", [])),
                )
            )
    for stale in health.get("stale_nodes", []):
        findings.append(
            _lint_finding(
                finding_id=f"stale:{stale['id']}",
                finding_type="stale_concept",
                title=f"Stale concept: {stale['label']}",
                detail=(
                    f"This concept has not been seen for {int(stale.get('days_stale', 0))} days "
                    f"(threshold: {stale_days})."
                ),
                severity=0.45,
                node_ids=[stale["id"]],
                days_stale=int(stale.get("days_stale", 0)),
            )
        )
    for claim in weak_claims:
        findings.append(
            _lint_finding(
                finding_id=f"weak-claim:{claim['id']}",
                finding_type="weak_claim",
                title=f"Weak claim: {claim['label']}",
                detail=(
                    f"This claim is below the confidence threshold "
                    f"({float(claim.get('confidence', 0.0)):.2f} < {weak_claim_confidence:.2f})."
                ),
                severity=max(0.3, 1.0 - float(claim.get("confidence", 0.0))),
                node_ids=[str(claim["id"])],
                confidence=round(float(claim.get("confidence", 0.0)), 2),
                tags=list(claim.get("tags", [])),
            )
        )
    for article in thin_articles:
        article_title = str(article.get("title") or Path(str(article.get("source_path") or "")).name)
        findings.append(
            _lint_finding(
                finding_id=f"thin-article:{article['id']}",
                finding_type="thin_article",
                title=f"Thin source page: {article_title}",
                detail=(
                    f"This compiled source is thin ({int(article.get('char_count', 0))} chars) "
                    "or lacks useful headings, so the Brainpack may not have enough structure yet."
                ),
                severity=0.35,
                path=str(article.get("wiki_path") or ""),
                source_path=str(article.get("source_path") or ""),
                char_count=int(article.get("char_count", 0)),
            )
        )
    for skipped in skipped_sources:
        findings.append(
            _lint_finding(
                finding_id=f"unreadable:{make_node_id(skipped)}",
                finding_type="unreadable_source",
                title=f"Unreadable source: {Path(skipped).name}",
                detail="This source was ingested but could not be compiled as readable text.",
                severity=0.32,
                path=skipped,
            )
        )

    findings.sort(
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}[item["level"]],
            -float(item["severity"]),
            item["title"].lower(),
        )
    )

    summary = {
        "total_findings": len(findings),
        "high": sum(1 for item in findings if item["level"] == "high"),
        "medium": sum(1 for item in findings if item["level"] == "medium"),
        "low": sum(1 for item in findings if item["level"] == "low"),
        "contradictions": len(contradictions),
        "duplicates": len(duplicates),
        "orphan_concepts": int(health.get("orphan_count", 0)),
        "stale_concepts": int(health.get("stale_count", 0)),
        "weak_claims": len(weak_claims),
        "thin_articles": len(thin_articles),
        "unreadable_sources": len(skipped_sources),
        "artifact_count": len(artifacts),
        "total_nodes": int(health.get("total_nodes", 0)),
        "total_edges": int(health.get("total_edges", 0)),
    }
    lint_status = "fail" if summary["high"] else "warn" if summary["total_findings"] else "pass"

    suggestions: list[str] = []
    if summary["contradictions"]:
        suggestions.append("Review contradictory claims before mounting this Brainpack widely.")
    if summary["duplicates"]:
        suggestions.append("Deduplicate similar concepts so future answers stop splitting the same idea across nodes.")
    if summary["unreadable_sources"]:
        suggestions.append("Convert unreadable sources to markdown or plain text, then re-run compile.")
    if summary["thin_articles"]:
        suggestions.append(
            "Add richer source material or restructure thin notes so compile produces stronger wiki pages."
        )
    if not len(artifacts):
        suggestions.append("Use `cortex pack ask` a few times so the pack starts compounding durable outputs.")

    payload = {
        "status": "ok",
        "pack": manifest.name,
        "lint_status": lint_status,
        "linted_at": _iso_now(),
        "summary": summary,
        "findings": findings,
        "health": health,
        "suggestions": suggestions,
        "report_path": str(lint_report_path(store_dir, name)),
    }
    _write_json(lint_report_path(store_dir, name), payload)
    return payload


def pack_status(store_dir: Path, name: str) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    source_index = _read_json(source_index_path(store_dir, name), default={"pack": name, "sources": []})
    compile_meta = _read_json(
        compile_meta_path(store_dir, name),
        default={
            "pack": name,
            "compile_status": "idle",
            "compiled_at": "",
            "source_count": len(source_index.get("sources", [])),
            "text_source_count": 0,
            "graph_nodes": 0,
            "graph_edges": 0,
            "article_count": 0,
            "claim_count": 0,
            "unknown_count": 0,
            "artifact_count": 0,
        },
    )
    lint_report = pack_lint_report(store_dir, name)
    return {
        "status": "ok",
        "pack": manifest.name,
        "path": str(pack_path(store_dir, name)),
        "manifest": {
            "name": manifest.name,
            "description": manifest.description,
            "owner": manifest.owner,
            "default_policy": manifest.default_policy,
            "created_at": manifest.created_at,
            "updated_at": manifest.updated_at,
        },
        "source_count": len(source_index.get("sources", [])),
        "text_source_count": int(compile_meta.get("text_source_count", 0)),
        "graph_nodes": int(compile_meta.get("graph_nodes", 0)),
        "graph_edges": int(compile_meta.get("graph_edges", 0)),
        "article_count": int(compile_meta.get("article_count", 0)),
        "claim_count": int(compile_meta.get("claim_count", 0)),
        "unknown_count": int(compile_meta.get("unknown_count", 0)),
        "artifact_count": int(compile_meta.get("artifact_count", 0)),
        "compiled_at": str(compile_meta.get("compiled_at") or ""),
        "compile_status": str(compile_meta.get("compile_status") or "idle"),
        "lint_status": str(lint_report.get("lint_status") or "not_run"),
        "linted_at": str(lint_report.get("linted_at") or ""),
        "lint_summary": dict(lint_report.get("summary") or {}),
    }


def list_packs(store_dir: Path) -> dict[str, Any]:
    root = _packs_root(store_dir)
    packs: list[dict[str, Any]] = []
    if root.exists():
        for path in sorted(root.iterdir()):
            if not path.is_dir() or not (path / "manifest.toml").exists():
                continue
            packs.append(pack_status(store_dir, path.name))
    return {
        "status": "ok",
        "packs": packs,
        "count": len(packs),
    }


def render_pack_context(
    store_dir: Path,
    name: str,
    *,
    target: str,
    smart: bool = True,
    policy_name: str = "technical",
    max_chars: int = 1500,
    project_dir: str = "",
) -> dict[str, Any]:
    graph_payload = _read_json(graph_path(store_dir, name), default={})
    if not graph_payload:
        raise FileNotFoundError(f"Brainpack '{name}' has not been compiled yet.")
    graph = CortexGraph.from_v5_json(graph_payload)
    canonical_target = canonical_target_name(target)
    resolved_policy_name = policy_name or load_manifest(store_dir, name).default_policy
    policy, route_tags = _policy_for_target(canonical_target, smart=smart, policy_name=resolved_policy_name)
    filtered = apply_disclosure(graph, policy)
    ctx = NormalizedContext.from_v5(filtered.export_v5())
    context_markdown = ""
    consume_as = "instruction_markdown"
    target_payload: dict[str, Any] = {}
    resolved_project_dir = Path(project_dir).resolve() if project_dir else None
    if filtered.nodes:
        if canonical_target == "hermes":
            documents = build_hermes_documents(ctx, max_chars=max_chars, min_confidence=policy.min_confidence)
            context_markdown = documents["memory"]
            consume_as = "hermes_memory"
            target_payload = {
                "user_text": documents["user"],
                "memory_text": documents["memory"],
                "agents_text": documents["agents"],
            }
        elif canonical_target in PORTABLE_DIRECT_TARGETS:
            with tempfile.TemporaryDirectory() as tmp_dir:
                temp_graph_path = Path(tmp_dir) / f"{canonical_target}.json"
                _write_json(temp_graph_path, filtered.export_v5())
                context_markdown = generate_compact_context(
                    HookConfig(
                        graph_path=str(temp_graph_path),
                        policy="full",
                        max_chars=max_chars,
                        include_project=False,
                    ),
                    cwd=str(resolved_project_dir) if resolved_project_dir is not None else None,
                )
        elif canonical_target == "claude":
            preferences_text = export_claude_preferences(ctx, min_confidence=policy.min_confidence)
            memories = export_claude_memories(ctx, min_confidence=policy.min_confidence)
            context_markdown = preferences_text
            consume_as = "claude_profile"
            target_payload = {
                "preferences_text": preferences_text,
                "memories": memories,
            }
        elif canonical_target in {"chatgpt", "grok"}:
            pack = build_instruction_pack(ctx, min_confidence=policy.min_confidence)
            context_markdown = pack.combined
            consume_as = "custom_instructions"
            target_payload = {
                "about": pack.about,
                "respond": pack.respond,
                "combined": pack.combined,
            }
    facts = [
        {"id": node.id, "label": node.label, "tags": list(node.tags), "confidence": round(node.confidence, 2)}
        for node in sorted(filtered.nodes.values(), key=lambda item: (-item.confidence, item.label.lower()))
        if "brainpack_source" not in node.tags and "brainpack" not in node.tags
    ]
    return {
        "status": "ok",
        "pack": name,
        "target": canonical_target,
        "name": display_name(canonical_target),
        "mode": "smart" if smart else "full",
        "policy": resolved_policy_name,
        "route_tags": route_tags,
        "fact_count": len(facts),
        "labels": [item["label"] for item in facts],
        "facts": facts,
        "graph_path": str(graph_path(store_dir, name)),
        "project_dir": str(resolved_project_dir) if resolved_project_dir is not None else "",
        "context_markdown": context_markdown,
        "consume_as": consume_as,
        "target_payload": target_payload,
        "graph": filtered.export_v5(),
        "message": ""
        if facts
        else "This Brainpack compiled successfully but did not yield routed facts for this target.",
    }
