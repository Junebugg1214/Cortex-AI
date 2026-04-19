from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from cortex.graph.contradictions import ContradictionEngine
from cortex.graph.dedup import find_duplicates, text_similarity
from cortex.graph.graph import CortexGraph, make_node_id
from cortex.hermes_integration import build_hermes_documents
from cortex.hooks import HookConfig, generate_compact_context
from cortex.import_memory import NormalizedContext, export_claude_memories, export_claude_preferences
from cortex.packs import (
    _iso_now,
    _packs_root,
    _read_json,
    _require_pack_namespace,
    _write_json,
    claims_path,
    compile_meta_path,
    graph_path,
    lint_report_path,
    load_manifest,
    pack_mounts,
    pack_path,
    source_index_path,
    unknowns_path,
)
from cortex.portability.portability import PORTABLE_DIRECT_TARGETS, build_instruction_pack
from cortex.portability.portable_runtime import _policy_for_target, canonical_target_name, display_name
from cortex.versioning.upai.disclosure import apply_disclosure


class PackProvenanceUnavailableError(RuntimeError):
    """Raised when provenance was intentionally omitted from a compiled Brainpack."""


class PackFactNotFoundError(ValueError):
    """Raised when a requested fact is not present in the compiled Brainpack."""


def _load_compiled_graph(store_dir: Path, name: str) -> CortexGraph:
    graph_payload = _read_json(graph_path(store_dir, name), default={})
    if not graph_payload:
        raise FileNotFoundError(f"Brainpack '{name}' has not been compiled yet.")
    return CortexGraph.from_v5_json(graph_payload)


def _compile_meta(store_dir: Path, name: str) -> dict[str, Any]:
    return _read_json(compile_meta_path(store_dir, name), default={"pack": name, "compile_mode": "distribution"})


def _compile_mode(store_dir: Path, name: str) -> str:
    meta = _compile_meta(store_dir, name)
    return str(meta.get("compile_mode") or "distribution")


def _resolve_fact_node(graph: CortexGraph, fact_identifier: str):
    cleaned = str(fact_identifier).strip()
    if not cleaned:
        raise PackFactNotFoundError("Fact identifier is required.")
    node = graph.get_node(cleaned)
    if node is not None:
        return node
    matches = graph.find_nodes(label=cleaned)
    if matches:
        return matches[0]
    raise PackFactNotFoundError(f"Fact not found in compiled Brainpack: {cleaned}")


def _load_claims(store_dir: Path, name: str) -> list[dict[str, Any]]:
    payload = _read_json(claims_path(store_dir, name), default={"pack": name, "claims": []})
    return [dict(item) for item in payload.get("claims", [])]


def _load_unknowns(store_dir: Path, name: str) -> list[dict[str, Any]]:
    payload = _read_json(unknowns_path(store_dir, name), default={"pack": name, "unknowns": []})
    return [dict(item) for item in payload.get("unknowns", [])]


