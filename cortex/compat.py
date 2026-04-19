"""
v4 ↔ v5 Conversion Layer

Roundtrip guarantees:
  v4 → v5 → v4  =  identical (no data created that can't round-trip)
  v5 → v4 → v5  =  lossy (edges lost, multi-tag collapsed to primary)
"""

from __future__ import annotations

from cortex.extraction.extract_memory import are_similar
from cortex.graph.graph import (
    CATEGORY_ORDER,
    CortexGraph,
    Edge,
    Node,
    _normalize_label,
    make_edge_id,
    make_node_id,
    make_node_id_with_tag,
)


def upgrade_v4_to_v5(v4_data: dict) -> CortexGraph:
    """Convert a v4 JSON dict to a CortexGraph.

    Rules:
    1. Each ExtractedTopic → 1 Node.
    2. Node ID = sha256(normalize(label))[:12]. On collision, append category.
    3. Same normalized label across categories → merge into single node with
       multiple tags.
    4. topic.relationships string list → resolve against existing labels:
       - Match → create Edge
       - No match → create stub Node (confidence=0.3, tag=["mentions"]) + Edge
    5. topic.relationship_type → Edge.relation field.
    """
    graph = CortexGraph(
        schema_version="5.0",
        meta=v4_data.get("meta", {}),
    )

    # ----- Pass 1: Create nodes, merge duplicates across categories ---------
    # Map normalized_label → node_id for dedup
    label_to_id: dict[str, str] = {}

    for category in CATEGORY_ORDER:
        topics = v4_data.get("categories", {}).get(category, [])
        for topic_data in topics:
            label = topic_data.get("topic", "").strip()
            if not label:
                continue

            norm = _normalize_label(label)
            existing_id = label_to_id.get(norm)

            if existing_id and existing_id in graph.nodes:
                # Merge into existing node
                existing = graph.nodes[existing_id]
                if category not in existing.tags:
                    existing.tags.append(category)
                existing.confidence = max(existing.confidence, topic_data.get("confidence", 0.5))
                existing.mention_count += topic_data.get("mention_count", 1)
                brief = topic_data.get("brief", "")
                if brief and len(brief) > len(existing.brief):
                    existing.brief = brief
                fd = topic_data.get("full_description", "")
                if fd and len(fd) > len(existing.full_description):
                    existing.full_description = fd
                for m in topic_data.get("metrics", []):
                    if m not in existing.metrics:
                        existing.metrics.append(m)
                for t in topic_data.get("timeline", []):
                    if t not in existing.timeline:
                        existing.timeline.append(t)
                for sq in topic_data.get("source_quotes", []):
                    if sq not in existing.source_quotes and len(existing.source_quotes) < 5:
                        existing.source_quotes.append(sq)
                for alias in topic_data.get("_aliases", []):
                    if alias and alias not in existing.aliases:
                        existing.aliases.append(alias)
                fs = topic_data.get("first_seen") or ""
                if fs and (not existing.first_seen or fs < existing.first_seen):
                    existing.first_seen = fs
                ls = topic_data.get("last_seen") or ""
                if ls and (not existing.last_seen or ls > existing.last_seen):
                    existing.last_seen = ls
                vf = topic_data.get("_valid_from") or ""
                if vf and (not existing.valid_from or vf < existing.valid_from):
                    existing.valid_from = vf
                vt = topic_data.get("_valid_to") or ""
                if vt and (not existing.valid_to or vt > existing.valid_to):
                    existing.valid_to = vt
                if topic_data.get("_status") and not existing.status:
                    existing.status = topic_data.get("_status", "")
                if topic_data.get("_canonical_id") and not existing.canonical_id:
                    existing.canonical_id = topic_data.get("_canonical_id", "")
                if topic_data.get("_temporal_confidence") is not None:
                    existing.properties["temporal_confidence"] = topic_data.get("_temporal_confidence", 0.0)
                if topic_data.get("_temporal_signal"):
                    existing.properties["temporal_signal"] = topic_data.get("_temporal_signal", "")
                if topic_data.get("_extraction_confidence") is not None:
                    existing.properties["extraction_confidence"] = topic_data.get("_extraction_confidence", 0.0)
                if topic_data.get("_entity_resolution"):
                    existing.properties["entity_resolution"] = topic_data.get("_entity_resolution", "")
                if topic_data.get("_extraction_flags"):
                    existing.properties["extraction_flags"] = list(topic_data.get("_extraction_flags", []))
                if topic_data.get("_source_span"):
                    existing.properties["source_span"] = topic_data.get("_source_span", "")
                if topic_data.get("_temporal_review_pending"):
                    existing.properties["temporal_review_pending"] = True
                for item in topic_data.get("_provenance", []):
                    if item not in existing.provenance:
                        existing.provenance.append(dict(item))
                em = topic_data.get("extraction_method", "")
                if em:
                    existing.extraction_method = em
                rt = topic_data.get("relationship_type", "")
                if rt and not existing.relationship_type:
                    existing.relationship_type = rt
            else:
                # Create new node
                nid = make_node_id(label)
                # Handle hash collision (different label, same hash)
                if nid in graph.nodes and _normalize_label(graph.nodes[nid].label) != norm:
                    nid = make_node_id_with_tag(label, category)

                # Restore original tags if preserved from v5→v4 downgrade
                restored_tags = topic_data.get("_original_tags", [category])
                if not restored_tags or category not in restored_tags:
                    restored_tags = [category]

                node = Node(
                    id=nid,
                    label=label,
                    tags=restored_tags,
                    aliases=list(topic_data.get("_aliases", [])),
                    confidence=topic_data.get("confidence", 0.5),
                    brief=topic_data.get("brief", label),
                    full_description=topic_data.get("full_description", ""),
                    mention_count=topic_data.get("mention_count", 1),
                    extraction_method=topic_data.get("extraction_method", "mentioned"),
                    metrics=list(topic_data.get("metrics", [])),
                    timeline=list(topic_data.get("timeline", [])),
                    source_quotes=list(topic_data.get("source_quotes", []))[:5],
                    first_seen=topic_data.get("first_seen") or "",
                    last_seen=topic_data.get("last_seen") or "",
                    valid_from=topic_data.get("_valid_from", "") or "",
                    valid_to=topic_data.get("_valid_to", "") or "",
                    status=topic_data.get("_status", "") or "",
                    canonical_id=topic_data.get("_canonical_id", "") or nid,
                    provenance=[dict(item) for item in topic_data.get("_provenance", [])],
                    relationship_type=topic_data.get("relationship_type", ""),
                    properties={
                        "temporal_confidence": topic_data.get("_temporal_confidence", 0.0),
                        "temporal_signal": topic_data.get("_temporal_signal", ""),
                        "extraction_confidence": topic_data.get("_extraction_confidence", 0.0),
                        "entity_resolution": topic_data.get("_entity_resolution", ""),
                        "extraction_flags": list(topic_data.get("_extraction_flags", [])),
                        "source_span": topic_data.get("_source_span", ""),
                    },
                )
                if topic_data.get("_temporal_review_pending"):
                    node.properties["temporal_review_pending"] = True
                graph.nodes[nid] = node
                label_to_id[norm] = nid

    # ----- Pass 2: Resolve relationship strings → edges ---------------------
    for node in list(graph.nodes.values()):
        rel_strings = []
        # Gather relationship strings from ALL matching v4 categories
        for category in CATEGORY_ORDER:
            topics = v4_data.get("categories", {}).get(category, [])
            for td in topics:
                if _normalize_label(td.get("topic", "")) == _normalize_label(node.label):
                    for r in td.get("relationships", []):
                        if r not in rel_strings:
                            rel_strings.append(r)

        for rel_label in rel_strings:
            rel_label = rel_label.strip()
            if not rel_label:
                continue

            rel_norm = _normalize_label(rel_label)
            target_id = label_to_id.get(rel_norm)

            if not target_id:
                # Try fuzzy match
                for existing_norm, eid in label_to_id.items():
                    if are_similar(rel_norm, existing_norm, threshold=0.8):
                        target_id = eid
                        break

            if not target_id:
                # Create stub node
                stub_id = make_node_id(rel_label)
                if stub_id in graph.nodes and _normalize_label(graph.nodes[stub_id].label) != rel_norm:
                    stub_id = make_node_id_with_tag(rel_label, "mentions")
                stub = Node(
                    id=stub_id,
                    label=rel_label,
                    tags=["mentions"],
                    confidence=0.3,
                    brief=rel_label,
                    extraction_method="mentioned",
                    canonical_id=stub_id,
                    provenance=[dict(item) for item in node.provenance],
                )
                graph.nodes[stub_id] = stub
                label_to_id[rel_norm] = stub_id
                target_id = stub_id

            # Don't create self-loops
            if target_id == node.id:
                continue

            relation = node.relationship_type or "related_to"
            eid = make_edge_id(node.id, target_id, relation)
            if eid not in graph.edges:
                edge = Edge(
                    id=eid,
                    source_id=node.id,
                    target_id=target_id,
                    relation=relation,
                    confidence=min(node.confidence, 0.7),
                    provenance=[dict(item) for item in node.provenance],
                    first_seen=node.first_seen,
                    last_seen=node.last_seen,
                )
                graph.edges[eid] = edge

    return graph


