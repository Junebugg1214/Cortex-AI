from __future__ import annotations

import copy
import json
from time import perf_counter
from typing import Any

from cortex.compat import upgrade_v4_to_v5
from cortex.extract_memory import AggressiveExtractor
from cortex.extract_memory import build_eval_compat_view as _build_eval_compat_view
from cortex.graph import CATEGORY_ORDER, CortexGraph, Edge, Node
from cortex.temporal import apply_temporal_review_policy

from .backend import ExtractionBackend
from .pipeline import (
    Document,
    empty_result,
    legacy_context_from_pipeline_context,
    result_from_backend_result,
)
from .pipeline import (
    ExtractionContext as PipelineExtractionContext,
)
from .pipeline import (
    ExtractionResult as PipelineExtractionResult,
)
from .types import ExtractedEdge, ExtractedNode, ExtractionResult


def _primary_tag(node: Node) -> str:
    for category in CATEGORY_ORDER:
        if category in node.tags:
            return category
    return node.tags[0] if node.tags else "mentions"


def result_from_graph(
    graph: CortexGraph,
    *,
    raw_source: str,
    extraction_method: str,
    warnings: list[str] | None = None,
) -> ExtractionResult:
    """Translate a CortexGraph into a backend-agnostic extraction result."""

    nodes = [
        ExtractedNode(
            label=node.label,
            category=_primary_tag(node),
            value=node.full_description or node.brief or node.label,
            confidence=node.confidence,
            canonical_match=(node.canonical_id if node.canonical_id and node.canonical_id != node.id else None),
            match_confidence=(
                float(node.properties.get("extraction_confidence"))
                if node.properties.get("extraction_confidence") is not None
                else None
            ),
            needs_review=bool(
                node.properties.get("temporal_review_pending")
                or node.properties.get("needs_review")
                or "requires_reviewer_approval" in list(node.properties.get("extraction_flags", []))
            ),
            embedding=(
                [float(item) for item in node.properties.get("embedding", [])]
                if isinstance(node.properties.get("embedding"), list)
                else None
            ),
        )
        for node in sorted(graph.nodes.values(), key=lambda item: (item.label.lower(), item.id))
    ]
    edges = [
        ExtractedEdge(
            source=graph.nodes[edge.source_id].label if edge.source_id in graph.nodes else edge.source_id,
            target=graph.nodes[edge.target_id].label if edge.target_id in graph.nodes else edge.target_id,
            relationship=edge.relation,
            direction_confidence=edge.confidence,
            needs_review=bool(edge.properties.get("needs_review") or edge.confidence < 0.6),
        )
        for edge in sorted(
            graph.edges.values(), key=lambda item: (item.source_id, item.target_id, item.relation, item.id)
        )
    ]
    return ExtractionResult(
        nodes=nodes,
        edges=edges,
        extraction_method=extraction_method,  # type: ignore[arg-type]
        raw_source=raw_source,
        warnings=list(warnings or []),
    )


def graph_from_result(
    result: ExtractionResult,
    *,
    fallback_statement: str = "",
    fallback_confidence: float = 0.85,
) -> CortexGraph:
    """Convert an extraction result into a CortexGraph."""

    cached = getattr(result, "_graph", None)
    if isinstance(cached, CortexGraph):
        return CortexGraph.from_v5_json(cached.export_v5())

    from cortex.portable_graphs import create_fallback_graph

    graph = CortexGraph()
    label_to_id: dict[str, str] = {}

    for node in result.nodes:
        from cortex.graph import make_node_id_with_tag

        graph_node = Node(
            id=make_node_id_with_tag(node.label, node.category or "mentions"),
            label=node.label,
            tags=[node.category or "mentions"],
            confidence=node.confidence,
            brief=node.value or node.label,
            full_description=node.value if node.value != node.label else "",
            canonical_id=node.canonical_match or "",
            properties={
                "extraction_confidence": node.match_confidence if node.match_confidence is not None else 0.0,
                "entity_resolution": "canonical_match" if node.canonical_match else "",
                "extraction_flags": ["needs_review"] if node.needs_review else [],
                "embedding": list(node.embedding) if node.embedding is not None else [],
                "needs_review": bool(node.needs_review),
            },
        )
        if not graph_node.canonical_id:
            graph_node.canonical_id = graph_node.id
        graph.add_node(graph_node)
        label_to_id.setdefault(node.label, graph_node.id)

    for edge in result.edges:
        from cortex.graph import make_edge_id, make_node_id_with_tag

        source_id = label_to_id.get(edge.source)
        if source_id is None:
            source_id = make_node_id_with_tag(edge.source, "mentions")
            if source_id not in graph.nodes:
                graph.add_node(
                    Node(
                        id=source_id,
                        label=edge.source,
                        tags=["mentions"],
                        confidence=0.3,
                        brief=edge.source,
                    )
                )
            label_to_id[edge.source] = source_id
        target_id = label_to_id.get(edge.target)
        if target_id is None:
            target_id = make_node_id_with_tag(edge.target, "mentions")
            if target_id not in graph.nodes:
                graph.add_node(
                    Node(
                        id=target_id,
                        label=edge.target,
                        tags=["mentions"],
                        confidence=0.3,
                        brief=edge.target,
                    )
                )
            label_to_id[edge.target] = target_id
        if source_id == target_id:
            continue
        graph.add_edge(
            Edge(
                id=make_edge_id(source_id, target_id, edge.relationship),
                source_id=source_id,
                target_id=target_id,
                relation=edge.relationship,
                confidence=edge.direction_confidence,
                properties={"needs_review": edge.needs_review},
            )
        )

    if graph.nodes:
        return graph
    if fallback_statement.strip():
        return create_fallback_graph(fallback_statement, confidence=fallback_confidence)
    return graph


