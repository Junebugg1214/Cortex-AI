from __future__ import annotations

import argparse
import sys

from cortex.versioning.upai.disclosure import BUILTIN_POLICIES

FIRST_CLASS_COMMANDS = ("init", "mind", "pack", "mount", "sync", "serve", "admin")
GUIDED_HELP_NOTE = "Guided help:\n  cortex help init\n  cortex help runtime\n  cortex help legacy\n"
ADVANCED_HELP_NOTE = (
    "Advanced / compatibility:\n"
    "  Run `cortex help` or `cortex --help-all` for the generated command tree, including "
    "namespaces and compatibility aliases."
)
DEFAULT_HELP_START_HERE = (
    "Start Here:\n"
    "  1. cortex init\n"
    "  2. cortex serve ui\n"
    '  3. cortex mind remember self "I prefer concise, implementation-first answers."\n'
    "  4. cortex connect manus\n"
)
DEFAULT_HELP_SURFACE_MAP = (
    "Surface Map:\n"
    "  Core user flows      init, remember, mount, sync, compose\n"
    "  Audience / lineage   source, audience\n"
    "  Runtime / admin      serve, admin doctor, admin integrity\n"
    "  Command tree         namespaces + compatibility aliases via cortex help\n"
)
INIT_HELP_EPILOG = (
    "Bootstrap flow:\n"
    "  cortex init\n"
    "  cortex serve ui\n"
    '  cortex mind remember self "I prefer concise, implementation-first answers."\n'
    "\nAdvanced init flags live under `cortex help init`.\n"
)
MIND_HELP_EPILOG = (
    "Common Mind flow:\n"
    "  cortex mind status self\n"
    '  cortex mind remember self "We are building Cortex as a first-class AI CLI."\n'
    '  cortex mind compose self --to codex --task "product strategy"\n'
    "  cortex mind mount self --to codex\n"
)
PACK_HELP_EPILOG = (
    "Common Brainpack flow:\n"
    "  cortex pack init ai-memory\n"
    "  cortex pack ingest ai-memory docs/\n"
    "  cortex pack compile ai-memory\n"
    "  cortex mind attach-pack self ai-memory\n"
)
CONNECT_HELP_EPILOG = (
    "Connect is runtime wiring only.\n"
    "Use `cortex mind mount` to materialize Cortex state into a target once the connector is ready.\n\n"
    "Common connect flow:\n"
    "  cortex connect manus --check\n"
    "  cortex connect manus --print-config\n"
    "  cortex mind mount self --to codex\n"
)
SERVE_HELP_EPILOG = (
    "Runtime / admin surfaces:\n"
    "  serve api     REST API for programmatic access\n"
    "  serve mcp     stdio MCP for local agent runtimes\n"
    "  serve manus   hosted HTTPS-friendly MCP bridge\n"
    "  serve ui      local infrastructure UI\n\n"
    "These are runtime/admin commands; day-to-day workflows usually start with `cortex init`,\n"
    "`cortex mind`, or `cortex connect`.\n"
)
DOCTOR_HELP_EPILOG = (
    "Health / repair flow:\n"
    "  cortex admin doctor\n"
    "  cortex admin integrity check\n"
    "  cortex admin doctor --fix --dry-run\n"
    "  cortex admin doctor --fix-store\n"
    "  cortex admin doctor --portability\n"
)
CONNECT_RUNTIME_TARGETS = ("hermes", "codex", "cursor", "claude-code")
HELP_TOPIC_TEXT = {
    "overview": (
        "Cortex guided help\n"
        "\n"
        "Start with the first-class path:\n"
        "  cortex init\n"
        '  cortex mind remember self "I prefer concise, implementation-first answers."\n'
        "  cortex connect manus\n"
        "  cortex serve manus\n"
        "\n"
        "Topic guides:\n"
        "  cortex help init\n"
        "  cortex help runtime\n"
        "  cortex help legacy\n"
    ),
    "init": (
        "Cortex init\n"
        "\n"
        "Zero-config path:\n"
        "  cortex init\n"
        "\n"
        "What it does by default:\n"
        "  - creates or reuses the canonical .cortex store\n"
        "  - writes config.toml with scoped reader/writer keys\n"
        "  - creates a default `self` Mind when none exists\n"
        "  - prepares the first-run wizard so the UI can guide the first workflow\n"
        "\n"
        "Common beginner flow:\n"
        "  cortex serve ui\n"
        '  cortex mind remember self "I prefer concise, implementation-first answers."\n'
        "  cortex admin doctor\n"
        "\n"
        "Advanced init flags:\n"
        "  --label            override the display label for the default Mind\n"
        "  --owner            record an explicit owner label in the default Mind manifest\n"
        "  --kind             choose person|agent|project|team for the default Mind\n"
        "  --default-policy   override the default disclosure policy\n"
        "  --namespace        pin the initial MCP/API namespace (default: team)\n"
        "  --no-mind          initialize only the store/config and skip Mind creation\n"
    ),
    "runtime": (
        "Cortex runtime wiring\n"
        "\n"
        "Prepare a runtime first:\n"
        "  cortex connect manus --check\n"
        "  cortex connect codex --install\n"
        "\n"
        "Then run or expose the runtime surface:\n"
        "  cortex serve manus\n"
        "  cortex serve mcp\n"
        "  cortex serve api\n"
        "  cortex serve ui\n"
        "\n"
        "Mount state after the runtime is wired:\n"
        "  cortex mind mount self --to codex\n"
    ),
    "legacy": (
        "Cortex permanent aliases\n"
        "\n"
        "Most CLI v1 flat verbs were retired in the CLI v2 cutover. These aliases remain:\n"
        "  connect  -> cortex remote add / runtime connector setup\n"
        "  rollback -> cortex checkout --at <ref>\n"
        "  scan     -> cortex source status\n"
        "  checkout -> explicit snapshot export\n"
        "  sources  -> cortex source\n"
        "  pull     -> cortex source ingest --pull\n"
        "\n"
        "Use namespaces such as `cortex admin`, `cortex debug`, and `cortex extract` for advanced flows.\n"
    ),
}
ARGPARSE_RECOVERY_HINTS = {
    "cortex connect": "cortex connect manus --check",
    "cortex serve": "cortex serve manus --check",
    "cortex mind status": "cortex mind list",
    "cortex mind remember": 'cortex mind remember self "..."',
    "cortex mind compose": 'cortex mind compose self --to codex --task "..."',
}


