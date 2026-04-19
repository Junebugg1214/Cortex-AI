"""
Cortex Auto-Extraction Monitor — Phase 6 (v6.0)

Polls a directory for new/modified export files using os.stat().
Auto-runs extraction pipeline on detected changes.
Pure Python stdlib — no external dependencies.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from cortex.compat import upgrade_v4_to_v5
from cortex.graph.graph import CortexGraph
from cortex.runtime_logging import get_logger, log_operation

LOGGER = get_logger(__name__)

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
        self.watch_dir = Path(watch_dir).resolve()
        self.graph_path = Path(graph_path)
        self.interval = interval
        # Validate watch_dir: reject path traversal (#25)
        if ".." in str(watch_dir):
            raise ValueError(f"watch_dir must not contain '..': {watch_dir}")
        self.on_extract = on_extract
        self._file_mtimes: dict[str, float] = {}
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()  # Guards file check+process (#33)

    def start(self) -> None:
        """Start monitoring in a background daemon thread."""
        self._running = True
        self._scan_initial()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        log_operation(
            LOGGER,
            logging.INFO,
            "export_monitor_start",
            "Started export monitor.",
            watch_dir=str(self.watch_dir),
            interval_seconds=self.interval,
        )

    def stop(self) -> None:
        """Signal the monitor to stop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self.interval + 5)
            self._thread = None
        log_operation(LOGGER, logging.INFO, "export_monitor_stop", "Stopped export monitor.")

    @property
    def running(self) -> bool:
        return self._running

    def _scan_initial(self) -> None:
        """Record initial file modification times without triggering extraction."""
        for path in self._exportable_files():
            try:
                self._file_mtimes[str(path)] = path.stat().st_mtime
            except OSError:
                continue

    def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            time.sleep(self.interval)
            if not self._running:
                break
            self._check_changes()

    def _check_changes(self) -> list[Path]:
        """Check for new or modified files. Returns list of changed paths."""
        with self._lock:
            changed: list[Path] = []
            current_files = self._exportable_files()

            for path in current_files:
                key = str(path)
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
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

        except Exception as exc:
            log_operation(
                LOGGER,
                logging.ERROR,
                "export_monitor_process",
                f"Error processing {path.name}.",
                exc_info=True,
                path=str(path),
                error=str(exc),
            )

    def _load_or_create_graph(self) -> CortexGraph:
        """Load existing graph from graph_path, or create empty."""
        if self.graph_path.exists():
            try:
                with open(self.graph_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                log_operation(
                    LOGGER,
                    logging.WARNING,
                    "export_monitor_graph_load",
                    f"Corrupted graph file {self.graph_path.name}; starting fresh.",
                    graph_path=str(self.graph_path),
                )
                return CortexGraph()
            version = data.get("schema_version", "")
            if version.startswith("5") or version.startswith("6"):
                return CortexGraph.from_v5_json(data)
            return upgrade_v4_to_v5(data)
        return CortexGraph()

    def _save_graph(self, graph: CortexGraph) -> None:
        """Save graph to graph_path atomically via tmp+rename."""
        import secrets as _secrets

        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.graph_path.with_suffix(f".{_secrets.token_hex(8)}.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(graph.export_v5(), f, indent=2)
        tmp_path.replace(self.graph_path)

    def _extract_from_file(self, path: Path) -> dict | None:
        """Attempt to extract v4 data from a file. Returns None on failure."""
        try:
            from cortex.extraction.extract_memory import AggressiveExtractor, load_file
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
        elif detected_format == "gemini":
            extractor.process_gemini_export(data)
        elif detected_format == "perplexity":
            extractor.process_perplexity_export(data)
        elif detected_format == "grok":
            extractor.process_grok_export(data)
        elif detected_format == "cursor":
            extractor.process_cursor_export(data)
        elif detected_format == "windsurf":
            extractor.process_windsurf_export(data)
        elif detected_format == "copilot":
            extractor.process_copilot_export(data)
        elif detected_format in {"jsonl", "claude_code"}:
            extractor.process_jsonl_messages(data)
        elif detected_format == "api_logs":
            extractor.process_api_logs(data)
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
