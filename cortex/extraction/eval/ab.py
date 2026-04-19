from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runner import METRIC_NAMES, BackendName, EvaluationOutcome, run_extraction_eval

DEFAULT_SIGNIFICANCE_THRESHOLD = 0.01
_WILSON_Z_95 = 1.96


@dataclass(frozen=True)
class PromptVariant:
    """One prompt file used in an extraction A/B run."""

    slot: str
    path: Path
    content: str
    content_sha256: str
    prompt_version: str
    declared_version: str

    @property
    def display_name(self) -> str:
        version = f" {self.declared_version}" if self.declared_version else ""
        return f"Prompt {self.slot}{version} ({self.path})"


@dataclass(frozen=True)
class MetricDelta:
    """One aggregate metric comparison between two prompt variants."""

    name: str
    value_a: float
    value_b: float
    delta: float
    numerator_a: float
    denominator_a: float
    numerator_b: float
    denominator_b: float
    interval_a: tuple[float, float] | None
    interval_b: tuple[float, float] | None
    significant: bool


@dataclass(frozen=True)
class PromptABOutcome:
    """Completed prompt A/B comparison."""

    prompt_a: PromptVariant
    prompt_b: PromptVariant
    report_a: dict[str, Any]
    report_b: dict[str, Any]
    metric_deltas: list[MetricDelta]
    differing_cases: list[str]
    recommended_winner: str
    markdown: str
    output_path: Path