def format_cli_error(message: str, *, hint: str | None = None, why: str | None = None) -> str:
    """Render a plain-English CLI error with a recovery path."""
    normalized_message = message.strip().rstrip(".")
    normalized_why = (
        (why or "Cortex could not safely infer the next step from the arguments provided.").strip().rstrip(".")
    )
    normalized_hint = (hint or "Run `cortex --help` to see the available commands and examples.").strip().rstrip(".")
    return (
        f"What went wrong: {normalized_message}.\n"
        f"Why it happened: {normalized_why}.\n"
        f"What to do next: {normalized_hint}."
    )


class CortexArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, show_all_commands: bool = False, **kwargs):
        self.show_all_commands = show_all_commands
        super().__init__(*args, **kwargs)

    def format_help(self) -> str:
        if self.show_all_commands or self.prog != "cortex":
            if not self.show_all_commands and self.prog == "cortex init":
                hidden_dests = {"label", "owner", "kind", "default_policy", "namespace", "no_mind"}
                original_help: dict[argparse.Action, str] = {}
                for action in self._actions:
                    if action.dest in hidden_dests:
                        original_help[action] = action.help
                        action.help = argparse.SUPPRESS
                try:
                    return super().format_help()
                finally:
                    for action, help_text in original_help.items():
                        action.help = help_text
            return super().format_help()

        action = next((item for item in self._actions if isinstance(item, argparse._SubParsersAction)), None)
        if action is None:
            return super().format_help()

        help_text = super().format_help().rstrip()
        command_rows = []
        for choice in sorted(action._choices_actions, key=lambda item: item.dest):
            if not choice.dest:
                continue
            example = "cortex help init" if choice.dest == "help" else f"cortex {choice.dest} --help"
            command_rows.append(
                f"  {choice.dest:<16} {choice.help or 'No description available.'}\n    Example: {example}"
            )
        command_index = "Command index:\n" + "\n".join(command_rows)
        return (
            f"{help_text}\n\n"
            f"{DEFAULT_HELP_START_HERE}\n"
            f"{DEFAULT_HELP_SURFACE_MAP}\n"
            f"{GUIDED_HELP_NOTE}\n"
            f"{ADVANCED_HELP_NOTE}\n\n"
            f"{command_index}\n"
        )

    def error(self, message: str) -> None:
        normalized_prog = " ".join(self.prog.split())
        original_argv = list(getattr(self, "_cortex_original_argv", []))
        hint = ""
        why = None
        if "the following arguments are required:" in message:
            hint = ARGPARSE_RECOVERY_HINTS.get(normalized_prog, "")
            why = "The command parser expected more input for a required argument."
        elif "invalid choice" in message or "unrecognized arguments" in message or "argument subcommand" in message:
            if normalized_prog == "cortex compose" or (
                normalized_prog == "cortex" and original_argv[:1] == ["compose"] and "--to" in original_argv
            ):
                why = "Top-level `cortex compose` renders a graph JSON file and does not accept target arguments."
                hint = "Run `cortex mind compose <mind> --to codex` to preview a Mind for Codex, or `cortex compose <graph.json> --policy technical` to render a graph file."
            else:
                why = "Cortex could not match the command you typed to a known subcommand."
                hint = "If you meant to migrate a chat export, run `cortex migrate <input-file>` explicitly. Otherwise, run `cortex --help` to see the available commands and examples."
        structured = format_cli_error(message, hint=hint, why=why)
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {structured}\n")


