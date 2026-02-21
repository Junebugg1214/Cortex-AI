"""Tests for cortex.continuous — Continuous extraction from Claude Code sessions."""

import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

from cortex.continuous import (
    CodingSessionWatcher,
)
from cortex.graph import CortexGraph, Node, make_node_id

# ---------------------------------------------------------------------------
# Helpers — synthetic Claude Code JSONL
# ---------------------------------------------------------------------------

def _user_record(content, ts="2026-02-08T10:00:00.000Z", session_id="sess-1",
                 cwd="/home/user/myproject", branch="main"):
    return {
        "type": "user",
        "uuid": "u-1",
        "sessionId": session_id,
        "timestamp": ts,
        "cwd": cwd,
        "gitBranch": branch,
        "version": "2.1.37",
        "message": {"role": "user", "content": content},
    }


def _assistant_record(tool_uses, ts="2026-02-08T10:01:00.000Z",
                      session_id="sess-1", model="claude-opus-4-6"):
    content = []
    for name, inp in tool_uses:
        content.append({
            "type": "tool_use",
            "id": f"toolu_{name}",
            "name": name,
            "input": inp,
        })
    return {
        "type": "assistant",
        "uuid": "a-1",
        "sessionId": session_id,
        "timestamp": ts,
        "cwd": "/home/user/myproject",
        "gitBranch": "main",
        "message": {
            "role": "assistant",
            "model": model,
            "content": content,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        },
    }


def _write_session_jsonl(path: Path, records: list[dict]) -> None:
    """Write records as JSONL."""
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _make_session_records(cwd="/home/user/myproject", session_id="sess-1"):
    """A sample session that touches Python files and runs pytest."""
    return [
        _user_record("Fix the bug", session_id=session_id, cwd=cwd),
        _assistant_record([
            ("Read", {"file_path": f"{cwd}/app.py"}),
            ("Edit", {"file_path": f"{cwd}/app.py",
                      "old_string": "x", "new_string": "y"}),
            ("Bash", {"command": "pytest tests/"}),
        ], session_id=session_id),
    ]


def _make_watch_dir(tmp_path: Path) -> Path:
    """Create a fake ~/.claude/projects/ structure with a session file."""
    watch_dir = tmp_path / "claude_projects"
    session_dir = watch_dir / "project-a" / "abc123"
    session_dir.mkdir(parents=True)
    _write_session_jsonl(
        session_dir / "session.jsonl",
        _make_session_records(),
    )
    return watch_dir


# ===========================================================================
# TestFileStateTracking
# ===========================================================================

class TestFileStateTracking:
    """Test file state tracking and change detection."""

    def test_new_file_detected(self, tmp_path):
        """New JSONL file is added to pending changes."""
        watch_dir = tmp_path / "projects"
        watch_dir.mkdir()
        graph_path = tmp_path / "graph.json"

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            interval=60,
        )
        watcher._graph = CortexGraph()
        watcher._scan_initial()
        assert watcher.files_tracked == 0

        # Add a new file
        sub = watch_dir / "proj" / "abc"
        sub.mkdir(parents=True)
        _write_session_jsonl(sub / "session.jsonl", _make_session_records())

        watcher._check_for_changes()
        assert len(watcher._pending_changes) == 1

    def test_modified_file_detected(self, tmp_path):
        """Modified file is added to pending changes."""
        watch_dir = _make_watch_dir(tmp_path)
        graph_path = tmp_path / "graph.json"

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            interval=60,
        )
        watcher._graph = CortexGraph()
        watcher._scan_initial()
        assert watcher.files_tracked == 1
        assert len(watcher._pending_changes) == 0

        # Modify the file
        session_file = list(watch_dir.rglob("*.jsonl"))[0]
        time.sleep(0.05)  # Ensure mtime changes
        with open(session_file, "a") as f:
            f.write(json.dumps(_user_record("more work")) + "\n")

        watcher._check_for_changes()
        assert len(watcher._pending_changes) == 1

    def test_unchanged_file_not_triggered(self, tmp_path):
        """Unchanged files don't appear in pending changes."""
        watch_dir = _make_watch_dir(tmp_path)
        graph_path = tmp_path / "graph.json"

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            interval=60,
        )
        watcher._graph = CortexGraph()
        watcher._scan_initial()

        # Check twice — no changes
        watcher._check_for_changes()
        assert len(watcher._pending_changes) == 0
        watcher._check_for_changes()
        assert len(watcher._pending_changes) == 0

    def test_nonexistent_watch_dir(self, tmp_path):
        """Watcher with nonexistent dir doesn't crash."""
        graph_path = tmp_path / "graph.json"
        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=tmp_path / "does_not_exist",
        )
        watcher._graph = CortexGraph()
        watcher._scan_initial()
        assert watcher.files_tracked == 0
        watcher._check_for_changes()
        assert len(watcher._pending_changes) == 0


