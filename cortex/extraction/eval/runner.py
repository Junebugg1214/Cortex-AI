from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from cortex.extraction.eval.metrics import (
    ExtractionFailure,
    MetricReport,
    canonicalization_accuracy,
    completeness_score,
    contradiction_recall,
    node_prf,
    relation_prf,
)
from cortex.extraction.eval.replay_cache import ReplayCache, ReplayMode
from cortex.extraction.extract_memory_context import ExtractedClaim, ExtractedFact, ExtractedRelationship
from cortex.extraction.pipeline import Document, ExtractionContext, ExtractionPipeline

BackendName = Literal["heuristic", "model", "hybrid"]

REPORT_SCHEMA_VERSION = "extraction-eval-report-v1"
BASELINE_SCHEMA_VERSION = "extraction-eval-baseline-v1"
DEFAULT_PROMPT_VERSION = "corpus-v1"
METRIC_NAMES = (
    "node_precision",
    "node_recall",
    "node_f1",
    "relation_precision",
    "relation_recall",
    "relation_f1",
    "canonicalization_accuracy",
    "contradiction_recall",
    "completeness_score",
)


class EvaluationError(RuntimeError):
    """Raised when an extraction eval run cannot complete."""


@dataclass(frozen=True)
class CorpusCase:
    """One extraction eval corpus case."""

    case_id: str
    source_type: str
    input_name: str
    gold_name: str
    description: str = ""

    @property
    def manifest_payload(self) -> dict[str, str]:
        return {
            "id": self.case_id,
            "source_type": self.source_type,
            "input": self.input_name,
            "gold": self.gold_name,
            "description": self.description,
        }


@dataclass(frozen=True)
class EvaluationOutcome:
    """Completed extraction eval run."""

    report: dict[str, Any]
    summary: str
    regressions: list[dict[str, Any]]

    @property
    def failed(self) -> bool:
        return bool(self.regressions)


@dataclass(frozen=True)
class RefreshOutcome:
    """Completed replay-cache refresh run."""

    refreshed: int
    cache_hits: int
    replay_root: Path


def load_corpus_cases(corpus_root: str | Path) -> list[CorpusCase]:
    """Load corpus cases from a minimal manifest.yml."""

    root = Path(corpus_root)
    manifest_path = root / "manifest.yml"
    if not root.exists():
        raise EvaluationError(f"Extraction corpus not found: {root}")
    if not manifest_path.exists():
        raise EvaluationError(f"Extraction corpus manifest not found: {manifest_path}")

    raw_cases = _parse_corpus_manifest(manifest_path)
    cases: list[CorpusCase] = []
    for raw in raw_cases:
        case_id = raw.get("id", "").strip()
        source_type = raw.get("source_type", "").strip()
        input_name = raw.get("input", "").strip()
        gold_name = raw.get("gold", "").strip() or "gold.json"
        if not case_id or not source_type or not input_name:
            raise EvaluationError(f"Invalid corpus manifest case entry: {raw}")
        cases.append(
            CorpusCase(
                case_id=case_id,
                source_type=source_type,
                input_name=input_name,
                gold_name=gold_name,
                description=raw.get("description", "").strip(),
            )
        )
    if not cases:
        raise EvaluationError(f"No corpus cases found in {manifest_path}")
    return cases


