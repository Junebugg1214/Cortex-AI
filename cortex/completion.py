"""Shell completion helpers for the Cortex CLI.

The completion scripts are generated from argparse metadata, then extended with
small runtime hooks so users can tab-complete dynamic values such as Mind IDs,
audience IDs, and source IDs.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def _get_subcommands(parser: argparse.ArgumentParser) -> list[str]:
    """Return the top-level subcommand names for a parser."""
    for action in getattr(parser, "_actions", []):
        if isinstance(action, argparse._SubParsersAction):
            return sorted(action.choices.keys())
    return []


def _get_flags(parser: argparse.ArgumentParser, subcommand: str | None = None) -> list[str]:
    """Return option flags for the parser or one of its subcommands."""
    target = parser
    if subcommand:
        for action in getattr(parser, "_actions", []):
            if isinstance(action, argparse._SubParsersAction) and subcommand in action.choices:
                target = action.choices[subcommand]
                break

    flags: list[str] = []
    for action in getattr(target, "_actions", []):
        flags.extend(action.option_strings)
    return sorted(dict.fromkeys(flags))


def _dedupe(values: list[str]) -> list[str]:
    """Return a stable list of unique, non-empty values."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def completion_candidates(kind: str, *, store_dir: str | Path, mind: str = "") -> list[str]:
    """Return newline-safe dynamic completion candidates.

    Args:
        kind: Candidate family to list. Supported values are ``mind``,
            ``audience``, and ``source``.
        store_dir: Cortex store directory to inspect.
        mind: Optional Mind id used to scope audience and source candidates.
    """
    store_path = Path(store_dir)

    if kind == "mind":
        from cortex.minds import list_minds

        payload = list_minds(store_path)
        return _dedupe([item.get("mind", "") for item in payload.get("minds", [])])

    if kind == "audience":
        from cortex.audience.policy import PolicyEngine
        from cortex.minds import list_minds

        engine = PolicyEngine(store_path)
        mind_ids = [mind] if mind else [item.get("mind", "") for item in list_minds(store_path).get("minds", [])]
        values: list[str] = []
        for mind_id in mind_ids:
            if not mind_id:
                continue
            try:
                payload = engine.list_policies(mind_id)
            except Exception:
                continue
            values.extend(item.get("audience_id", "") for item in payload.get("policies", []))
        return _dedupe(values)

    if kind == "source":
        from cortex.minds import list_minds, load_mind_core_graph
        from cortex.sources import SourceRegistry, graph_source_ids

        registry = SourceRegistry.for_store(store_path)
        mind_ids = [mind] if mind else [item.get("mind", "") for item in list_minds(store_path).get("minds", [])]
        values: list[str] = []
        for mind_id in mind_ids:
            if not mind_id:
                continue
            try:
                mind_payload = load_mind_core_graph(store_path, mind_id)
            except Exception:
                continue
            graph = mind_payload.get("graph")
            if graph is None:
                continue
            records = registry.list_records(stable_ids=graph_source_ids(graph))
            if not records:
                records = registry.list_records()
            values.extend(record.get("stable_id", "") for record in records)
        return _dedupe(values)

    raise ValueError(f"Unsupported completion candidate kind: {kind}")


def _script_command(shell: str, *, kind: str, mind: str = "") -> str:
    """Return the command used by generated shell hooks to fetch candidates."""
    command = [
        "cortex",
        "completion",
        "--shell",
        shell,
        "--candidates",
        kind,
        "--store-dir",
        "${CORTEX_STORE_DIR:-.cortex}",
    ]
    if mind:
        command.extend(["--mind", mind])
    return " ".join(command)


def generate_bash(parser: argparse.ArgumentParser) -> str:
    """Generate a bash completion script with dynamic candidate hooks."""
    subcommands = _get_subcommands(parser)
    subs_str = " ".join(subcommands)

    flag_cases: list[str] = []
    for sub in subcommands:
        flags = " ".join(_get_flags(parser, sub))
        flag_cases.append(f'        {sub})\n            opts="{flags}"\n            ;;')

    flag_cases_str = "\n".join(flag_cases)
    mind_command = _script_command("bash", kind="mind")
    audience_command = _script_command("bash", kind="audience")
    source_command = _script_command("bash", kind="source")

    return f'''__cortex_completion() {{
    local cur prev subcmd opts mind
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"

    mind=""
    for ((i=1; i < COMP_CWORD; i++)); do
        if [[ "${{COMP_WORDS[i]}}" == "--mind" && $((i + 1)) -lt $COMP_CWORD ]]; then
            mind="${{COMP_WORDS[i+1]}}"
            break
        fi
    done

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

    case "$prev" in
        --mind)
            COMPREPLY=( $(compgen -W "$({mind_command})" -- "$cur") )
            return 0
            ;;
        --audience|--audience-id)
            COMPREPLY=( $(compgen -W "$({audience_command} --mind \"$mind\")" -- "$cur") )
            return 0
            ;;
        --source|--source-identifier)
            COMPREPLY=( $(compgen -W "$({source_command} --mind \"$mind\")" -- "$cur") )
            return 0
            ;;
        retract)
            if [[ "$subcmd" == "sources" ]]; then
                COMPREPLY=( $(compgen -W "$({source_command} --mind \"$mind\")" -- "$cur") )
                return 0
            fi
            ;;
    esac

    case "$subcmd" in
{flag_cases_str}
        *)
            opts=""
            ;;
    esac

    COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
    return 0
}}

_cortex_completion() {{
    __cortex_completion "$@"
}}

complete -F _cortex_completion cortex
'''


