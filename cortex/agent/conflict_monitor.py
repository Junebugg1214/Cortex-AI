"""Autonomous conflict monitoring for Cortex fact graphs."""

from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from cortex.atomic_io import atomic_write_json, locked_path
from cortex.graph import CATEGORY_ORDER, CortexGraph, Node
from cortex.intelligence import GapAnalyzer
from cortex.mind_runtime import _refresh_mind_mounts
from cortex.minds import _persist_mind_core_graph, load_mind_core_graph, resolve_default_mind
from cortex.portable_runtime import load_canonical_graph, load_portability_state, save_canonical_graph

DEFAULT_LOG_DIR = Path(__file__).resolve().parent / "logs"
SCOPE_SCALAR_TAGS = frozenset(
    {
        "identity",
        "professional_context",
        "business_context",
        "user_preferences",
        "communication_preferences",
        "values",
        "constraints",
    }
)
CRITICAL_TAGS = frozenset({"identity"})
HIGH_TAGS = frozenset({"professional_context", "business_context", "work_history", "education_history"})
LOW_TAGS = frozenset({"user_preferences", "communication_preferences"})
SAFETY_KEYWORDS = ("safety", "emergency", "danger", "hazard", "allergy")
MEDICAL_KEYWORDS = ("medical", "health", "medication", "diagnosis", "allergy")
FINANCIAL_KEYWORDS = ("financial", "finance", "salary", "compensation", "bank", "tax", "budget")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _agent_state_dir(store_dir: Path) -> Path:
    return Path(store_dir) / "agent"


def _monitor_registry_path(store_dir: Path) -> Path:
    return _agent_state_dir(store_dir) / "monitor_state.json"


def _pending_conflicts_path(store_dir: Path) -> Path:
    return _agent_state_dir(store_dir) / "pending_conflicts.json"


def _read_json(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)
    if not isinstance(payload, dict):
        return dict(default)
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_path(path):
        atomic_write_json(path, payload)