def _load_source_articles(store_dir: Path, name: str) -> list[dict[str, Any]]:
    payload = _read_json(
        pack_path(store_dir, name) / "indexes" / "source_index.json",
        default={"pack": name, "sources": []},
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


def _pack_artifacts_module():
    from cortex import pack_artifacts

    return pack_artifacts


def _list_artifact_records(store_dir: Path, name: str) -> list[dict[str, Any]]:
    return _pack_artifacts_module()._list_artifact_records(store_dir, name)


def _refresh_artifact_count(store_dir: Path, name: str) -> int:
    return _pack_artifacts_module()._refresh_artifact_count(store_dir, name)


def pack_lint_report(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
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


def pack_sources(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
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
        "namespace": manifest.namespace,
        "source_count": len(sources),
        "readable_count": sum(1 for item in sources if item["readable"]),
        "skipped_count": sum(1 for item in sources if item["skipped"]),
        "sources": sources,
    }


def pack_concepts(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
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
        "namespace": manifest.namespace,
        "concept_count": len(concepts),
        "concepts": concepts,
    }


def pack_claims(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
    claims = _load_claims(store_dir, name)
    return {
        "status": "ok",
        "pack": manifest.name,
        "namespace": manifest.namespace,
        "claim_count": len(claims),
        "claims": claims,
    }


def pack_unknowns(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
    unknowns = _load_unknowns(store_dir, name)
    return {
        "status": "ok",
        "pack": manifest.name,
        "namespace": manifest.namespace,
        "unknown_count": len(unknowns),
        "unknowns": unknowns,
    }


def pack_fact_provenance(
    store_dir: Path,
    name: str,
    fact_identifier: str,
    *,
    namespace: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
    mode = _compile_mode(store_dir, name)
    graph = _load_compiled_graph(store_dir, name)
    node = _resolve_fact_node(graph, fact_identifier)
    if mode != "full":
        return {
            "status": "PROVENANCE_UNAVAILABLE",
            "pack": manifest.name,
            "namespace": manifest.namespace,
            "compile_mode": mode,
            "fact_id": node.id,
            "fact_label": node.label,
            "message": "This Brainpack was compiled in distribution mode; provenance is unavailable by design.",
        }
    return {
        "status": "ok",
        "pack": manifest.name,
        "namespace": manifest.namespace,
        "compile_mode": mode,
        "fact_id": node.id,
        "fact_label": node.label,
        "provenance": [dict(item) for item in node.provenance],
        "source_quotes": list(node.source_quotes),
        "claim_history": list(node.properties.get("claim_history", [])),
        "contested": bool(node.properties.get("contested", False)),
        "temporal_confidence": float(node.properties.get("temporal_confidence", 0.0) or 0.0),
        "extraction_confidence": float(node.properties.get("extraction_confidence", 0.0) or 0.0),
    }


def inspect_pack_artifact(path: str | Path, *, show_provenance: bool = False) -> dict[str, Any]:
    artifact_path = Path(path)
    if not artifact_path.exists():
        raise FileNotFoundError(f"Pack artifact not found: {artifact_path}")
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    compile_mode = str(
        payload.get("compile_mode")
        or ((payload.get("graph") or {}).get("meta") or {}).get("compile_mode")
        or "distribution"
    )
    graph_payload = payload.get("graph") or payload
    graph = CortexGraph.from_v5_json(graph_payload)
    result = {
        "status": "ok",
        "path": str(artifact_path),
        "compile_mode": compile_mode,
        "provenance_available": bool(
            payload.get("provenance_available")
            if "provenance_available" in payload
            else ((graph.meta or {}).get("provenance_available", compile_mode == "full"))
        ),
        "lossy": bool(
            payload.get("lossy") if "lossy" in payload else ((graph.meta or {}).get("lossy", compile_mode != "full"))
        ),
        "graph_nodes": len(graph.nodes),
        "graph_edges": len(graph.edges),
    }
    if show_provenance:
        provenance_nodes = [
            {
                "id": node.id,
                "label": node.label,
                "provenance_count": len(node.provenance),
                "claim_history_count": len(node.properties.get("claim_history", [])),
                "contested": bool(node.properties.get("contested", False)),
            }
            for node in sorted(graph.nodes.values(), key=lambda item: item.label.lower())
            if node.provenance or node.properties.get("claim_history") or node.properties.get("contested")
        ]
        result["provenance_nodes"] = provenance_nodes
    return result


def pack_artifacts(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    return _pack_artifacts_module().pack_artifacts(store_dir, name, namespace=namespace)


def _pack_query_module():
    from cortex import pack_query

    return pack_query


def query_pack(
    store_dir: Path,
    name: str,
    query: str,
    *,
    limit: int = 8,
    mode: str = "hybrid",
    namespace: str | None = None,
) -> dict[str, Any]:
    return _pack_query_module().query_pack(
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
    return _pack_query_module().ask_pack(
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
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
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
                severity=min(0.79, max(0.55, float(similarity))),
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
    if not artifacts:
        suggestions.append("Use `cortex pack ask` a few times so the pack starts compounding durable outputs.")

    payload = {
        "status": "ok",
        "pack": manifest.name,
        "namespace": manifest.namespace,
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


def pack_status(store_dir: Path, name: str, *, namespace: str | None = None) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
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
    lint_report = pack_lint_report(store_dir, name, namespace=namespace)
    mount_report = pack_mounts(store_dir, name, namespace=namespace)
    return {
        "status": "ok",
        "pack": manifest.name,
        "namespace": manifest.namespace,
        "path": str(pack_path(store_dir, name)),
        "manifest": {
            "name": manifest.name,
            "description": manifest.description,
            "owner": manifest.owner,
            "namespace": manifest.namespace,
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
        "compile_mode": str(compile_meta.get("compile_mode") or "distribution"),
        "provenance_available": bool(compile_meta.get("provenance_available", False)),
        "lossy": bool(compile_meta.get("lossy", True)),
        "lint_status": str(lint_report.get("lint_status") or "not_run"),
        "linted_at": str(lint_report.get("linted_at") or ""),
        "lint_summary": dict(lint_report.get("summary") or {}),
        "mount_count": int(mount_report.get("mount_count") or 0),
        "mounted_targets": [str(item.get("target") or "") for item in mount_report.get("mounts", [])],
    }


def list_packs(store_dir: Path, *, namespace: str | None = None) -> dict[str, Any]:
    root = _packs_root(store_dir)
    packs: list[dict[str, Any]] = []
    if root.exists():
        for path in sorted(root.iterdir()):
            if not path.is_dir() or not (path / "manifest.toml").exists():
                continue
            try:
                packs.append(pack_status(store_dir, path.name, namespace=namespace))
            except PermissionError:
                continue
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
    namespace: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
    graph_payload = _read_json(graph_path(store_dir, name), default={})
    if not graph_payload:
        raise FileNotFoundError(f"Brainpack '{name}' has not been compiled yet.")
    graph = CortexGraph.from_v5_json(graph_payload)
    canonical_target = canonical_target_name(target)
    resolved_policy_name = policy_name or manifest.default_policy
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
        "pack": manifest.name,
        "namespace": manifest.namespace,
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
        "message": (
            "" if facts else "This Brainpack compiled successfully but did not yield routed facts for this target."
        ),
    }