# ===========================================================================
# TestDebounce
# ===========================================================================

class TestDebounce:
    """Test the settle_seconds debounce mechanism."""

    def test_file_settles_after_wait(self, tmp_path):
        """File is processed after settle_seconds of inactivity."""
        watch_dir = tmp_path / "projects"
        watch_dir.mkdir()
        graph_path = tmp_path / "graph.json"

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            settle_seconds=0.1,  # Very short for testing
            enrich=False,
        )
        watcher._graph = CortexGraph()
        watcher._scan_initial()

        # Add file
        sub = watch_dir / "proj" / "abc"
        sub.mkdir(parents=True)
        _write_session_jsonl(sub / "session.jsonl", _make_session_records())

        watcher._check_for_changes()
        assert len(watcher._pending_changes) == 1

        # Wait for settle
        time.sleep(0.15)
        processed = watcher._process_settled_files()
        assert len(processed) == 1
        assert len(watcher._pending_changes) == 0

    def test_file_not_processed_while_unsettled(self, tmp_path):
        """File is not processed before settle_seconds elapse."""
        watch_dir = tmp_path / "projects"
        watch_dir.mkdir()
        graph_path = tmp_path / "graph.json"

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            settle_seconds=60,  # Very long — won't settle
            enrich=False,
        )
        watcher._graph = CortexGraph()
        watcher._scan_initial()

        sub = watch_dir / "proj" / "abc"
        sub.mkdir(parents=True)
        _write_session_jsonl(sub / "session.jsonl", _make_session_records())

        watcher._check_for_changes()
        processed = watcher._process_settled_files()
        assert len(processed) == 0
        assert len(watcher._pending_changes) == 1  # Still pending

    def test_rapid_writes_debounced(self, tmp_path):
        """Rapid writes reset the debounce timer."""
        watch_dir = tmp_path / "projects"
        watch_dir.mkdir()
        graph_path = tmp_path / "graph.json"

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            settle_seconds=0.2,
            enrich=False,
        )
        watcher._graph = CortexGraph()
        watcher._scan_initial()

        sub = watch_dir / "proj" / "abc"
        sub.mkdir(parents=True)
        session_file = sub / "session.jsonl"
        _write_session_jsonl(session_file, _make_session_records())

        # First change detected
        watcher._check_for_changes()
        time.sleep(0.1)

        # Modify again before settle — resets timer
        with open(session_file, "a") as f:
            f.write(json.dumps(_user_record("another prompt")) + "\n")
        watcher._check_for_changes()

        # Not settled yet (timer was reset)
        processed = watcher._process_settled_files()
        assert len(processed) == 0

        # Now wait for settle
        time.sleep(0.25)
        processed = watcher._process_settled_files()
        assert len(processed) == 1


# ===========================================================================
# TestExtractionPipeline
# ===========================================================================

