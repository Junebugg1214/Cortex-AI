#!/usr/bin/env python3
"""
Chatbot Memory Extractor — stub that delegates to cortex.extract_memory.

This file exists for backward compatibility with direct script invocation:
    python skills/chatbot-memory-extractor/scripts/extract_memory.py --help

All logic now lives in cortex/extract_memory.py.
"""
import sys
from pathlib import Path

# For cloned-repo usage without pip install: ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cortex.extract_memory import *  # noqa: F401,F403
from cortex.extract_memory import main  # noqa: F811

if __name__ == "__main__":
    exit(main())