def add_setup_and_runtime_parsers(sub, *, add_runtime_security_args) -> None:
    help_parser = sub.add_parser(
        "help",
        help="Guided help for beginner, runtime, and legacy Cortex topics",
    )
    help_parser.add_argument(
        "topic",
        nargs="?",
        choices=tuple(HELP_TOPIC_TEXT.keys()),
        default=None,
        help="Help topic to print; omit for the generated command tree",
    )

    init = sub.add_parser(
        "init",
        help="Initialize a first-class local Cortex workspace",
        description="Bootstrap a local Cortex workspace around one default portable Mind.",
        epilog=INIT_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    init.add_argument("--store-dir", default=None, help="Store directory (default: nearest .cortex or ./ .cortex)")
    init.add_argument("--mind", default="self", help="Default Mind id to create when none exists (default: self)")
    init.add_argument("--label", default="", help="Optional display label for the default Mind")
    init.add_argument("--owner", default="", help="Optional owner label for the default Mind")
    init.add_argument(
        "--kind",
        choices=["person", "agent", "project", "team"],
        default="person",
        help="Default Mind kind (default: person)",
    )
    init.add_argument(
        "--default-policy",
        default="professional",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Default disclosure policy for the default Mind",
    )
    init.add_argument("--namespace", default="team", help="Default MCP/API namespace (default: team)")
    init.add_argument("--no-mind", action="store_true", help="Skip Mind creation and only initialize the store/config")
    init.add_argument("--format", choices=["json", "text"], default="text")

    connect = sub.add_parser(
        "connect",
        help="Prepare first-class runtime connection setup",
        description="Prepare runtime wiring for Cortex without materializing Mind state yet.",
        epilog=CONNECT_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    connect_sub = connect.add_subparsers(dest="connect_subcommand")

    connect_manus = connect_sub.add_parser("manus", help="Generate a Manus custom MCP connector config")
    connect_manus.add_argument("--store-dir", default=None, help="Storage directory (default from config discovery)")
    connect_manus.add_argument("--context-file", help="Optional default context graph file")
    connect_manus.add_argument("--namespace", help="Optional namespace to pin the bridge session to")
    connect_manus.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    connect_manus.add_argument(
        "--url",
        help="Public HTTPS Manus MCP URL, with or without the trailing /mcp path",
    )
    connect_manus.add_argument("--name", default="Cortex-Manus", help="Connector name to include in the MCP JSON")
    connect_manus.add_argument("--key-name", default="", help="Preferred read-scoped API key name from config.toml")
    connect_manus.add_argument(
        "--auth-header",
        choices=["x-api-key", "authorization"],
        default="x-api-key",
        help="Header style Manus should send (default: x-api-key)",
    )
    connect_manus.add_argument(
        "--host",
        default="127.0.0.1",
        help="Suggested local bind host for `cortex serve manus` (default: 127.0.0.1)",
    )
    connect_manus.add_argument(
        "--port",
        type=int,
        default=8790,
        help="Suggested local bind port for `cortex serve manus` (default: 8790)",
    )
    connect_manus.add_argument("--check", action="store_true", help="Validate local Manus bridge readiness")
    connect_manus.add_argument("--print-config", action="store_true", help="Include a Manus MCP JSON preview")
    connect_manus.add_argument(
        "--write-config",
        help="Write the full Manus MCP JSON with live secrets to this file path instead of only printing a masked preview",
    )
    connect_manus.add_argument(
        "--reveal-secret",
        action="store_true",
        help="Print live secrets in the generated JSON preview (unsafe; may leak to shell history or logs)",
    )
    connect_manus.add_argument("--format", choices=["json", "text"], default="text")

    def _add_connect_runtime_args(target_parser, *, target_label: str):
        target_parser.add_argument(
            "--store-dir", default=None, help="Storage directory (default from config discovery)"
        )
        target_parser.add_argument("--project", "-d", help="Project directory for project-scoped files (default: cwd)")
        target_parser.add_argument("--config", help="Path to the Cortex self-host config.toml used by cortex-mcp")
        target_parser.add_argument("--check", action="store_true", help=f"Validate local {target_label} readiness")
        target_parser.add_argument(
            "--print-config",
            action="store_true",
            help=f"Include a paste-ready Cortex MCP config snippet for {target_label}",
        )
        target_parser.add_argument(
            "--install",
            action="store_true",
            help=f"Write or update the local {target_label} Cortex MCP config",
        )
        target_parser.add_argument("--format", choices=["json", "text"], default="text")

    connect_hermes = connect_sub.add_parser("hermes", help="Prepare Hermes for Cortex MCP + mounted context")
    _add_connect_runtime_args(connect_hermes, target_label="Hermes")

    connect_codex = connect_sub.add_parser("codex", help="Prepare Codex for Cortex MCP + mounted context")
    _add_connect_runtime_args(connect_codex, target_label="Codex")

    connect_cursor = connect_sub.add_parser("cursor", help="Prepare Cursor for Cortex MCP + mounted context")
    _add_connect_runtime_args(connect_cursor, target_label="Cursor")

    connect_claude_code = connect_sub.add_parser(
        "claude-code",
        help="Prepare Claude Code for Cortex MCP + mounted context",
    )
    _add_connect_runtime_args(connect_claude_code, target_label="Claude Code")

    serve = sub.add_parser(
        "serve",
        help="Run local Cortex runtime surfaces",
        description="Run local or hosted Cortex runtime surfaces.",
        epilog=SERVE_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    serve_sub = serve.add_subparsers(dest="serve_subcommand")

    serve_api = serve_sub.add_parser("api", help="Launch the local Cortex REST API server")
    serve_api.add_argument("--store-dir", default=None, help="Storage directory (default from config or .cortex)")
    serve_api.add_argument("--context-file", help="Optional default context graph file")
    serve_api.add_argument("--host", default=None, help="Bind host (default from config or 127.0.0.1)")
    serve_api.add_argument("--port", type=int, default=None, help="Bind port (default from config or 8766)")
    add_runtime_security_args(serve_api)
    serve_api.add_argument("--api-key", help="Optional API key required for requests")
    serve_api.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    serve_api.add_argument("--asgi", action="store_true", help="Run the REST API through Starlette/Uvicorn")
    serve_api.add_argument(
        "--cors-origin",
        action="append",
        default=[],
        help="Allowed CORS origin for the ASGI server. Repeatable; use '*' to allow all origins.",
    )
    serve_api.add_argument("--check", action="store_true", help="Print startup diagnostics and exit")
    serve_api.add_argument("--format", choices=["json", "text"], default="text")

    serve_mcp = serve_sub.add_parser("mcp", help="Launch the local Cortex MCP server over stdio")
    serve_mcp.add_argument("--store-dir", default=None, help="Storage directory (default from config or .cortex)")
    serve_mcp.add_argument("--context-file", help="Optional default context graph file")
    serve_mcp.add_argument(
        "--namespace",
        help="Optional namespace prefix to pin the MCP session to, such as 'team' or 'team/atlas'",
    )
    serve_mcp.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    serve_mcp.add_argument("--check", action="store_true", help="Print startup diagnostics and exit")
    serve_mcp.add_argument("--format", choices=["json", "text"], default="text")

    serve_manus = serve_sub.add_parser("manus", help="Launch the Manus-friendly hosted Cortex MCP bridge")
    serve_manus.add_argument("--store-dir", default=None, help="Storage directory (default from config or .cortex)")
    serve_manus.add_argument("--context-file", help="Optional default context graph file")
    serve_manus.add_argument("--namespace", help="Optional namespace to pin the Manus bridge session to")
    serve_manus.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    serve_manus.add_argument("--host", default=None, help="Bind host (default from config or 127.0.0.1)")
    serve_manus.add_argument("--port", type=int, default=None, help="Bind port (default from config or 8790)")
    add_runtime_security_args(serve_manus, include_legacy_manus_alias=True)
    serve_manus.add_argument(
        "--tool",
        action="append",
        default=[],
        help="Expose an additional Cortex MCP tool by name. Repeatable.",
    )
    serve_manus.add_argument(
        "--allow-write-tools",
        action="store_true",
        help="Expose the curated Manus write-tool set in addition to the default read-oriented toolset.",
    )
    serve_manus.add_argument(
        "--protocol-version",
        default=None,
        help="Optional negotiated MCP protocol version override for Manus compatibility",
    )
    serve_manus.add_argument("--check", action="store_true", help="Print bridge diagnostics and exit")
    serve_manus.add_argument("--format", choices=["json", "text"], default="text")

    serve_ui = serve_sub.add_parser("ui", help="Launch the local Cortex infrastructure web UI")
    serve_ui.add_argument("--store-dir", default=None, help="Storage directory (default from config discovery)")
    serve_ui.add_argument("--context-file", help="Default context graph file to prefill in the UI")
    serve_ui.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    serve_ui.add_argument("--host", default=None, help="Bind host (default: 127.0.0.1)")
    serve_ui.add_argument("--port", type=int, default=None, help="Bind port (default: 8765, or 0 for any free port)")
    add_runtime_security_args(serve_ui)
    serve_ui.add_argument("--open", action="store_true", help="Open the UI in your browser automatically")
    serve_ui.add_argument("--check", action="store_true", help="Print startup diagnostics and exit")
    serve_ui.add_argument("--format", choices=["json", "text"], default="text")

    doc = sub.add_parser(
        "doctor",
        help="Inspect and repair Cortex store, config, and runtime drift",
        description="Inspect and repair Cortex store, config, and runtime drift in a local workspace.",
        epilog=DOCTOR_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    doc.add_argument("--store-dir", default=".cortex", help="Store directory to inspect (default: .cortex)")
    doc.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    doc.add_argument(
        "--fix",
        action="store_true",
        help="Apply safe repairs for first-class Cortex CLI store/config issues",
    )
    doc.add_argument(
        "--fix-store",
        action="store_true",
        help="Normalize accidental root-level stores back into a canonical .cortex store",
    )
    doc.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview safe doctor repairs without writing changes",
    )
    doc.add_argument(
        "--backup-repair",
        action="store_true",
        help="Copy touched store/config files into a doctor-backups snapshot before applying repairs",
    )
    doc.add_argument(
        "--portability",
        action="store_true",
        help="Include tool coverage and smart-routing details in the doctor report",
    )
    doc.add_argument("--format", choices=["json", "text"], default="text")
