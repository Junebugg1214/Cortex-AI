from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9+.#/_ -]+", " ", value.lower()).split())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_timestamp(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value):
        value += "+00:00"
    dt = datetime.fromisoformat(value)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def flatten_topic_text(topic: dict[str, Any]) -> str:
    parts = [
        str(topic.get("topic", "")),
        str(topic.get("brief", "")),
        str(topic.get("full_description", "")),
        " ".join(str(item) for item in topic.get("metrics", [])),
    ]
    return normalize_text(" ".join(part for part in parts if part))


def f1_score(expected: set[Any], predicted: set[Any]) -> float:
    if not expected and not predicted:
        return 1.0
    if not expected or not predicted:
        return 0.0
    true_positive = len(expected & predicted)
    precision = safe_div(true_positive, len(predicted))
    recall = safe_div(true_positive, len(expected))
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)
