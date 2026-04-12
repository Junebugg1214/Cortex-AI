from __future__ import annotations


def add_runtime_misc_parsers(sub, *, add_runtime_security_args):
    ui = sub.add_parser(
        "ui",
        help="Compatibility alias for `cortex serve ui`",
        description="Compatibility alias for `cortex serve ui`.",
    )
    ui.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    ui.add_argument("--context-file", help="Default context graph file to prefill in the UI")
    ui.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    ui.add_argument("--host", default=None, help="Bind host (default: 127.0.0.1)")
    ui.add_argument("--port", type=int, default=None, help="Bind port (default: 8765, or 0 for any free port)")
    add_runtime_security_args(ui)
    ui.add_argument("--open", action="store_true", help="Open the UI in your browser automatically")
    ui.add_argument("--check", action="store_true", help="Print startup diagnostics and exit")
    ui.add_argument("--format", choices=["json", "text"], default="text")

    oa = sub.add_parser("openapi", help="Write the Cortex OpenAPI contract")
    oa.add_argument("--output", "-o", default="openapi/cortex-api-v1.json", help="Output path for the OpenAPI JSON")
    oa.add_argument("--server-url", help="Optional server URL to include in the contract")
    oa.add_argument("--compat-output", help="Optional output path for the API compatibility snapshot JSON")

    rn = sub.add_parser("release-notes", help="Write release notes and a release manifest")
    rn.add_argument("--output", "-o", default="dist/release-notes.md", help="Output path for the Markdown notes")
    rn.add_argument(
        "--manifest-output",
        default="dist/release-manifest.json",
        help="Output path for the JSON release manifest",
    )
    rn.add_argument("--tag", help="Optional git tag or release label to include in the notes")
    rn.add_argument("--commit-sha", help="Optional commit SHA to include in the notes")

    bench = sub.add_parser("benchmark", help="Run the lightweight self-host benchmark harness")
    bench.add_argument(
        "--store-dir", default=".cortex-bench", help="Benchmark store directory (default: .cortex-bench)"
    )
    bench.add_argument("--iterations", type=int, default=3, help="Number of benchmark iterations (default: 3)")
    bench.add_argument("--nodes", type=int, default=24, help="Nodes per generated graph (default: 24)")
    bench.add_argument("--output", "-o", help="Optional JSON output path")

    srv = sub.add_parser(
        "server",
        help="Compatibility alias for `cortex serve api`",
        description="Compatibility alias for `cortex serve api`.",
    )
    srv.add_argument("--store-dir", default=None, help="Storage directory (default from config or .cortex)")
    srv.add_argument("--context-file", help="Optional default context graph file")
    srv.add_argument("--host", default=None, help="Bind host (default from config or 127.0.0.1)")
    srv.add_argument("--port", type=int, default=None, help="Bind port (default from config or 8766)")
    add_runtime_security_args(srv)
    srv.add_argument("--api-key", help="Optional API key required for requests")
    srv.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    srv.add_argument("--check", action="store_true", help="Print startup diagnostics and exit")
    srv.add_argument("--format", choices=["json", "text"], default="text")

    mcp = sub.add_parser(
        "mcp",
        help="Compatibility alias for `cortex serve mcp`",
        description="Compatibility alias for `cortex serve mcp`.",
    )
    mcp.add_argument("--store-dir", default=None, help="Storage directory (default from config or .cortex)")
    mcp.add_argument("--context-file", help="Optional default context graph file")
    mcp.add_argument(
        "--namespace",
        help="Optional namespace prefix to pin the MCP session to, such as 'team' or 'team/atlas'",
    )
    mcp.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    mcp.add_argument("--check", action="store_true", help="Print startup diagnostics and exit")
    mcp.add_argument("--format", choices=["json", "text"], default="text")

    bk = sub.add_parser("backup", help="Backup, verify, and restore a Cortex store")
    bk_sub = bk.add_subparsers(dest="backup_subcommand")

    bk_export = bk_sub.add_parser("export", help="Export the store into a verified backup archive")
    bk_export.add_argument("--store-dir", default=".cortex", help="Storage directory to archive (default: .cortex)")
    bk_export.add_argument("--output", "-o", help="Output archive path (default: backups/<timestamp>.zip)")
    bk_export.add_argument("--no-verify", action="store_true", help="Skip post-write archive verification")

    bk_verify = bk_sub.add_parser("verify", help="Verify a Cortex backup archive")
    bk_verify.add_argument("archive", help="Path to the backup archive")

    bk_restore = bk_sub.add_parser("restore", help="Restore a backup archive into a store directory")
    bk_restore.add_argument("archive", help="Path to the backup archive")
    bk_restore.add_argument("--store-dir", default=".cortex", help="Target storage directory (default: .cortex)")
    bk_restore.add_argument("--force", action="store_true", help="Overwrite a non-empty target directory")
    bk_restore.add_argument("--skip-verify", action="store_true", help="Skip archive verification before restore")

    bk_import = bk_sub.add_parser("import", help="Alias of backup restore")
    bk_import.add_argument("archive", help="Path to the backup archive")
    bk_import.add_argument("--store-dir", default=".cortex", help="Target storage directory (default: .cortex)")
    bk_import.add_argument("--force", action="store_true", help="Overwrite a non-empty target directory")
    bk_import.add_argument("--skip-verify", action="store_true", help="Skip archive verification before restore")

    cp = sub.add_parser("completion", help="Generate shell completion script")
    cp.add_argument(
        "--shell", "-s", required=True, choices=["bash", "zsh", "fish"], help="Shell type (bash, zsh, fish)"
    )

    ro = sub.add_parser("rotate", help="Rotate UPAI identity key")
    ro.add_argument("--store-dir", default=".cortex", help="Identity store directory (default: .cortex)")
    ro.add_argument(
        "--reason",
        default="rotated",
        choices=["rotated", "compromised", "expired"],
        help="Rotation reason (default: rotated)",
    )

    agent = sub.add_parser("agent", help="Autonomous conflict monitoring and context dispatch")
    agent_sub = agent.add_subparsers(dest="agent_subcommand")

    agent_monitor = agent_sub.add_parser("monitor", help="Monitor the active fact graph for conflicts")
    agent_monitor.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    agent_monitor.add_argument("--mind", help="Optional Mind id to monitor (default: default Mind or canonical graph)")
    agent_monitor.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Polling interval in seconds (default: 300)",
    )
    agent_monitor.add_argument(
        "--auto-resolve-threshold",
        type=float,
        default=0.85,
        help="Confidence delta required for low-severity auto-resolution (default: 0.85)",
    )
    agent_monitor.add_argument("--once", action="store_true", help="Run one monitor cycle and exit")
    agent_monitor.add_argument(
        "--no-prompt", action="store_true", help="Queue review-required conflicts without prompting"
    )
    agent_monitor.add_argument("--format", choices=["json", "text"], default="text")

    agent_compile = agent_sub.add_parser("compile", help="Manually compile audience-specific context")
    agent_compile.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    agent_compile.add_argument("--mind", required=True, help="Mind id to compile from")
    agent_compile.add_argument("--audience", help="Audience id such as recruiter, attorney, team, or onboarding")
    agent_compile.add_argument(
        "--output",
        required=True,
        choices=["pack", "brief", "cv", "onboarding-doc", "summary"],
        help="Compilation output format",
    )
    agent_compile.add_argument(
        "--delivery",
        default="local-file",
        choices=["local-file", "webhook", "stdout"],
        help="Where to deliver the compiled output (default: local-file)",
    )
    agent_compile.add_argument("--webhook-url", help="Webhook URL used when --delivery webhook")
    agent_compile.add_argument("--output-dir", help="Local output directory (default: ./output)")
    agent_compile.add_argument("--format", choices=["json", "text"], default="text")

    agent_dispatch = agent_sub.add_parser("dispatch", help="Inject an agent event manually")
    agent_dispatch.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    agent_dispatch.add_argument(
        "--event",
        required=True,
        choices=[
            "PROJECT_STAGE_CHANGED",
            "SCHEDULED_REVIEW",
            "FACT_THRESHOLD_REACHED",
            "MANUAL_TRIGGER",
        ],
        help="Built-in event type",
    )
    agent_dispatch.add_argument("--payload", required=True, help="JSON payload for the event")
    agent_dispatch.add_argument("--output-dir", help="Local output directory (default: ./output)")
    agent_dispatch.add_argument("--format", choices=["json", "text"], default="text")

    agent_schedule = agent_sub.add_parser("schedule", help="Register a recurring trigger")
    agent_schedule.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    agent_schedule.add_argument("--mind", required=True, help="Mind id to compile from")
    agent_schedule.add_argument("--audience", required=True, help="Audience id such as attorney or recruiter")
    agent_schedule.add_argument("--cron", required=True, help='Cron expression such as "0 9 * * 1"')
    agent_schedule.add_argument(
        "--output",
        required=True,
        choices=["pack", "brief", "cv", "onboarding-doc", "summary"],
        help="Compilation output format",
    )
    agent_schedule.add_argument(
        "--delivery",
        default="local-file",
        choices=["local-file", "webhook", "stdout"],
        help="Where to deliver the compiled output (default: local-file)",
    )
    agent_schedule.add_argument("--webhook-url", help="Webhook URL used when --delivery webhook")
    agent_schedule.add_argument("--format", choices=["json", "text"], default="text")

    agent_status = agent_sub.add_parser("status", help="Show monitor, conflict, and schedule status")
    agent_status.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    agent_status.add_argument("--review", action="store_true", help="Prompt through queued conflict reviews")
    agent_status.add_argument("--format", choices=["json", "text"], default="text")
