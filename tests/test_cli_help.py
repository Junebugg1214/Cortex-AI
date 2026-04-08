from __future__ import annotations

import re

from cortex.cli import ADVANCED_HELP_NOTE, CORE_PORTABILITY_COMMANDS, build_parser, main


def _listed_commands(help_text: str) -> set[str]:
    commands: set[str] = set()
    for line in help_text.splitlines():
        match = re.match(r"^\s{4,}([a-z][a-z0-9-]*)\s{2,}", line)
        if match:
            commands.add(match.group(1))
    return commands


def test_default_help_is_portability_first():
    help_text = build_parser().format_help()
    commands = _listed_commands(help_text)

    assert set(CORE_PORTABILITY_COMMANDS).issubset(commands)
    assert {"merge", "governance", "remote", "backup", "server", "ui", "memory", "mind"}.isdisjoint(commands)
    assert ADVANCED_HELP_NOTE in help_text


def test_help_all_shows_full_command_list(capsys):
    rc = main(["--help-all"])
    out = capsys.readouterr().out
    commands = _listed_commands(out)

    assert rc == 0
    assert set(CORE_PORTABILITY_COMMANDS).issubset(commands)
    assert {"merge", "governance", "remote", "backup", "server", "ui", "memory", "doctor", "mind", "pack"}.issubset(
        commands
    )
    assert ADVANCED_HELP_NOTE not in out
