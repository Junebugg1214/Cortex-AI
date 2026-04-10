from __future__ import annotations

import argparse

from cortex.upai.disclosure import BUILTIN_POLICIES

FIRST_CLASS_COMMANDS = ("init", "mind", "pack", "connect", "serve", "doctor")
ADVANCED_HELP_NOTE = (
    "Advanced / compatibility:\n"
    "  Run `cortex --help-all` for graph/versioning internals and legacy aliases such as "
    "`scan`, `sync`, `status`, `portable`, `remember`, `build`, `audit`, `server`, and `mcp`."
)
DEFAULT_HELP_START_HERE = (
    "Start Here:\n"
    "  1. cortex init\n"
    '  2. cortex mind remember self "I prefer concise, implementation-first answers."\n'
    "  3. cortex connect manus\n"
    "  4. cortex serve manus\n"
)
DEFAULT_HELP_SURFACE_MAP = (
    "Surface Map:\n"
    "  Core user flows      init, mind, pack, connect\n"
    "  Runtime / admin      serve, doctor\n"
    "  Advanced internals   graph/versioning + compatibility aliases via --help-all\n"
)
INIT_HELP_EPILOG = (
    "Bootstrap flow:\n"
    "  cortex init\n"
    '  cortex mind remember self "I prefer concise, implementation-first answers."\n'
    "  cortex connect manus\n"
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
    "  cortex doctor\n"
    "  cortex doctor --fix --dry-run\n"
    "  cortex doctor --fix-store\n"
    "  cortex doctor --portability\n"
)
CONNECT_RUNTIME_TARGETS = ("hermes", "codex", "cursor", "claude-code")


class CortexArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, show_all_commands: bool = False, **kwargs):
        self.show_all_commands = show_all_commands
        super().__init__(*args, **kwargs)

    def format_help(self) -> str:
        if self.show_all_commands or self.prog != "cortex":
            return super().format_help()

        action = next((item for item in self._actions if isinstance(item, argparse._SubParsersAction)), None)
        if action is None:
            return super().format_help()

        original_choices_actions = action._choices_actions
        original_metavar = action.metavar
        filtered_map = {choice.dest: choice for choice in original_choices_actions}
        action._choices_actions = [filtered_map[name] for name in FIRST_CLASS_COMMANDS if name in filtered_map]
        action.metavar = "{" + ",".join(FIRST_CLASS_COMMANDS) + "}"
        try:
            help_text = super().format_help().rstrip()
        finally:
            action._choices_actions = original_choices_actions
            action.metavar = original_metavar
        return f"{help_text}\n\n{DEFAULT_HELP_START_HERE}\n{DEFAULT_HELP_SURFACE_MAP}\n{ADVANCED_HELP_NOTE}\n"


def add_setup_and_runtime_parsers(sub, *, add_runtime_security_args) -> None:
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