def run_extraction_eval(
    *,
    corpus: str | Path,
    backend: BackendName,
    tolerance: float = 0.01,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    prompt_overrides: dict[str, str] | None = None,
    update_baseline: bool = False,
    replay_root: str | Path | None = None,
    provider_name: str | None = None,
    model_id: str | None = None,
) -> EvaluationOutcome:
    """Run the extraction eval corpus and compare against the committed baseline."""

    corpus_root = Path(corpus)
    baseline_path = corpus_root / "baseline.json"
    cases = load_corpus_cases(corpus_root)
    backend_instance = _make_backend(
        backend,
        replay_root=Path(replay_root) if replay_root else corpus_root / "replay",
        provider_name=provider_name,
        model_id=model_id,
    )
    public_cases: list[dict[str, Any]] = []
    case_metric_reports: list[dict[str, MetricReport]] = []
    try:
        for case in cases:
            public_case, reports = _evaluate_case(
                corpus_root=corpus_root,
                case=case,
                backend=backend_instance,
                prompt_version=prompt_version,
                prompt_overrides=prompt_overrides,
            )
            public_cases.append(public_case)
            case_metric_reports.append(reports)
    finally:
        close = getattr(backend_instance, "close", None)
        if callable(close):
            close()

    aggregate_metrics = _aggregate_metrics(case_metric_reports)
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "backend": backend,
        "prompt_version": prompt_version,
        "corpus": str(corpus_root),
        "case_count": len(public_cases),
        "metrics": aggregate_metrics,
        "cases": public_cases,
    }

    if update_baseline:
        baseline = _baseline_from_report(report)
        _write_json(baseline_path, baseline)
    else:
        baseline = _read_baseline(baseline_path)

    baseline_section = _compare_to_baseline(
        current_metrics=aggregate_metrics,
        baseline=baseline,
        baseline_path=baseline_path,
        tolerance=tolerance,
        updated=update_baseline,
    )
    report["baseline"] = baseline_section
    summary = format_eval_summary(report)
    return EvaluationOutcome(report=report, summary=summary, regressions=list(baseline_section["regressions"]))


def write_eval_report(report: dict[str, Any], output_path: str | Path) -> Path:
    """Write a deterministic JSON report."""

    path = Path(output_path)
    _write_json(path, report)
    return path


def refresh_extraction_replay_cache(
    *,
    corpus: str | Path,
    backend_name: BackendName = "model",
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    replay_root: str | Path | None = None,
    provider_name: str | None = None,
    model_id: str | None = None,
    output_func: Any | None = None,
) -> RefreshOutcome:
    """Refresh replay responses for a model-backed extraction eval corpus run."""

    corpus_root = Path(corpus)
    resolved_replay_root = Path(replay_root) if replay_root else corpus_root / "replay"
    if backend_name == "heuristic":
        return RefreshOutcome(refreshed=0, cache_hits=0, replay_root=resolved_replay_root)

    cases = load_corpus_cases(corpus_root)
    backend = _make_backend(
        backend_name,
        replay_root=resolved_replay_root,
        provider_name=provider_name,
        model_id=model_id,
        replay_mode="write",
    )
    refreshed = 0
    cache_hits = 0
    try:
        for case in cases:
            case_dir = corpus_root / case.case_id
            input_path = case_dir / case.input_name
            if not input_path.exists():
                raise EvaluationError(f"Corpus input not found for {case.case_id}: {input_path}")
            content = input_path.read_text(encoding="utf-8")
            result = backend.run(
                Document(
                    source_id=case.case_id,
                    source_type=case.source_type,  # type: ignore[arg-type]
                    content=content,
                    metadata={"corpus": str(corpus_root), "input": case.input_name},
                ),
                ExtractionContext(prompt_version=prompt_version),
            )
            refreshed += 1
            if result.diagnostics.cache_hit:
                cache_hits += 1
            if callable(output_func):
                output_func(
                    f"refreshed {case.case_id}: items={len(result.items)} cache_hit={result.diagnostics.cache_hit}"
                )
    finally:
        close = getattr(backend, "close", None)
        if callable(close):
            close()
    return RefreshOutcome(refreshed=refreshed, cache_hits=cache_hits, replay_root=resolved_replay_root)