def _normalized_timestamp(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return cleaned
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def _timestamp_key(value: str) -> tuple[int, str]:
    normalized = _normalized_timestamp(value)
    if not normalized:
        return (0, "")
    return (1, normalized)


def _latest_lineage_timestamp(lineage: list[dict[str, Any]]) -> str:
    latest = ""
    for item in lineage:
        candidate = _normalized_timestamp(str(item.get("timestamp", "")))
        if candidate and candidate > latest:
            latest = candidate
    return latest


def _primary_tag(node: Node) -> str:
    for tag in CATEGORY_ORDER:
        if tag in node.tags:
            return tag
    return node.tags[0] if node.tags else "mentions"


def _clean_value(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _label_key_value(node: Node, primary: str) -> tuple[str, str] | None:
    if primary != "mentions":
        return None
    label = _clean_value(node.label)
    if ":" not in label:
        return None
    key, raw_value = label.split(":", 1)
    key = _clean_value(key).lower().replace(" ", "_")
    value = _clean_value(raw_value)
    if not key or not value:
        return None
    return key, value


def _lineage_for_node(node: Node) -> list[dict[str, Any]]:
    lineage: list[dict[str, Any]] = []
    for item in list(node.provenance) + list(node.snapshots):
        if not isinstance(item, dict):
            continue
        lineage.append(
            {
                "source": str(item.get("source", "")).strip(),
                "method": str(item.get("method", "")).strip(),
                "timestamp": _normalized_timestamp(str(item.get("timestamp", ""))),
                "quote": _clean_value(item.get("quote", "") or item.get("source_quote", "")),
            }
        )
    if not lineage:
        fallback_timestamp = _normalized_timestamp(node.last_seen or node.first_seen)
        lineage.append(
            {
                "source": "graph_state",
                "method": "graph_state",
                "timestamp": fallback_timestamp,
                "quote": "",
            }
        )
    lineage.sort(key=lambda item: _timestamp_key(item.get("timestamp", "")))
    return lineage


def _manual_support(lineage: list[dict[str, Any]]) -> float:
    for item in lineage:
        method = str(item.get("method", "")).lower()
        source = str(item.get("source", "")).lower()
        if method == "manual" or "manual" in source:
            return 1.0
    return 0.0


def _entity_for_node(node: Node, *, scope_entity: str, attribute: str) -> str:
    explicit = _clean_value(node.properties.get("entity", "")) or _clean_value(node.properties.get("subject", ""))
    if explicit:
        return explicit
    if attribute in SCOPE_SCALAR_TAGS:
        return scope_entity
    return _clean_value(node.canonical_id or node.label or node.id)


@dataclass(slots=True)
class FactVariant:
    """A comparable fact projected from a graph node."""

    node_id: str
    entity: str
    attribute: str
    value: str
    confidence: float
    field_kind: str
    field_key: str | None
    lineage: list[dict[str, Any]]
    tags: tuple[str, ...]

    @property
    def latest_timestamp(self) -> str:
        return _latest_lineage_timestamp(self.lineage)

    def source_labels(self) -> list[str]:
        labels = []
        seen: set[str] = set()
        for item in self.lineage:
            source = str(item.get("source", "")).strip()
            if source and source not in seen:
                seen.add(source)
                labels.append(source)
        return labels


@dataclass(slots=True)
class ResolutionCandidate:
    """A ranked conflict resolution option."""

    rank: int
    value: str
    node_ids: list[str]
    lineage: list[dict[str, Any]]
    support_count: int
    confidence_weight: float
    recency_weight: float
    combined_score: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "value": self.value,
            "node_ids": list(self.node_ids),
            "lineage": [dict(item) for item in self.lineage],
            "support_count": self.support_count,
            "confidence_weight": round(self.confidence_weight, 4),
            "recency_weight": round(self.recency_weight, 4),
            "combined_score": round(self.combined_score, 4),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResolutionCandidate":
        return cls(
            rank=int(payload.get("rank", 0)),
            value=str(payload.get("value", "")),
            node_ids=[str(item) for item in payload.get("node_ids", [])],
            lineage=[dict(item) for item in payload.get("lineage", [])],
            support_count=int(payload.get("support_count", 0)),
            confidence_weight=float(payload.get("confidence_weight", 0.0)),
            recency_weight=float(payload.get("recency_weight", 0.0)),
            combined_score=float(payload.get("combined_score", 0.0)),
            rationale=str(payload.get("rationale", "")),
        )


@dataclass(slots=True)
class ConflictProposal:
    """Structured proposal for a detected graph conflict."""

    conflict_id: str
    graph_scope: str
    graph_source: str
    mind_id: str | None
    entity: str
    attribute: str
    severity: str
    summary: str
    sources_in_tension: list[dict[str, Any]]
    candidates: list[ResolutionCandidate]
    requires_confirmation: bool
    confidence_delta: float
    detected_at: str
    auto_resolved: bool = False
    resolution_outcome: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "graph_scope": self.graph_scope,
            "graph_source": self.graph_source,
            "mind_id": self.mind_id,
            "entity": self.entity,
            "attribute": self.attribute,
            "severity": self.severity,
            "summary": self.summary,
            "sources_in_tension": [dict(item) for item in self.sources_in_tension],
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "requires_confirmation": self.requires_confirmation,
            "confidence_delta": round(self.confidence_delta, 4),
            "detected_at": self.detected_at,
            "auto_resolved": self.auto_resolved,
            "resolution_outcome": self.resolution_outcome,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ConflictProposal":
        return cls(
            conflict_id=str(payload.get("conflict_id", "")),
            graph_scope=str(payload.get("graph_scope", "")),
            graph_source=str(payload.get("graph_source", "")),
            mind_id=str(payload.get("mind_id", "")).strip() or None,
            entity=str(payload.get("entity", "")),
            attribute=str(payload.get("attribute", "")),
            severity=str(payload.get("severity", "LOW")),
            summary=str(payload.get("summary", "")),
            sources_in_tension=[dict(item) for item in payload.get("sources_in_tension", [])],
            candidates=[ResolutionCandidate.from_dict(item) for item in payload.get("candidates", [])],
            requires_confirmation=bool(payload.get("requires_confirmation", True)),
            confidence_delta=float(payload.get("confidence_delta", 0.0)),
            detected_at=str(payload.get("detected_at", "")),
            auto_resolved=bool(payload.get("auto_resolved", False)),
            resolution_outcome=str(payload.get("resolution_outcome", "pending")),
        )


@dataclass(slots=True)
class ConflictMonitorConfig:
    """Configuration for the conflict monitor loop."""

    store_dir: Path
    mind_id: str | None = None
    interval_seconds: int = 300
    auto_resolve_threshold: float = 0.85
    interactive: bool = True
    log_dir: Path = field(default_factory=lambda: DEFAULT_LOG_DIR)
    input_func: Callable[[str], str] = input


@dataclass(slots=True)
class MonitoredGraphContext:
    """A load/persist wrapper for the monitored graph source."""

    graph: CortexGraph
    graph_scope: str
    graph_source: str
    scope_entity: str
    mind_id: str | None
    persist: Callable[[CortexGraph, str], dict[str, Any]]


def _iter_fact_variants(graph: CortexGraph, *, scope_entity: str) -> list[FactVariant]:
    variants: list[FactVariant] = []
    for node in graph.nodes.values():
        lineage = _lineage_for_node(node)
        primary = _clean_value(node.properties.get("attribute", "")) or _primary_tag(node)
        label_pair = _label_key_value(node, primary)
        attribute = label_pair[0] if label_pair is not None else primary
        entity = (
            scope_entity
            if label_pair is not None
            else _entity_for_node(node, scope_entity=scope_entity, attribute=attribute)
        )
        base_value = _clean_value(node.properties.get("value", "")) or (
            label_pair[1] if label_pair is not None else _clean_value(node.label)
        )
        if base_value:
            variants.append(
                FactVariant(
                    node_id=node.id,
                    entity=entity,
                    attribute=attribute,
                    value=base_value,
                    confidence=float(node.confidence),
                    field_kind="label",
                    field_key=None,
                    lineage=list(lineage),
                    tags=tuple(node.tags),
                )
            )

        if _clean_value(node.status):
            variants.append(
                FactVariant(
                    node_id=node.id,
                    entity=entity,
                    attribute=f"{attribute}.status",
                    value=_clean_value(node.status),
                    confidence=float(node.confidence),
                    field_kind="status",
                    field_key=None,
                    lineage=list(lineage),
                    tags=tuple(node.tags),
                )
            )

        for field_name in ("valid_from", "valid_to"):
            value = _clean_value(getattr(node, field_name))
            if value:
                variants.append(
                    FactVariant(
                        node_id=node.id,
                        entity=entity,
                        attribute=f"{attribute}.{field_name}",
                        value=value,
                        confidence=float(node.confidence),
                        field_kind=field_name,
                        field_key=None,
                        lineage=list(lineage),
                        tags=tuple(node.tags),
                    )
                )

        for key, raw_value in sorted(node.properties.items()):
            if key in {"entity", "subject", "attribute", "value"}:
                continue
            value = _clean_value(raw_value)
            if not value:
                continue
            variants.append(
                FactVariant(
                    node_id=node.id,
                    entity=entity,
                    attribute=f"{attribute}.{key}",
                    value=value,
                    confidence=float(node.confidence),
                    field_kind="property",
                    field_key=key,
                    lineage=list(lineage),
                    tags=tuple(node.tags),
                )
            )
    return variants


def _severity_for_group(attribute: str, variants: list[FactVariant]) -> str:
    tag_set = {tag for variant in variants for tag in variant.tags}
    haystack = " ".join([attribute, *tag_set, *(variant.value for variant in variants)]).lower()
    if tag_set & CRITICAL_TAGS or any(keyword in haystack for keyword in SAFETY_KEYWORDS):
        return "CRITICAL"
    if tag_set & HIGH_TAGS or any(keyword in haystack for keyword in MEDICAL_KEYWORDS + FINANCIAL_KEYWORDS):
        return "HIGH"
    if tag_set & LOW_TAGS:
        return "LOW"
    return "HIGH"


def _conflict_id(entity: str, attribute: str, values: list[str], graph_scope: str) -> str:
    payload = json.dumps(
        {
            "entity": entity,
            "attribute": attribute,
            "values": sorted(values),
            "graph_scope": graph_scope,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def _candidate_scores(variants: list[FactVariant]) -> list[ResolutionCandidate]:
    if not variants:
        return []

    sorted_by_time = sorted(variants, key=lambda item: _timestamp_key(item.latest_timestamp))
    earliest_key = _timestamp_key(sorted_by_time[0].latest_timestamp)
    latest_key = _timestamp_key(sorted_by_time[-1].latest_timestamp)
    min_conf = min(item.confidence for item in variants)
    max_conf = max(item.confidence for item in variants)

    grouped: dict[str, list[FactVariant]] = {}
    for variant in variants:
        grouped.setdefault(variant.value, []).append(variant)

    candidates: list[ResolutionCandidate] = []
    for value, grouped_variants in grouped.items():
        best_variant = max(grouped_variants, key=lambda item: (item.confidence, _timestamp_key(item.latest_timestamp)))
        best_key = _timestamp_key(best_variant.latest_timestamp)
        if latest_key == earliest_key:
            recency_weight = 1.0
        else:
            numerator = 0.0
            denominator = 1.0
            if best_key[0] and latest_key[0]:
                best_dt = datetime.fromisoformat(best_key[1].replace("Z", "+00:00"))
                first_dt = datetime.fromisoformat(earliest_key[1].replace("Z", "+00:00"))
                last_dt = datetime.fromisoformat(latest_key[1].replace("Z", "+00:00"))
                numerator = max((best_dt - first_dt).total_seconds(), 0.0)
                denominator = max((last_dt - first_dt).total_seconds(), 1.0)
            recency_weight = numerator / denominator
        if max_conf == min_conf:
            confidence_weight = max_conf
        else:
            confidence_weight = (best_variant.confidence - min_conf) / max(max_conf - min_conf, 1e-9)
        corroboration_bonus = min(0.15, 0.05 * max(len(grouped_variants) - 1, 0))
        manual_bonus = 0.1 * _manual_support(best_variant.lineage)
        combined = min(1.0, 0.55 * confidence_weight + 0.3 * recency_weight + corroboration_bonus + manual_bonus)
        candidates.append(
            ResolutionCandidate(
                rank=0,
                value=value,
                node_ids=sorted({item.node_id for item in grouped_variants}),
                lineage=[dict(item) for item in best_variant.lineage],
                support_count=len(grouped_variants),
                confidence_weight=confidence_weight,
                recency_weight=recency_weight,
                combined_score=combined,
                rationale=(
                    f"Best-supported '{value}' combines confidence {best_variant.confidence:.2f}, "
                    f"recency weight {recency_weight:.2f}, and {len(grouped_variants)} supporting fact(s)."
                ),
            )
        )

    candidates.sort(key=lambda item: item.combined_score, reverse=True)
    for index, candidate in enumerate(candidates, start=1):
        candidate.rank = index
    return candidates[:3]


def _candidate_confidence_delta(candidates: list[ResolutionCandidate], variants: list[FactVariant]) -> float:
    if len(candidates) < 2:
        return 0.0
    confidence_by_value: dict[str, float] = {}
    for variant in variants:
        current = confidence_by_value.get(variant.value, 0.0)
        confidence_by_value[variant.value] = max(current, float(variant.confidence))
    first = confidence_by_value.get(candidates[0].value, 0.0)
    second = confidence_by_value.get(candidates[1].value, 0.0)
    return max(first - second, 0.0)


def detect_conflicts(
    graph: CortexGraph,
    *,
    graph_scope: str,
    graph_source: str,
    scope_entity: str,
    mind_id: str | None = None,
    auto_resolve_threshold: float = 0.85,
) -> list[ConflictProposal]:
    """Project the graph into source-aware facts and build conflict proposals."""
    grouped: dict[tuple[str, str], list[FactVariant]] = {}
    for variant in _iter_fact_variants(graph, scope_entity=scope_entity):
        grouped.setdefault((variant.entity, variant.attribute), []).append(variant)

    proposals: list[ConflictProposal] = []
    for (entity, attribute), variants in grouped.items():
        values = sorted({_clean_value(item.value) for item in variants if _clean_value(item.value)})
        if len(values) < 2:
            continue
        severity = _severity_for_group(attribute, variants)
        candidates = _candidate_scores(variants)
        if len(candidates) < 2:
            continue
        confidence_delta = _candidate_confidence_delta(candidates, variants)
        summary = (
            f"{entity} has conflicting '{attribute}' facts: "
            + ", ".join(f"'{candidate.value}'" for candidate in candidates[:3])
            + "."
        )
        proposals.append(
            ConflictProposal(
                conflict_id=_conflict_id(entity, attribute, values, graph_scope),
                graph_scope=graph_scope,
                graph_source=graph_source,
                mind_id=mind_id,
                entity=entity,
                attribute=attribute,
                severity=severity,
                summary=summary,
                sources_in_tension=[
                    {
                        "value": variant.value,
                        "node_id": variant.node_id,
                        "sources": variant.source_labels(),
                        "lineage": [dict(item) for item in variant.lineage],
                    }
                    for variant in sorted(
                        variants,
                        key=lambda item: (item.value.lower(), -item.confidence, item.node_id),
                    )
                ],
                candidates=candidates,
                requires_confirmation=severity in {"HIGH", "CRITICAL"} or confidence_delta < auto_resolve_threshold,
                confidence_delta=confidence_delta,
                detected_at=_utc_now(),
            )
        )
    proposals.sort(key=lambda item: (item.severity != "CRITICAL", item.severity == "LOW", -item.confidence_delta))
    return proposals


def load_pending_conflicts(store_dir: Path) -> list[ConflictProposal]:
    payload = _read_json(_pending_conflicts_path(store_dir), default={"conflicts": []})
    return [ConflictProposal.from_dict(item) for item in payload.get("conflicts", []) if isinstance(item, dict)]


def _save_pending_conflicts(store_dir: Path, proposals: list[ConflictProposal]) -> None:
    _write_json(
        _pending_conflicts_path(store_dir),
        {"conflicts": [proposal.to_dict() for proposal in proposals]},
    )


def load_monitor_registry(store_dir: Path) -> dict[str, Any]:
    return _read_json(_monitor_registry_path(store_dir), default={"active_monitors": []})


def _write_log(log_dir: Path, *, kind: str, conflict_id: str, outcome: str, payload: dict[str, Any]) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
    line = json.dumps(
        {
            "timestamp": _utc_now(),
            "kind": kind,
            "conflict_id": conflict_id,
            "outcome": outcome,
            **payload,
        },
        ensure_ascii=False,
    )
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    with locked_path(path):
        path.write_text(existing + line + "\n", encoding="utf-8")


def _replace_monitor_session(store_dir: Path, session_id: str, record: dict[str, Any] | None) -> None:
    path = _monitor_registry_path(store_dir)
    payload = load_monitor_registry(store_dir)
    active = [dict(item) for item in payload.get("active_monitors", []) if isinstance(item, dict)]
    active = [item for item in active if str(item.get("session_id", "")) != session_id]
    if record is not None:
        active.append(record)
    _write_json(path, {"active_monitors": active})


def _load_graph_context(store_dir: Path, *, requested_mind_id: str | None = None) -> MonitoredGraphContext:
    mind_id = requested_mind_id or resolve_default_mind(store_dir)
    if mind_id:
        payload = load_mind_core_graph(store_dir, mind_id)
        graph = payload["graph"]

        def persist(updated_graph: CortexGraph, message: str) -> dict[str, Any]:
            result = _persist_mind_core_graph(
                store_dir,
                mind_id,
                updated_graph,
                message=message,
                source="agent.conflict_monitor",
            )
            _refresh_mind_mounts(store_dir, mind_id)
            return result

        return MonitoredGraphContext(
            graph=graph,
            graph_scope=f"mind:{mind_id}",
            graph_source=str(payload.get("graph_source", "mind_branch")),
            scope_entity=mind_id,
            mind_id=mind_id,
            persist=persist,
        )

    state = load_portability_state(store_dir)
    graph, graph_path = load_canonical_graph(store_dir, state)

    def persist(updated_graph: CortexGraph, message: str) -> dict[str, Any]:
        updated_state = load_portability_state(store_dir)
        saved_state, saved_path = save_canonical_graph(store_dir, updated_graph, state=updated_state)
        return {
            "status": "ok",
            "graph_path": str(saved_path),
            "updated_at": saved_state.updated_at,
            "message": message,
        }

    return MonitoredGraphContext(
        graph=graph,
        graph_scope="portable:canonical",
        graph_source=str(graph_path),
        scope_entity="portable_context",
        mind_id=None,
        persist=persist,
    )


def _apply_candidate(graph: CortexGraph, proposal: ConflictProposal, candidate: ResolutionCandidate) -> dict[str, Any]:
    chosen_value = candidate.value
    chosen_nodes = set(candidate.node_ids)
    nodes_removed = 0
    nodes_updated = 0
    for entry in proposal.sources_in_tension:
        value = str(entry.get("value", ""))
        node_id = str(entry.get("node_id", ""))
        if value == chosen_value and node_id in chosen_nodes:
            continue
        node = graph.get_node(node_id)
        if node is None:
            continue
        if proposal.attribute.endswith(".status"):
            if node.status != chosen_value:
                node.status = chosen_value
                nodes_updated += 1
            continue
        if proposal.attribute.endswith(".valid_from"):
            if node.valid_from != chosen_value:
                node.valid_from = chosen_value
                nodes_updated += 1
            continue
        if proposal.attribute.endswith(".valid_to"):
            if node.valid_to != chosen_value:
                node.valid_to = chosen_value
                nodes_updated += 1
            continue
        if "." in proposal.attribute:
            property_key = proposal.attribute.rsplit(".", 1)[-1]
            if property_key in node.properties and _clean_value(node.properties.get(property_key)) != chosen_value:
                node.properties[property_key] = chosen_value
                nodes_updated += 1
            continue
        if graph.remove_node(node_id):
            nodes_removed += 1

    winner_node_id = next(iter(chosen_nodes), None)
    if winner_node_id:
        winner = graph.get_node(winner_node_id)
        if winner is not None:
            winner.confidence = max(winner.confidence, min(1.0, winner.confidence + 0.02))
            nodes_updated += 1

    return {
        "status": "ok",
        "conflict_id": proposal.conflict_id,
        "chosen_value": chosen_value,
        "nodes_removed": nodes_removed,
        "nodes_updated": nodes_updated,
    }


def review_pending_conflicts(
    store_dir: Path,
    *,
    input_func: Callable[[str], str] = input,
    echo: Callable[..., None] = print,
    log_dir: Path = DEFAULT_LOG_DIR,
) -> dict[str, Any]:
    """Prompt the user to review queued conflicts and apply chosen resolutions."""
    pending = load_pending_conflicts(store_dir)
    if not pending:
        return {"status": "ok", "reviewed": 0, "resolved": 0, "remaining": 0}

    pending_by_scope: dict[str, list[ConflictProposal]] = {}
    for proposal in pending:
        pending_by_scope.setdefault(proposal.graph_scope, []).append(proposal)

    resolved_ids: set[str] = set()
    resolved_count = 0
    for proposals in pending_by_scope.values():
        graph_context = _load_graph_context(store_dir, requested_mind_id=proposals[0].mind_id)
        changed = False
        for proposal in proposals:
            echo("")
            echo(f"[{proposal.severity}] {proposal.summary}")
            for candidate in proposal.candidates:
                echo(
                    f"  {candidate.rank}. Keep '{candidate.value}' "
                    f"(score={candidate.combined_score:.2f}; sources={', '.join(item.get('source', '') for item in candidate.lineage if item.get('source'))})"
                )
            echo("  s. Skip for now")
            choice = input_func("Choose a resolution: ").strip().lower()
            if choice in {"", "s", "skip"}:
                continue
            try:
                selected = next(candidate for candidate in proposal.candidates if candidate.rank == int(choice))
            except (StopIteration, ValueError):
                continue
            _apply_candidate(graph_context.graph, proposal, selected)
            proposal.resolution_outcome = "user_resolved"
            proposal.auto_resolved = False
            changed = True
            resolved_count += 1
            resolved_ids.add(proposal.conflict_id)
            _write_log(
                log_dir,
                kind="resolution",
                conflict_id=proposal.conflict_id,
                outcome="user_resolved",
                payload=proposal.to_dict(),
            )
        if changed:
            graph_context.persist(
                graph_context.graph,
                f"Resolve {resolved_count} queued agent conflict(s) for {graph_context.graph_scope}",
            )

    remaining = [proposal for proposal in pending if proposal.conflict_id not in resolved_ids]
    _save_pending_conflicts(store_dir, remaining)
    return {
        "status": "ok",
        "reviewed": len(pending),
        "resolved": resolved_count,
        "remaining": len(remaining),
    }


def review_pending_conflicts_with_decisions(
    store_dir: Path,
    decisions: list[dict[str, Any]],
    *,
    log_dir: Path = DEFAULT_LOG_DIR,
    allowed_conflict_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Apply explicit review decisions to queued conflicts without prompting."""
    pending = load_pending_conflicts(store_dir)
    if not pending:
        return {"status": "ok", "reviewed": 0, "resolved": 0, "remaining": 0}

    allowed = set(allowed_conflict_ids or ())
    target_pending = [proposal for proposal in pending if not allowed_conflict_ids or proposal.conflict_id in allowed]
    if not target_pending:
        return {"status": "ok", "reviewed": 0, "resolved": 0, "remaining": len(pending)}

    decision_map: dict[str, dict[str, Any]] = {}
    for item in decisions:
        if not isinstance(item, dict):
            continue
        conflict_id = str(item.get("conflict_id", "")).strip()
        if not conflict_id:
            continue
        if allowed_conflict_ids and conflict_id not in allowed:
            continue
        decision_map[conflict_id] = dict(item)

    target_ids = {proposal.conflict_id for proposal in target_pending}
    target_by_scope: dict[str, list[ConflictProposal]] = {}
    for proposal in target_pending:
        target_by_scope.setdefault(proposal.graph_scope, []).append(proposal)

    resolved_ids: set[str] = set()
    resolved_count = 0
    for proposals in target_by_scope.values():
        graph_context = _load_graph_context(store_dir, requested_mind_id=proposals[0].mind_id)
        changed = False
        for proposal in proposals:
            decision = decision_map.get(proposal.conflict_id)
            if not decision or bool(decision.get("skip", False)):
                continue
            try:
                candidate_rank = int(decision.get("candidate_rank", 0))
            except (TypeError, ValueError):
                continue
            try:
                selected = next(candidate for candidate in proposal.candidates if candidate.rank == candidate_rank)
            except StopIteration:
                continue
            _apply_candidate(graph_context.graph, proposal, selected)
            proposal.resolution_outcome = "user_resolved"
            proposal.auto_resolved = False
            changed = True
            resolved_count += 1
            resolved_ids.add(proposal.conflict_id)
            _write_log(
                log_dir,
                kind="resolution",
                conflict_id=proposal.conflict_id,
                outcome="user_resolved",
                payload=proposal.to_dict(),
            )
        if changed:
            graph_context.persist(
                graph_context.graph,
                f"Resolve {resolved_count} queued agent conflict(s) for {graph_context.graph_scope}",
            )

    remaining = [proposal for proposal in pending if proposal.conflict_id not in resolved_ids]
    _save_pending_conflicts(store_dir, remaining)
    remaining_target = [proposal for proposal in remaining if proposal.conflict_id in target_ids]
    return {
        "status": "ok",
        "reviewed": len(target_pending),
        "resolved": resolved_count,
        "remaining": len(remaining_target),
        "remaining_total": len(remaining),
    }


class ConflictMonitor:
    """Background loop that detects and queues graph conflicts."""

    def __init__(self, config: ConflictMonitorConfig) -> None:
        self.config = config
        self.store_dir = Path(config.store_dir)
        self.log_dir = Path(config.log_dir)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._session_id = uuid4().hex[:16]

    def _session_record(self) -> dict[str, Any]:
        return {
            "session_id": self._session_id,
            "pid": os.getpid(),
            "mind_id": self.config.mind_id,
            "interval_seconds": self.config.interval_seconds,
            "auto_resolve_threshold": self.config.auto_resolve_threshold,
            "interactive": self.config.interactive,
            "started_at": _utc_now(),
        }

    def start(self) -> None:
        """Start monitoring in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        _replace_monitor_session(self.store_dir, self._session_id, self._session_record())
        self._thread = threading.Thread(target=self.run_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background monitor thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.config.interval_seconds + 2)
            self._thread = None
        _replace_monitor_session(self.store_dir, self._session_id, None)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run_forever(self) -> None:
        """Run the monitor loop until stopped."""
        _replace_monitor_session(self.store_dir, self._session_id, self._session_record())
        try:
            while not self._stop_event.is_set():
                self.run_cycle()
                if self._stop_event.wait(self.config.interval_seconds):
                    break
        finally:
            _replace_monitor_session(self.store_dir, self._session_id, None)

    def run_cycle(self) -> dict[str, Any]:
        """Run a single monitoring cycle."""
        graph_context = _load_graph_context(self.store_dir, requested_mind_id=self.config.mind_id)
        proposals = detect_conflicts(
            graph_context.graph,
            graph_scope=graph_context.graph_scope,
            graph_source=graph_context.graph_source,
            scope_entity=graph_context.scope_entity,
            mind_id=graph_context.mind_id,
            auto_resolve_threshold=self.config.auto_resolve_threshold,
        )

        pending = {proposal.conflict_id: proposal for proposal in load_pending_conflicts(self.store_dir)}

        auto_resolved = 0
        queued = 0
        changed = False
        for proposal in proposals:
            _write_log(
                self.log_dir,
                kind="detection",
                conflict_id=proposal.conflict_id,
                outcome="detected",
                payload=proposal.to_dict(),
            )
            if proposal.severity == "LOW" and proposal.confidence_delta >= self.config.auto_resolve_threshold:
                selected = proposal.candidates[0]
                _apply_candidate(graph_context.graph, proposal, selected)
                proposal.auto_resolved = True
                proposal.requires_confirmation = False
                proposal.resolution_outcome = "auto_resolved"
                auto_resolved += 1
                changed = True
                pending.pop(proposal.conflict_id, None)
                _write_log(
                    self.log_dir,
                    kind="resolution",
                    conflict_id=proposal.conflict_id,
                    outcome="auto_resolved",
                    payload=proposal.to_dict(),
                )
                continue

            proposal.resolution_outcome = "queued"
            pending[proposal.conflict_id] = proposal
            queued += 1
            _write_log(
                self.log_dir,
                kind="proposal",
                conflict_id=proposal.conflict_id,
                outcome="queued",
                payload=proposal.to_dict(),
            )

        _save_pending_conflicts(self.store_dir, list(pending.values()))

        if changed:
            graph_context.persist(
                graph_context.graph,
                f"Auto-resolve {auto_resolved} low-severity conflict(s) for {graph_context.graph_scope}",
            )

        reviewed = 0
        if self.config.interactive and sys.stdin.isatty():
            review_result = review_pending_conflicts(
                self.store_dir,
                input_func=self.config.input_func,
                echo=print,
                log_dir=self.log_dir,
            )
            reviewed = int(review_result.get("resolved", 0))

        return {
            "status": "ok",
            "graph_scope": graph_context.graph_scope,
            "graph_source": graph_context.graph_source,
            "mind_id": graph_context.mind_id,
            "detected": len(proposals),
            "auto_resolved": auto_resolved,
            "queued": queued,
            "reviewed": reviewed,
            "pending": len(load_pending_conflicts(self.store_dir)),
            "proposals": [proposal.to_dict() for proposal in proposals],
        }


def conflict_status(store_dir: Path) -> dict[str, Any]:
    """Return monitor state and pending conflict summaries."""
    pending = load_pending_conflicts(store_dir)
    registry = load_monitor_registry(store_dir)
    return {
        "active_monitors": [dict(item) for item in registry.get("active_monitors", []) if isinstance(item, dict)],
        "pending_conflicts": [proposal.to_dict() for proposal in pending],
        "pending_count": len(pending),
    }


def professional_history_flags(graph: CortexGraph) -> list[dict[str, Any]]:
    """Return professional-history gaps and conflict summaries for CV generation."""
    gap_analyzer = GapAnalyzer()
    flags: list[dict[str, Any]] = []

    for gap in gap_analyzer.temporal_gaps(graph):
        node = graph.get_node(str(gap.get("node_id", "")))
        if node is None:
            continue
        if not set(node.tags) & HIGH_TAGS:
            continue
        flags.append({"type": "temporal_gap", **gap})

    employment_nodes = [
        node for node in graph.nodes.values() if "work_history" in node.tags or "professional_context" in node.tags
    ]
    dated_nodes = [
        node
        for node in employment_nodes
        if _normalized_timestamp(node.valid_from or "") or _normalized_timestamp(node.valid_to or "")
    ]
    dated_nodes.sort(key=lambda item: (_normalized_timestamp(item.valid_from or ""), item.label.lower()))
    for first, second in zip(dated_nodes, dated_nodes[1:]):
        first_end = _normalized_timestamp(first.valid_to or "")
        second_start = _normalized_timestamp(second.valid_from or "")
        if first_end and second_start and first_end < second_start:
            first_dt = datetime.fromisoformat(first_end.replace("Z", "+00:00"))
            second_dt = datetime.fromisoformat(second_start.replace("Z", "+00:00"))
            gap_days = (second_dt - first_dt).days
            if gap_days > 1:
                flags.append(
                    {
                        "type": "employment_gap",
                        "label": f"{first.label} -> {second.label}",
                        "kind": "employment_gap",
                        "days": gap_days,
                        "valid_from": second_start,
                        "valid_to": first_end,
                    }
                )

    for proposal in detect_conflicts(
        graph,
        graph_scope="professional",
        graph_source="professional_subgraph",
        scope_entity="professional_history",
        auto_resolve_threshold=1.0,
    ):
        if proposal.severity in {"HIGH", "CRITICAL"}:
            flags.append(
                {
                    "type": "conflict",
                    "conflict_id": proposal.conflict_id,
                    "severity": proposal.severity,
                    "summary": proposal.summary,
                }
            )
    return flags


__all__ = [
    "ConflictMonitor",
    "ConflictMonitorConfig",
    "ConflictProposal",
    "ResolutionCandidate",
    "conflict_status",
    "detect_conflicts",
    "load_monitor_registry",
    "load_pending_conflicts",
    "professional_history_flags",
    "review_pending_conflicts",
    "review_pending_conflicts_with_decisions",
]
