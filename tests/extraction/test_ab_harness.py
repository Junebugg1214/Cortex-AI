from __future__ import annotations

from pathlib import Path

from cortex.cli import main

CORPUS_ROOT = Path(__file__).parent / "corpus"


def test_identical_prompts_report_no_significant_delta(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CORTEX_EXTRACTION_LOG_PATH", str(tmp_path / "extractions.jsonl"))
    prompt_body = "\n".join(
        [
            "---",
            "version: v-test",
            "schema_ref: typed-items",
            "inputs:",
            "  - text",
            "outputs:",
            "  - items",
            "test_fixture: tests/extraction/corpus",
            "---",
            "Extract typed memory items from the supplied text.",
            "",
        ]
    )
    prompt_a = tmp_path / "prompt-a.md"
    prompt_b = tmp_path / "prompt-b.md"
    prompt_a.write_text(prompt_body, encoding="utf-8")
    prompt_b.write_text(prompt_body, encoding="utf-8")
    output = tmp_path / "diff.md"

    rc = main(
        [
            "extract",
            "ab",
            "--prompt-a",
            str(prompt_a),
            "--prompt-b",
            str(prompt_b),
            "--corpus",
            str(CORPUS_ROOT),
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    diff = output.read_text(encoding="utf-8")
    assert "Recommended winner: none; F1 deltas are not statistically significant." in diff
    assert "Output-different cases: 0" in diff
    assert "No case output differences." in diff
    assert "| node_f1 |" in diff
    assert "| relation_f1 |" in diff
