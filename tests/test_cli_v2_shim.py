from __future__ import annotations

import argparse
import warnings
from types import SimpleNamespace

import pytest

from cortex.cli import (
    CLI_V2_DEPRECATED_COMMANDS,
    CLI_V2_ROUTES,
    CLI_V2_TIER2_NAMESPACES,
    _deprecated_cli_v2_handler,
    _route_cli_v2_argv,
)
from cortex.cli_parser import build_parser, register_namespace


def _subparser_choices(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    return action.choices


def test_register_namespace_builds_nested_subcommands():
    parser = argparse.ArgumentParser(prog="cortex-test")
    subparsers = parser.add_subparsers(dest="subcommand")

    register_namespace(
        subparsers,
        "admin",
        {
            "doctor": lambda child: child.add_argument("--check", action="store_true"),
        },
    )

    args = parser.parse_args(["admin", "doctor", "--check"])
    assert args.subcommand == "admin"
    assert args.admin_subcommand == "doctor"
    assert args.check is True


def test_tier2_namespaces_are_registered_on_real_parser():
    choices = _subparser_choices(build_parser())

    assert set(CLI_V2_TIER2_NAMESPACES) <= set(choices)


def test_every_deprecated_old_command_preserves_exit_code_and_warns_once():
    for command, replacement in CLI_V2_DEPRECATED_COMMANDS.items():
        calls: list[str] = []

        def handler(_args, *, command=command):
            calls.append(command)
            return 23

        shim = _deprecated_cli_v2_handler(command, replacement, handler)
        with pytest.warns(DeprecationWarning) as captured:
            exit_code = shim(SimpleNamespace(_cli_v2_routed=False))

        assert exit_code == 23
        assert calls == [command]
        assert len(captured) == 1
        assert str(captured[0].message) == f"'cortex {command}' is deprecated; use 'cortex {replacement}'"


def test_routed_new_namespace_invocation_does_not_emit_deprecation_warning():
    shim = _deprecated_cli_v2_handler("doctor", "admin doctor", lambda _args: 7)

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        exit_code = shim(SimpleNamespace(_cli_v2_routed=True))

    assert exit_code == 7
    assert [item for item in captured if issubclass(item.category, DeprecationWarning)] == []


def test_every_new_namespaced_route_reaches_existing_parser_help():
    parser = build_parser()

    for route, replacement in CLI_V2_ROUTES.items():
        routed, is_routed = _route_cli_v2_argv([*route, "--help"])

        assert is_routed is True
        assert routed == [*replacement, "--help"]
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(routed)
        assert exc.value.code == 0
