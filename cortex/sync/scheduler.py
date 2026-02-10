"""
Cortex Scheduled Sync — Phase 6 (v6.0)

Periodic platform sync using threading.Timer.
Config-driven, runs adapter.push() on schedule.
Pure Python stdlib — no external dependencies.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SyncSchedule:
    """A single platform sync schedule."""
    platform: str           # "claude", "system-prompt", "notion", "gdocs"
    policy: str             # "full", "professional", "technical", "minimal"
    interval_minutes: int   # sync interval
    output_dir: str         # where to write output files


@dataclass
class SyncConfig:
    """Configuration for the sync scheduler."""
    schedules: list[SyncSchedule]
    graph_path: str
    store_dir: str = ".cortex"

    @classmethod
    def from_file(cls, path: Path) -> SyncConfig:
        """Load config from a JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        schedules = [
            SyncSchedule(**s) for s in data.get("schedules", [])
        ]
        return cls(
            schedules=schedules,
            graph_path=data["graph_path"],
            store_dir=data.get("store_dir", ".cortex"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedules": [
                {
                    "platform": s.platform,
                    "policy": s.policy,
                    "interval_minutes": s.interval_minutes,
                    "output_dir": s.output_dir,
                }
                for s in self.schedules
            ],
            "graph_path": self.graph_path,
            "store_dir": self.store_dir,
        }


# ---------------------------------------------------------------------------
# Graph loader (inline to avoid circular imports)
# ---------------------------------------------------------------------------

def _load_graph_from_path(path: Path):
    """Load a v4 or v5 JSON file and return a CortexGraph."""
    from cortex.graph import CortexGraph
    from cortex.compat import upgrade_v4_to_v5

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    version = data.get("schema_version", "")
    if version.startswith("5") or version.startswith("6"):
        return CortexGraph.from_v5_json(data)
    return upgrade_v4_to_v5(data)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class SyncScheduler:
    """Run periodic platform syncs on schedule using threading.Timer."""

    def __init__(self, config: SyncConfig) -> None:
        self.config = config
        self._timers: list[threading.Timer] = []
        self._running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start all scheduled sync timers."""
        self._running = True
        for schedule in self.config.schedules:
            self._schedule_next(schedule)

    def stop(self) -> None:
        """Cancel all pending timers."""
        self._running = False
        with self._lock:
            for timer in self._timers:
                timer.cancel()
            self._timers.clear()

    @property
    def running(self) -> bool:
        return self._running

    def run_once(self) -> dict[str, list[Path]]:
        """Run all syncs immediately and return results."""
        results: dict[str, list[Path]] = {}
        for schedule in self.config.schedules:
            paths = self._execute_sync(schedule)
            results[schedule.platform] = paths
        return results

    def _schedule_next(self, schedule: SyncSchedule) -> None:
        """Schedule the next sync for a given platform."""
        if not self._running:
            return
        interval_sec = schedule.interval_minutes * 60
        timer = threading.Timer(interval_sec, self._run_sync, args=(schedule,))
        timer.daemon = True
        timer.start()
        with self._lock:
            # Prune completed timers to prevent memory leak
            self._timers = [t for t in self._timers if t.is_alive()]
            self._timers.append(timer)

    def _run_sync(self, schedule: SyncSchedule) -> None:
        """Execute a single sync and reschedule."""
        try:
            self._execute_sync(schedule)
        except Exception as exc:
            import sys
            print(f"[cortex scheduler] Error syncing {schedule.platform}: {exc}", file=sys.stderr)
        finally:
            self._schedule_next(schedule)

    def _execute_sync(self, schedule: SyncSchedule) -> list[Path]:
        """Execute a sync for one schedule. Returns output file paths."""
        from cortex.adapters import ADAPTERS
        from cortex.upai.disclosure import BUILTIN_POLICIES
        from cortex.upai.identity import UPAIIdentity

        graph_path = Path(self.config.graph_path)
        if not graph_path.exists():
            return []

        graph = _load_graph_from_path(graph_path)

        adapter = ADAPTERS.get(schedule.platform)
        if adapter is None:
            return []

        policy = BUILTIN_POLICIES.get(schedule.policy)
        if policy is None:
            return []

        # Load identity if available
        identity = None
        store_dir = Path(self.config.store_dir)
        id_path = store_dir / "identity.json"
        if id_path.exists():
            identity = UPAIIdentity.load(store_dir)

        output_dir = Path(schedule.output_dir)
        return adapter.push(graph, policy, identity=identity, output_dir=output_dir)
