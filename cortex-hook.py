#!/usr/bin/env python3
"""
Thin stub — delegates to cortex._hook.main().

Preserves ``python cortex-hook.py`` for cloned-repo users who haven't pip-installed.
"""
import sys
from pathlib import Path

# For cloned-repo usage without pip install: ensure project root is importable
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cortex._hook import main

if __name__ == "__main__":
    main()
