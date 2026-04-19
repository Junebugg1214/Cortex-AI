"""
Cortex Continuous Extraction — Watch Claude Code sessions in real-time.

Polls ~/.claude/projects/ for new/modified JSONL files, extracts behavioral
signals, and incrementally merges them into an existing Cortex graph.
Optionally chains to context-write for cross-platform refresh.

Zero external deps. Pure Python stdlib + threading for background.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Per-file state tracking
# ---------------------------------------------------------------------------


@dataclass
class _FileState:
    """Track per-file state for incremental change detection."""

    mtime: float
    size: int
    last_processed: float  # timestamp when last processed
    line_count: int = 0  # reserved for future incremental line tracking


# ---------------------------------------------------------------------------
# Core watcher
# ---------------------------------------------------------------------------

_DEFAULT_WATCH_DIR = Path.home() / ".claude" / "projects"


class CodingSessionWatcher:
    """Watch for Claude Code session changes and auto-extract to graph."""

    def __init__(
        self,
        graph_path: Path,
        watch_dir: Path | None = None,
        project_filter: str | None = None,
        interval: int = 10,
        settle_seconds: float = 5.0,
        enrich: bool = True,
        on_update: Callable[[Path, object], None] | None = None,
    ) -> None:
        self.graph_path = Path(graph_path)
        self.watch_dir = Path(watch_dir) if watch_dir else _DEFAULT_WATCH_DIR
        self.project_filter = project_filter
        self.interval = interval
        self.settle_seconds = settle_seconds
        self.enrich = enrich
        self.on_update = on_update

        self._file_states: dict[str, _FileState] = {}
        self._pending_changes: dict[str, float] = {}
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._graph = None  # Loaded lazily

    # -- Public API ---------------------------------------------------------

    def start(self) -> None:
        """Start watching in a background daemon thread."""
        if self._running:
            return
        self._stop_event.clear()
        self._graph = self._load_or_create_graph()
        self._scan_initial()
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the watcher to stop."""
        self._running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def files_tracked(self) -> int:
        """Number of JSONL files currently being tracked."""
        return len(self._file_states)

    def process_now(self) -> list[Path]:
        """Force immediate processing of all pending changes (for testing)."""
        self._check_for_changes()
        # Force all pending as settled
        with self._lock:
            for key in list(self._pending_changes):
                self._pending_changes[key] = 0.0  # epoch = always settled
        return self._process_settled_files()

    # -- Private: polling ---------------------------------------------------

    def _scan_initial(self) -> None:
        """Record initial file states without triggering extraction."""
        for path in self._discover_jsonl_files():
            key = str(path)
            try:
                stat = path.stat()
                self._file_states[key] = _FileState(
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                    last_processed=time.time(),
                )
            except OSError:
                pass

    def _poll_loop(self) -> None:
        """Main polling loop. Runs in daemon thread."""
        while self._running:
            if self._stop_event.wait(self.interval):
                break
            self._check_for_changes()
            self._process_settled_files()

    def _discover_jsonl_files(self) -> list[Path]:
        """Find all *.jsonl files under watch_dir, applying project_filter."""
        if not self.watch_dir.exists():
            return []
        files = list(self.watch_dir.rglob("*.jsonl"))
        if self.project_filter:
            files = [f for f in files if self.project_filter in str(f)]
        return sorted(files)

    def _check_for_changes(self) -> None:
        """Compare current file stats against tracked state."""
        current_files = set()
        for path in self._discover_jsonl_files():
            key = str(path)
            current_files.add(key)
            try:
                stat = path.stat()
            except OSError:
                continue

            with self._lock:
                existing = self._file_states.get(key)
                if existing is None or stat.st_mtime != existing.mtime or stat.st_size != existing.size:
                    self._pending_changes[key] = time.time()

        # Clean up state for files that no longer exist
        with self._lock:
            stale = [k for k in self._file_states if k not in current_files]
            for k in stale:
                del self._file_states[k]
                self._pending_changes.pop(k, None)

    def _process_settled_files(self) -> list[Path]:
        """Process files that have been stable for settle_seconds."""
        now = time.time()
        settled: list[str] = []
        with self._lock:
            for path_str, last_change in list(self._pending_changes.items()):
                if (now - last_change) >= self.settle_seconds:
                    settled.append(path_str)

        processed: list[Path] = []
        for path_str in settled:
            path = Path(path_str)
            try:
                self._extract_and_merge(path)
                processed.append(path)
            except Exception as exc:
                import sys as _sys

                print(f"  [cortex] extraction failed for {path.name}: {exc}", file=_sys.stderr)
            finally:
                with self._lock:
                    self._pending_changes.pop(path_str, None)
                # Update file state
                try:
                    stat = path.stat()
                    self._file_states[path_str] = _FileState(
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                        last_processed=now,
                    )
                except OSError:
                    pass

        if processed:
            self._save_graph()
            if self.on_update:
                try:
                    self.on_update(self.graph_path, self._graph)
                except Exception as exc:
                    import sys

                    print(f"[cortex continuous] on_update callback error: {exc}", file=sys.stderr)

        return processed

    # -- Private: extraction pipeline ---------------------------------------

    def _extract_and_merge(self, path: Path) -> None:
        """Full extraction pipeline for a single JSONL file."""
        # Lazy imports to avoid circular deps and keep startup fast
        from cortex.coding import (
            enrich_session,
            load_claude_code_session,
            parse_claude_code_session,
            session_to_context,
        )
        from cortex.compat import upgrade_v4_to_v5

        records = load_claude_code_session(path)
        if not records:
            return

        session = parse_claude_code_session(records)

        if self.enrich and session.project_path:
            try:
                enrich_session(session)
            except Exception:
                pass  # Enrichment failure is non-fatal

        v4_data = session_to_context(session)
        new_graph = upgrade_v4_to_v5(v4_data)
        self._merge_graph(new_graph)

    def _merge_graph(self, new_graph) -> None:
        """Merge nodes and edges from new_graph into self._graph."""
        # Map new_graph node IDs to self._graph node IDs (for edge rewiring)
        id_map: dict[str, str] = {}
        existing_by_label = {node.label: node for node in self._graph.nodes.values()}
        for new_node in new_graph.nodes.values():
            target = existing_by_label.get(new_node.label)
            if target is not None:
                id_map[new_node.id] = target.id
                target.confidence = max(target.confidence, new_node.confidence)
                target.mention_count += new_node.mention_count
                # Union tags preserving order
                target.tags = list(dict.fromkeys(target.tags + new_node.tags))
                if len(new_node.brief) > len(target.brief):
                    target.brief = new_node.brief
                if len(new_node.full_description) > len(target.full_description):
                    target.full_description = new_node.full_description
                target.metrics = list(dict.fromkeys(target.metrics + new_node.metrics))
                if new_node.first_seen and (not target.first_seen or new_node.first_seen < target.first_seen):
                    target.first_seen = new_node.first_seen
                if new_node.last_seen and (not target.last_seen or new_node.last_seen > target.last_seen):
                    target.last_seen = new_node.last_seen
            else:
                id_map[new_node.id] = new_node.id
                self._graph.add_node(new_node)
                existing_by_label[new_node.label] = new_node

        for edge in new_graph.edges.values():
            src = id_map.get(edge.source_id)
            tgt = id_map.get(edge.target_id)
            if src and tgt and src in self._graph.nodes and tgt in self._graph.nodes:
                from cortex.graph.graph import Edge, make_edge_id

                new_eid = make_edge_id(src, tgt, edge.relation)
                if new_eid not in self._graph.edges:
                    rewired = Edge(
                        id=new_eid,
                        source_id=src,
                        target_id=tgt,
                        relation=edge.relation,
                        confidence=edge.confidence,
                        first_seen=edge.first_seen,
                        last_seen=edge.last_seen,
                    )
                    self._graph.add_edge(rewired)

    # -- Private: graph I/O -------------------------------------------------

    def _load_or_create_graph(self):
        """Load existing graph from graph_path, or create empty."""
        from cortex.compat import upgrade_v4_to_v5
        from cortex.graph.graph import CortexGraph

        if self.graph_path.exists():
            try:
                with open(self.graph_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                import sys

                print(f"[cortex] Warning: corrupted graph at {self.graph_path}: {exc}", file=sys.stderr)
                return CortexGraph()
            version = data.get("schema_version", "")
            if version.startswith("5") or version.startswith("6"):
                return CortexGraph.from_v5_json(data)
            return upgrade_v4_to_v5(data)
        return CortexGraph()

    def _save_graph(self) -> None:
        """Save graph to graph_path atomically (write tmp + rename)."""
        import random as _rng

        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = f".tmp_{_rng.randint(0, 0xFFFFFF):06x}"
        tmp_path = self.graph_path.with_suffix(suffix)
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._graph.export_v5(), f, indent=2)
            os.replace(str(tmp_path), str(self.graph_path))
        except BaseException:
            # Clean up temp file on failure
            try:
                os.unlink(str(tmp_path))
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# High-level convenience function for CLI
# ---------------------------------------------------------------------------


