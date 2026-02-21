#!/usr/bin/env python3
"""
Chatbot Memory Importer — stub that delegates to cortex.import_memory.

This file exists for backward compatibility with direct script invocation:
    python skills/chatbot-memory-importer/scripts/import_memory.py --help

All logic now lives in cortex/import_memory.py.
"""
import sys
from pathlib import Path

# For cloned-repo usage without pip install: ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cortex.import_memory import *  # noqa: E402,F401,F403
from cortex.import_memory import main  # noqa: E402,F811

if __name__ == "__main__":
    exit(main())
