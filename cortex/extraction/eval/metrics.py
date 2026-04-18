from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

Breakdown = dict[str, int | float | str]


@dataclass(frozen=True)
class MetricReport:
    """Scalar metric result with enough counts to debug score movement."""

    value: float
    numerator: int | float
    denominator: int | float
    per_class_breakdown: dict[str, Breakdown] = field(default_factory=dict)


@dataclass(frozen=True)
class _NodeRecord:
    id: str
    canonical_id: str
    canonical_label: str
    type: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class _EdgeRecord:
    source: str
    relation: str
    target: str


@dataclass(frozen=True)
class _GraphRecords:
    nodes: tuple[_NodeRecord, ...]
    edges: tuple[_EdgeRecord, ...]
    contradictions: tuple[_EdgeRecord, ...]
    alias_resolutions: dict[str, str]


def node_prf(predicted: Any, gold: Any) -> tuple[MetricReport, MetricReport, MetricReport]:
    """Return precision, recall, and F1 for nodes matched by ``(type, canonical_label)``."""

    predicted_graph = _coerce_graph(predicted)
    gold_graph = _coerce_graph(gold)
    predicted_keys = Counter(_node_key(node) for node in predicted_graph.nodes)
    gold_keys = Counter(_node_key(node) for node in gold_graph.nodes)
    return _prf(predicted_keys, gold_keys, class_index=0)


def relation_prf(predicted: Any, gold: Any) -> tuple[MetricReport, MetricReport, MetricReport]:
    """Return precision, recall, and F1 for relations matched by endpoint labels and relation type."""

    predicted_graph = _coerce_graph(predicted)
    gold_graph = _coerce_graph(gold)
    predicted_keys = Counter(_edge_key(edge) for edge in predicted_graph.edges)
    gold_keys = Counter(_edge_key(edge) for edge in gold_graph.edges)
    return _prf(predicted_keys, gold_keys, class_index=1)


def canonicalization_accuracy(predicted: Any, gold: Any) -> MetricReport:
    """Return the fraction of gold aliases mapped to the expected gold canonical IDs."""

    predicted_graph = _coerce_graph(predicted)
    gold_graph = _coerce_graph(gold)
    expected = gold_graph.alias_resolutions
    actual = predicted_graph.alias_resolutions
    matched_aliases = {
        alias
        for alias, canonical_id in expected.items()
        if alias in actual and _normalize_id(actual[alias]) == _normalize_id(canonical_id)
    }
    breakdown: dict[str, Breakdown] = {}
    for alias, canonical_id in sorted(expected.items()):
        breakdown[alias] = _breakdown(
            1 if alias in matched_aliases else 0,
            1,
            expected_canonical_id=canonical_id,
            predicted_canonical_id=actual.get(alias, ""),
        )
    return _metric(len(matched_aliases), len(expected), breakdown)


def contradiction_recall(predicted: Any, gold: Any) -> MetricReport:
    """Return the fraction of gold contradictions detected by the prediction."""

    predicted_graph = _coerce_graph(predicted)
    gold_graph = _coerce_graph(gold)
    predicted_keys = Counter(_contradiction_key(edge) for edge in predicted_graph.contradictions)
    gold_keys = Counter(_contradiction_key(edge) for edge in gold_graph.contradictions)
    true_positives = _intersection_count(predicted_keys, gold_keys)

    breakdown: dict[str, Breakdown] = {}
    for key in sorted(set(gold_keys)):
        matched = min(predicted_keys.get(key, 0), gold_keys[key])
        class_name = _class_key(key[1])
        current = breakdown.setdefault(class_name, _breakdown(0, 0))
        current["numerator"] += matched
        current["denominator"] += gold_keys[key]
        current["value"] = _safe_divide(current["numerator"], current["denominator"])
    return _metric(true_positives, sum(gold_keys.values()), breakdown)


