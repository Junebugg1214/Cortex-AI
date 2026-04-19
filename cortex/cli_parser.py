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

CLI_V2_INTERNAL_COMMANDS: dict[str, tuple[str, str]] = {
    "extract": ("__cli_v2_extract", "extract run"),
    "extract-eval": ("__cli_v2_extract_eval", "extract eval"),
    "extract-refresh-cache": ("__cli_v2_extract_refresh_cache", "extract refresh-cache"),
    "extract-review": ("__cli_v2_extract_review", "extract review"),
    "ingest": ("__cli_v2_ingest", "source ingest"),
    "import": ("__cli_v2_import", "sync --to <target>"),
    "memory": ("__cli_v2_memory", "remember/source/debug"),
    "migrate": ("__cli_v2_migrate", "admin migrate"),
    "query": ("__cli_v2_query", "debug query"),
    "extractions-tail": ("__cli_v2_extractions_tail", "debug extractions tail"),
    "stats": ("__cli_v2_stats", "debug stats"),
    "timeline": ("__cli_v2_timeline", "debug timeline"),
    "contradictions": ("__cli_v2_contradictions", "debug contradictions"),
    "drift": ("__cli_v2_drift", "debug drift"),
    "blame": ("__cli_v2_blame", "debug blame"),
    "history": ("__cli_v2_history", "debug history"),
    "claim": ("__cli_v2_claim", "debug claims"),
    "identity": ("__cli_v2_identity", "admin identity"),
    "switch": ("__cli_v2_switch", "branch switch"),
    "review": ("__cli_v2_review", "debug review"),
    "gaps": ("__cli_v2_gaps", "debug gaps"),
    "digest": ("__cli_v2_digest", "debug digest"),
    "viz": ("__cli_v2_viz", "debug viz"),
    "watch": ("__cli_v2_watch", "debug watch"),
    "sync-schedule": ("__cli_v2_sync_schedule", "debug watch --sync"),
    "extract-coding": ("__cli_v2_extract_coding", "extract coding"),
    "context-hook": ("__cli_v2_context_hook", "mount hook"),
    "context-export": ("__cli_v2_context_export", "compose"),
    "context-write": ("__cli_v2_context_write", "mount"),
    "portable": ("__cli_v2_portable", "sync/mount/compose"),
    "build": ("__cli_v2_build", "pack compile"),
    "audit": ("__cli_v2_audit", "admin integrity"),
    "doctor": ("__cli_v2_doctor", "admin doctor"),
    "integrity": ("__cli_v2_integrity", "admin integrity"),
    "ui": ("__cli_v2_ui", "serve ui"),
    "benchmark": ("__cli_v2_benchmark", "admin benchmark"),
    "server": ("__cli_v2_server", "serve api"),
    "mcp": ("__cli_v2_mcp", "serve mcp"),
    "backup": ("__cli_v2_backup", "admin backup"),
    "agent": ("__cli_v2_agent", "admin agent"),
    "openapi": ("__cli_v2_openapi", "admin openapi"),
    "release-notes": ("__cli_v2_release_notes", "admin release-notes"),
    "rotate": ("__cli_v2_rotate", "admin rotate"),
    "completion": ("__cli_v2_completion", "admin completion"),
}

PUBLIC_SUBCOMMANDS_METAVAR = (
    "{init,remember,mount,sync,compose,status,commit,branch,merge,log,diff,verify,"
    "mind,pack,source,audience,remote,governance,extract,serve,admin,debug,"
    "connect,rollback,scan,checkout,sources,pull,help}"
)


class _CliV2SubparserAdapter:
    """Hide retired flat commands while preserving internal parser targets."""

    def __init__(self, sub):
        self._sub = sub

    def __getattr__(self, name: str):
        return getattr(self._sub, name)

    def add_parser(self, name: str, *args, **kwargs):
        internal = CLI_V2_INTERNAL_COMMANDS.get(name)
        if internal is None:
            return self._sub.add_parser(name, *args, **kwargs)
        internal_name, display_name = internal
        hidden_kwargs = dict(kwargs)
        hidden_kwargs["help"] = argparse.SUPPRESS
        hidden_kwargs.setdefault("prog", f"cortex {display_name}")
        parser = self._sub.add_parser(internal_name, *args, **hidden_kwargs)
        self._sub._choices_actions = [
            action for action in self._sub._choices_actions if getattr(action, "dest", "") != internal_name
        ]
        parser.set_defaults(_cli_v2_internal_from=name)
        return parser


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


def _configure_debug_extractions(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="debug_extractions_subcommand")
    tail = sub.add_parser("tail", help="Pretty-print recent extraction diagnostics")
    tail.add_argument("--limit", type=int, default=20, help="Number of records to show (default: 20)")


def _register_cli_v2_namespaces(sub) -> None:
    if "compose" not in getattr(sub, "choices", {}):
        sub.add_parser("compose", help="Render context without writing a persistent mount target")
    register_namespace(
        sub,
        "extract",
        {
            "run": _no_args,
            "status": _no_args,
            "coding": _no_args,
            "eval": _no_args,
            "refresh-cache": _no_args,
            "review": _no_args,
        },
    )
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
            "extractions": _configure_debug_extractions,
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
    sub = parser.add_subparsers(dest="subcommand", metavar=PUBLIC_SUBCOMMANDS_METAVAR)

    cli_v2_sub = _CliV2SubparserAdapter(sub)
    add_setup_and_runtime_parsers(cli_v2_sub, add_runtime_security_args=_add_runtime_security_args)
    add_extract_pipeline_parsers(cli_v2_sub, platform_formats=PLATFORM_FORMATS, builtin_policies=BUILTIN_POLICIES)
    add_graph_history_parsers(
        cli_v2_sub,
        governance_action_choices=GOVERNANCE_ACTION_CHOICES,
        builtin_policies=BUILTIN_POLICIES,
    )
    add_portable_mind_pack_parsers(
        cli_v2_sub,
        builtin_policies=BUILTIN_POLICIES,
        mind_help_epilog=MIND_HELP_EPILOG,
        pack_help_epilog=PACK_HELP_EPILOG,
    )
    add_runtime_misc_parsers(cli_v2_sub, add_runtime_security_args=_add_runtime_security_args)
    _register_cli_v2_namespaces(sub)

    return parser


__all__ = [
    "ADVANCED_HELP_NOTE",
    "CONNECT_RUNTIME_TARGETS",
    "CLI_V2_INTERNAL_COMMANDS",
    "FIRST_CLASS_COMMANDS",
    "GOVERNANCE_ACTION_CHOICES",
    "PLATFORM_FORMATS",
    "build_parser",
    "register_namespace",
]