def format_eval_summary(report: dict[str, Any]) -> str:
    """Return a human-readable eval summary with baseline deltas."""

    baseline = report.get("baseline") if isinstance(report.get("baseline"), dict) else {}
    deltas = baseline.get("deltas") if isinstance(baseline.get("deltas"), dict) else {}
    baseline_metrics = baseline.get("metrics") if isinstance(baseline.get("metrics"), dict) else {}
    regressions = baseline.get("regressions") if isinstance(baseline.get("regressions"), list) else []
    tolerance = float(baseline.get("tolerance") or 0.0)

    lines = [
        f"Extraction eval: backend={report.get('backend')} cases={report.get('case_count')}",
        "metric                       value     baseline  delta",
    ]
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    for name in METRIC_NAMES:
        current = _metric_value(metrics.get(name))
        previous = _metric_value(baseline_metrics.get(name))
        delta = float(deltas.get(name, current - previous) or 0.0)
        lines.append(f"{name:<28} {current:>7.3f}  {previous:>8.3f}  {delta:>+7.3f}")

    if regressions:
        lines.append(f"Regressions beyond tolerance {tolerance:.3f}: {len(regressions)}")
        for regression in regressions:
            lines.append(
                f"- {regression['metric']}: {regression['current']:.3f} "
                f"vs {regression['baseline']:.3f} ({regression['delta']:+.3f})"
            )
    else:
        lines.append(f"No metric regressions beyond tolerance {tolerance:.3f}.")
    if baseline.get("updated"):
        lines.append(f"Updated baseline: {baseline.get('path')}")
    return "\n".join(lines)


def _evaluate_case(
    *,
    corpus_root: Path,
    case: CorpusCase,
    backend: ExtractionPipeline,
    prompt_version: str,
    prompt_overrides: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, MetricReport]]:
    case_dir = corpus_root / case.case_id
    input_path = case_dir / case.input_name
    gold_path = case_dir / case.gold_name
    if not input_path.exists():
        raise EvaluationError(f"Corpus input not found for {case.case_id}: {input_path}")
    if not gold_path.exists():
        raise EvaluationError(f"Corpus gold not found for {case.case_id}: {gold_path}")

    content = input_path.read_text(encoding="utf-8")
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    if not isinstance(gold, dict):
        raise EvaluationError(f"Corpus gold must be a JSON object: {gold_path}")

    result = backend.run(
        Document(
            source_id=case.case_id,
            source_type=case.source_type,  # type: ignore[arg-type]
            content=content,
            metadata={"corpus": str(corpus_root), "input": case.input_name},
        ),
        ExtractionContext(prompt_version=prompt_version, prompt_overrides=dict(prompt_overrides or {})),
    )
    predicted = graph_payload_from_items(result.items)
    reports = _metric_reports(predicted, gold)
    failures = _failure_dicts_from_reports(reports)
    public_case = {
        "case_id": case.case_id,
        "source_type": case.source_type,
        "input": case.input_name,
        "gold": case.gold_name,
        "description": case.description,
        "item_count": len(result.items),
        "predicted_graph": predicted,
        "predicted": {
            "node_count": len(predicted["nodes"]),
            "edge_count": len(predicted["edges"]),
            "alias_resolution_count": len(predicted["alias_resolutions"]),
        },
        "metrics": {name: _metric_to_dict(report) for name, report in reports.items()},
        "failures": failures,
    }
    return public_case, reports


