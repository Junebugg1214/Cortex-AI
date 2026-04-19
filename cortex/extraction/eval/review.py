from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .runner import EvaluationError, run_extraction_eval

InputFunc = Callable[[str], str]
OutputFunc = Callable[[str], None]

REVIEW_ACTIONS = {"true_failure", "gold_is_wrong"}


@dataclass(frozen=True)
class ReviewItem:
    """One failure selected for operator review."""

    case: dict[str, Any]
    failure: dict[str, Any]
    index: int


@dataclass(frozen=True)
class ReviewOutcome:
    """Completed extraction review flow."""

    summary_path: Path
    reviewed: int
    true_failures: int
    gold_patches: int
    baseline_updated: bool


def run_extraction_review(
    report_path: str | Path,
    *,
    input_func: InputFunc | None = None,
    output_func: OutputFunc = print,
    docs_dir: str | Path = Path("docs") / "extraction-reviews",
    timestamp: datetime | None = None,
) -> ReviewOutcome:
    """Walk an extraction eval report and optionally patch gold labels."""

    report_file = Path(report_path)
    report = _read_report(report_file)
    input_func = input if input_func is None else input_func
    corpus_root = Path(str(report.get("corpus") or "tests/extraction/corpus"))
    items = _review_items(report)
    decisions: list[dict[str, Any]] = []
    patched_files: set[Path] = set()

    if not items:
        output_func("No extraction failures found in report.")

    for position, item in enumerate(items, start=1):
        failure = item.failure
        output_func("")
        output_func(f"[{position}/{len(items)}] {item.case.get('case_id')} :: {failure.get('kind')}")
        output_func(_format_pair(failure.get("pair")))
        action = _prompt_action(input_func)
        patched = False
        gold_path = _gold_path(corpus_root, item.case)
        if action == "gold_is_wrong":
            patched = _patch_gold_file(gold_path, failure)
            if patched:
                patched_files.add(gold_path)
        decisions.append(
            {
                "case_id": item.case.get("case_id", ""),
                "kind": failure.get("kind", ""),
                "action": action,
                "patched": patched,
                "gold": str(gold_path),
                "pair": failure.get("pair", {}),
            }
        )

    baseline_updated = False
    if patched_files:
        run_extraction_eval(
            corpus=corpus_root,
            backend=str(report.get("backend") or "heuristic"),  # type: ignore[arg-type]
            tolerance=float((report.get("baseline") or {}).get("tolerance") or 0.01),
            prompt_version=str(report.get("prompt_version") or "corpus-v1"),
            update_baseline=True,
        )
        baseline_updated = True

    summary_path = _write_review_summary(
        docs_dir=Path(docs_dir),
        report_path=report_file,
        report=report,
        decisions=decisions,
        patched_files=patched_files,
        baseline_updated=baseline_updated,
        timestamp=timestamp or datetime.now(timezone.utc),
    )
    output_func("")
    output_func(f"Review summary: {summary_path}")
    if baseline_updated:
        output_func(f"Updated baseline: {corpus_root / 'baseline.json'}")
    return ReviewOutcome(
        summary_path=summary_path,
        reviewed=len(decisions),
        true_failures=sum(1 for item in decisions if item["action"] == "true_failure"),
        gold_patches=sum(1 for item in decisions if item["patched"]),
        baseline_updated=baseline_updated,
    )