class TestExtractionPipeline:
    """Test the full extract-and-merge pipeline."""

    def test_single_session_extracted(self, tmp_path):
        """Single session file produces graph nodes."""
        watch_dir = _make_watch_dir(tmp_path)
        graph_path = tmp_path / "graph.json"

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            settle_seconds=0,
            enrich=False,
        )
        watcher._graph = CortexGraph()
        watcher._scan_initial()

        # Force process the file
        session_file = list(watch_dir.rglob("*.jsonl"))[0]
        watcher._extract_and_merge(session_file)

        assert len(watcher._graph.nodes) > 0
        # Should have Python (from .py files)
        python_nodes = watcher._graph.find_nodes(label="Python")
        assert len(python_nodes) >= 1

    def test_incremental_merge(self, tmp_path):
        """Processing two files incrementally merges both into graph."""
        watch_dir = tmp_path / "projects"
        watch_dir.mkdir()
        graph_path = tmp_path / "graph.json"

        # Session A — Python + pytest
        dir_a = watch_dir / "proj-a" / "aaa"
        dir_a.mkdir(parents=True)
        _write_session_jsonl(dir_a / "session.jsonl", _make_session_records(
            cwd="/home/user/proj-a", session_id="sess-a",
        ))

        # Session B — different project, same Python
        dir_b = watch_dir / "proj-b" / "bbb"
        dir_b.mkdir(parents=True)
        records_b = [
            _user_record("Deploy", session_id="sess-b", cwd="/home/user/proj-b"),
            _assistant_record([
                ("Read", {"file_path": "/home/user/proj-b/server.py"}),
                ("Bash", {"command": "docker build ."}),
            ], session_id="sess-b"),
        ]
        _write_session_jsonl(dir_b / "session.jsonl", records_b)

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            enrich=False,
        )
        watcher._graph = CortexGraph()

        # Extract both
        watcher._extract_and_merge(dir_a / "session.jsonl")
        nodes_after_a = len(watcher._graph.nodes)

        watcher._extract_and_merge(dir_b / "session.jsonl")
        nodes_after_b = len(watcher._graph.nodes)

        # B should add nodes (e.g., Docker) beyond what A had
        assert nodes_after_b >= nodes_after_a

    def test_duplicate_nodes_merged(self, tmp_path):
        """Same technology from two sessions merges into one node."""
        watch_dir = tmp_path / "projects"
        watch_dir.mkdir()
        graph_path = tmp_path / "graph.json"

        # Both sessions use Python
        for name, sid in [("a", "sess-a"), ("b", "sess-b")]:
            d = watch_dir / f"proj-{name}" / "xxx"
            d.mkdir(parents=True)
            _write_session_jsonl(d / "session.jsonl", _make_session_records(
                cwd=f"/home/user/proj-{name}", session_id=sid,
            ))

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            enrich=False,
        )
        watcher._graph = CortexGraph()

        files = sorted(watch_dir.rglob("*.jsonl"))
        for f in files:
            watcher._extract_and_merge(f)

        # Python should be ONE node, not duplicated
        python_nodes = watcher._graph.find_nodes(label="Python")
        assert len(python_nodes) == 1
        # Mention count should be accumulated
        assert python_nodes[0].mention_count >= 2

    def test_corrupt_file_skipped(self, tmp_path):
        """Corrupt JSONL doesn't crash the watcher."""
        watch_dir = tmp_path / "projects"
        sub = watch_dir / "proj" / "abc"
        sub.mkdir(parents=True)
        graph_path = tmp_path / "graph.json"

        # Write corrupt content
        (sub / "session.jsonl").write_text("not valid json\n{broken", encoding="utf-8")

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            enrich=False,
        )
        watcher._graph = CortexGraph()

        # Should not raise
        watcher._extract_and_merge(sub / "session.jsonl")
        assert len(watcher._graph.nodes) == 0

    def test_empty_file_handled(self, tmp_path):
        """Empty JSONL produces no nodes."""
        watch_dir = tmp_path / "projects"
        sub = watch_dir / "proj" / "abc"
        sub.mkdir(parents=True)
        graph_path = tmp_path / "graph.json"

        (sub / "session.jsonl").write_text("", encoding="utf-8")

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            enrich=False,
        )
        watcher._graph = CortexGraph()
        watcher._extract_and_merge(sub / "session.jsonl")
        assert len(watcher._graph.nodes) == 0

    def test_graph_saved_after_processing(self, tmp_path):
        """Graph is written to disk after processing settled files."""
        watch_dir = tmp_path / "projects"
        watch_dir.mkdir()
        graph_path = tmp_path / "graph.json"

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            settle_seconds=0,
            enrich=False,
        )
        watcher.start()

        # Add a file AFTER start (so it's detected as new)
        sub = watch_dir / "proj" / "abc"
        sub.mkdir(parents=True)
        _write_session_jsonl(sub / "session.jsonl", _make_session_records())

        watcher.process_now()
        watcher.stop()

        assert graph_path.exists()
        data = json.loads(graph_path.read_text())
        assert data.get("schema_version", "").startswith(("5", "6"))


# ===========================================================================
# TestGraphMerge
# ===========================================================================

