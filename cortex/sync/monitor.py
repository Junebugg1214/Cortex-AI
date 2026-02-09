"""
Cortex Auto-Extraction Monitor — Phase 6 (v6.0)

Polls a directory for new/modified export files using os.stat().
Auto-runs extraction pipeline on detected changes.
Pure Python stdlib — no external dependencies.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Any

from cortex.graph import CortexGraph
from cortex.compat import upgrade_v4_to_v5


# ---------------------------------------------------------------------------
# Exportable file patterns
# ---------------------------------------------------------------------------

EXPORT_PATTERNS = ("*.json", "*.zip", "*.jsonl", "*.txt")


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class ExportMonitor:
    """Watch a directory for new/modified export files and auto-extract."""

    def __init__(
        self,
        watch_dir: Path,
        graph_path: Path,
        interval: int = 30,
        on_extract: Callable[[Path, CortexGraph], None] | None = None,
    ) -> None:
        self.watch_dir = Path(watch_dir)
        self.graph_path = Path(graph_path)
        self.interval = interval
        self.on_extract = on_extract
        self._file_mtimes: dict[str, float] = {}
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start monitoring in a background daemon thread."""
        self._running = True
        self._scan_initial()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the monitor to stop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self.interval + 5)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._running

    def _scan_initial(self) -> None:
        """Record initial file modification times without triggering extraction."""
        for path in self._exportable_files():
            self._file_mtimes[str(path)] = path.stat().st_mtime

    def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            time.sleep(self.interval)
            if not self._running:
                break
            self._check_changes()

    def _check_changes(self) -> list[Path]:
        """Check for new or modified files. Returns list of changed paths."""
        changed: list[Path] = []
        current_files = self._exportable_files()

        for path in current_files:
            key = str(path)
            mtime = path.stat().st_mtime
            old_mtime = self._file_mtimes.get(key)
            if old_mtime is None or mtime > old_mtime:
                changed.append(path)
                self._file_mtimes[key] = mtime

        for path in changed:
            self._process_file(path)

        return changed

    def _exportable_files(self) -> list[Path]:
        """List files in watch_dir that look like chat exports."""
        if not self.watch_dir.exists():
            return []
        files: list[Path] = []
        for pattern in EXPORT_PATTERNS:
            files.extend(self.watch_dir.glob(pattern))
        return sorted(files)

    def _process_file(self, path: Path) -> None:
        """Run extraction pipeline on a detected file."""
        # Load existing graph (or create empty)
        graph = self._load_or_create_graph()

        # Attempt extraction
        try:
            v4_data = self._extract_from_file(path)
            if v4_data is None:
                return

            new_graph = upgrade_v4_to_v5(v4_data)

            # Merge new nodes into existing graph
            for node in new_graph.nodes.values():
                existing = graph.find_nodes(label=node.label)
                if not existing:
                    graph.add_node(node)

            # Merge new edges
            for edge in new_graph.edges.values():
                if edge.id not in graph.edges:
                    if edge.source_id in graph.nodes and edge.target_id in graph.nodes:
                        graph.add_edge(edge)

            # Save updated graph
            self._save_graph(graph)

            if self.on_extract:
                self.on_extract(path, graph)

        except Exception:
            pass  # Silently skip files that fail extraction

    def _load_or_create_graph(self) -> CortexGraph:
        """Load existing graph from graph_path, or create empty."""
        if self.graph_path.exists():
            with open(self.graph_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            version = data.get("schema_version", "")
            if version.startswith("5") or version.startswith("6"):
                return CortexGraph.from_v5_json(data)
            return upgrade_v4_to_v5(data)
        return CortexGraph()

    def _save_graph(self, graph: CortexGraph) -> None:
        """Save graph to graph_path."""
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.graph_path, "w", encoding="utf-8") as f:
            json.dump(graph.export_v5(), f, indent=2)

    def _extract_from_file(self, path: Path) -> dict | None:
        """Attempt to extract v4 data from a file. Returns None on failure."""
        # Import extraction tools (lazy, they have heavy path setup)
        _root = Path(__file__).resolve().parent.parent.parent
        if str(_root / "skills" / "chatbot-memory-extractor" / "scripts") not in sys.path:
            sys.path.insert(0, str(_root / "skills" / "chatbot-memory-extractor" / "scripts"))

        try:
            from extract_memory import AggressiveExtractor, load_file
        except ImportError:
            return None

        try:
            data, detected_format = load_file(path)
        except Exception:
            return None

        extractor = AggressiveExtractor()

        # Route through extraction
        if detected_format == "openai":
            extractor.process_openai_export(data)
        elif isinstance(data, list):
            extractor.process_messages_list(data)
        elif isinstance(data, dict) and "messages" in data:
            extractor.process_messages_list(data["messages"])
        elif isinstance(data, str):
            extractor.process_plain_text(data)
        else:
            extractor.process_plain_text(json.dumps(data))

        extractor.post_process()
        return extractor.context.export()
