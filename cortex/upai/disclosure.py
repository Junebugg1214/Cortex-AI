"""
Selective Disclosure — Filter graph nodes by policy before export.

Policies control which nodes are visible to a given platform or audience.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from cortex.graph import CortexGraph


@dataclass
class DisclosurePolicy:
    name: str                     # "professional", "technical", "full", "minimal"
    include_tags: list[str]       # tags to include (empty = all)
    exclude_tags: list[str]       # tags to exclude
    min_confidence: float         # confidence floor
    redact_properties: list[str]  # property keys to strip
    max_nodes: int = 0            # 0 = unlimited


BUILTIN_POLICIES = {
    "full": DisclosurePolicy(
        name="full",
        include_tags=[],
        exclude_tags=[],
        min_confidence=0.0,
        redact_properties=[],
    ),
    "professional": DisclosurePolicy(
        name="professional",
        include_tags=[
            "identity", "professional_context", "business_context",
            "technical_expertise", "active_priorities",
        ],
        exclude_tags=["negations", "correction_history"],
        min_confidence=0.6,
        redact_properties=[],
    ),
    "technical": DisclosurePolicy(
        name="technical",
        include_tags=[
            "technical_expertise", "domain_knowledge", "active_priorities",
        ],
        exclude_tags=[],
        min_confidence=0.5,
        redact_properties=[],
    ),
    "minimal": DisclosurePolicy(
        name="minimal",
        include_tags=["identity", "communication_preferences"],
        exclude_tags=[],
        min_confidence=0.8,
        redact_properties=[],
    ),
}


def apply_disclosure(graph: CortexGraph, policy: DisclosurePolicy) -> CortexGraph:
    """Return a filtered deep copy of the graph based on disclosure policy.

    - Filter nodes by include_tags/exclude_tags/min_confidence
    - Strip redact_properties from node.properties
    - Cap at max_nodes (highest confidence first)
    - Remove edges where either endpoint was filtered out
    """
    result = CortexGraph(
        schema_version=graph.schema_version,
        meta=copy.deepcopy(graph.meta),
    )

    # Collect candidate nodes
    candidates = []
    for nid, node in graph.nodes.items():
        # Confidence filter
        if node.confidence < policy.min_confidence:
            continue

        # Exclude tags filter
        if policy.exclude_tags and any(t in policy.exclude_tags for t in node.tags):
            continue

        # Include tags filter (empty = include all)
        if policy.include_tags:
            if not any(t in policy.include_tags for t in node.tags):
                continue

        candidates.append((nid, node))

    # Sort by confidence descending for max_nodes cap
    candidates.sort(key=lambda x: x[1].confidence, reverse=True)

    # Cap at max_nodes
    if policy.max_nodes > 0:
        candidates = candidates[:policy.max_nodes]

    # Build result graph
    included_ids = set()
    for nid, node in candidates:
        node_copy = copy.deepcopy(node)

        # Redact properties
        for prop_key in policy.redact_properties:
            node_copy.properties.pop(prop_key, None)

        result.nodes[nid] = node_copy
        included_ids.add(nid)

    # Include edges where both endpoints exist
    for eid, edge in graph.edges.items():
        if edge.source_id in included_ids and edge.target_id in included_ids:
            result.edges[eid] = copy.deepcopy(edge)

    return result
