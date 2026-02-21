"""Tests for cortex.plugins — hook-based plugin system."""

from __future__ import annotations

import types

import pytest

from cortex.plugins import HOOKS, PluginManager, PluginRegistry

# ---------------------------------------------------------------------------
# PluginRegistry tests
# ---------------------------------------------------------------------------

class TestPluginRegistry:
    def test_on_valid_hook(self):
        reg = PluginRegistry()
        calls = []
        reg.on("POST_NODE_CREATE", lambda ctx: calls.append(ctx))
        assert reg.subscriber_count("POST_NODE_CREATE") == 1

    def test_on_invalid_hook_raises(self):
        reg = PluginRegistry()
        with pytest.raises(ValueError, match="Unknown hook"):
            reg.on("INVALID_HOOK", lambda ctx: None)

    def test_multiple_subscribers(self):
        reg = PluginRegistry()
        reg.on("PRE_SEARCH", lambda ctx: None)
        reg.on("PRE_SEARCH", lambda ctx: None)
        reg.on("PRE_SEARCH", lambda ctx: None)
        assert reg.subscriber_count("PRE_SEARCH") == 3

    def test_hook_names(self):
        reg = PluginRegistry()
        assert reg.hook_names == HOOKS
        assert len(HOOKS) == 12

    def test_loaded_plugins_empty(self):
        reg = PluginRegistry()
        assert reg.loaded_plugins == []


# ---------------------------------------------------------------------------
# PluginManager tests
# ---------------------------------------------------------------------------

class TestPluginManager:
    def test_fire_no_subscribers(self):
        mgr = PluginManager()
        # Should not raise
        mgr.fire("POST_NODE_CREATE", {"node_id": "abc"})

    def test_fire_with_subscriber(self):
        mgr = PluginManager()
        calls = []
        mgr.registry.on("POST_NODE_CREATE", lambda ctx: calls.append(ctx))
        mgr.fire("POST_NODE_CREATE", {"node_id": "n1"})
        assert len(calls) == 1
        assert calls[0]["node_id"] == "n1"

    def test_fire_multiple_subscribers_ordered(self):
        mgr = PluginManager()
        order = []
        mgr.registry.on("POST_EDGE_CREATE", lambda ctx: order.append("a"))
        mgr.registry.on("POST_EDGE_CREATE", lambda ctx: order.append("b"))
        mgr.fire("POST_EDGE_CREATE", {})
        assert order == ["a", "b"]

    def test_fire_unknown_hook_noop(self):
        mgr = PluginManager()
        # Unknown hook silently ignored
        mgr.fire("NOT_A_HOOK", {"data": 1})

    def test_fire_error_in_callback_logged_not_raised(self):
        mgr = PluginManager()
        calls = []

        def bad_callback(ctx):
            raise RuntimeError("plugin boom")

        def good_callback(ctx):
            calls.append("ok")

        mgr.registry.on("POST_NODE_DELETE", bad_callback)
        mgr.registry.on("POST_NODE_DELETE", good_callback)
        # Should not raise; good callback still runs
        mgr.fire("POST_NODE_DELETE", {})
        assert calls == ["ok"]

    def test_fire_none_context(self):
        mgr = PluginManager()
        calls = []
        mgr.registry.on("PRE_SEARCH", lambda ctx: calls.append(ctx))
        mgr.fire("PRE_SEARCH")
        assert calls == [{}]

    def test_load_module(self):
        # Create a temporary module in sys.modules
        mod = types.ModuleType("_test_plugin_load")
        calls = []

        def register(registry):
            registry.on("POST_SEARCH", lambda ctx: calls.append(ctx))

        mod.register = register
        import sys
        sys.modules["_test_plugin_load"] = mod
        try:
            mgr = PluginManager()
            mgr.load("_test_plugin_load")
            assert "_test_plugin_load" in mgr.loaded_plugins
            mgr.fire("POST_SEARCH", {"query": "test"})
            assert len(calls) == 1
        finally:
            del sys.modules["_test_plugin_load"]

    def test_load_module_missing_register(self):
        mod = types.ModuleType("_test_plugin_no_register")
        import sys
        sys.modules["_test_plugin_no_register"] = mod
        try:
            mgr = PluginManager()
            mgr.load("_test_plugin_no_register")
            assert "_test_plugin_no_register" not in mgr.loaded_plugins
        finally:
            del sys.modules["_test_plugin_no_register"]

    def test_load_nonexistent_module(self):
        mgr = PluginManager()
        # Should log error but not raise
        mgr.load("nonexistent_module_12345")
        assert mgr.loaded_plugins == []

    def test_load_module_register_raises(self):
        mod = types.ModuleType("_test_plugin_bad_register")

        def register(registry):
            raise RuntimeError("init boom")

        mod.register = register
        import sys
        sys.modules["_test_plugin_bad_register"] = mod
        try:
            mgr = PluginManager()
            mgr.load("_test_plugin_bad_register")
            assert "_test_plugin_bad_register" not in mgr.loaded_plugins
        finally:
            del sys.modules["_test_plugin_bad_register"]

    def test_init_with_modules(self):
        mod = types.ModuleType("_test_plugin_init")
        calls = []

        def register(registry):
            registry.on("PRE_NODE_CREATE", lambda ctx: calls.append("init"))

        mod.register = register
        import sys
        sys.modules["_test_plugin_init"] = mod
        try:
            mgr = PluginManager(modules=["_test_plugin_init"])
            assert "_test_plugin_init" in mgr.loaded_plugins
            assert mgr.subscriber_count("PRE_NODE_CREATE") == 1
        finally:
            del sys.modules["_test_plugin_init"]

    def test_subscriber_count(self):
        mgr = PluginManager()
        assert mgr.subscriber_count("PRE_EDGE_CREATE") == 0
        mgr.registry.on("PRE_EDGE_CREATE", lambda ctx: None)
        assert mgr.subscriber_count("PRE_EDGE_CREATE") == 1


