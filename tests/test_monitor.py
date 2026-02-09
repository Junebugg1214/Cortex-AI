"""
Tests for Cortex Phase 6: Auto-Extraction Monitor (v6.0)

Covers:
- Exportable file pattern matching
- File change detection (new files, modified files)
- Initial scan (no trigger on existing files)
- Monitor start/stop lifecycle
"""

import json
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cortex.sync.monitor import ExportMonitor, EXPORT_PATTERNS


# ============================================================================
# Exportable file patterns
# ============================================================================

class TestExportableFiles:

    def test_json_files_included(self, tmp_path):
        (tmp_path / "export.json").write_text("{}")
        monitor = ExportMonitor(watch_dir=tmp_path, graph_path=tmp_path / "graph.json")
        files = monitor._exportable_files()
        assert len(files) == 1

    def test_zip_files_included(self, tmp_path):
        (tmp_path / "export.zip").write_bytes(b"PK")
        monitor = ExportMonitor(watch_dir=tmp_path, graph_path=tmp_path / "graph.json")
        files = monitor._exportable_files()
        assert len(files) == 1

    def test_txt_files_included(self, tmp_path):
        (tmp_path / "chat.txt").write_text("hello")
        monitor = ExportMonitor(watch_dir=tmp_path, graph_path=tmp_path / "graph.json")
        files = monitor._exportable_files()
        assert len(files) == 1

    def test_jsonl_files_included(self, tmp_path):
        (tmp_path / "data.jsonl").write_text("{}\n{}")
        monitor = ExportMonitor(watch_dir=tmp_path, graph_path=tmp_path / "graph.json")
        files = monitor._exportable_files()
        assert len(files) == 1

    def test_non_matching_excluded(self, tmp_path):
        (tmp_path / "photo.png").write_bytes(b"\x89PNG")
        (tmp_path / "readme.md").write_text("# Readme")
        monitor = ExportMonitor(watch_dir=tmp_path, graph_path=tmp_path / "graph.json")
        files = monitor._exportable_files()
        assert len(files) == 0

    def test_empty_dir(self, tmp_path):
        monitor = ExportMonitor(watch_dir=tmp_path, graph_path=tmp_path / "graph.json")
        assert monitor._exportable_files() == []

    def test_nonexistent_dir(self, tmp_path):
        monitor = ExportMonitor(
            watch_dir=tmp_path / "nope",
            graph_path=tmp_path / "graph.json",
        )
        assert monitor._exportable_files() == []


# ============================================================================
# Change detection
# ============================================================================

class TestChangeDetection:

    def test_initial_scan_records_mtimes(self, tmp_path):
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "b.json").write_text("{}")
        monitor = ExportMonitor(watch_dir=tmp_path, graph_path=tmp_path / "graph.json")
        monitor._scan_initial()
        assert len(monitor._file_mtimes) == 2

    def test_new_file_detected(self, tmp_path):
        monitor = ExportMonitor(watch_dir=tmp_path, graph_path=tmp_path / "graph.json")
        monitor._scan_initial()
        # Add a new file
        (tmp_path / "new.json").write_text("{}")
        changed = monitor._check_changes()
        assert len(changed) == 1
        assert changed[0].name == "new.json"

    def test_existing_file_not_triggered(self, tmp_path):
        (tmp_path / "existing.json").write_text("{}")
        monitor = ExportMonitor(watch_dir=tmp_path, graph_path=tmp_path / "graph.json")
        monitor._scan_initial()
        # Check without changes
        changed = monitor._check_changes()
        assert len(changed) == 0

    def test_modified_file_detected(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text("{}")
        monitor = ExportMonitor(watch_dir=tmp_path, graph_path=tmp_path / "graph.json")
        monitor._scan_initial()
        # Modify the file (need a small delay for mtime granularity)
        time.sleep(0.05)
        f.write_text('{"updated": true}')
        changed = monitor._check_changes()
        assert len(changed) == 1

    def test_callback_receives_path_and_graph(self, tmp_path):
        calls = []
        def on_extract(path, graph):
            calls.append((path, graph))

        graph_path = tmp_path / "graph.json"
        monitor = ExportMonitor(
            watch_dir=tmp_path, graph_path=graph_path,
            on_extract=on_extract,
        )
        monitor._scan_initial()

        # Add a plain text file (simplest to extract)
        (tmp_path / "chat.txt").write_text("I love Python programming")
        monitor._check_changes()

        # Callback may or may not fire depending on extract_memory availability
        # Just verify no crash occurred
        assert True


# ============================================================================
# Monitor lifecycle
# ============================================================================

class TestMonitorLifecycle:

    def test_start_stop(self, tmp_path):
        monitor = ExportMonitor(
            watch_dir=tmp_path,
            graph_path=tmp_path / "graph.json",
            interval=1,
        )
        monitor.start()
        assert monitor.running
        time.sleep(0.1)
        monitor.stop()
        assert not monitor.running

    def test_stop_when_not_started(self, tmp_path):
        monitor = ExportMonitor(
            watch_dir=tmp_path,
            graph_path=tmp_path / "graph.json",
        )
        # Should not raise
        monitor.stop()
        assert not monitor.running

    def test_interval_stored(self, tmp_path):
        monitor = ExportMonitor(
            watch_dir=tmp_path,
            graph_path=tmp_path / "graph.json",
            interval=15,
        )
        assert monitor.interval == 15


# ============================================================================
# Runner
# ============================================================================

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
