from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

from cortex.compat import upgrade_v4_to_v5
from cortex.extract_memory import AggressiveExtractor
from cortex.graph import CortexGraph, Edge, Node, make_edge_id, make_node_id
from cortex.packs import (
    BrainpackManifest,
    _artifacts_root,
    _compact_summary,
    _iso_now,
    _read_json,
    _read_text_if_possible,
    _replace_manifest,
    _require_pack_namespace,
    _safe_stem,
    _wiki_root,
    _wiki_sources_dir,
    _write_json,
    _write_text,
    claims_path,
    compile_meta_path,
    graph_path,
    load_manifest,
    pack_path,
    source_index_path,
    unknowns_path,
)


def _source_file_path(pack_root: Path, record: dict[str, object]) -> Path:
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


def _clean_inline_text(text: str, *, limit: int = 0) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip(" \t\r\n-:;|#`*_")
    if limit and len(cleaned) > limit:
        return cleaned[: limit - 3].rstrip() + "..."
    return cleaned


def _markdown_extraction_text(text: str) -> str:
    lines = text.splitlines()
    body_lines: list[str] = []
    skipped_leading_title = False
    for line in lines:
        stripped = line.strip()
        if not skipped_leading_title and not stripped:
            continue
        if not skipped_leading_title and stripped.startswith("#"):
            skipped_leading_title = True
            continue
        skipped_leading_title = True
        if stripped.startswith("#"):
            continue
        body_lines.append(line)
    candidate = "\n".join(body_lines).strip()
    if candidate:
        return candidate
    return text.strip()


def _normalize_matchable_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _sanitize_pack_graph(graph: CortexGraph) -> None:
    removable: list[str] = []
    for node in graph.nodes.values():
        label = _clean_inline_text(node.label, limit=180)
        if not label or not re.search(r"[A-Za-z0-9]", label):
            removable.append(node.id)
            continue
        node.label = label
        node.brief = _clean_inline_text(node.brief or node.full_description, limit=280)
        if node.full_description:
            node.full_description = _clean_inline_text(node.full_description, limit=1200)
        node.tags = list(dict.fromkeys(node.tags))
    if removable:
        graph.remove_nodes(removable)


def _link_cooccurring_pack_nodes(graph: CortexGraph, source_texts: list[str]) -> None:
    knowledge_nodes = [
        node
        for node in graph.nodes.values()
        if "brainpack" not in node.tags and "brainpack_source" not in node.tags and _clean_inline_text(node.label)
    ]
    if len(knowledge_nodes) < 2:
        return

    normalized_labels = {node.id: _normalize_matchable_text(node.label) for node in knowledge_nodes}
    for text in source_texts:
        haystack = _normalize_matchable_text(text)
        if not haystack:
            continue
        mentioned_ids = sorted(
            node.id
            for node in knowledge_nodes
            if normalized_labels[node.id] and f" {normalized_labels[node.id]} " in f" {haystack} "
        )
        if len(mentioned_ids) < 2:
            continue
        for source_id, target_id in combinations(mentioned_ids[:12], 2):
            edge_id = make_edge_id(source_id, target_id, "co_occurs")
            if edge_id in graph.edges:
                continue
            graph.add_edge(
                Edge(
                    id=edge_id,
                    source_id=source_id,
                    target_id=target_id,
                    relation="co_occurs",
                    confidence=0.58,
                )
            )


def _brainpack_root_node(manifest: BrainpackManifest, *, fallback_summary: str = "") -> Node:
    brief = manifest.description or fallback_summary or f"Brainpack for {manifest.name}"
    return Node(
        id=make_node_id(f"brainpack:{manifest.name}"),
        label=manifest.name.replace("-", " ").replace("_", " ").title(),
        tags=["brainpack", "domain_knowledge"],
        confidence=1.0,
        brief=brief,
        full_description=manifest.description or fallback_summary,
        properties={"brainpack": manifest.name, "owner": manifest.owner},
    )


def _source_node(record: dict[str, object], *, title: str, summary: str) -> Node:
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


def _claim_payload(graph: CortexGraph) -> list[dict[str, object]]:
    claims: list[dict[str, object]] = []
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
    claims.sort(key=lambda item: (-float(item["confidence"]), str(item["label"]).lower()))
    return claims


def _build_unknowns(
    *,
    manifest: BrainpackManifest,
    source_summaries: list[dict[str, object]],
    graph: CortexGraph,
    skipped_sources: list[str],
    suggest_questions: bool,
) -> list[dict[str, object]]:
    unknowns: list[dict[str, object]] = []
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


def _wiki_index(markdown_articles: list[dict[str, str]], manifest: BrainpackManifest) -> str:
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


def _wiki_article(record: dict[str, object], *, title: str, summary: str, headings: list[str], excerpt: str) -> str:
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
    namespace: str | None = None,
) -> dict[str, object]:
    manifest = load_manifest(store_dir, name)
    _require_pack_namespace(manifest, namespace)
    pack_root = pack_path(store_dir, name)
    source_index = _read_json(source_index_path(store_dir, name), default={"pack": name, "sources": []})
    source_records = list(source_index.get("sources", []))
    extractor = AggressiveExtractor()
    readable_sources: list[dict[str, object]] = []
    skipped_sources: list[str] = []
    wiki_articles: list[dict[str, str]] = []
    extraction_texts: list[str] = []
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
        article_slug = f"{_safe_stem(Path(str(record['source_path'])))}-{str(record['id'])[:8]}"
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
        extraction_text = _markdown_extraction_text(text)
        extraction_texts.append(extraction_text or text)
        extractor.extract_from_text(extraction_text or text)
    extractor.post_process()
    graph = upgrade_v4_to_v5(extractor.context.export())
    _sanitize_pack_graph(graph)
    _link_cooccurring_pack_nodes(graph, extraction_texts)

    root_summary = str(readable_sources[0]["summary"]) if readable_sources else ""
    root_node = _brainpack_root_node(manifest, fallback_summary=root_summary)
    graph.add_node(root_node)
    for record in readable_sources:
        source_node = _source_node(record, title=str(record["title"]), summary=str(record["summary"]))
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


__all__ = ["compile_pack"]
