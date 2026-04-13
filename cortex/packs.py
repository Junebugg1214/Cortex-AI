from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11 fallback
    import tomli as tomllib

from cortex.namespaces import describe_resource_namespace, normalize_resource_namespace, resource_namespace_matches

PACKS_DIRNAME = "packs"
BRAINPACK_BUNDLE_FORMAT_VERSION = "1"
BRAINPACK_BUNDLE_MANIFEST = "bundle_manifest.json"
BRAINPACK_BUNDLE_PREFIX = "pack/"
OPENCLAW_MOUNT_TARGET = "openclaw"
OPENCLAW_MOUNT_REGISTRY = "brainpacks.mounted.json"
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
SUPPORTED_PACK_MOUNT_TARGETS = (
    "claude",
    "claude-code",
    "chatgpt",
    "codex",
    "copilot",
    "cursor",
    "gemini",
    "grok",
    "hermes",
    "windsurf",
    OPENCLAW_MOUNT_TARGET,
)
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
    namespace: str | None
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


def _require_pack_namespace(manifest: BrainpackManifest, namespace: str | None) -> None:
    if resource_namespace_matches(manifest.namespace, namespace):
        return
    raise PermissionError(
        f"Brainpack '{manifest.name}' is outside namespace '{describe_resource_namespace(namespace)}'."
    )


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


def pack_mounts_path(store_dir: Path, name: str) -> Path:
    return pack_path(store_dir, name) / "indexes" / "mounts.json"


def _wiki_root(store_dir: Path, name: str) -> Path:
    return pack_path(store_dir, name) / "wiki"


def _wiki_sources_dir(store_dir: Path, name: str) -> Path:
    return _wiki_root(store_dir, name) / "sources"


def _artifacts_root(store_dir: Path, name: str) -> Path:
    return pack_path(store_dir, name) / "artifacts"


def _artifact_bucket_root(store_dir: Path, name: str, output: str) -> Path:
    bucket = {"note": "notes", "report": "reports", "slides": "slides"}.get(output, f"{output}s")
    return _artifacts_root(store_dir, name) / bucket


def _default_openclaw_store_dir() -> Path:
    return Path.home() / ".openclaw" / "cortex"


def openclaw_mount_registry_path(openclaw_store_dir: Path | None = None) -> Path:
    root = Path(openclaw_store_dir) if openclaw_store_dir is not None else _default_openclaw_store_dir()
    return root / OPENCLAW_MOUNT_REGISTRY


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
    if manifest.namespace is not None:
        lines.insert(3, f"namespace = {json.dumps(manifest.namespace)}")
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
        namespace=normalize_resource_namespace(payload.get("namespace")),
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
        namespace=manifest.namespace,
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
    namespace: str | None = None,
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
        namespace=normalize_resource_namespace(namespace),
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


def _pack_ingest_module():
    from cortex import pack_ingest

    return pack_ingest


def ingest_pack(
    store_dir: Path,
    name: str,
    paths: list[str],
    *,
    mode: str = "copy",
    source_type: str = "auto",
    recurse: bool = False,
) -> dict[str, Any]:
    return _pack_ingest_module().ingest_pack(
        store_dir,
        name,
        paths,
        mode=mode,
        source_type=source_type,
        recurse=recurse,
    )


def _pack_bundles_module():
    from cortex import pack_bundles

    return pack_bundles


def verify_pack_bundle(archive_path: str | Path) -> dict[str, Any]:
    return _pack_bundles_module().verify_pack_bundle(archive_path)


def export_pack_bundle(
    store_dir: Path,
    name: str,
    output_path: str | Path,
    *,
    verify: bool = True,
    namespace: str | None = None,
) -> dict[str, Any]:
    return _pack_bundles_module().export_pack_bundle(
        store_dir,
        name,
        output_path,
        verify=verify,
        namespace=namespace,
    )


def import_pack_bundle(
    archive_path: str | Path,
    store_dir: Path,
    *,
    as_name: str = "",
    namespace: str | None = None,
) -> dict[str, Any]:
    return _pack_bundles_module().import_pack_bundle(
        archive_path,
        store_dir,
        as_name=as_name,
        namespace=namespace,
    )


def _pack_mounts_module():
    from cortex import pack_mounts as pack_mounts_module

    return pack_mounts_module


