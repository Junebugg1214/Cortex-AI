#!/usr/bin/env python3
"""Argparse assembly for the Cortex CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable

from cortex import cli_runtime as cli_runtime_module
from cortex import cli_surface as cli_surface_module
from cortex.cli_parser_extract import add_extract_pipeline_parsers
from cortex.cli_parser_graph import add_graph_history_parsers
from cortex.cli_parser_portable import add_portable_mind_pack_parsers
from cortex.cli_parser_runtime_misc import add_runtime_misc_parsers
from cortex.upai.disclosure import BUILTIN_POLICIES

ADVANCED_HELP_NOTE = cli_surface_module.ADVANCED_HELP_NOTE
CONNECT_RUNTIME_TARGETS = cli_surface_module.CONNECT_RUNTIME_TARGETS
CortexArgumentParser = cli_surface_module.CortexArgumentParser
FIRST_CLASS_COMMANDS = cli_surface_module.FIRST_CLASS_COMMANDS
MIND_HELP_EPILOG = cli_surface_module.MIND_HELP_EPILOG
PACK_HELP_EPILOG = cli_surface_module.PACK_HELP_EPILOG
add_setup_and_runtime_parsers = cli_surface_module.add_setup_and_runtime_parsers
_add_runtime_security_args = cli_runtime_module._add_runtime_security_args

GOVERNANCE_ACTION_CHOICES = ("branch", "merge", "pull", "push", "read", "rollback", "write")

PLATFORM_FORMATS = {
    "claude": ["claude-preferences", "claude-memories"],
    "notion": ["notion", "notion-db"],
    "gdocs": ["gdocs"],
    "system-prompt": ["system-prompt"],
    "summary": ["summary"],
    "full": ["full"],
    "all": [
        "claude-preferences",
        "claude-memories",
        "system-prompt",
        "notion",
        "notion-db",
        "gdocs",
        "summary",
        "full",
    ],
}


def register_namespace(parser, name: str, handlers: dict[str, Callable]) -> argparse.ArgumentParser:
    """Register a v2 namespace shell with nested subcommands.

    The callable values may customize each nested parser in-place. Parser
    dispatch still routes through the existing v1 handlers until the command
    implementation is moved in a follow-up PR.
    """
    choices = getattr(parser, "choices", {})
    namespace = choices.get(name)
    if namespace is None:
        namespace = parser.add_parser(name, help=f"CLI v2 namespace for {name} workflows")

    subparser_action = next(
        (action for action in namespace._actions if isinstance(action, argparse._SubParsersAction)),
        None,
    )
    if subparser_action is None:
        subparser_action = namespace.add_subparsers(dest=f"{name}_subcommand")

    for subcommand, configure in handlers.items():
        if subcommand in subparser_action.choices:
            continue
        child = subparser_action.add_parser(subcommand, help=f"CLI v2 `{name} {subcommand}` command")
        configure(child)
    return namespace


def _no_args(_parser: argparse.ArgumentParser) -> None:
    return None


def _register_cli_v2_namespaces(sub) -> None:
    register_namespace(
        sub,
        "source",
        {
            "ingest": _no_args,
            "list": _no_args,
            "retract": _no_args,
            "status": _no_args,
        },
    )
    register_namespace(
        sub,
        "admin",
        {
            "doctor": _no_args,
            "integrity": _no_args,
            "rehash": _no_args,
            "backup": _no_args,
            "restore": _no_args,
            "rotate": _no_args,
            "completion": _no_args,
            "openapi": _no_args,
            "benchmark": _no_args,
            "release-notes": _no_args,
            "migrate": _no_args,
            "identity": _no_args,
            "agent": _no_args,
        },
    )
    register_namespace(
        sub,
        "debug",
        {
            "viz": _no_args,
            "timeline": _no_args,
            "digest": _no_args,
            "gaps": _no_args,
            "watch": _no_args,
            "query": _no_args,
            "blame": _no_args,
            "history": _no_args,
            "claims": _no_args,
            "contradictions": _no_args,
            "drift": _no_args,
            "review": _no_args,
            "stats": _no_args,
        },
    )


def build_parser(*, show_all_commands: bool = False):
    parser = CortexArgumentParser(
        prog="cortex",
        description="Cortex — one portable Mind across AI tools.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        show_all_commands=show_all_commands,
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output when supported")
    parser.add_argument("--quiet", action="store_true", help="Suppress human-readable success output")
    parser.add_argument("--help-all", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="subcommand")

    add_setup_and_runtime_parsers(sub, add_runtime_security_args=_add_runtime_security_args)
    add_extract_pipeline_parsers(sub, platform_formats=PLATFORM_FORMATS, builtin_policies=BUILTIN_POLICIES)
    add_graph_history_parsers(
        sub,
        governance_action_choices=GOVERNANCE_ACTION_CHOICES,
        builtin_policies=BUILTIN_POLICIES,
    )
    add_portable_mind_pack_parsers(
        sub,
        builtin_policies=BUILTIN_POLICIES,
        mind_help_epilog=MIND_HELP_EPILOG,
        pack_help_epilog=PACK_HELP_EPILOG,
    )
    add_runtime_misc_parsers(sub, add_runtime_security_args=_add_runtime_security_args)
    _register_cli_v2_namespaces(sub)

    return parser


__all__ = [
    "ADVANCED_HELP_NOTE",
    "CONNECT_RUNTIME_TARGETS",
    "FIRST_CLASS_COMMANDS",
    "GOVERNANCE_ACTION_CHOICES",
    "PLATFORM_FORMATS",
    "build_parser",
    "register_namespace",
]
