import json

from cortex.cli import main
from cortex.connectors import connector_to_text, docs_to_text, github_export_to_text, slack_export_to_text


def test_github_export_to_text_handles_issue_shape(tmp_path):
    path = tmp_path / "issue.json"
    path.write_text(
        json.dumps(
            {
                "title": "Improve Project Atlas",
                "number": 42,
                "state": "OPEN",
                "body": "We use Python for Project Atlas.",
                "author": {"login": "junebugg"},
                "comments": [{"author": {"login": "reviewer"}, "body": "Keep the docs updated."}],
            }
        ),
        encoding="utf-8",
    )

    text = github_export_to_text(path)

    assert "Improve Project Atlas" in text
    assert "Python" in text
    assert "Comment by reviewer" in text


def test_slack_export_to_text_handles_channel_export(tmp_path):
    channel_dir = tmp_path / "engineering"
    channel_dir.mkdir()
    (channel_dir / "2026-03-23.json").write_text(
        json.dumps(
            [
                {"user": "U123", "text": "Project Atlas prefers concise updates.", "ts": "1711152000.000100"},
                {"username": "bot", "text": "Deploy complete.", "ts": "1711152600.000200"},
            ]
        ),
        encoding="utf-8",
    )

    text = slack_export_to_text(tmp_path)

    assert "Slack Channel: engineering" in text
    assert "Project Atlas prefers concise updates." in text
    assert "Deploy complete." in text


def test_docs_to_text_reads_directory(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "overview.md").write_text("# Overview\nProject Atlas runs on Python.\n", encoding="utf-8")
    (docs_dir / "notes.txt").write_text("Prefer MIT license.\n", encoding="utf-8")

    text = docs_to_text(docs_dir)

    assert "Document: overview.md" in text
    assert "Project Atlas runs on Python." in text
    assert "Prefer MIT license." in text


def test_ingest_github_runs_extraction_and_records_claims(tmp_path, capsys):
    input_path = tmp_path / "issue.json"
    output_path = tmp_path / "context.json"
    store_dir = tmp_path / ".cortex"
    input_path.write_text(
        json.dumps(
            {
                "title": "Improve Project Atlas",
                "body": "We use Python for Project Atlas and prefer concise updates.",
                "comments": [{"author": {"login": "reviewer"}, "body": "Keep docs current."}],
            }
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "ingest",
            "github",
            str(input_path),
            "--output",
            str(output_path),
            "--store-dir",
            str(store_dir),
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert output_path.exists()
    assert "Recorded" in out
    assert (store_dir / "claims.jsonl").exists()
    assert "connector input" in out.lower()


def test_connector_to_text_dispatches_docs(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Project Atlas runs on Python.", encoding="utf-8")
    text = connector_to_text("docs", path)
    assert "Project Atlas runs on Python." in text
