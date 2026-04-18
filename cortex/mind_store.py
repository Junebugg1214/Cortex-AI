from __future__ import annotations

import sys as _sys
import warnings as _warnings
from importlib import import_module as _import_module

_warnings.warn(
    'cortex.mind_store is deprecated; use cortex.graph.mind_store instead.',
    DeprecationWarning,
    stacklevel=2,
)
from cortex.graph.mind_store import *  # pragma: deprecation  # noqa: F401,F403,E402

_module = _import_module('cortex.graph.mind_store')
globals().update({
    _name: _value
    for _name, _value in vars(_module).items()
    if _name not in {'__name__', '__package__', '__loader__', '__spec__'}
})
__all__ = getattr(_module, '__all__', [
    _name for _name in vars(_module) if not _name.startswith('_')
])
_sys.modules[__name__] = _module

if __name__ == '__main__' and hasattr(_module, 'main'):
    raise SystemExit(_module.main())

del _import_module, _module, _sys, _warnings