def watch_coding_sessions(
    graph_path: str,
    project_filter: str | None = None,
    interval: int = 10,
    settle_seconds: float = 5.0,
    enrich: bool = True,
    context_platforms: list[str] | None = None,
    context_policy: str | None = None,
    context_max_chars: int = 1500,
    verbose: bool = False,
) -> None:
    """Watch Claude Code sessions and auto-extract. Blocks until Ctrl+C.

    Args:
        graph_path: Path to Cortex graph JSON (created if not exists).
        project_filter: Only watch sessions matching this substring.
        interval: Poll interval in seconds.
        settle_seconds: Debounce — seconds of inactivity before processing.
        enrich: Run project enrichment on extracted sessions.
        context_platforms: If set, auto-refresh context files after each update.
        context_policy: Disclosure policy for context refresh.
        context_max_chars: Max chars for context output.
        verbose: Print status messages.
    """

    def on_update(gpath: Path, graph) -> None:
        if verbose:
            print(f"  Graph updated: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
        if context_platforms:
            from cortex.portability.context import write_context

            results = write_context(
                graph_path=str(gpath),
                platforms=context_platforms,
                policy=context_policy,
                max_chars=context_max_chars,
            )
            if verbose:
                for name, fpath, status in results:
                    if status in ("created", "updated"):
                        print(f"  Context: {name} {status} ({fpath})")

    watcher = CodingSessionWatcher(
        graph_path=Path(graph_path),
        project_filter=project_filter,
        interval=interval,
        settle_seconds=settle_seconds,
        enrich=enrich,
        on_update=on_update,
    )
    watcher.start()

    if verbose:
        print(f"Watching {watcher.watch_dir} ({watcher.files_tracked} files tracked)")
        print(f"  Graph: {graph_path}")
        print(f"  Interval: {interval}s, settle: {settle_seconds}s")
        if context_platforms:
            print(f"  Auto-refresh: {', '.join(context_platforms)}")
        print("Press Ctrl+C to stop.\n")

    try:
        while watcher.running:
            time.sleep(1)
    except KeyboardInterrupt:
        if verbose:
            print("\nStopping...")
        watcher.stop()
