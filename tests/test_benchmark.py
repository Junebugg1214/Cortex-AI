import json

from cortex.benchmark import main as benchmark_main
from cortex.benchmark import run_release_benchmark
from cortex.release import PROJECT_VERSION


def test_release_benchmark_returns_release_and_operation_summaries(tmp_path):
    result = run_release_benchmark(store_dir=tmp_path / ".cortex-bench", iterations=2, node_count=8)

    assert result["status"] == "ok"
    assert result["release"]["project_version"] == PROJECT_VERSION
    assert result["operations"]["commit"]["count"] == 2
    assert result["operations"]["query_search"]["count"] == 2
    assert result["last_results"]["merge"]["ok"] is True


def test_benchmark_cli_writes_report(tmp_path, capsys):
    output_path = tmp_path / "benchmark.json"

    rc = benchmark_main(
        [
            "--store-dir",
            str(tmp_path / ".cortex-bench"),
            "--iterations",
            "1",
            "--nodes",
            "6",
            "--output",
            str(output_path),
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert rc == 0
    assert "Wrote benchmark report" in out
    assert payload["operations"]["index_rebuild"]["count"] == 1