def completeness_score(predicted: Any, gold: Any) -> MetricReport:
    """Return the fraction of gold nodes with any predicted canonical-label match."""

    predicted_graph = _coerce_graph(predicted)
    gold_graph = _coerce_graph(gold)
    remaining_labels = Counter(_normalize_label(node.canonical_label) for node in predicted_graph.nodes)
    matched = 0

    breakdown: dict[str, Breakdown] = {}
    for node in gold_graph.nodes:
        label = _normalize_label(node.canonical_label)
        node_type = _class_key(node.type)
        current = breakdown.setdefault(node_type, _breakdown(0, 0))
        current["denominator"] += 1
        if remaining_labels.get(label, 0) > 0:
            current["numerator"] += 1
            matched += 1
            remaining_labels[label] -= 1
        current["value"] = _safe_divide(current["numerator"], current["denominator"])
    return _metric(matched, len(gold_graph.nodes), breakdown)


def _coerce_graph(payload: Any) -> _GraphRecords:
    if payload is None:
        return _GraphRecords(nodes=(), edges=(), contradictions=(), alias_resolutions={})

    nodes_payload, edges_payload, explicit_contradictions, explicit_aliases = _extract_payload_parts(payload)
    nodes = tuple(_coerce_node(node) for node in nodes_payload)
    node_labels = _node_label_index(nodes)
    edges = tuple(_coerce_edge(edge, node_labels) for edge in edges_payload)
    contradictions = tuple(_coerce_edge(item, node_labels) for item in explicit_contradictions)
    contradictions = contradictions + tuple(edge for edge in edges if _is_contradiction(edge.relation))
    aliases = _alias_resolutions(nodes, explicit_aliases, gold_label_to_id=_gold_label_to_id(nodes))
    return _GraphRecords(nodes=nodes, edges=edges, contradictions=contradictions, alias_resolutions=aliases)


def _extract_payload_parts(payload: Any) -> tuple[list[Any], list[Any], list[Any], Any]:
    if hasattr(payload, "nodes") and hasattr(payload, "edges"):
        nodes = (
            list(getattr(payload, "nodes").values())
            if isinstance(getattr(payload, "nodes"), dict)
            else list(payload.nodes)
        )
        edges = (
            list(getattr(payload, "edges").values())
            if isinstance(getattr(payload, "edges"), dict)
            else list(payload.edges)
        )
        contradictions = list(getattr(payload, "meta", {}).get("contradictions", []))
        aliases = getattr(payload, "meta", {}).get("alias_resolutions", [])
        return nodes, edges, contradictions, aliases

    if isinstance(payload, list):
        return list(payload), [], [], []

    if not isinstance(payload, dict):
        return [], [], [], []

    graph_payload = payload.get("expected_graph") or payload.get("graph") or payload
    nodes = list(graph_payload.get("nodes", [])) if isinstance(graph_payload, dict) else []
    edges = list(graph_payload.get("edges", [])) if isinstance(graph_payload, dict) else []
    contradictions = []
    aliases: Any = []
    if isinstance(graph_payload, dict):
        contradictions.extend(graph_payload.get("contradictions", []))
        contradictions.extend(graph_payload.get("conflicts", []))
        aliases = graph_payload.get("alias_resolutions") or graph_payload.get("aliases") or []
    contradictions.extend(payload.get("contradictions", []))
    contradictions.extend(payload.get("conflicts", []))
    aliases = payload.get("alias_resolutions") or payload.get("aliases") or aliases
    return nodes, edges, contradictions, aliases


def _coerce_node(node: Any) -> _NodeRecord:
    if isinstance(node, dict):
        node_id = _string(node.get("id") or node.get("node_id") or node.get("canonical_id"))
        label = _string(node.get("canonical_label") or node.get("label") or node.get("name") or node_id)
        canonical_id = _string(node.get("canonical_id") or node_id)
        node_type = _node_type(node)
        aliases = _aliases_from_node(node)
        return _NodeRecord(
            id=node_id,
            canonical_id=canonical_id or node_id,
            canonical_label=label,
            type=node_type,
            aliases=aliases,
        )

    node_id = _string(getattr(node, "id", "") or getattr(node, "canonical_id", ""))
    label = _string(
        getattr(node, "canonical_label", "") or getattr(node, "label", "") or getattr(node, "name", "") or node_id
    )
    canonical_id = _string(getattr(node, "canonical_id", "") or node_id)
    tags = getattr(node, "tags", [])
    node_type = _string(getattr(node, "type", "") or getattr(node, "category", "") or (tags[0] if tags else "mentions"))
    aliases = tuple(_string(alias) for alias in getattr(node, "aliases", []) if _string(alias))
    return _NodeRecord(
        id=node_id,
        canonical_id=canonical_id or node_id,
        canonical_label=label,
        type=node_type or "mentions",
        aliases=aliases,
    )


