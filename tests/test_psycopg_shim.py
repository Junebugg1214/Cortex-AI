"""Tests for local psycopg compatibility shim behavior."""

import importlib

def test_psycopg_shim_has_connect_symbol():
    mod = importlib.import_module("psycopg")
    assert hasattr(mod, "connect")


def test_psycopg_shim_connect_raises_when_real_module_unavailable():
    # If the real psycopg package exists in environment, shim delegates to it,
    # so this test is only meaningful in our minimal dependency environment.
    mod = importlib.import_module("psycopg")
    if getattr(mod, "__file__", "").endswith("site-packages/psycopg/__init__.py"):
        return

    try:
        mod.connect("dbname=test")
        assert False, "Expected RuntimeError in stub mode"
    except RuntimeError as exc:
        assert "not installed" in str(exc)