def graph_payload_from_items(items: list[Any]) -> dict[str, Any]:
    """Convert typed extracted items into the graph-like dict consumed by metrics."""

    nodes: dict[tuple[str, str], dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    alias_resolutions: dict[str, str] = {}

    for item in items:
        if isinstance(item, ExtractedRelationship):
            source = _clean_label(item.source_label or "self")
            target = _clean_label(item.target_label or item.topic)
            relation = _clean_label(item.relation or item.relationship_type or "related_to")
            if source and target:
                edges[(source.lower(), relation.lower(), target.lower())] = {
                    "source": source,
                    "target": target,
                    "type": relation,
                    "confidence": round(float(item.confidence or 0.0), 6),
                }
            continue

        label = _node_label(item)
        node_type = _clean_label(getattr(item, "category", "") or "mentions")
        if not label:
            continue
        resolution = _canonical_resolution(item)
        canonical_id = resolution or _node_id(node_type, label)
        key = (node_type.lower(), label.lower())
        node = nodes.get(key)
        confidence = round(float(getattr(item, "confidence", 0.0) or 0.0), 6)
        if node is None or confidence > float(node.get("confidence", 0.0)):
            node = {
                "id": canonical_id,
                "canonical_id": canonical_id,
                "label": label,
                "type": node_type,
                "confidence": confidence,
                "aliases": [],
                "properties": _item_properties(item),
            }
            nodes[key] = node
        if resolution:
            alias_resolutions[_normalize_alias(label)] = canonical_id
            if label not in node["aliases"]:
                node["aliases"].append(label)

    return {
        "nodes": sorted(nodes.values(), key=lambda node: (node["type"].lower(), node["label"].lower())),
        "edges": sorted(
            edges.values(), key=lambda edge: (edge["source"].lower(), edge["type"].lower(), edge["target"].lower())
        ),
        "alias_resolutions": [
            {"alias": alias, "canonical_id": canonical_id} for alias, canonical_id in sorted(alias_resolutions.items())
        ],
    }


def _metric_reports(predicted: dict[str, Any], gold: dict[str, Any]) -> dict[str, MetricReport]:
    node_precision, node_recall, node_f1 = node_prf(predicted, gold)
    relation_precision, relation_recall, relation_f1 = relation_prf(predicted, gold)
    return {
        "node_precision": node_precision,
        "node_recall": node_recall,
        "node_f1": node_f1,
        "relation_precision": relation_precision,
        "relation_recall": relation_recall,
        "relation_f1": relation_f1,
        "canonicalization_accuracy": canonicalization_accuracy(predicted, gold),
        "contradiction_recall": contradiction_recall(predicted, gold),
        "completeness_score": completeness_score(predicted, gold),
    }


def _aggregate_metrics(case_reports: list[dict[str, MetricReport]]) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for name in METRIC_NAMES:
        numerator = sum(float(reports[name].numerator) for reports in case_reports)
        denominator = sum(float(reports[name].denominator) for reports in case_reports)
        metrics[name] = {
            "value": round((numerator / denominator) if denominator else 0.0, 6),
            "numerator": _integer_if_whole(numerator),
            "denominator": _integer_if_whole(denominator),
        }
    return metrics


def _compare_to_baseline(
    *,
    current_metrics: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    baseline_path: Path,
    tolerance: float,
    updated: bool,
) -> dict[str, Any]:
    baseline_metrics = baseline.get("metrics")
    if not isinstance(baseline_metrics, dict):
        raise EvaluationError(f"Invalid extraction eval baseline: {baseline_path}")

    deltas: dict[str, float] = {}
    regressions: list[dict[str, Any]] = []
    for name in METRIC_NAMES:
        current_value = _metric_value(current_metrics.get(name))
        baseline_value = _metric_value(baseline_metrics.get(name))
        delta = round(current_value - baseline_value, 6)
        deltas[name] = delta
        if not updated and delta < -float(tolerance):
            regressions.append(
                {
                    "metric": name,
                    "current": current_value,
                    "baseline": baseline_value,
                    "delta": delta,
                    "tolerance": float(tolerance),
                }
            )

    return {
        "path": str(baseline_path),
        "schema_version": baseline.get("schema_version", ""),
        "backend": baseline.get("backend", ""),
        "metrics": baseline_metrics,
        "deltas": deltas,
        "tolerance": float(tolerance),
        "regressions": regressions,
        "updated": bool(updated),
    }


def _baseline_from_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "backend": report["backend"],
        "prompt_version": report["prompt_version"],
        "case_count": report["case_count"],
        "metrics": report["metrics"],
        "cases": {
            case["case_id"]: {
                "item_count": case["item_count"],
                "predicted": case["predicted"],
                "metrics": case["metrics"],
                "failures": case.get("failures", []),
            }
            for case in report["cases"]
        },
    }