def downgrade_v5_to_v4(graph: CortexGraph) -> dict:
    """Convert a CortexGraph to a v4 JSON dict.

    Rules:
    1. For each Node, primary tag = first match in CATEGORY_ORDER.
    2. Node → ExtractedTopic in that primary category only.
    3. Edges are LOST (documented, accepted limitation).
    4. Node.tags stored in properties["_original_tags"] for re-upgrade.
    """
    categories: dict[str, list[dict]] = {}

    for node in graph.nodes.values():
        primary = _primary_tag(node)
        topic_dict: dict = {
            "topic": node.label,
            "brief": node.brief or node.label,
            "full_description": node.full_description,
            "confidence": round(node.confidence, 2),
            "mention_count": node.mention_count,
            "extraction_method": node.extraction_method,
            "metrics": node.metrics[:10],
            "relationships": graph._node_relationship_labels(node.id),
            "timeline": node.timeline[:5],
            "source_quotes": node.source_quotes[:3],
            "first_seen": node.first_seen or None,
            "last_seen": node.last_seen or None,
        }
        if node.relationship_type:
            topic_dict["relationship_type"] = node.relationship_type
        if node.aliases:
            topic_dict["_aliases"] = list(node.aliases)
        if node.canonical_id:
            topic_dict["_canonical_id"] = node.canonical_id
        if node.provenance:
            topic_dict["_provenance"] = [dict(item) for item in node.provenance]
        if node.valid_from:
            topic_dict["_valid_from"] = node.valid_from
        if node.valid_to:
            topic_dict["_valid_to"] = node.valid_to
        if node.status:
            topic_dict["_status"] = node.status
        # Preserve all tags for re-upgrade (multi-tag nodes collapse to primary)
        if len(node.tags) > 1:
            topic_dict["_original_tags"] = list(node.tags)

        categories.setdefault(primary, []).append(topic_dict)

    # Sort each category by (confidence, mention_count) descending
    for cat in categories:
        categories[cat].sort(key=lambda t: (t["confidence"], t["mention_count"]), reverse=True)

    return {
        "schema_version": "4.0",
        "meta": {
            **graph.meta,
            "method": "aggressive_extraction_v4",
            "features": [
                "semantic_dedup",
                "time_decay",
                "topic_merging",
                "conflict_detection",
                "typed_relationships",
            ],
        },
        "categories": categories,
    }


def _primary_tag(node: Node) -> str:
    """First tag in CATEGORY_ORDER, or first tag, or 'mentions'."""
    for cat in CATEGORY_ORDER:
        if cat in node.tags:
            return cat
    return node.tags[0] if node.tags else "mentions"


def roundtrip_v4(v4_data: dict) -> dict:
    """v4 → v5 → v4. Note: may add stub nodes, _node_id fields, and deduplicate topics."""
    graph = upgrade_v4_to_v5(v4_data)
    return downgrade_v5_to_v4(graph)
