from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cortex.pack_artifacts import _list_artifact_records, _refresh_artifact_count
from cortex.pack_runtime import _load_claims, _load_compiled_graph, _load_source_articles, _load_unknowns
from cortex.packs import (
    BrainpackManifest,
    _artifact_bucket_root,
    _iso_now,
    _normalize_query_terms,
    _require_pack_namespace,
    _score_fields,
    _slugify_text,
    _write_text,
    load_manifest,
)


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
        artifact_count = len(_list_artifact_records(store_dir, name))

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