def generate_zsh(parser: argparse.ArgumentParser) -> str:
    """Generate a zsh completion script with dynamic candidate hooks."""
    subcommands = _get_subcommands(parser)
    subs_str = " ".join(subcommands)
    mind_command = _script_command("zsh", kind="mind")
    audience_command = _script_command("zsh", kind="audience")
    source_command = _script_command("zsh", kind="source")

    sub_cases: list[str] = []
    for sub in subcommands:
        flags = " ".join(_get_flags(parser, sub))
        sub_cases.append(f"        {sub})\n            _arguments '*:flags:({flags})'\n            ;;")
    sub_cases_str = "\n".join(sub_cases)

    return f"""#compdef cortex

_cortex() {{
    local -a subcmds
    subcmds=({subs_str})

    if (( CURRENT == 2 )); then
        _describe 'subcommand' subcmds
        return
    fi

    local subcmd=${{words[2]}}
    local prev=${{words[CURRENT-1]}}
    local mind=""
    local i
    for (( i = 1; i < CURRENT; ++i )); do
        if [[ ${{words[i]}} == --mind && $((i + 1)) -lt CURRENT ]]; then
            mind=${{words[i+1]}}
            break
        fi
    done

    case "$prev" in
        --mind)
            _describe 'mind ids' "$({mind_command})"
            return
            ;;
        --audience|--audience-id)
            _describe 'audience ids' "$({audience_command} --mind \"$mind\")"
            return
            ;;
        --source|--source-identifier|retract)
            _describe 'source ids' "$({source_command} --mind \"$mind\")"
            return
            ;;
    esac

    case "$subcmd" in
{sub_cases_str}
    esac
}}

_cortex "$@"
"""


def generate_fish(parser: argparse.ArgumentParser) -> str:
    """Generate a fish completion script with dynamic candidate hooks."""
    subcommands = _get_subcommands(parser)
    mind_command = _script_command("fish", kind="mind")
    audience_command = _script_command("fish", kind="audience")
    source_command = _script_command("fish", kind="source")

    lines: list[str] = ["# Fish completions for cortex", ""]
    for sub in subcommands:
        lines.append(f"complete -c cortex -n '__fish_use_subcommand' -a '{sub}' -d '{sub} subcommand'")

    lines.extend(
        [
            "",
            "function __cortex_minds --description 'List Cortex Mind ids'",
            f"    {mind_command}",
            "end",
            "",
            "function __cortex_audiences --description 'List Cortex audience ids'",
            f"    {audience_command}",
            "end",
            "",
            "function __cortex_sources --description 'List Cortex source ids'",
            f"    {source_command}",
            "end",
            "",
        ]
    )

    for sub in subcommands:
        flags = _get_flags(parser, sub)
        for flag in flags:
            if flag.startswith("--"):
                short_flag = flag.lstrip("-")
                lines.append(f"complete -c cortex -n '__fish_seen_subcommand_from {sub}' -l '{short_flag}'")
            elif flag.startswith("-") and len(flag) == 2:
                lines.append(f"complete -c cortex -n '__fish_seen_subcommand_from {sub}' -s '{flag[1]}'")

    lines.extend(
        [
            "complete -c cortex -n '__fish_seen_subcommand_from completion; and test (commandline -ct) = \"\"' -a 'mind audience source'",
            "complete -c cortex -n '__fish_seen_subcommand_from sources; and test (commandline -ct) = \"\"' -a '(__cortex_sources)'",
            "complete -c cortex -n '__fish_seen_subcommand_from audience; and test (commandline -ct) = \"\"' -a '(__cortex_audiences)'",
            "complete -c cortex -n '__fish_seen_subcommand_from mind; and test (commandline -ct) = \"\"' -a '(__cortex_minds)'",
            "",
        ]
    )
    return "\n".join(lines)


GENERATORS = {
    "bash": generate_bash,
    "zsh": generate_zsh,
    "fish": generate_fish,
}


def generate_completion(parser: argparse.ArgumentParser, shell: str) -> str:
    """Generate a completion script for the requested shell."""
    gen = GENERATORS.get(shell)
    if gen is None:
        raise ValueError(f"Unsupported shell: {shell}. Choose from: {', '.join(GENERATORS)}")
    return gen(parser)


__all__ = [
    "GENERATORS",
    "_get_flags",
    "_get_subcommands",
    "completion_candidates",
    "generate_bash",
    "generate_completion",
    "generate_fish",
    "generate_zsh",
]
