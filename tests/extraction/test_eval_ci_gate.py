from __future__ import annotations

import json
from pathlib import Path

from cortex.cli import main

CORPUS_ROOT = Path(__file__).parent / "corpus"


def _run_eval(output_path: Path) -> dict:
    rc = main(
        [
            "extract",
            "eval",
            "--corpus",
            str(CORPUS_ROOT),
            "--backend",
            "heuristic",
            "--output",
            str(output_path),
            "--tolerance",
            "0.01",
        ]
    )
    assert rc == 0
    return json.loads(output_path.read_text(encoding="utf-8"))


def test_baseline_report_is_reproducible_offline(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CORTEX_EXTRACTION_REPLAY", "read")
    monkeypatch.setenv("CORTEX_EXTRACTION_REPLAY_DIR", str(CORPUS_ROOT / "replay"))
    monkeypatch.setenv("CORTEX_EXTRACTION_LOG_PATH", str(tmp_path / "extractions.jsonl"))

    first = _run_eval(tmp_path / "first-report.json")
    second = _run_eval(tmp_path / "second-report.json")

    assert first == second
    assert first["schema_version"] == "extraction-eval-report-v1"
    assert first["baseline"]["regressions"] == []
    assert first["baseline"]["path"] == str(CORPUS_ROOT / "baseline.json")
    assert first["metrics"] == first["baseline"]["metrics"]
