from __future__ import annotations

import pytest

from cortex.cli import CLI_V2_ROUTES, _route_cli_v2_argv, build_parser
from cortex.cli_parser import CLI_V2_INTERNAL_COMMANDS

REMOVED_FLAT_COMMANDS = {
    "extract",
    "ingest",
    "import",
    "memory",
    "migrate",
    "query",
    "stats",
    "timeline",
    "contradictions",
    "drift",
    "blame",
    "history",
    "claim",
    "identity",
    "switch",
    "review",
    "gaps",
    "digest",
    "viz",
    "watch",
    "sync-schedule",
    "extract-coding",
    "context-hook",
    "context-export",
    "context-write",
    "portable",
    "build",
    "audit",
    "doctor",
    "integrity",
    "ui",
    "benchmark",
    "server",
    "mcp",
    "backup",
    "agent",
    "openapi",
    "release-notes",
    "rotate",
    "completion",
}


def _top_level_choices(parser):
    return parser._subparsers._group_actions[0].choices


def test_removed_flat_commands_are_not_public_choices():
    choices = _top_level_choices(build_parser(show_all_commands=True))

    assert not (REMOVED_FLAT_COMMANDS - {"extract"}).intersection(choices)
    assert {"connect", "rollback", "scan"} <= set(choices)
    assert {"init", "remember", "mount", "sync", "compose", "status"} <= set(choices)
    assert {"source", "extract", "admin", "debug"} <= set(choices)


@pytest.mark.parametrize("route", sorted(CLI_V2_ROUTES))
def test_namespaced_routes_reach_an_existing_parser(route):
    parser = build_parser(show_all_commands=True)
    routed, was_routed = _route_cli_v2_argv([*route, "--help"])

    assert was_routed
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(routed)
    assert exc.value.code == 0


def test_internal_targets_are_hidden_from_public_help():
    parser = build_parser(show_all_commands=True)
    choices = _top_level_choices(parser)
    help_text = parser.format_help()

    for internal, _display in CLI_V2_INTERNAL_COMMANDS.values():
        assert internal in choices
        assert internal.startswith("__cli_v2_")
        assert internal not in help_text


@pytest.mark.parametrize(
    "argv",
    [
        ["ingest", "docs", "notes.md"],
        ["doctor", "--help"],
        ["server", "--help"],
        ["query", "context.json"],
        ["context-export", "context.json"],
    ],
)
def test_removed_old_invocation_shapes_fail(argv):
    parser = build_parser(show_all_commands=True)
    routed, was_routed = _route_cli_v2_argv(argv)

    assert routed == argv
    assert not was_routed
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(argv)
    assert exc.value.code == 2
