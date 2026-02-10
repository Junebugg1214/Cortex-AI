#!/usr/bin/env python3
"""
Thin stub — delegates to cortex.cli.main().

Preserves ``python migrate.py`` for cloned-repo users who haven't pip-installed.
"""
import sys
from pathlib import Path

# For cloned-repo usage without pip install: ensure project root is importable
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cortex.cli import main

if __name__ == "__main__":
    sys.exit(main())