# ---------------------------------------------------------------------------
# Example plugins
# ---------------------------------------------------------------------------

class TestExamplePlugins:
    def test_example_logger_loads(self):
        mgr = PluginManager()
        mgr.load("cortex.plugins.example_logger")
        assert "cortex.plugins.example_logger" in mgr.loaded_plugins
        # Should have subscribers on mutation hooks
        assert mgr.subscriber_count("POST_NODE_CREATE") >= 1
        assert mgr.subscriber_count("POST_EDGE_DELETE") >= 1

    def test_example_validator_loads(self):
        mgr = PluginManager()
        mgr.load("cortex.plugins.example_validator")
        assert "cortex.plugins.example_validator" in mgr.loaded_plugins
        assert mgr.subscriber_count("PRE_NODE_CREATE") >= 1

    def test_example_logger_fires(self):
        mgr = PluginManager(modules=["cortex.plugins.example_logger"])
        # Should not raise
        mgr.fire("POST_NODE_CREATE", {"hook": "POST_NODE_CREATE", "node_id": "n1"})
        mgr.fire("POST_NODE_DELETE", {"hook": "POST_NODE_DELETE", "node_id": "n2"})

    def test_example_validator_fires(self):
        mgr = PluginManager(modules=["cortex.plugins.example_validator"])
        # Short label — no warning
        mgr.fire("PRE_NODE_CREATE", {"label": "Hello"})
        # Long label — should log warning but not raise
        mgr.fire("PRE_NODE_CREATE", {"label": "x" * 300})


# ---------------------------------------------------------------------------
# HOOKS constant
# ---------------------------------------------------------------------------

class TestHooksConstant:
    def test_all_hooks_present(self):
        expected = {
            "PRE_NODE_CREATE", "POST_NODE_CREATE",
            "PRE_NODE_UPDATE", "POST_NODE_UPDATE",
            "PRE_NODE_DELETE", "POST_NODE_DELETE",
            "PRE_EDGE_CREATE", "POST_EDGE_CREATE",
            "PRE_EDGE_DELETE", "POST_EDGE_DELETE",
            "PRE_SEARCH", "POST_SEARCH",
        }
        assert HOOKS == expected

    def test_hooks_is_frozenset(self):
        assert isinstance(HOOKS, frozenset)
