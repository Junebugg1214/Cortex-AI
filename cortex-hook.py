#!/usr/bin/env python3
"""
Cortex SessionStart hook for Claude Code.

This script is called by Claude Code on session start. It reads JSON from
stdin, loads your Cortex identity graph, and returns compact context for
injection as a system message.

Install via: python migrate.py context-hook install <graph.json>
"""

import json
import sys
from pathlib import Path

# Ensure cortex package is importable
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "skills" / "chatbot-memory-extractor" / "scripts"))

from cortex.hooks import load_hook_config, handle_session_start


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        input_data = {}

    config = load_hook_config()
    result = handle_session_start(input_data, config)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
