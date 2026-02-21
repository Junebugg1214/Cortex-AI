"""
Tests for Cortex Phase 6: Scheduled Sync (v6.0)

Covers:
- SyncConfig loading from JSON
- SyncSchedule dataclass
- SyncScheduler start/stop lifecycle
- run_once execution
- Timer cancellation on stop
"""

import json
import sys
import time

import pytest

from cortex.sync.scheduler import SyncConfig, SyncSchedule, SyncScheduler

# ============================================================================
# SyncSchedule
# ============================================================================

class TestSyncSchedule:

    def test_creation(self):
        s = SyncSchedule(
            platform="claude",
            policy="professional",
            interval_minutes=60,
            output_dir="./sync/claude",
        )
        assert s.platform == "claude"
        assert s.interval_minutes == 60


# ============================================================================
# SyncConfig
# ============================================================================

class TestSyncConfig:

    def test_from_file(self, tmp_path):
        config_data = {
            "schedules": [
                {
                    "platform": "claude",
                    "policy": "professional",
                    "interval_minutes": 60,
                    "output_dir": "./sync/claude",
                },
                {
                    "platform": "system-prompt",
                    "policy": "technical",
                    "interval_minutes": 120,
                    "output_dir": "./sync/sp",
                },
            ],
            "graph_path": "context.json",
            "store_dir": ".cortex",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = SyncConfig.from_file(config_file)
        assert len(config.schedules) == 2
        assert config.graph_path == "context.json"
        assert config.store_dir == ".cortex"

    def test_default_store_dir(self, tmp_path):
        config_data = {
            "schedules": [],
            "graph_path": "context.json",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        config = SyncConfig.from_file(config_file)
        assert config.store_dir == ".cortex"

    def test_to_dict(self):
        config = SyncConfig(
            schedules=[
                SyncSchedule("claude", "full", 60, "./out"),
            ],
            graph_path="ctx.json",
        )
        d = config.to_dict()
        assert d["graph_path"] == "ctx.json"
        assert len(d["schedules"]) == 1
        assert d["schedules"][0]["platform"] == "claude"

    def test_empty_schedules(self, tmp_path):
        config_data = {"schedules": [], "graph_path": "ctx.json"}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        config = SyncConfig.from_file(config_file)
        assert config.schedules == []


# ============================================================================
# SyncScheduler
# ============================================================================

class TestSyncScheduler:

    def _config(self, tmp_path):
        # Create a minimal valid graph file
        from cortex.graph import CortexGraph, Node
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Test", tags=["t"], confidence=0.5))
        graph_path = tmp_path / "context.json"
        graph_path.write_text(json.dumps(g.export_v5(), indent=2))

        return SyncConfig(
            schedules=[
                SyncSchedule(
                    platform="system-prompt",
                    policy="full",
                    interval_minutes=999,  # Long interval so it won't fire during test
                    output_dir=str(tmp_path / "sync_out"),
                ),
            ],
            graph_path=str(graph_path),
            store_dir=str(tmp_path / ".cortex"),
        )

    def test_start_stop(self, tmp_path):
        config = self._config(tmp_path)
        scheduler = SyncScheduler(config)
        scheduler.start()
        assert scheduler.running
        time.sleep(0.1)
        scheduler.stop()
        assert not scheduler.running

    def test_timers_cancelled_on_stop(self, tmp_path):
        config = self._config(tmp_path)
        scheduler = SyncScheduler(config)
        scheduler.start()
        assert len(scheduler._timers) >= 1
        scheduler.stop()
        assert len(scheduler._timers) == 0

    def test_run_once(self, tmp_path):
        config = self._config(tmp_path)
        scheduler = SyncScheduler(config)
        results = scheduler.run_once()
        assert "system-prompt" in results
        # Should have produced output files
        assert len(results["system-prompt"]) >= 1

    def test_run_once_missing_graph(self, tmp_path):
        config = SyncConfig(
            schedules=[
                SyncSchedule("claude", "full", 60, str(tmp_path / "out")),
            ],
            graph_path=str(tmp_path / "nonexistent.json"),
        )
        scheduler = SyncScheduler(config)
        results = scheduler.run_once()
        assert results["claude"] == []

    def test_run_once_invalid_platform(self, tmp_path):
        config = self._config(tmp_path)
        config.schedules = [
            SyncSchedule("nonexistent_platform", "full", 60, str(tmp_path / "out")),
        ]
        scheduler = SyncScheduler(config)
        results = scheduler.run_once()
        assert results["nonexistent_platform"] == []

    def test_run_once_invalid_policy(self, tmp_path):
        config = self._config(tmp_path)
        config.schedules = [
            SyncSchedule("system-prompt", "nonexistent_policy", 60, str(tmp_path / "out")),
        ]
        scheduler = SyncScheduler(config)
        results = scheduler.run_once()
        assert results["system-prompt"] == []


# ============================================================================
# Runner
# ============================================================================

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
