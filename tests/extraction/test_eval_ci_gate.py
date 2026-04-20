from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cortex.cli import main
from cortex.cli_extract_commands import run_extract_eval

CORPUS_ROOT = Path(__file__).parent / "corpus"
MODEL_ID = "claude-3-5-sonnet-20241022"
MODEL_REPLAY_SUFFIX = f"replay/model/anthropic/{MODEL_ID}"


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


def test_extract_eval_passes_provider_and_model(monkeypatch, tmp_path) -> None:
    from cortex.extraction.eval import runner

    captured: dict[str, object] = {}

    class _Ctx:
        def error(self, message: str) -> int:
            raise AssertionError(f"unexpected error: {message}")

        def permission_error(self, *_args, **_kwargs) -> int:
            raise AssertionError("permission path should not be used")

        def echo(self, *_args, **_kwargs) -> None:
            return None

    def _run_extraction_eval(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(report={"ok": True}, summary="summary", failed=False)

    def _write_eval_report(report, output):
        assert report == {"ok": True}
        return Path(output)

    monkeypatch.setattr(runner, "run_extraction_eval", _run_extraction_eval)
    monkeypatch.setattr(runner, "write_eval_report", _write_eval_report)

    rc = run_extract_eval(
        SimpleNamespace(
            corpus=str(CORPUS_ROOT),
            replay_dir=str(tmp_path / "replay"),
            backend="model",
            tolerance=0.01,
            prompt_version="corpus-v1",
            update_baseline=False,
            provider="custom_provider:create",
            model="custom-model",
            output=str(tmp_path / "report.json"),
        ),
        ctx=_Ctx(),
    )

    assert rc == 0
    assert captured["provider_name"] == "custom_provider:create"
    assert captured["model_id"] == "custom-model"


def test_refresh_cache_requires_valid_backend_choice(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["extract", "refresh-cache", "--backend", "foo"])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "invalid choice: 'foo'" in captured.err
    assert "--backend" in captured.err


def test_refresh_cache_heuristic_short_circuits_without_calling_runner(monkeypatch, capsys) -> None:
    from cortex.extraction.eval import runner

    def _unexpected_refresh(**_kwargs):
        raise AssertionError("refresh runner should not be called for heuristic backend")

    monkeypatch.setattr(runner, "refresh_extraction_replay_cache", _unexpected_refresh)

    rc = main(["extract", "refresh-cache", "--backend", "heuristic"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "heuristic backend is deterministic; nothing to cache." in captured.out


def test_refresh_cache_default_path_nests_by_backend_provider_model(monkeypatch, tmp_path) -> None:
    from cortex.extraction.eval import runner

    captured: dict[str, object] = {}

    def _refresh_extraction_replay_cache(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(refreshed=0, cache_hits=0, replay_root=kwargs["replay_root"])

    monkeypatch.setattr(runner, "refresh_extraction_replay_cache", _refresh_extraction_replay_cache)

    rc = main(
        [
            "extract",
            "refresh-cache",
            "--corpus",
            str(CORPUS_ROOT),
            "--backend",
            "model",
            "--provider",
            "anthropic",
            "--model",
            MODEL_ID,
        ]
    )

    assert rc == 0
    assert captured["backend_name"] == "model"
    assert captured["provider_name"] == "anthropic"
    assert captured["model_id"] == MODEL_ID
    assert Path(captured["replay_root"]).as_posix().endswith(MODEL_REPLAY_SUFFIX)


def test_eval_default_path_nests_by_backend_provider_model(monkeypatch, tmp_path) -> None:
    from cortex.extraction.eval import runner

    captured: dict[str, object] = {}

    def _run_extraction_eval(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(report={"ok": True}, summary="summary", failed=False)

    def _write_eval_report(report, output):
        assert report == {"ok": True}
        return Path(output)

    monkeypatch.setattr(runner, "run_extraction_eval", _run_extraction_eval)
    monkeypatch.setattr(runner, "write_eval_report", _write_eval_report)

    rc = main(
        [
            "extract",
            "eval",
            "--corpus",
            str(CORPUS_ROOT),
            "--backend",
            "model",
            "--provider",
            "anthropic",
            "--model",
            MODEL_ID,
            "--output",
            str(tmp_path / "model-report.json"),
        ]
    )

    assert rc == 0
    assert captured["backend"] == "model"
    assert captured["provider_name"] == "anthropic"
    assert captured["model_id"] == MODEL_ID
    assert Path(captured["replay_root"]).as_posix().endswith(MODEL_REPLAY_SUFFIX)
