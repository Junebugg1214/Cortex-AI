"""Entry point for the ``cortex-hook`` console script.

Reads JSON from stdin, loads Cortex hook config, and prints the result
for Claude Code SessionStart injection.
"""

import json
import logging
import os
import sys

from cortex.hooks import handle_session_start, load_hook_config


def _configure_logging() -> None:
    level_name = os.environ.get("CORTEX_HOOK_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)
    logging.basicConfig(level=level, format="cortex-hook: %(levelname)s: %(message)s", stream=sys.stderr)


def main():
    _configure_logging()
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        input_data = {}

    config = load_hook_config()
    result = handle_session_start(input_data, config)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
