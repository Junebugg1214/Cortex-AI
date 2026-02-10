"""Entry point for the ``cortex-hook`` console script.

Reads JSON from stdin, loads Cortex hook config, and prints the result
for Claude Code SessionStart injection.
"""

import json
import sys

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
