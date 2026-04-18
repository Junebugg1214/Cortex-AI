#!/usr/bin/env python3
"""CLI entrypoint and top-level dispatch for Cortex."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable, Mapping

KNOWN_SUBCOMMANDS = (
    "init",
    "connect",
    "serve",
    "compose",
    "source",
    "extract",
    "admin",
    "debug",
    "diff",
    "checkout",
    "rollback",
    "commit",
    "branch",
    "merge",
    "log",
    "governance",
    "remote",
    "sync",
    "verify",
    "scan",
    "remember",
    "status",
    "mount",
    "help",
    "mind",
    "sources",
    "audience",
    "pack",
    "pull",
    "-h",
    "--help",
    "--help-all",
)


@dataclass(frozen=True)
class EntryPointCliContext:
    """Callbacks supplied by the public CLI facade."""

    build_parser: Callable[..., Any]
    error: Callable[..., int]
    extract_global_flags: Callable[[list[str]], tuple[list[str], bool, bool]]
    set_cli_quiet: Callable[[bool], None]
    handlers: Mapping[str, Callable[[Any], int]]
    route_argv: Callable[[list[str]], tuple[list[str], bool]] | None = None
    format_help_tree: Callable[[Any], str] | None = None


def _route_default_subcommand(argv: list[str]) -> tuple[list[str], bool]:
    return argv, False


def _apply_json_mode(args: Any, *, force_json: bool, ctx: EntryPointCliContext) -> int | None:
    if not force_json:
        return None
    if hasattr(args, "format"):
        args.format = "json"
        return None
    if args.subcommand not in {"extract"}:
        return ctx.error(
            f"`--json` is not supported for '{args.subcommand}'.",
            hint="Use the command's documented output flag or `cortex --help`.",
        )
    return None


def main(argv=None, *, ctx: EntryPointCliContext) -> int:
    if argv is None:
        argv = sys.argv[1:]
    else:
        argv = list(argv)

    argv, force_json, quiet = ctx.extract_global_flags(argv)
    ctx.set_cli_quiet(quiet or force_json)
    route_argv = ctx.route_argv or _route_default_subcommand
    argv, cli_v2_routed = route_argv(argv)

    parser = ctx.build_parser()
    args = parser.parse_args(argv)
    setattr(args, "json_output", force_json)
    setattr(args, "quiet", quiet)
    setattr(args, "_cli_v2_routed", cli_v2_routed)

    if getattr(args, "help_all", False):
        if ctx.format_help_tree is not None:
            print(ctx.format_help_tree(parser), end="")
        else:
            parser.show_all_commands = True
            print(parser.format_help(), end="")
        return 0

    if args.subcommand is None:
        parser.print_help()
        return 1

    json_error = _apply_json_mode(args, force_json=force_json, ctx=ctx)
    if json_error is not None:
        return json_error

    handler = ctx.handlers.get(args.subcommand)
    if handler is not None:
        return handler(args)
    return ctx.handlers["migrate"](args)
