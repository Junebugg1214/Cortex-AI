from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cortex.contradictions import ContradictionEngine
from cortex.dedup import find_duplicates, text_similarity
from cortex.graph import CortexGraph, make_node_id
from cortex.hermes_integration import build_hermes_documents
from cortex.hooks import HookConfig, generate_compact_context
from cortex.import_memory import NormalizedContext, export_claude_memories, export_claude_preferences
from cortex.packs import (
    BrainpackManifest,
    _artifact_bucket_root,
    _artifacts_root,
    _compact_summary,
    _iso_now,
    _normalize_query_terms,
    _packs_root,
    _read_json,
    _read_text_if_possible,
    _replace_manifest,
    _require_pack_namespace,
    _score_fields,
    _slugify_text,
    _write_json,
    _write_text,
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
from cortex.portability import PORTABLE_DIRECT_TARGETS, build_instruction_pack
from cortex.portable_runtime import _policy_for_target, canonical_target_name, display_name
from cortex.upai.disclosure import apply_disclosure


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


def query_pack(
    store_dir: Path,
    name: str,
    query: str,
    *,
    limit: int = 8,
    mode: str = "hybrid",
    namespace: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
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
        "namespace": manifest.namespace,
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
    claims = list(query_payload.get("claims", []))
    strong_claims = [item for item in claims if float(item.get("confidence", 0.0)) >= 0.55]
    claims = (strong_claims or claims)[:5]
    wiki = list(query_payload.get("wiki", []))[:4]
    unknowns = list(query_payload.get("unknowns", []))[:4]
    concepts = list(query_payload.get("concepts", []))
    strong_concepts = [item for item in concepts if float(item.get("confidence", 0.0)) >= 0.55]
    concepts = (strong_concepts or concepts)[:4]
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
        (
            f"Cortex searched the compiled knowledge inside `{pack.name}` and assembled the most relevant "
            f"claims, concepts, source pages, and unresolved questions for: {question}"
        ),
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
    namespace: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
    query_payload = query_pack(store_dir, name, question, limit=limit, mode="hybrid", namespace=namespace)
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
        artifact_count = pack_status(store_dir, name, namespace=namespace)["artifact_count"]

    summary = (
        f"Built a {output} from {query_payload['total_matches']} ranked Brainpack matches."
        if query_payload["total_matches"]
        else f"No ranked matches were found in `{name}` yet; the artifact captures the current gap."
    )
    return {
        "status": "ok",
        "pack": manifest.name,
        "namespace": manifest.namespace,
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
        "message": (
            ""
            if artifact_path_value
            else "Artifact write-back is disabled for this pack, so Cortex returned the generated answer without saving it."
        ),
    }


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