class TestGraphMerge:
    """Test _merge_graph node/edge merge logic."""

    def test_new_node_added(self):
        """Novel node is added to graph."""
        watcher = CodingSessionWatcher(graph_path=Path("/tmp/x.json"))
        watcher._graph = CortexGraph()

        new_graph = CortexGraph()
        node = Node(
            id=make_node_id("Python"),
            label="Python",
            tags=["technical_expertise"],
            confidence=0.9,
            properties={},
        )
        new_graph.add_node(node)
        watcher._merge_graph(new_graph)

        assert len(watcher._graph.nodes) == 1
        assert watcher._graph.find_nodes(label="Python")

    def test_existing_node_updated(self):
        """Merging same-label node updates confidence and mentions."""
        watcher = CodingSessionWatcher(graph_path=Path("/tmp/x.json"))
        watcher._graph = CortexGraph()

        # Add initial node
        initial = Node(
            id=make_node_id("Python"),
            label="Python",
            tags=["technical_expertise"],
            confidence=0.7,
            properties={},
            mention_count=5,
        )
        watcher._graph.add_node(initial)

        # Merge with higher confidence
        new_graph = CortexGraph()
        updated = Node(
            id=make_node_id("Python"),
            label="Python",
            tags=["domain_knowledge"],
            confidence=0.9,
            properties={},
            mention_count=3,
        )
        new_graph.add_node(updated)
        watcher._merge_graph(new_graph)

        result = watcher._graph.find_nodes(label="Python")
        assert len(result) == 1
        assert result[0].confidence == 0.9  # max
        assert result[0].mention_count == 8  # accumulated
        assert "technical_expertise" in result[0].tags
        assert "domain_knowledge" in result[0].tags

    def test_edges_transferred(self):
        """Edges are added when both endpoints exist."""
        from cortex.graph import Edge, make_edge_id

        watcher = CodingSessionWatcher(graph_path=Path("/tmp/x.json"))
        watcher._graph = CortexGraph()

        # Add two nodes to main graph
        for label in ["Python", "Pytest"]:
            watcher._graph.add_node(Node(
                id=make_node_id(label), label=label,
                tags=["technical_expertise"], confidence=0.8, properties={},
            ))

        # New graph with same nodes + edge between them
        new_graph = CortexGraph()
        for label in ["Python", "Pytest"]:
            new_graph.add_node(Node(
                id=make_node_id(label), label=label,
                tags=["technical_expertise"], confidence=0.8, properties={},
            ))
        edge = Edge(
            id=make_edge_id(make_node_id("Python"), make_node_id("Pytest"), "used_in"),
            source_id=make_node_id("Python"),
            target_id=make_node_id("Pytest"),
            relation="used_in",
            confidence=0.6,
        )
        new_graph.edges[edge.id] = edge
        watcher._merge_graph(new_graph)

        assert len(watcher._graph.edges) == 1

    def test_edge_skipped_if_endpoint_missing(self):
        """Edges are not added if endpoints don't exist in graph."""
        from cortex.graph import Edge, make_edge_id

        watcher = CodingSessionWatcher(graph_path=Path("/tmp/x.json"))
        watcher._graph = CortexGraph()

        new_graph = CortexGraph()
        edge = Edge(
            id=make_edge_id("fake_a", "fake_b", "related"),
            source_id="fake_a",
            target_id="fake_b",
            relation="related",
            confidence=0.5,
        )
        new_graph.edges[edge.id] = edge
        watcher._merge_graph(new_graph)

        assert len(watcher._graph.edges) == 0


# ===========================================================================
# TestOnUpdateCallback
# ===========================================================================

class TestOnUpdateCallback:
    """Test the callback/hook mechanism."""

    def test_callback_fires_after_extraction(self, tmp_path):
        """on_update callback is called after successful extraction."""
        watch_dir = tmp_path / "projects"
        watch_dir.mkdir()
        graph_path = tmp_path / "graph.json"
        callback_args = []

        def on_update(gpath, graph):
            callback_args.append((gpath, len(graph.nodes)))

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            settle_seconds=0,
            enrich=False,
            on_update=on_update,
        )
        watcher.start()

        # Add file AFTER start so it's detected as new
        sub = watch_dir / "proj" / "abc"
        sub.mkdir(parents=True)
        _write_session_jsonl(sub / "session.jsonl", _make_session_records())

        watcher.process_now()
        watcher.stop()

        assert len(callback_args) == 1
        assert callback_args[0][1] > 0  # graph has nodes

    def test_no_callback_if_none(self, tmp_path):
        """No crash when on_update is None."""
        watch_dir = _make_watch_dir(tmp_path)
        graph_path = tmp_path / "graph.json"

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            settle_seconds=0,
            enrich=False,
            on_update=None,
        )
        watcher.start()
        watcher.process_now()
        watcher.stop()
        # No crash = pass


