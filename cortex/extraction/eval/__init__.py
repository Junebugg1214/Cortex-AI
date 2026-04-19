"""Evaluation helpers for extraction harnesses."""

from __future__ import annotations

from .metrics import (
    ExtractionFailure,
    MetricReport,
    canonicalization_accuracy,
    completeness_score,
    contradiction_recall,
    node_prf,
    relation_prf,
)
from .replay_cache import ReplayCache, replay_mode_from_env
from .review import ReviewOutcome, run_extraction_review
from .runner import (
    EvaluationError,
    EvaluationOutcome,
    format_eval_summary,
    graph_payload_from_items,
    load_corpus_cases,
    run_extraction_eval,
    write_eval_report,
)

__all__ = [
    "EvaluationError",
    "EvaluationOutcome",
    "ExtractionFailure",
    "MetricReport",
    "ReplayCache",
    "ReviewOutcome",
    "canonicalization_accuracy",
    "completeness_score",
    "contradiction_recall",
    "format_eval_summary",
    "graph_payload_from_items",
    "load_corpus_cases",
    "node_prf",
    "replay_mode_from_env",
    "relation_prf",
    "run_extraction_eval",
    "run_extraction_review",
    "write_eval_report",
]
