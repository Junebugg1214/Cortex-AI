#!/usr/bin/env python3
"""Argparse assembly for the Cortex CLI."""

from __future__ import annotations

import argparse

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

    return parser


__all__ = [
    "ADVANCED_HELP_NOTE",
    "CONNECT_RUNTIME_TARGETS",
    "FIRST_CLASS_COMMANDS",
    "GOVERNANCE_ACTION_CHOICES",
    "PLATFORM_FORMATS",
    "build_parser",
]
