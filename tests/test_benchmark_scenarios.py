"""Tests for benchmarks/scenarios — validate load test scenario structure."""

from __future__ import annotations

import inspect
from pathlib import Path

BENCHMARKS_DIR = Path(__file__).resolve().parent.parent / "benchmarks"


class TestBenchmarkStructure:
    def test_locustfile_exists(self):
        assert (BENCHMARKS_DIR / "locustfile.py").exists()

    def test_scenarios_dir_exists(self):
        assert (BENCHMARKS_DIR / "scenarios").is_dir()

    def test_readme_exists(self):
        assert (BENCHMARKS_DIR / "README.md").exists()

    def test_all_scenario_files_exist(self):
        for name in ("read_heavy.py", "write_heavy.py", "mixed.py"):
            assert (BENCHMARKS_DIR / "scenarios" / name).exists(), f"Missing: {name}"


class TestReadHeavyScenario:
    def test_class_exists(self):
        from benchmarks.scenarios.read_heavy import ReadHeavyScenario
        assert inspect.isclass(ReadHeavyScenario)

    def test_has_task_methods(self):
        from benchmarks.scenarios.read_heavy import ReadHeavyScenario
        methods = [m for m in dir(ReadHeavyScenario) if not m.startswith("_")]
        assert "health_check" in methods
        assert "get_context_stats" in methods
        assert "search_nodes" in methods


class TestWriteHeavyScenario:
    def test_class_exists(self):
        from benchmarks.scenarios.write_heavy import WriteHeavyScenario
        assert inspect.isclass(WriteHeavyScenario)

    def test_has_task_methods(self):
        from benchmarks.scenarios.write_heavy import WriteHeavyScenario
        methods = [m for m in dir(WriteHeavyScenario) if not m.startswith("_")]
        assert "create_node" in methods
        assert "delete_node" in methods
        assert "create_edge" in methods


class TestMixedScenario:
    def test_class_exists(self):
        from benchmarks.scenarios.mixed import MixedScenario
        assert inspect.isclass(MixedScenario)

    def test_has_read_and_write_tasks(self):
        from benchmarks.scenarios.mixed import MixedScenario
        methods = [m for m in dir(MixedScenario) if not m.startswith("_")]
        assert "health_check" in methods
        assert "create_node" in methods
        assert "search" in methods
        assert "delete_node" in methods


class TestLocustfile:
    def test_locustfile_imports_scenarios(self):
        text = (BENCHMARKS_DIR / "locustfile.py").read_text()
        assert "ReadHeavyScenario" in text
        assert "WriteHeavyScenario" in text
        assert "MixedScenario" in text

    def test_locustfile_defines_users(self):
        text = (BENCHMARKS_DIR / "locustfile.py").read_text()
        assert "ReadHeavyUser" in text
        assert "WriteHeavyUser" in text
        assert "MixedUser" in text