def pack_mounts(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    return _pack_mounts_module().pack_mounts(store_dir, name, namespace=namespace)


def mount_pack(
    store_dir: Path,
    name: str,
    *,
    targets: list[str],
    project_dir: str = "",
    smart: bool = True,
    policy_name: str = "technical",
    max_chars: int = 1500,
    openclaw_store_dir: str = "",
    namespace: str | None = None,
) -> dict[str, Any]:
    return _pack_mounts_module().mount_pack(
        store_dir,
        name,
        targets=targets,
        project_dir=project_dir,
        smart=smart,
        policy_name=policy_name,
        max_chars=max_chars,
        openclaw_store_dir=openclaw_store_dir,
        namespace=namespace,
    )


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


def _pack_compile_module():
    from cortex import pack_compile

    return pack_compile


def compile_pack(
    store_dir: Path,
    name: str,
    *,
    incremental: bool = True,
    suggest_questions: bool = True,
    max_summary_chars: int | None = None,
    mode: str = "distribution",
    output_path: str | Path | None = None,
    namespace: str | None = None,
) -> dict[str, Any]:
    return _pack_compile_module().compile_pack(
        store_dir,
        name,
        incremental=incremental,
        suggest_questions=suggest_questions,
        max_summary_chars=max_summary_chars,
        mode=mode,
        output_path=output_path,
        namespace=namespace,
    )


def _pack_runtime_module():
    from cortex import pack_runtime

    return pack_runtime


def pack_lint_report(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    return _pack_runtime_module().pack_lint_report(store_dir, name, namespace=namespace)


def pack_sources(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    return _pack_runtime_module().pack_sources(store_dir, name, namespace=namespace)


def pack_concepts(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    return _pack_runtime_module().pack_concepts(store_dir, name, namespace=namespace)


def pack_claims(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    return _pack_runtime_module().pack_claims(store_dir, name, namespace=namespace)


def pack_unknowns(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    return _pack_runtime_module().pack_unknowns(store_dir, name, namespace=namespace)


def pack_artifacts(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    return _pack_runtime_module().pack_artifacts(store_dir, name, namespace=namespace)


def query_pack(
    store_dir: Path,
    name: str,
    query: str,
    *,
    limit: int = 8,
    mode: str = "hybrid",
    namespace: str | None = None,
) -> dict[str, Any]:
    return _pack_runtime_module().query_pack(
        store_dir,
        name,
        query,
        limit=limit,
        mode=mode,
        namespace=namespace,
    )


def ask_pack(
    store_dir: Path,
    name: str,
    question: str,
    *,
    output: str = "note",
    limit: int = 8,
    write_back: bool = True,
    namespace: str | None = None,
) -> dict[str, Any]:
    return _pack_runtime_module().ask_pack(
        store_dir,
        name,
        question,
        output=output,
        limit=limit,
        write_back=write_back,
        namespace=namespace,
    )


def lint_pack(
    store_dir: Path,
    name: str,
    *,
    stale_days: int = 30,
    duplicate_threshold: float = 0.88,
    weak_claim_confidence: float = 0.65,
    thin_article_chars: int = 220,
    namespace: str | None = None,
) -> dict[str, Any]:
    return _pack_runtime_module().lint_pack(
        store_dir,
        name,
        stale_days=stale_days,
        duplicate_threshold=duplicate_threshold,
        weak_claim_confidence=weak_claim_confidence,
        thin_article_chars=thin_article_chars,
        namespace=namespace,
    )


def pack_status(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    return _pack_runtime_module().pack_status(store_dir, name, namespace=namespace)


def inspect_pack_artifact(path: str | Path, *, show_provenance: bool = False) -> dict[str, Any]:
    return _pack_runtime_module().inspect_pack_artifact(path, show_provenance=show_provenance)


def pack_fact_provenance(
    store_dir: Path,
    name: str,
    fact_identifier: str,
    *,
    namespace: str | None = None,
) -> dict[str, Any]:
    return _pack_runtime_module().pack_fact_provenance(
        store_dir,
        name,
        fact_identifier,
        namespace=namespace,
    )


def list_packs(store_dir: Path, *, namespace: str | None = None) -> dict[str, Any]:
    return _pack_runtime_module().list_packs(store_dir, namespace=namespace)


def render_pack_context(
    store_dir: Path,
    name: str,
    *,
    target: str,
    smart: bool = True,
    policy_name: str = "technical",
    max_chars: int = 1500,
    project_dir: str = "",
    namespace: str | None = None,
) -> dict[str, Any]:
    return _pack_runtime_module().render_pack_context(
        store_dir,
        name,
        target=target,
        smart=smart,
        policy_name=policy_name,
        max_chars=max_chars,
        project_dir=project_dir,
        namespace=namespace,
    )
