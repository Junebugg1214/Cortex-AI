from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass
class ExtractionDiagnostics:
    """Runtime observability emitted by an extraction pipeline call."""

    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    stage_timings: dict[str, float] = field(default_factory=dict)
    model: str = ""
    prompt_version: str = ""
    warnings: list[str] = field(default_factory=list)
    cache_hit: bool = False
    router_decision: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


def extraction_log_path(*, store_dir: str | Path | None = None) -> Path:
    """Return the JSONL diagnostics log path for extraction records."""

    explicit_path = os.environ.get("CORTEX_EXTRACTION_LOG_PATH", "").strip()
    if explicit_path:
        return Path(explicit_path)
    root = Path(store_dir or os.environ.get("CORTEX_STORE_DIR", "").strip() or ".cortex")
    return root / "logs" / "extractions.jsonl"


def write_extraction_record(
    diagnostics: ExtractionDiagnostics,
    *,
    backend: str,
    operation: str,
    source_id: str = "",
    source_type: str = "",
    item_count: int = 0,
    path: str | Path | None = None,
) -> None:
    """Append one extraction diagnostics record to the JSONL log."""

    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "backend": backend,
        "operation": operation,
        "source_id": source_id,
        "source_type": source_type,
        "item_count": item_count,
    }
    record.update(diagnostics.as_dict())
    log_path = Path(path) if path is not None else extraction_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    except OSError as exc:  # pragma: no cover - logging should never break extraction
        LOGGER.warning("Unable to write extraction diagnostics to %s: %s", log_path, exc)


def tail_extraction_records(
    *,
    limit: int = 20,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return the most recent extraction diagnostic records."""

    if limit <= 0:
        return []
    log_path = Path(path) if path is not None else extraction_log_path()
    if not log_path.exists():
        return []
    try:
        lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as exc:
        LOGGER.warning("Unable to read extraction diagnostics from %s: %s", log_path, exc)
        return []

    records: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            records.append({"raw": line, "warnings": ["invalid diagnostics JSON"]})
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def format_extraction_records(records: list[dict[str, Any]]) -> str:
    """Pretty-print extraction diagnostics records for the CLI."""

    if not records:
        return "No extraction diagnostics found."

    lines: list[str] = []
    for record in records:
        if "raw" in record:
            lines.append(f"invalid-record raw={record['raw']}")
            continue
        timestamp = str(record.get("timestamp") or "?")
        backend = str(record.get("backend") or "?")
        operation = str(record.get("operation") or "?")
        model = str(record.get("model") or "-")
        prompt_version = str(record.get("prompt_version") or "-")
        tokens_in = int(record.get("tokens_in") or 0)
        tokens_out = int(record.get("tokens_out") or 0)
        cost_usd = float(record.get("cost_usd") or 0.0)
        latency_ms = float(record.get("latency_ms") or 0.0)
        cache_hit = bool(record.get("cache_hit", False))
        item_count = int(record.get("item_count") or 0)
        stage_timings = record.get("stage_timings")
        stage_text = ""
        if isinstance(stage_timings, dict) and stage_timings:
            stage_text = " stages=" + ", ".join(
                f"{name}:{float(duration):.1f}ms" for name, duration in sorted(stage_timings.items())
            )
        router_decision = record.get("router_decision")
        router_text = ""
        if isinstance(router_decision, dict) and router_decision:
            kept = int(router_decision.get("heuristic_kept") or 0)
            escalated = int(router_decision.get("escalated") or 0)
            cost_saved = float(router_decision.get("cost_saved_usd") or 0.0)
            router_text = f" router=kept:{kept},escalated:{escalated},saved:${cost_saved:.6f}"
        warnings = record.get("warnings")
        warning_count = len(warnings) if isinstance(warnings, list) else 0
        lines.append(
            f"{timestamp} {backend}.{operation} model={model} prompt={prompt_version} "
            f"items={item_count} tokens={tokens_in}/{tokens_out} cost=${cost_usd:.6f} "
            f"latency={latency_ms:.1f}ms cache_hit={cache_hit} warnings={warning_count}{router_text}{stage_text}"
        )
    return "\n".join(lines)


__all__ = [
    "ExtractionDiagnostics",
    "extraction_log_path",
    "format_extraction_records",
    "tail_extraction_records",
    "write_extraction_record",
]