def _make_backend(
    backend: BackendName,
    *,
    replay_root: Path,
    provider_name: str | None = None,
    model_id: str | None = None,
    replay_mode: ReplayMode = "read",
) -> ExtractionPipeline:
    if backend == "heuristic":
        from cortex.extraction.heuristic_backend import HeuristicBackend

        return HeuristicBackend()
    if backend == "model":
        from cortex.extraction.model_backend import ModelBackend

        return ModelBackend(
            provider_name=provider_name,
            model_id=model_id,
            replay_cache=ReplayCache(root=replay_root, mode=replay_mode),
        )
    if backend == "hybrid":
        from cortex.extraction.hybrid_backend import HybridBackend
        from cortex.extraction.model_backend import ModelBackend

        return HybridBackend(
            rescore_backend=ModelBackend(
                provider_name=provider_name,
                model_id=model_id,
                replay_cache=ReplayCache(root=replay_root, mode=replay_mode),
            )
        )
    raise EvaluationError(f"Unknown extraction backend: {backend}")


def _parse_corpus_manifest(path: Path) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        stripped = raw_line.strip()
        if stripped.startswith("- "):
            if current is not None:
                cases.append(current)
            current = {}
            stripped = stripped[2:]
        if current is None or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        current[key.strip()] = value.strip().strip("\"'")
    if current is not None:
        cases.append(current)
    return cases


def _read_baseline(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise EvaluationError(f"Extraction eval baseline not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvaluationError(f"Extraction eval baseline must be a JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _metric_to_dict(report: MetricReport) -> dict[str, Any]:
    return {
        "value": round(float(report.value), 6),
        "numerator": _integer_if_whole(float(report.numerator)),
        "denominator": _integer_if_whole(float(report.denominator)),
        "per_class_breakdown": report.per_class_breakdown,
        "failures": [_failure_to_dict(failure) for failure in report.failures],
    }


def _failure_dicts_from_reports(reports: dict[str, MetricReport]) -> list[dict[str, Any]]:
    failures: list[ExtractionFailure] = []
    for report in reports.values():
        failures.extend(report.failures)
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for failure in failures:
        payload = _failure_to_dict(failure)
        key = json.dumps(payload, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(payload)
    return result


def _failure_to_dict(failure: ExtractionFailure | dict[str, Any]) -> dict[str, Any]:
    if isinstance(failure, ExtractionFailure):
        return failure.as_dict()
    return dict(failure)


def _metric_value(payload: Any) -> float:
    if isinstance(payload, MetricReport):
        return float(payload.value)
    if isinstance(payload, dict):
        return float(payload.get("value") or 0.0)
    return 0.0


def _node_label(item: Any) -> str:
    if isinstance(item, ExtractedFact):
        return _clean_label(item.attribute_value or item.topic)
    if isinstance(item, ExtractedClaim):
        return _clean_label(item.assertion or item.topic)
    return _clean_label(getattr(item, "topic", ""))


def _item_properties(item: Any) -> dict[str, Any]:
    properties: dict[str, Any] = {"extraction_type": item.__class__.__name__}
    if isinstance(item, ExtractedFact):
        properties.update({"attribute_name": item.attribute_name, "attribute_value": item.attribute_value})
    elif isinstance(item, ExtractedClaim):
        properties.update({"assertion": item.assertion, "stance": item.stance})
    return {key: value for key, value in properties.items() if value}


def _node_id(node_type: str, label: str) -> str:
    return f"{_slug(node_type) or 'node'}:{_slug(label) or 'unknown'}"


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return text or "unknown"


def _clean_label(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize_alias(value: str) -> str:
    return _clean_label(value).lower()


def _canonical_resolution(item: Any) -> str:
    value = _clean_label(getattr(item, "entity_resolution", "") or "")
    normalized = value.lower()
    if normalized in {"", "new", "new_entity", "none", "null"} or normalized.startswith("net_new"):
        return ""
    return value


def _integer_if_whole(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 6)
