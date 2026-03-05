"""Compatibility shim for optional psycopg dependency.

If real ``psycopg`` is installed, this file delegates to it to avoid shadowing.
If not installed, it provides a minimal ``connect`` symbol so tests can patch it.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()
_THIS_DIR = _THIS_FILE.parent


def _load_real_psycopg():
    """Load site-installed psycopg module if available outside this repo."""
    search_paths: list[str] = []
    for entry in sys.path:
        try:
            p = Path(entry or ".").resolve()
        except Exception:
            continue
        if p == _THIS_DIR:
            continue
        search_paths.append(str(p))

    for path in search_paths:
        spec = importlib.machinery.PathFinder.find_spec("psycopg", [path])
        if spec is None or spec.origin is None:
            continue
        try:
            origin = Path(spec.origin).resolve()
        except Exception:
            continue
        if origin == _THIS_FILE:
            continue
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        # Real psycopg imports submodules via `import psycopg...`; temporarily
        # bind the real module under that name so imports do not recurse here.
        previous = sys.modules.get("psycopg")
        try:
            sys.modules["psycopg"] = module
            spec.loader.exec_module(module)
            return module
        except Exception:
            if previous is None:
                sys.modules.pop("psycopg", None)
            else:
                sys.modules["psycopg"] = previous
            continue
    return None


_real = _load_real_psycopg()

if _real is not None:
    for _name in dir(_real):
        if not _name.startswith("__"):
            globals()[_name] = getattr(_real, _name)
    __all__ = [n for n in dir(_real) if not n.startswith("__")]
else:

    def connect(*args, **kwargs):
        raise RuntimeError("psycopg is not installed in this environment")

    __all__ = ["connect"]
