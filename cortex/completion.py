"""
Shell completion scripts for the Cortex CLI.

Generates completion scripts for bash, zsh, and fish by introspecting
the argparse parser. Activate via:

    eval "$(cortex completion --shell bash)"
    eval "$(cortex completion --shell zsh)"
    cortex completion --shell fish | source
"""

from __future__ import annotations

import argparse


def _get_subcommands(parser: argparse.ArgumentParser) -> list[str]:
    """Extract subcommand names from an argparse parser."""
    for action in parser._subparsers._actions:
        if isinstance(action, argparse._SubParsersAction):
            return sorted(action.choices.keys())
    return []


def _get_flags(parser: argparse.ArgumentParser, subcommand: str | None = None) -> list[str]:
    """Extract option flags for a given parser or subcommand."""
    target = parser
    if subcommand:
        for action in parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                if subcommand in action.choices:
                    target = action.choices[subcommand]
                    break

    flags: list[str] = []
    for action in target._actions:
        for opt in action.option_strings:
            flags.append(opt)
    return sorted(flags)


def generate_bash(parser: argparse.ArgumentParser) -> str:
    """Generate bash completion script."""
    subcommands = _get_subcommands(parser)
    subs_str = " ".join(subcommands)

    # Build per-subcommand flag maps
    flag_cases: list[str] = []
    for sub in subcommands:
        flags = _get_flags(parser, sub)
        flags_str = " ".join(flags)
        flag_cases.append(f"        {sub})\n            opts=\"{flags_str}\"\n            ;;")

    flag_cases_str = "\n".join(flag_cases)

    return f'''_cortex_completion() {{
    local cur prev subcmd opts
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"

    # Find the subcommand
    subcmd=""
    for ((i=1; i < COMP_CWORD; i++)); do
        case "${{COMP_WORDS[i]}}" in
            -*) ;;
            *)
                subcmd="${{COMP_WORDS[i]}}"
                break
                ;;
        esac
    done

    if [[ -z "$subcmd" ]]; then
        opts="{subs_str}"
        COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
        return 0
    fi

    case "$subcmd" in
{flag_cases_str}
        *)
            opts=""
            ;;
    esac

    COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
    return 0
}}

complete -F _cortex_completion cortex
'''


def generate_zsh(parser: argparse.ArgumentParser) -> str:
    """Generate zsh completion script."""
    subcommands = _get_subcommands(parser)
    subs_str = " ".join(subcommands)

    # Build per-subcommand flag completions
    sub_cases: list[str] = []
    for sub in subcommands:
        flags = _get_flags(parser, sub)
        flags_str = " ".join(flags)
        sub_cases.append(f"        {sub})\n            _arguments '*:flags:({flags_str})'\n            ;;")

    sub_cases_str = "\n".join(sub_cases)

    return f'''#compdef cortex

_cortex() {{
    local -a subcmds
    subcmds=({subs_str})

    if (( CURRENT == 2 )); then
        _describe 'subcommand' subcmds
        return
    fi

    local subcmd=${{words[2]}}
    case "$subcmd" in
{sub_cases_str}
    esac
}}

_cortex "$@"
'''


def generate_fish(parser: argparse.ArgumentParser) -> str:
    """Generate fish completion script."""
    subcommands = _get_subcommands(parser)

    lines: list[str] = []
    lines.append("# Fish completions for cortex")
    lines.append("")

    # Subcommand completions
    for sub in subcommands:
        lines.append(
            f"complete -c cortex -n '__fish_use_subcommand' "
            f"-a '{sub}' -d '{sub} subcommand'"
        )

    lines.append("")

    # Per-subcommand flag completions
    for sub in subcommands:
        flags = _get_flags(parser, sub)
        for flag in flags:
            if flag.startswith("--"):
                short_flag = flag.lstrip("-")
                lines.append(
                    f"complete -c cortex -n '__fish_seen_subcommand_from {sub}' "
                    f"-l '{short_flag}'"
                )
            elif flag.startswith("-") and len(flag) == 2:
                lines.append(
                    f"complete -c cortex -n '__fish_seen_subcommand_from {sub}' "
                    f"-s '{flag[1]}'"
                )

    lines.append("")
    return "\n".join(lines)


GENERATORS = {
    "bash": generate_bash,
    "zsh": generate_zsh,
    "fish": generate_fish,
}


def generate_completion(parser: argparse.ArgumentParser, shell: str) -> str:
    """Generate a completion script for the given shell.

    Args:
        parser: The argparse ArgumentParser to introspect.
        shell: One of 'bash', 'zsh', 'fish'.

    Returns:
        The completion script as a string.

    Raises:
        ValueError: If the shell is not supported.
    """
    gen = GENERATORS.get(shell)
    if gen is None:
        raise ValueError(f"Unsupported shell: {shell}. Choose from: {', '.join(GENERATORS)}")
    return gen(parser)