def _coerce_edge(edge: Any, node_labels: dict[str, str]) -> _EdgeRecord:
    if isinstance(edge, dict):
        source = _string(edge.get("source_label") or edge.get("source") or edge.get("source_id") or edge.get("from"))
        target = _string(edge.get("target_label") or edge.get("target") or edge.get("target_id") or edge.get("to"))
        relation = _string(
            edge.get("relation") or edge.get("type") or edge.get("relationship") or edge.get("predicate")
        )
        node_ids = edge.get("node_ids")
        if (not source or not target) and isinstance(node_ids, list) and len(node_ids) >= 2:
            source = source or _string(node_ids[0])
            target = target or _string(node_ids[1])
        return _EdgeRecord(
            source=node_labels.get(source, source),
            relation=relation or "related_to",
            target=node_labels.get(target, target),
        )

    source = _string(getattr(edge, "source_label", "") or getattr(edge, "source", "") or getattr(edge, "source_id", ""))
    target = _string(getattr(edge, "target_label", "") or getattr(edge, "target", "") or getattr(edge, "target_id", ""))
    relation = _string(getattr(edge, "relation", "") or getattr(edge, "type", "") or getattr(edge, "relationship", ""))
    return _EdgeRecord(
        source=node_labels.get(source, source),
        relation=relation or "related_to",
        target=node_labels.get(target, target),
    )


def _node_type(node: dict[str, Any]) -> str:
    tags = node.get("tags")
    return _string(
        node.get("type")
        or node.get("category")
        or node.get("node_type")
        or (tags[0] if isinstance(tags, list) and tags else "")
        or "mentions"
    )


def _aliases_from_node(node: dict[str, Any]) -> tuple[str, ...]:
    aliases = node.get("aliases", [])
    if isinstance(aliases, dict):
        aliases = aliases.keys()
    if not isinstance(aliases, list | tuple | set):
        return ()
    result: list[str] = []
    for alias in aliases:
        if isinstance(alias, dict):
            alias_value = _string(alias.get("alias") or alias.get("label") or alias.get("name"))
        else:
            alias_value = _string(alias)
        if alias_value:
            result.append(alias_value)
    return tuple(result)


