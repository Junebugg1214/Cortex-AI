from __future__ import annotations

import json
from pathlib import Path

from cortex.cli import main


def _write_tiny_corpus(root: Path) -> None:
    case_dir = root / "python_skill"
    case_dir.mkdir(parents=True)
    (root / "manifest.yml").write_text(
        "\n".join(
            [
                "schema_version: extraction-corpus-v1",
                "cases:",
                "  - id: python_skill",
                "    source_type: doc",
                "    input: input.md",
                "    gold: gold.json",
                "    description: Python skill smoke case.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (case_dir / "input.md").write_text("I use Python.", encoding="utf-8")
    (case_dir / "gold.json").write_text(
        json.dumps(
            {
                "schema_version": "extraction-eval-v1",
                "case_id": "python_skill",
                "source_type": "doc",
                "expected_graph": {"nodes": [], "edges": []},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_review_patches_gold_and_updates_baseline(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CORTEX_EXTRACTION_LOG_PATH", str(tmp_path / "extractions.jsonl"))
    corpus = tmp_path / "corpus"
    _write_tiny_corpus(corpus)
    report_path = tmp_path / "report.json"

    assert (
        main(
            [
                "extract",
                "eval",
                "--corpus",
                str(corpus),
                "--backend",
                "heuristic",
                "--output",
                str(report_path),
                "--update-baseline",
            ]
        )
        == 0
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["cases"][0]["failures"][0]["kind"] == "hallucinated_node"

    answers = iter(["gold_is_wrong"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    docs_dir = tmp_path / "docs" / "extraction-reviews"

    assert main(["extract", "review", str(report_path), "--docs-dir", str(docs_dir)]) == 0

    gold = json.loads((corpus / "python_skill" / "gold.json").read_text(encoding="utf-8"))
    nodes = gold["expected_graph"]["nodes"]
    assert nodes == [
        {
            "canonical_id": "technical-expertise:python",
            "confidence": 0.9,
            "id": "technical-expertise:python",
            "label": "Python",
            "type": "technical_expertise",
        }
    ]

    baseline = json.loads((corpus / "baseline.json").read_text(encoding="utf-8"))
    assert baseline["metrics"]["node_precision"]["value"] == 1.0
    assert baseline["metrics"]["node_recall"]["value"] == 1.0
    assert baseline["metrics"]["completeness_score"]["value"] == 1.0

    summaries = list(docs_dir.glob("extraction-review-*.md"))
    assert len(summaries) == 1
    summary = summaries[0].read_text(encoding="utf-8")
    assert "Gold patches: 1" in summary
    assert "Baseline updated: yes" in summary
