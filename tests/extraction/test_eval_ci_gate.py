from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cortex.cli import main
from cortex.cli_extract_commands import run_extract_eval

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


def test_model_eval_replay_miss_reports_clean_cli_error(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.delenv("CORTEX_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CORTEX_EXTRACTION_REPLAY", "read")
    monkeypatch.setenv("CORTEX_EXTRACTION_REPLAY_DIR", str(tmp_path / "empty-replay"))
    monkeypatch.setenv("CORTEX_EXTRACTION_LOG_PATH", str(tmp_path / "extractions.jsonl"))

    rc = main(
        [
            "extract",
            "eval",
            "--corpus",
            str(CORPUS_ROOT),
            "--backend",
            "model",
            "--output",
            str(tmp_path / "model-report.json"),
            "--replay-dir",
            str(tmp_path / "empty-replay"),
            "--tolerance",
            "0.01",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "Could not run extraction eval" in captured.err
    assert "Extraction replay cache miss in read mode" in captured.err
    assert "Traceback" not in captured.err


def test_extract_eval_wraps_unexpected_backend_exception(monkeypatch, tmp_path) -> None:
    from cortex.extraction.eval import runner

    messages: list[str] = []

    class _Ctx:
        def error(self, message: str) -> int:
            messages.append(message)
            return 7

        def permission_error(self, *_args, **_kwargs) -> int:
            raise AssertionError("permission path should not be used")

        def echo(self, *_args, **_kwargs) -> None:
            raise AssertionError("success path should not be used")

    def _raise_provider_error(**_kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(runner, "run_extraction_eval", _raise_provider_error)

    rc = run_extract_eval(
        SimpleNamespace(
            corpus=str(CORPUS_ROOT),
            replay_dir=str(tmp_path / "replay"),
            backend="model",
            tolerance=0.01,
            prompt_version="corpus-v1",
            update_baseline=False,
            output=str(tmp_path / "report.json"),
        ),
        ctx=_Ctx(),
    )

    assert rc == 7
    assert messages == ["Could not run extraction eval: provider exploded"]