def _node_label_index(nodes: tuple[_NodeRecord, ...]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for node in nodes:
        for key in (node.id, node.canonical_id, node.canonical_label, *node.aliases):
            if key:
                labels[key] = node.canonical_label
    return labels


def _gold_label_to_id(nodes: tuple[_NodeRecord, ...]) -> dict[str, str]:
    return {_normalize_label(node.canonical_label): node.canonical_id for node in nodes}


def _alias_resolutions(
    nodes: tuple[_NodeRecord, ...], explicit_aliases: Any, gold_label_to_id: dict[str, str]
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in nodes:
        for alias in node.aliases:
            alias_key = _normalize_label(alias)
            if alias_key:
                aliases[alias_key] = node.canonical_id

    if isinstance(explicit_aliases, dict):
        for alias, canonical_id in explicit_aliases.items():
            alias_key = _normalize_label(_string(alias))
            if alias_key:
                aliases[alias_key] = _canonical_id_from_alias_payload(canonical_id, gold_label_to_id)
        return aliases

    if not isinstance(explicit_aliases, list | tuple | set):
        return aliases

    for item in explicit_aliases:
        if isinstance(item, dict):
            alias = _string(item.get("alias") or item.get("label") or item.get("name"))
            canonical_id = _canonical_id_from_alias_payload(
                item.get("canonical_id") or item.get("node_id") or item.get("target_id") or item.get("canonical_label"),
                gold_label_to_id,
            )
        else:
            continue
        alias_key = _normalize_label(alias)
        if alias_key and canonical_id:
            aliases[alias_key] = canonical_id
    return aliases


def _canonical_id_from_alias_payload(value: Any, gold_label_to_id: dict[str, str]) -> str:
    canonical_id = _string(value)
    if not canonical_id:
        return ""
    return gold_label_to_id.get(_normalize_label(canonical_id), canonical_id)


def _prf(
    predicted: Counter[tuple[str, ...]],
    gold: Counter[tuple[str, ...]],
    *,
    class_index: int,
) -> tuple[MetricReport, MetricReport, MetricReport]:
    true_positives = _intersection_count(predicted, gold)
    predicted_total = sum(predicted.values())
    gold_total = sum(gold.values())
    precision = _metric(
        true_positives,
        predicted_total,
        _per_class_breakdown(predicted, gold, class_index=class_index, denominator_source="predicted"),
    )
    recall = _metric(
        true_positives,
        gold_total,
        _per_class_breakdown(predicted, gold, class_index=class_index, denominator_source="gold"),
    )
    f1_denominator = predicted_total + gold_total
    f1 = _metric(
        2 * true_positives,
        f1_denominator,
        _per_class_breakdown(predicted, gold, class_index=class_index, denominator_source="f1"),
    )
    return precision, recall, f1


def _per_class_breakdown(
    predicted: Counter[tuple[str, ...]],
    gold: Counter[tuple[str, ...]],
    *,
    class_index: int,
    denominator_source: str,
) -> dict[str, Breakdown]:
    classes = {_class_key(key[class_index]) for key in set(predicted) | set(gold)}
    breakdown: dict[str, Breakdown] = {}
    for class_name in sorted(classes):
        predicted_count = sum(count for key, count in predicted.items() if _class_key(key[class_index]) == class_name)
        gold_count = sum(count for key, count in gold.items() if _class_key(key[class_index]) == class_name)
        matched = sum(
            min(predicted.get(key, 0), gold.get(key, 0))
            for key in set(predicted) | set(gold)
            if _class_key(key[class_index]) == class_name
        )
        if denominator_source == "predicted":
            breakdown[class_name] = _breakdown(matched, predicted_count)
        elif denominator_source == "gold":
            breakdown[class_name] = _breakdown(matched, gold_count)
        else:
            breakdown[class_name] = _breakdown(2 * matched, predicted_count + gold_count)
    return breakdown


def _metric(
    numerator: int | float,
    denominator: int | float,
    per_class_breakdown: dict[str, Breakdown] | None = None,
) -> MetricReport:
    return MetricReport(
        value=_safe_divide(numerator, denominator),
        numerator=numerator,
        denominator=denominator,
        per_class_breakdown=per_class_breakdown or {},
    )


def _breakdown(numerator: int | float, denominator: int | float, **extra: int | float | str) -> Breakdown:
    result: Breakdown = {
        "value": _safe_divide(numerator, denominator),
        "numerator": numerator,
        "denominator": denominator,
    }
    result.update(extra)
    return result


def _intersection_count(left: Counter[Any], right: Counter[Any]) -> int:
    return sum(min(left.get(key, 0), right.get(key, 0)) for key in set(left) | set(right))


def _node_key(node: _NodeRecord) -> tuple[str, str]:
    return (_class_key(node.type), _normalize_label(node.canonical_label))


def _edge_key(edge: _EdgeRecord) -> tuple[str, str, str]:
    return (_normalize_label(edge.source), _class_key(edge.relation), _normalize_label(edge.target))


def _contradiction_key(edge: _EdgeRecord) -> tuple[str, str, str]:
    endpoints = sorted((_normalize_label(edge.source), _normalize_label(edge.target)))
    return (endpoints[0] if endpoints else "", _class_key(edge.relation), endpoints[1] if len(endpoints) > 1 else "")


def _is_contradiction(relation: str) -> bool:
    normalized = _class_key(relation)
    return normalized in {"contradicts", "contradiction", "conflicts_with", "in_conflict_with"}


def _normalize_label(label: str) -> str:
    text = unicodedata.normalize("NFKD", _string(label)).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return " ".join(text.split())


def _normalize_id(value: str) -> str:
    return _string(value).strip()


def _class_key(value: str) -> str:
    return _normalize_label(value).replace(" ", "_") or "unknown"


def _safe_divide(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 0.0
    return float(numerator) / float(denominator)


def _string(value: Any) -> str:
    return str(value).strip() if value is not None else ""