def v4_from_result(
    result: ExtractionResult,
    *,
    fallback_statement: str = "",
    fallback_confidence: float = 0.85,
) -> dict[str, Any]:
    """Convert one extraction result into a v4-compatible payload."""

    cached = getattr(result, "_v4_output", None)
    if isinstance(cached, dict):
        return copy.deepcopy(cached)

    graph = graph_from_result(
        result,
        fallback_statement=fallback_statement,
        fallback_confidence=fallback_confidence,
    )
    payload = graph.export_v4()
    payload.update(_build_eval_compat_view(payload))
    contradictions = graph.meta.get("contradictions")
    if contradictions:
        payload["conflicts"] = list(contradictions)
    resolution_conflicts = graph.meta.get("resolution_conflicts")
    if resolution_conflicts:
        payload["resolution_conflicts"] = list(resolution_conflicts)
    return payload


def merged_graph_from_results(results: list[ExtractionResult]) -> CortexGraph:
    """Merge multiple extraction results into one graph."""

    from cortex.portable_graphs import merge_graphs

    merged = CortexGraph()
    for result in results:
        merged = merge_graphs(merged, graph_from_result(result))
    return merged


def merged_v4_from_results(results: list[ExtractionResult]) -> dict[str, Any]:
    """Merge multiple extraction results into one v4 payload."""

    if len(results) == 1:
        return v4_from_result(results[0])
    graph = merged_graph_from_results(results)
    payload = graph.export_v4()
    payload.update(_build_eval_compat_view(payload))
    return payload


class HeuristicBackend(ExtractionBackend):
    """Extraction backend that preserves the current heuristic pipeline."""

    def run(self, document: Document, context: PipelineExtractionContext) -> PipelineExtractionResult:
        """Run heuristic extraction through the unified pipeline contract."""

        started = perf_counter()
        if not document.content.strip():
            return empty_result(document, started_at=started)
        result = self.extract_statement(
            document.content,
            context=legacy_context_from_pipeline_context(context),
        )
        return result_from_backend_result(result, document=document, context=context, started_at=started)

    def extract_statement(
        self,
        text: str,
        context: dict | None = None,
    ) -> ExtractionResult:
        """Run the existing AggressiveExtractor on one statement."""

        extractor = None
        if context:
            candidate = context.get("extractor")
            if isinstance(candidate, AggressiveExtractor):
                extractor = candidate
        extractor = extractor or AggressiveExtractor()
        extractor.extract_from_text(text)
        extractor.post_process()
        payload = extractor.context.export()
        graph = upgrade_v4_to_v5(payload)
        if graph.nodes:
            apply_temporal_review_policy(graph)
        else:
            from cortex.portable_graphs import create_fallback_graph

            graph = create_fallback_graph(text, confidence=float((context or {}).get("confidence", 0.85)))
        result = result_from_graph(graph, raw_source=text, extraction_method="heuristic")
        result._graph = graph
        result._v4_output = payload
        return result

    def extract_bulk(
        self,
        texts: list[str],
        context: dict | None = None,
    ) -> list[ExtractionResult]:
        """Run the existing processing router over a batch of texts or parsed export data."""

        ctx = dict(context or {})
        extractor = ctx.get("extractor")
        data = ctx.get("data")
        fmt = str(ctx.get("fmt") or "")
        if isinstance(extractor, AggressiveExtractor) and fmt:
            if fmt == "openai":
                extractor.process_openai_export(data)
            elif fmt == "gemini":
                extractor.process_gemini_export(data)
            elif fmt == "perplexity":
                extractor.process_perplexity_export(data)
            elif fmt == "grok":
                extractor.process_grok_export(data)
            elif fmt == "cursor":
                extractor.process_cursor_export(data)
            elif fmt == "windsurf":
                extractor.process_windsurf_export(data)
            elif fmt == "copilot":
                extractor.process_copilot_export(data)
            elif fmt in ("jsonl", "claude_code"):
                extractor.process_jsonl_messages(data)
            elif fmt == "api_logs":
                extractor.process_api_logs(data)
            elif fmt == "messages":
                extractor.process_messages_list(
                    data["messages"] if isinstance(data, dict) and "messages" in data else data
                )
            elif fmt == "text":
                extractor.process_plain_text(data)
            else:
                if isinstance(data, list):
                    extractor.process_messages_list(data)
                elif isinstance(data, dict) and "messages" in data:
                    extractor.process_messages_list(data["messages"])
                else:
                    extractor.process_plain_text(json.dumps(data) if not isinstance(data, str) else data)
            payload = extractor.context.export()
            graph = upgrade_v4_to_v5(payload)
            result = result_from_graph(graph, raw_source="\n\n".join(texts), extraction_method="heuristic")
            result._graph = graph
            result._v4_output = payload
            return [result]

        return [self.extract_statement(text, context=context) for text in texts]

    def canonical_match(
        self,
        node: ExtractedNode,
        existing_nodes: list[dict],
    ) -> tuple[str | None, float]:
        """Heuristic extraction does not perform backend-level canonical matching."""

        return None, 0.0

    @property
    def supports_async_rescoring(self) -> bool:
        """Return false because the heuristic backend is fully synchronous."""

        return False

    @property
    def supports_embeddings(self) -> bool:
        """Return false because the heuristic backend does not emit embeddings."""

        return False