def _read_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise EvaluationError(f"Extraction eval report not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvaluationError(f"Extraction eval report must be a JSON object: {path}")
    return payload


def _review_items(report: dict[str, Any]) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    cases = report.get("cases")
    if not isinstance(cases, list):
        return items
    for case in cases:
        if not isinstance(case, dict):
            continue
        failures = case.get("failures")
        if not isinstance(failures, list):
            failures = _failures_from_case_metrics(case)
        for failure in failures:
            if isinstance(failure, dict) and failure.get("kind"):
                items.append(ReviewItem(case=case, failure=failure, index=len(items)))
    return _dedupe_review_items(items)


def _failures_from_case_metrics(case: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = case.get("metrics")
    if not isinstance(metrics, dict):
        return []
    failures: list[dict[str, Any]] = []
    for metric in metrics.values():
        if isinstance(metric, dict) and isinstance(metric.get("failures"), list):
            failures.extend(item for item in metric["failures"] if isinstance(item, dict))
    return failures


def _dedupe_review_items(items: list[ReviewItem]) -> list[ReviewItem]:
    seen: set[str] = set()
    result: list[ReviewItem] = []
    for item in items:
        key = json.dumps(
            {
                "case_id": item.case.get("case_id", ""),
                "failure": item.failure,
            },
            sort_keys=True,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(ReviewItem(case=item.case, failure=item.failure, index=len(result)))
    return result


def _prompt_action(input_func: InputFunc) -> str:
    while True:
        raw = input_func("Mark as [t] true_failure or [g] gold_is_wrong: ").strip().lower()
        if raw in {"", "t", "true", "true_failure"}:
            return "true_failure"
        if raw in {"g", "gold", "gold_is_wrong"}:
            return "gold_is_wrong"
        print("Please enter `true_failure` or `gold_is_wrong`.")


def _gold_path(corpus_root: Path, case: dict[str, Any]) -> Path:
    return corpus_root / str(case.get("case_id", "")) / str(case.get("gold") or "gold.json")


def _patch_gold_file(path: Path, failure: dict[str, Any]) -> bool:
    if not path.exists():
        raise EvaluationError(f"Gold file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvaluationError(f"Gold file must be a JSON object: {path}")
    changed = _patch_gold_payload(payload, failure)
    if changed:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return changed


def _patch_gold_payload(payload: dict[str, Any], failure: dict[str, Any]) -> bool:
    graph = payload.setdefault("expected_graph", {})
    if not isinstance(graph, dict):
        graph = {}
        payload["expected_graph"] = graph
    graph.setdefault("nodes", [])
    graph.setdefault("edges", [])
    kind = str(failure.get("kind") or "")
    pair = failure.get("pair") if isinstance(failure.get("pair"), dict) else {}
    gold = pair.get("gold") if isinstance(pair.get("gold"), dict) else None
    predicted = pair.get("predicted") if isinstance(pair.get("predicted"), dict) else None

    if kind == "hallucinated_node" and predicted:
        return _add_gold_node(graph, predicted)
    if kind == "missed_node" and gold:
        return _remove_gold_node(graph, gold)
    if kind == "wrong_type" and gold and predicted:
        return _update_gold_node_type(graph, gold, predicted)
    if kind == "hallucinated_relation" and predicted:
        return _add_gold_edge(graph, predicted)
    if kind in {"missed_relation", "missed_contradiction"} and gold:
        return _remove_gold_edge(graph, gold)
    if kind == "bad_canonicalization":
        return _patch_gold_alias(graph, pair)
    return False


def _add_gold_node(graph: dict[str, Any], predicted: dict[str, Any]) -> bool:
    nodes = _nodes(graph)
    label = _clean(predicted.get("label") or predicted.get("canonical_label") or predicted.get("id"))
    node_type = _clean(predicted.get("type") or "mentions")
    if not label:
        return False
    if any(_node_matches(node, {"label": label, "type": node_type}) for node in nodes):
        return False
    node_id = _clean(predicted.get("canonical_id") or predicted.get("id")) or f"{_slug(node_type)}:{_slug(label)}"
    nodes.append(
        {
            "id": node_id,
            "canonical_id": node_id,
            "label": label,
            "type": node_type,
            "confidence": float(predicted.get("confidence") or 0.9),
        }
    )
    return True


def _remove_gold_node(graph: dict[str, Any], gold: dict[str, Any]) -> bool:
    nodes = _nodes(graph)
    removed_values: set[str] = set()
    kept_nodes: list[dict[str, Any]] = []
    changed = False
    for node in nodes:
        if _node_matches(node, gold):
            changed = True
            removed_values.update(_node_identity_values(node))
        else:
            kept_nodes.append(node)
    if changed:
        graph["nodes"] = kept_nodes
        graph["edges"] = [
            edge
            for edge in _edges(graph)
            if _normalize(edge.get("source")) not in removed_values
            and _normalize(edge.get("target")) not in removed_values
        ]
    return changed


def _update_gold_node_type(graph: dict[str, Any], gold: dict[str, Any], predicted: dict[str, Any]) -> bool:
    predicted_type = _clean(predicted.get("type") or predicted.get("category"))
    if not predicted_type:
        return False
    for node in _nodes(graph):
        if _node_matches(node, gold):
            if node.get("type") == predicted_type:
                return False
            node["type"] = predicted_type
            return True
    return False


def _add_gold_edge(graph: dict[str, Any], predicted: dict[str, Any]) -> bool:
    edges = _edges(graph)
    relation = _clean(predicted.get("type") or predicted.get("relation") or predicted.get("relationship"))
    source = _ensure_node_reference(graph, _clean(predicted.get("source") or predicted.get("source_label")))
    target = _ensure_node_reference(graph, _clean(predicted.get("target") or predicted.get("target_label")))
    if not source or not target or not relation:
        return False
    candidate = {"source": source, "target": target, "type": relation}
    if any(_edge_matches(edge, candidate, graph) for edge in edges):
        return False
    edges.append(
        {
            "id": _unique_edge_id(edges, source, relation, target),
            "source": source,
            "target": target,
            "type": relation,
            "confidence": float(predicted.get("confidence") or 0.9),
        }
    )
    return True


def _remove_gold_edge(graph: dict[str, Any], gold: dict[str, Any]) -> bool:
    edges = _edges(graph)
    kept_edges = [edge for edge in edges if not _edge_matches(edge, gold, graph)]
    changed = len(kept_edges) != len(edges)
    if changed:
        graph["edges"] = kept_edges
    return changed


def _patch_gold_alias(graph: dict[str, Any], pair: dict[str, Any]) -> bool:
    alias = _clean(pair.get("alias"))
    predicted = pair.get("predicted") if isinstance(pair.get("predicted"), dict) else {}
    predicted_id = _clean(predicted.get("canonical_id") if isinstance(predicted, dict) else "")
    if not alias:
        return False
    aliases = graph.setdefault("alias_resolutions", [])
    if not isinstance(aliases, list):
        aliases = []
        graph["alias_resolutions"] = aliases
    before = list(aliases)
    aliases[:] = [
        item for item in aliases if not (isinstance(item, dict) and _normalize(item.get("alias")) == _normalize(alias))
    ]
    if predicted_id:
        aliases.append({"alias": alias, "canonical_id": predicted_id})
    return aliases != before


def _ensure_node_reference(graph: dict[str, Any], label: str) -> str:
    if not label:
        return ""
    for node in _nodes(graph):
        if _normalize(label) in _node_identity_values(node):
            return _clean(node.get("canonical_id") or node.get("id") or node.get("label"))
    node_id = f"mentions:{_slug(label)}"
    _nodes(graph).append(
        {
            "id": node_id,
            "canonical_id": node_id,
            "label": label,
            "type": "mentions",
            "confidence": 0.7,
        }
    )
    return node_id


def _nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = graph.setdefault("nodes", [])
    if not isinstance(nodes, list):
        nodes = []
        graph["nodes"] = nodes
    return nodes


def _edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    edges = graph.setdefault("edges", [])
    if not isinstance(edges, list):
        edges = []
        graph["edges"] = edges
    return edges


def _node_matches(node: dict[str, Any], wanted: dict[str, Any]) -> bool:
    wanted_values = {
        _normalize(wanted.get("id")),
        _normalize(wanted.get("canonical_id")),
        _normalize(wanted.get("label") or wanted.get("canonical_label")),
    }
    wanted_values.discard("")
    if not wanted_values:
        return False
    if (
        _clean(wanted.get("type"))
        and _clean(node.get("type"))
        and _clean(wanted.get("type")) != _clean(node.get("type"))
    ):
        return False
    return bool(_node_identity_values(node) & wanted_values)


def _node_identity_values(node: dict[str, Any]) -> set[str]:
    values = {
        _normalize(node.get("id")),
        _normalize(node.get("canonical_id")),
        _normalize(node.get("label") or node.get("canonical_label")),
    }
    return {value for value in values if value}


def _edge_matches(edge: dict[str, Any], wanted: dict[str, Any], graph: dict[str, Any]) -> bool:
    relation = _normalize(wanted.get("type") or wanted.get("relation") or wanted.get("relationship"))
    if relation and _normalize(edge.get("type") or edge.get("relation") or edge.get("relationship")) != relation:
        return False
    source = _normalize(wanted.get("source") or wanted.get("source_label"))
    target = _normalize(wanted.get("target") or wanted.get("target_label"))
    return source in _edge_endpoint_values(edge, "source", graph) and target in _edge_endpoint_values(
        edge, "target", graph
    )


def _edge_endpoint_values(edge: dict[str, Any], key: str, graph: dict[str, Any]) -> set[str]:
    raw = _normalize(edge.get(key))
    values = {raw} if raw else set()
    for node in _nodes(graph):
        if raw in _node_identity_values(node):
            values.update(_node_identity_values(node))
    return values


def _unique_edge_id(edges: list[dict[str, Any]], source: str, relation: str, target: str) -> str:
    base = f"edge:{_slug(source)}:{_slug(relation)}:{_slug(target)}"
    used = {_clean(edge.get("id")) for edge in edges}
    if base not in used:
        return base
    counter = 2
    while f"{base}-{counter}" in used:
        counter += 1
    return f"{base}-{counter}"


def _write_review_summary(
    *,
    docs_dir: Path,
    report_path: Path,
    report: dict[str, Any],
    decisions: list[dict[str, Any]],
    patched_files: set[Path],
    baseline_updated: bool,
    timestamp: datetime,
) -> Path:
    docs_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = docs_dir / f"extraction-review-{stamp}.md"
    lines = [
        f"# Extraction Review {stamp}",
        "",
        f"- Report: `{report_path}`",
        f"- Corpus: `{report.get('corpus', '')}`",
        f"- Backend: `{report.get('backend', '')}`",
        f"- Reviewed failures: {len(decisions)}",
        f"- True failures: {sum(1 for item in decisions if item['action'] == 'true_failure')}",
        f"- Gold patches: {sum(1 for item in decisions if item['patched'])}",
        f"- Baseline updated: {'yes' if baseline_updated else 'no'}",
        "",
        "## Decisions",
        "",
    ]
    if not decisions:
        lines.append("No failures were present in the report.")
    for decision in decisions:
        lines.append(
            f"- `{decision['case_id']}` `{decision['kind']}` -> `{decision['action']}`"
            f"{' (patched gold)' if decision['patched'] else ''}"
        )
    if patched_files:
        lines.extend(["", "## Patched Gold Files", ""])
        for patched_file in sorted(patched_files):
            lines.append(f"- `{patched_file}`")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def _format_pair(pair: Any) -> str:
    if not isinstance(pair, dict):
        return "pair: <missing>"
    return json.dumps(pair, ensure_ascii=False, indent=2, sort_keys=True)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize(value: Any) -> str:
    return _clean(value).lower()


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-") or "unknown"


__all__ = ["ReviewOutcome", "run_extraction_review"]
