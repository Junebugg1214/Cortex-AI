from __future__ import annotations

import warnings as _warnings
from importlib import import_module as _import_module

_warnings.warn(
    "cortex.extract_memory_loaders is deprecated; use cortex.extraction.extract_memory_loaders instead.",
    DeprecationWarning,
    stacklevel=2,
)
from cortex.extraction.extract_memory_loaders import *  # pragma: deprecation  # noqa: F401,F403,E402

_module = _import_module("cortex.extraction.extract_memory_loaders")
for _name, _value in vars(_module).items():
    if _name not in {"__name__", "__package__", "__loader__", "__spec__"}:
        globals()[_name] = _value
__all__ = getattr(_module, "__all__", [_name for _name in vars(_module) if not _name.startswith("_")])
del _import_module, _module, _name, _warnings
