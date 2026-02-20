"""Tests for cortex.caas.shutdown — Graceful shutdown coordinator."""

from __future__ import annotations

import signal
import threading
import time

import pytest

from cortex.caas.shutdown import ShutdownCoordinator


# ---------------------------------------------------------------------------
# TestRegistration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_register_callback(self):
        coord = ShutdownCoordinator()
        called = []
        coord.register("test", lambda: called.append("x"))
        coord.shutdown(timeout=5)
        assert called == ["x"]

    def test_multiple_callbacks(self):
        coord = ShutdownCoordinator()
        order = []
        coord.register("first", lambda: order.append("first"))
        coord.register("second", lambda: order.append("second"))
        coord.register("third", lambda: order.append("third"))
        coord.shutdown(timeout=5)
        assert len(order) == 3

    def test_reverse_execution_order(self):
        coord = ShutdownCoordinator()
        order = []
        coord.register("A", lambda: order.append("A"))
        coord.register("B", lambda: order.append("B"))
        coord.register("C", lambda: order.append("C"))
        coord.shutdown(timeout=5)
        assert order == ["C", "B", "A"]

    def test_no_callbacks(self):
        coord = ShutdownCoordinator()
        coord.shutdown(timeout=5)
        assert coord.is_shutdown


# ---------------------------------------------------------------------------
# TestShutdownBehavior
# ---------------------------------------------------------------------------

class TestShutdownBehavior:
    def test_sets_shutdown_event(self):
        coord = ShutdownCoordinator()
        assert not coord.is_shutdown
        coord.shutdown(timeout=5)
        assert coord.is_shutdown

    def test_idempotent_shutdown(self):
        coord = ShutdownCoordinator()
        count = []
        coord.register("counter", lambda: count.append(1))
        coord.shutdown(timeout=5)
        coord.shutdown(timeout=5)  # Second call should be no-op
        assert len(count) == 1

    def test_callback_failure_doesnt_block_others(self):
        coord = ShutdownCoordinator()
        results = []

        def bad_callback():
            raise RuntimeError("fail")

        coord.register("good1", lambda: results.append("good1"))
        coord.register("bad", bad_callback)
        coord.register("good2", lambda: results.append("good2"))
        coord.shutdown(timeout=10)
        # good2 (last registered, first executed) and good1 should both run
        assert "good1" in results
        assert "good2" in results

    def test_timeout_handling(self):
        """A slow callback should not block shutdown beyond the timeout."""
        coord = ShutdownCoordinator()
        coord.register("fast", lambda: None)
        coord.register("slow", lambda: time.sleep(100))
        start = time.monotonic()
        coord.shutdown(timeout=2)
        elapsed = time.monotonic() - start
        assert elapsed < 5  # Should complete well within 5s
        assert coord.is_shutdown

    def test_wait_for_shutdown_blocks(self):
        coord = ShutdownCoordinator()

        def trigger():
            time.sleep(0.1)
            coord.shutdown(timeout=5)

        t = threading.Thread(target=trigger)
        t.start()
        result = coord.wait_for_shutdown(timeout=5)
        assert result is True
        t.join()

    def test_wait_for_shutdown_timeout(self):
        coord = ShutdownCoordinator()
        result = coord.wait_for_shutdown(timeout=0.1)
        assert result is False


# ---------------------------------------------------------------------------
# TestSignalHandlers
# ---------------------------------------------------------------------------

class TestSignalHandlers:
    def test_install_from_main_thread(self):
        """Signal handlers can be installed from the main thread."""
        coord = ShutdownCoordinator()
        # This should not raise when called from main thread
        if threading.current_thread() is threading.main_thread():
            coord.install_signal_handlers()
            # Restore defaults
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.signal(signal.SIGINT, signal.SIG_DFL)

    def test_install_from_non_main_thread_raises(self):
        coord = ShutdownCoordinator()
        error = []

        def try_install():
            try:
                coord.install_signal_handlers()
            except RuntimeError as e:
                error.append(str(e))

        t = threading.Thread(target=try_install)
        t.start()
        t.join()
        assert len(error) == 1
        assert "main thread" in error[0]


# ---------------------------------------------------------------------------
# TestConcurrency
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_concurrent_shutdown_safe(self):
        """Multiple threads calling shutdown() simultaneously is safe."""
        coord = ShutdownCoordinator()
        count = []
        coord.register("counter", lambda: count.append(1))

        threads = [threading.Thread(target=coord.shutdown) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # Should only execute once despite 5 threads
        assert len(count) == 1
        assert coord.is_shutdown

    def test_register_during_normal_operation(self):
        """Registering callbacks from multiple threads is safe."""
        coord = ShutdownCoordinator()
        results = []

        def register_and_append(name):
            coord.register(name, lambda n=name: results.append(n))

        threads = [threading.Thread(target=register_and_append, args=(f"t{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        coord.shutdown(timeout=10)
        assert len(results) == 10