def run_prompt_ab(
    *,
    prompt_a: str | Path,
    prompt_b: str | Path,
    corpus: str | Path,
    output: str | Path,
    backend: BackendName = "heuristic",
    replay_root: str | Path | None = None,
    significance_threshold: float = DEFAULT_SIGNIFICANCE_THRESHOLD,
) -> PromptABOutcome:
    """Run an extraction prompt A/B comparison and write a markdown diff report."""

    corpus_root = Path(corpus)
    output_path = Path(output)
    variant_a = load_prompt_variant(prompt_a, slot="A")
    variant_b = load_prompt_variant(prompt_b, slot="B")
    shared_replay_root = Path(replay_root) if replay_root is not None else corpus_root / "replay"

    outcome_a = _run_variant(
        variant_a,
        corpus=corpus_root,
        backend=backend,
        replay_root=shared_replay_root,
    )
    outcome_b = _run_variant(
        variant_b,
        corpus=corpus_root,
        backend=backend,
        replay_root=shared_replay_root,
    )

    metric_deltas = _metric_deltas(
        outcome_a.report.get("metrics", {}),
        outcome_b.report.get("metrics", {}),
        significance_threshold=significance_threshold,
    )
    differing_cases = _differing_cases(outcome_a.report, outcome_b.report)
    recommended_winner = _recommended_winner(metric_deltas)
    markdown = format_prompt_ab_markdown(
        prompt_a=variant_a,
        prompt_b=variant_b,
        report_a=outcome_a.report,
        report_b=outcome_b.report,
        metric_deltas=metric_deltas,
        differing_cases=differing_cases,
        recommended_winner=recommended_winner,
        significance_threshold=significance_threshold,
        replay_root=shared_replay_root,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return PromptABOutcome(
        prompt_a=variant_a,
        prompt_b=variant_b,
        report_a=outcome_a.report,
        report_b=outcome_b.report,
        metric_deltas=metric_deltas,
        differing_cases=differing_cases,
        recommended_winner=recommended_winner,
        markdown=markdown,
        output_path=output_path,
    )


def load_prompt_variant(path: str | Path, *, slot: str) -> PromptVariant:
    """Load and fingerprint one prompt file."""

    prompt_path = Path(path)
    content = prompt_path.read_text(encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    declared_version = _declared_prompt_version(content)
    return PromptVariant(
        slot=slot,
        path=prompt_path,
        content=content,
        content_sha256=digest,
        prompt_version=f"ab-{digest[:16]}",
        declared_version=declared_version,
    )


def format_prompt_ab_markdown(
    *,
    prompt_a: PromptVariant,
    prompt_b: PromptVariant,
    report_a: dict[str, Any],
    report_b: dict[str, Any],
    metric_deltas: list[MetricDelta],
    differing_cases: list[str],
    recommended_winner: str,
    significance_threshold: float,
    replay_root: Path,
) -> str:
    """Return the markdown report for a prompt A/B run."""

    lines = [
        "# Extraction Prompt A/B Diff",
        "",
        f"- Corpus: `{report_a.get('corpus')}`",
        f"- Backend: `{report_a.get('backend')}`",
        f"- Replay cache: `{replay_root}`",
        f"- Significance threshold: `{significance_threshold:.3f}`",
        f"- Prompt A: `{prompt_a.path}` (`{prompt_a.prompt_version}`)",
        f"- Prompt B: `{prompt_b.path}` (`{prompt_b.prompt_version}`)",
        "",
        "## Metrics",
        "",
        "| Metric | A | B | Delta B-A | A 95% CI | B 95% CI | Significant |",
        "| --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for delta in metric_deltas:
        lines.append(
            "| "
            f"{delta.name} | "
            f"{delta.value_a:.3f} | "
            f"{delta.value_b:.3f} | "
            f"{delta.delta:+.3f} | "
            f"{_format_interval(delta.interval_a)} | "
            f"{_format_interval(delta.interval_b)} | "
            f"{'yes' if delta.significant else 'no'} |"
        )

    lines.extend(["", "## Output Differences", "", f"Output-different cases: {len(differing_cases)}"])
    if differing_cases:
        lines.extend(f"- `{case_id}`" for case_id in differing_cases)
    else:
        lines.append("No case output differences.")

    lines.extend(["", "## Recommendation", ""])
    if recommended_winner:
        winner = prompt_a if recommended_winner == "A" else prompt_b
        lines.append(f"Recommended winner: Prompt {recommended_winner} (`{winner.path}`).")
    else:
        lines.append("Recommended winner: none; F1 deltas are not statistically significant.")

    lines.extend(
        [
            "",
            "## Run Metadata",
            "",
            f"- Prompt A sha256: `{prompt_a.content_sha256}`",
            f"- Prompt B sha256: `{prompt_b.content_sha256}`",
            f"- Cases A/B: `{report_a.get('case_count')}` / `{report_b.get('case_count')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _run_variant(
    variant: PromptVariant,
    *,
    corpus: Path,
    backend: BackendName,
    replay_root: Path,
) -> EvaluationOutcome:
    return run_extraction_eval(
        corpus=corpus,
        backend=backend,
        tolerance=1.0,
        prompt_version=variant.prompt_version,
        prompt_overrides={"candidates": variant.content},
        replay_root=replay_root,
    )


def _metric_deltas(
    metrics_a: Any,
    metrics_b: Any,
    *,
    significance_threshold: float,
) -> list[MetricDelta]:
    result: list[MetricDelta] = []
    metrics_a = metrics_a if isinstance(metrics_a, dict) else {}
    metrics_b = metrics_b if isinstance(metrics_b, dict) else {}
    for name in METRIC_NAMES:
        current_a = _metric_payload(metrics_a.get(name))
        current_b = _metric_payload(metrics_b.get(name))
        value_a = _metric_value(current_a)
        value_b = _metric_value(current_b)
        interval_a = (
            _wilson_interval(current_a["numerator"], current_a["denominator"]) if name.endswith("_f1") else None
        )
        interval_b = (
            _wilson_interval(current_b["numerator"], current_b["denominator"]) if name.endswith("_f1") else None
        )
        significant = _significant_delta(
            value_a=value_a,
            value_b=value_b,
            interval_a=interval_a,
            interval_b=interval_b,
            significance_threshold=significance_threshold,
        )
        result.append(
            MetricDelta(
                name=name,
                value_a=value_a,
                value_b=value_b,
                delta=round(value_b - value_a, 6),
                numerator_a=current_a["numerator"],
                denominator_a=current_a["denominator"],
                numerator_b=current_b["numerator"],
                denominator_b=current_b["denominator"],
                interval_a=interval_a,
                interval_b=interval_b,
                significant=significant,
            )
        )
    return result


def _recommended_winner(metric_deltas: list[MetricDelta]) -> str:
    significant_f1 = [delta for delta in metric_deltas if delta.name.endswith("_f1") and delta.significant]
    if not significant_f1:
        return ""
    winners = {"B" if delta.delta > 0 else "A" for delta in significant_f1 if delta.delta != 0}
    return next(iter(winners)) if len(winners) == 1 else ""


def _significant_delta(
    *,
    value_a: float,
    value_b: float,
    interval_a: tuple[float, float] | None,
    interval_b: tuple[float, float] | None,
    significance_threshold: float,
) -> bool:
    if interval_a is None or interval_b is None:
        return False
    if abs(value_b - value_a) <= significance_threshold:
        return False
    a_low, a_high = interval_a
    b_low, b_high = interval_b
    return a_high < b_low or b_high < a_low


def _wilson_interval(numerator: float, denominator: float, *, z: float = _WILSON_Z_95) -> tuple[float, float]:
    if denominator <= 0:
        return (0.0, 0.0)
    p_hat = max(0.0, min(1.0, numerator / denominator))
    z2 = z * z
    denom = 1.0 + z2 / denominator
    center = (p_hat + z2 / (2.0 * denominator)) / denom
    margin = z * math.sqrt((p_hat * (1.0 - p_hat) + z2 / (4.0 * denominator)) / denominator) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def _differing_cases(report_a: dict[str, Any], report_b: dict[str, Any]) -> list[str]:
    cases_a = _case_index(report_a)
    cases_b = _case_index(report_b)
    differing: list[str] = []
    for case_id in sorted(set(cases_a) | set(cases_b)):
        case_a = cases_a.get(case_id, {})
        case_b = cases_b.get(case_id, {})
        comparable_a = _case_comparable_payload(case_a)
        comparable_b = _case_comparable_payload(case_b)
        if _stable_json(comparable_a) != _stable_json(comparable_b):
            differing.append(case_id)
    return differing


def _case_index(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = report.get("cases") if isinstance(report, dict) else []
    if not isinstance(cases, list):
        return {}
    return {str(case.get("case_id")): case for case in cases if isinstance(case, dict) and case.get("case_id")}


def _case_comparable_payload(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_count": case.get("item_count"),
        "predicted_graph": case.get("predicted_graph"),
        "failures": case.get("failures", []),
    }


def _metric_payload(payload: Any) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {"value": 0.0, "numerator": 0.0, "denominator": 0.0}
    return {
        "value": _as_float(payload.get("value")),
        "numerator": _as_float(payload.get("numerator")),
        "denominator": _as_float(payload.get("denominator")),
    }


def _metric_value(payload: dict[str, float]) -> float:
    return round(float(payload.get("value") or 0.0), 6)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _declared_prompt_version(content: str) -> str:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return ""
        if stripped.startswith("version:"):
            return stripped.split(":", 1)[1].strip().strip("\"'")
    return ""


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _format_interval(interval: tuple[float, float] | None) -> str:
    if interval is None:
        return "n/a"
    low, high = interval
    return f"{low:.3f}-{high:.3f}"


__all__ = [
    "DEFAULT_SIGNIFICANCE_THRESHOLD",
    "MetricDelta",
    "PromptABOutcome",
    "PromptVariant",
    "format_prompt_ab_markdown",
    "load_prompt_variant",
    "run_prompt_ab",
]