# ===========================================================================
# TestWatcherLifecycle
# ===========================================================================

class TestWatcherLifecycle:
    """Test start/stop/running state."""

    def test_start_stop(self, tmp_path):
        """Watcher starts and stops cleanly."""
        graph_path = tmp_path / "graph.json"
        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=tmp_path,
            interval=60,
        )
        watcher.start()
        assert watcher.running
        watcher.stop()
        assert not watcher.running

    def test_stop_when_not_started(self, tmp_path):
        """Stopping a never-started watcher doesn't crash."""
        graph_path = tmp_path / "graph.json"
        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=tmp_path,
        )
        watcher.stop()  # Should not raise
        assert not watcher.running

    def test_process_now_forces_extraction(self, tmp_path):
        """process_now() processes all pending files immediately."""
        watch_dir = tmp_path / "projects"
        watch_dir.mkdir()
        graph_path = tmp_path / "graph.json"

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
            settle_seconds=60,  # Long settle — won't settle naturally
            enrich=False,
        )
        watcher._graph = CortexGraph()
        watcher._scan_initial()

        # Add file
        sub = watch_dir / "proj" / "abc"
        sub.mkdir(parents=True)
        _write_session_jsonl(sub / "session.jsonl", _make_session_records())

        # process_now overrides settle and processes immediately
        processed = watcher.process_now()
        assert len(processed) == 1

    def test_initial_scan_no_extraction(self, tmp_path):
        """Files present at start are tracked but not extracted."""
        watch_dir = _make_watch_dir(tmp_path)
        graph_path = tmp_path / "graph.json"

        watcher = CodingSessionWatcher(
            graph_path=graph_path,
            watch_dir=watch_dir,
        )
        watcher._graph = CortexGraph()
        watcher._scan_initial()

        assert watcher.files_tracked == 1
        # No pending changes — initial files are baselined
        assert len(watcher._pending_changes) == 0
        # Graph is empty — no extraction happened
        assert len(watcher._graph.nodes) == 0


# ===========================================================================
# TestProjectFilter
# ===========================================================================

class TestProjectFilter:
    """Test project_filter substring matching."""

    def test_filter_includes_matching(self, tmp_path):
        """Filter includes files with matching path substring."""
        watch_dir = tmp_path / "projects"
        for name in ["myapp", "other"]:
            d = watch_dir / name / "abc"
            d.mkdir(parents=True)
            _write_session_jsonl(d / "session.jsonl", _make_session_records())

        watcher = CodingSessionWatcher(
            graph_path=tmp_path / "graph.json",
            watch_dir=watch_dir,
            project_filter="myapp",
        )
        watcher._graph = CortexGraph()
        watcher._scan_initial()
        assert watcher.files_tracked == 1

    def test_filter_excludes_nonmatching(self, tmp_path):
        """Filter excludes files that don't match."""
        watch_dir = tmp_path / "projects"
        d = watch_dir / "other-project" / "abc"
        d.mkdir(parents=True)
        _write_session_jsonl(d / "session.jsonl", _make_session_records())

        watcher = CodingSessionWatcher(
            graph_path=tmp_path / "graph.json",
            watch_dir=watch_dir,
            project_filter="myapp",
        )
        watcher._graph = CortexGraph()
        watcher._scan_initial()
        assert watcher.files_tracked == 0


# ===========================================================================
# TestMigrateSubcommand
# ===========================================================================

class TestMigrateSubcommand:
    """Tests for the --watch flag on extract-coding subcommand."""

    def test_extract_coding_watch_help(self):
        """extract-coding --help shows --watch flag."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(_ROOT / "migrate.py"), "extract-coding", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--watch" in result.stdout
        assert "--interval" in result.stdout
        assert "--settle" in result.stdout
        assert "--context-refresh" in result.stdout
