from __future__ import annotations

import argparse


def add_portable_mind_pack_parsers(sub, *, builtin_policies, mind_help_epilog, pack_help_epilog):
    pt = sub.add_parser(
        "portable",
        help="Compatibility command for legacy portability-first context sync",
        description="Compatibility command for legacy portability-first context sync.",
    )
    pt.add_argument("input_file", nargs="?", help="Path to a chat export or existing Cortex context graph")
    pt.add_argument(
        "--to",
        "-t",
        nargs="+",
        default=["all"],
        help="Targets: claude, claude-code, chatgpt, codex, copilot, gemini, grok, hermes, windsurf, cursor, or all",
    )
    pt.add_argument("--output", "-o", default="./portable", help="Output directory for context and generated artifacts")
    pt.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    pt.add_argument(
        "--input-format",
        "-F",
        choices=[
            "auto",
            "openai",
            "gemini",
            "perplexity",
            "grok",
            "cursor",
            "windsurf",
            "copilot",
            "jsonl",
            "api_logs",
            "messages",
            "text",
            "generic",
        ],
        default="auto",
        help="Override input format auto-detection for export inputs",
    )
    pt.add_argument(
        "--policy",
        default="technical",
        choices=list(builtin_policies.keys()),
        help="Disclosure policy for installed context and Claude artifacts",
    )
    pt.add_argument("--confidence", "-c", choices=["high", "medium", "low", "all"], default="medium")
    pt.add_argument("--max-chars", type=int, default=1500, help="Max characters per installed context file")
    pt.add_argument("--store-dir", default=".cortex", help="Identity store directory (default: .cortex)")
    pt.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    pt.add_argument("--verbose", "-v", action="store_true")
    pt.add_argument("--redact", action="store_true", help="Enable PII redaction when extracting raw exports")
    pt.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    pt.add_argument(
        "--from-detected",
        nargs="+",
        help="Explicitly adopt detected local platform sources instead of a raw export file",
    )
    pt.add_argument(
        "--search-root",
        action="append",
        default=[],
        help="Extra directory to search for detected exports (repeatable)",
    )
    pt.add_argument(
        "--include-config-metadata",
        action="store_true",
        help="Also ingest detected MCP config metadata; config files are metadata-only by default",
    )
    pt.add_argument(
        "--include-unmanaged-text",
        action="store_true",
        help="Also ingest unmanaged text outside Cortex markers from detected instruction files",
    )
    pt.add_argument(
        "--no-redact-detected",
        action="store_true",
        help="Disable the default PII redaction applied to detected local source adoption",
    )
    pt.add_argument("--format", choices=["json", "text"], default="text")

    scn = sub.add_parser(
        "scan",
        help="Operational command to inspect runtime context coverage",
        description="Operational command to inspect runtime context coverage.",
    )
    scn.add_argument("--store-dir", default=".cortex", help="Portability state directory (default: .cortex)")
    scn.add_argument("--project", "-d", help="Project directory to inspect (default: cwd)")
    scn.add_argument(
        "--search-root",
        action="append",
        default=[],
        help="Extra directory to search for chat exports or tool artifacts (repeatable)",
    )
    scn.add_argument("--format", choices=["json", "text"], default="text")

    rem = sub.add_parser(
        "remember",
        help="Compatibility command for portability-style remember-and-propagate",
        description="Compatibility command for portability-style remember-and-propagate.",
    )
    rem.add_argument("statement", help="Plain-language fact or preference to remember")
    rem.add_argument(
        "--to",
        "-t",
        nargs="+",
        default=["all"],
        help="Targets to update after remembering (default: all supported portability targets)",
    )
    rem.add_argument("--store-dir", default=".cortex", help="Portability state directory (default: .cortex)")
    rem.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    rem.add_argument("--smart", action="store_true", help="Use smart per-tool routing when propagating")
    rem.add_argument(
        "--policy",
        default="full",
        choices=list(builtin_policies.keys()),
        help="Disclosure policy when propagating remembered context",
    )
    rem.add_argument("--max-chars", type=int, default=1500, help="Max characters per written context file")
    rem.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    rem.add_argument(
        "--global",
        dest="allow_global",
        action="store_true",
        help="Allow remember to update target files outside --project, such as home-scoped runtime files",
    )
    rem.add_argument(
        "--yes-global",
        dest="allow_global",
        action="store_true",
        help="Alias for --global",
    )
    rem.add_argument("--format", choices=["json", "text"], default="text")

    sts = sub.add_parser(
        "status",
        help="Operational command to inspect stale or missing runtime context",
        description="Operational command to inspect stale or missing runtime context.",
    )
    sts.add_argument("--store-dir", default=".cortex", help="Portability state directory (default: .cortex)")
    sts.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    sts.add_argument("--format", choices=["json", "text"], default="text")

    mount = sub.add_parser(
        "mount",
        help="Watch and refresh mounted context files",
        description="Watch a Cortex graph and refresh mounted AI runtime context files.",
    )
    mount_sub = mount.add_subparsers(dest="mount_subcommand")

    mount_watch = mount_sub.add_parser(
        "watch",
        help="Poll a Cortex graph and refresh mounted context files when it changes",
        description="Poll a Cortex graph file and refresh mounted context files when its mtime changes.",
    )
    mount_watch.add_argument(
        "--project",
        "-d",
        default=".",
        help="Project directory for project-scoped targets and the default graph path (default: cwd)",
    )
    mount_watch.add_argument(
        "--graph",
        help="Cortex graph JSON to watch (default: <project>/<store-dir>/portable/context.json)",
    )
    mount_watch.add_argument(
        "--to",
        "-t",
        nargs="+",
        default=["all"],
        help="Targets: claude-code, claude-code-project, codex, cursor, copilot, windsurf, gemini, or all",
    )
    mount_watch.add_argument(
        "--policy",
        default=None,
        choices=list(builtin_policies.keys()),
        help="Override disclosure policy for all refreshed targets",
    )
    mount_watch.add_argument("--max-chars", type=int, default=1500, help="Max characters per context file")
    mount_watch.add_argument("--interval", type=float, default=30, help="Polling interval in seconds (default: 30)")
    mount_watch.add_argument("--store-dir", default=".cortex", help="Store directory used for the default graph path")

    bld = sub.add_parser(
        "build",
        help="Compatibility command for legacy digital-footprint imports",
        description="Compatibility command for legacy digital-footprint imports.",
    )
    bld.add_argument(
        "--from",
        dest="sources",
        action="append",
        required=True,
        help="Source to build from: github, resume, package.json, git-history",
    )
    bld.add_argument("inputs", nargs="*", help="Optional input paths consumed by sources like resume")
    bld.add_argument("--store-dir", default=".cortex", help="Portability state directory (default: .cortex)")
    bld.add_argument("--project", "-d", help="Project directory for manifests and git history (default: cwd)")
    bld.add_argument(
        "--search-root",
        action="append",
        default=[],
        help="Extra root to search for GitHub repos when using --from github",
    )
    bld.add_argument("--sync", action="store_true", help="Propagate the built context immediately after import")
    bld.add_argument(
        "--to",
        "-t",
        nargs="+",
        default=["claude-code", "codex", "cursor", "copilot", "windsurf", "gemini"],
        help="Targets to update when --sync is enabled",
    )
    bld.add_argument("--smart", action="store_true", help="Use smart per-tool routing when syncing")
    bld.add_argument(
        "--policy",
        default="technical",
        choices=list(builtin_policies.keys()),
        help="Disclosure policy when syncing after build",
    )
    bld.add_argument("--max-chars", type=int, default=1500, help="Max characters per written context file")
    bld.add_argument("--format", choices=["json", "text"], default="text")

    aud = sub.add_parser(
        "audit",
        help="Compatibility command for legacy portability drift diagnostics",
        description="Compatibility command for legacy portability drift diagnostics.",
    )
    aud.add_argument("--store-dir", default=".cortex", help="Portability state directory (default: .cortex)")
    aud.add_argument("--project", "-d", help="Project directory for live manifest comparison (default: cwd)")
    aud.add_argument("--format", choices=["json", "text"], default="text")

    mind = sub.add_parser(
        "mind",
        help="Manage Cortex Minds: portable, versioned, composable agent minds",
        description="Manage Cortex Minds: durable identity, memory, composition, and mounts.",
        epilog=mind_help_epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mind_sub = mind.add_subparsers(dest="mind_subcommand")

    mind_init = mind_sub.add_parser("init", help="Create a new Cortex Mind")
    mind_init.add_argument("name", help="Mind id")
    mind_init.add_argument(
        "--kind",
        choices=["person", "agent", "project", "team"],
        default="person",
        help="Mind kind (default: person)",
    )
    mind_init.add_argument("--label", default="", help="Display label for the Mind")
    mind_init.add_argument("--owner", default="", help="Owner label recorded in the manifest")
    mind_init.add_argument(
        "--default-policy",
        default="professional",
        choices=list(builtin_policies.keys()),
        help="Default disclosure policy for the Mind",
    )
    mind_init.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_init.add_argument("--format", choices=["json", "text"], default="text")

    mind_list = mind_sub.add_parser("list", help="List local Cortex Minds")
    mind_list.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_list.add_argument("--format", choices=["json", "text"], default="text")

    mind_status = mind_sub.add_parser("status", help="Show Cortex Mind status")
    mind_status.add_argument("name", help="Mind id")
    mind_status.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_status.add_argument("--format", choices=["json", "text"], default="text")

    mind_default = mind_sub.add_parser("default", help="Show, set, or clear the default Cortex Mind")
    mind_default.add_argument("name", nargs="?", help="Mind id to set as the default")
    mind_default.add_argument("--clear", action="store_true", help="Clear the configured default Mind")
    mind_default.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_default.add_argument("--format", choices=["json", "text"], default="text")

    mind_ingest = mind_sub.add_parser("ingest", help="Queue detected local context for review on a Cortex Mind")
    mind_ingest.add_argument("name", help="Mind id")
    mind_ingest.add_argument(
        "--from-detected",
        nargs="+",
        required=True,
        help="Queue detected local platform sources as a review proposal for the Mind",
    )
    mind_ingest.add_argument("--project", "-d", help="Project directory for detected local sources (default: cwd)")
    mind_ingest.add_argument(
        "--search-root",
        action="append",
        default=[],
        help="Extra directory to search for detected exports (repeatable)",
    )
    mind_ingest.add_argument(
        "--include-config-metadata",
        action="store_true",
        help="Also ingest detected MCP config metadata; config files are metadata-only by default",
    )
    mind_ingest.add_argument(
        "--include-unmanaged-text",
        action="store_true",
        help="Also ingest unmanaged text outside Cortex markers from detected instruction files",
    )
    mind_ingest.add_argument("--redact", action="store_true", help="Enable PII redaction for detected local sources")
    mind_ingest.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    mind_ingest.add_argument(
        "--no-redact-detected",
        action="store_true",
        help="Disable the default PII redaction applied to detected local source adoption",
    )
    mind_ingest.add_argument(
        "--message",
        default="",
        help="Optional commit message for the Mind graph update",
    )
    mind_ingest.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_ingest.add_argument("--format", choices=["json", "text"], default="text")

    mind_remember = mind_sub.add_parser("remember", help="Teach a Cortex Mind one new fact or preference directly")
    mind_remember.add_argument("name", help="Mind id")
    mind_remember.add_argument("statement", help="Plain-language fact or preference to add to the Mind")
    mind_remember.add_argument(
        "--message",
        default="",
        help="Optional commit message for the Mind graph update",
    )
    mind_remember.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_remember.add_argument("--format", choices=["json", "text"], default="text")

    mind_attach = mind_sub.add_parser("attach-pack", help="Attach an existing Brainpack to a Cortex Mind")
    mind_attach.add_argument("name", help="Mind id")
    mind_attach.add_argument("pack", help="Brainpack name")
    mind_attach.add_argument("--priority", type=int, default=100, help="Composition priority for the attachment")
    mind_attach.add_argument(
        "--always-on", action="store_true", help="Always include this Brainpack during composition"
    )
    mind_attach.add_argument(
        "--target",
        action="append",
        default=[],
        help="Optional target filter for this Brainpack attachment. Repeat for multiple targets.",
    )
    mind_attach.add_argument(
        "--task-term",
        action="append",
        default=[],
        help="Optional task-term activator for this Brainpack attachment. Repeat for multiple terms.",
    )
    mind_attach.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_attach.add_argument("--format", choices=["json", "text"], default="text")

    mind_detach = mind_sub.add_parser("detach-pack", help="Detach a Brainpack from a Cortex Mind")
    mind_detach.add_argument("name", help="Mind id")
    mind_detach.add_argument("pack", help="Brainpack name")
    mind_detach.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_detach.add_argument("--format", choices=["json", "text"], default="text")

    mind_compose = mind_sub.add_parser("compose", help="Compose a target-aware runtime slice from a Cortex Mind")
    mind_compose.add_argument("name", help="Mind id")
    mind_compose.add_argument(
        "--to", required=True, help="Target tool such as hermes, openclaw, codex, cursor, claude-code, or chatgpt"
    )
    mind_compose.add_argument("--task", default="", help="Optional task hint used to activate attached Brainpacks")
    mind_compose.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    mind_compose.add_argument("--smart", action="store_true", help="Use smart routing for the target")
    mind_compose.add_argument(
        "--policy",
        default="",
        choices=[""] + list(builtin_policies.keys()),
        help="Optional disclosure policy override",
    )
    mind_compose.add_argument("--max-chars", type=int, default=1500, help="Max characters in the rendered context")
    mind_compose.add_argument(
        "--activation-target",
        default="",
        help="Optional runtime target used only for Brainpack activation selection (for example: openclaw)",
    )
    mind_compose.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_compose.add_argument("--format", choices=["json", "text"], default="text")

    mind_mount = mind_sub.add_parser(
        "mount",
        help="Mount a Cortex Mind into supported runtimes and tools",
        description="Write a Mind's routed context into one or more runtime targets and persist the mount records.",
    )
    mind_mount.add_argument("name", help="Mind id")
    mind_mount.add_argument(
        "--to",
        nargs="+",
        required=True,
        choices=["claude-code", "codex", "cursor", "hermes", "openclaw"],
        help="Mount target(s)",
    )
    mind_mount.add_argument("--task", default="", help="Optional task hint used during Mind composition")
    mind_mount.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_mount.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    mind_mount.add_argument("--smart", action="store_true", help="Use smart routing when mounting")
    mind_mount.add_argument(
        "--policy",
        default="",
        choices=[""] + list(builtin_policies.keys()),
        help="Optional disclosure policy override",
    )
    mind_mount.add_argument("--max-chars", type=int, default=1500, help="Max characters per mounted context slice")
    mind_mount.add_argument(
        "--openclaw-store-dir",
        default="",
        help="Optional OpenClaw Cortex store dir if the plugin does not use ~/.openclaw/cortex",
    )
    mind_mount.add_argument("--format", choices=["json", "text"], default="text")

    mind_mounts = mind_sub.add_parser("mounts", help="List persisted mount records for a Cortex Mind")
    mind_mounts.add_argument("name", help="Mind id")
    mind_mounts.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_mounts.add_argument("--format", choices=["json", "text"], default="text")

    pk = sub.add_parser(
        "pack",
        help="Manage Brainpacks: portable, mountable domain minds",
        description="Manage Brainpacks: reusable specialist knowledge that can attach to a Mind.",
        epilog=pack_help_epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pk_sub = pk.add_subparsers(dest="pack_subcommand")

    pk_init = pk_sub.add_parser("init", help="Create a new Brainpack skeleton")
    pk_init.add_argument("name", help="Brainpack name")
    pk_init.add_argument("--description", default="", help="Short pack description")
    pk_init.add_argument("--owner", default="", help="Owner name recorded in the manifest")
    pk_init.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_init.add_argument("--format", choices=["json", "text"], default="text")

    pk_list = pk_sub.add_parser("list", help="List local Brainpacks")
    pk_list.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_list.add_argument("--format", choices=["json", "text"], default="text")

    pk_ingest = pk_sub.add_parser("ingest", help="Ingest raw files or folders into a Brainpack")
    pk_ingest.add_argument("name", help="Brainpack name")
    pk_ingest.add_argument("paths", nargs="+", help="File or directory paths to ingest")
    pk_ingest.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_ingest.add_argument("--copy", dest="mode", action="store_const", const="copy", default="copy")
    pk_ingest.add_argument("--reference", dest="mode", action="store_const", const="reference")
    pk_ingest.add_argument(
        "--type",
        dest="source_type",
        choices=["auto", "article", "paper", "repo", "dataset", "image", "transcript", "note"],
        default="auto",
        help="Override source type classification",
    )
    pk_ingest.add_argument("--recurse", action="store_true", help="Recurse into directories")
    pk_ingest.add_argument("--format", choices=["json", "text"], default="text")

    pk_compile = pk_sub.add_parser("compile", help="Compile a Brainpack into wiki, graph, claims, and unknowns")
    pk_compile.add_argument("name", help="Brainpack name")
    pk_compile.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_compile.add_argument("--incremental", action="store_true", help="Record this compile as incremental")
    pk_compile.add_argument("--suggest-questions", action="store_true", help="Suggest follow-up unknowns")
    pk_compile.add_argument("--max-summary-chars", type=int, default=1200, help="Summary length cap")
    pk_compile.add_argument(
        "--mode",
        choices=["distribution", "full"],
        default="distribution",
        help="Compilation mode (default: distribution)",
    )
    pk_compile.add_argument("--output", help="Optional path for a standalone compiled artifact")
    pk_compile.add_argument("--format", choices=["json", "text"], default="text")

    pk_inspect = pk_sub.add_parser("inspect", help="Inspect a compiled Brainpack artifact")
    pk_inspect.add_argument("path", help="Path to a compiled Brainpack artifact JSON file")
    pk_inspect.add_argument("--show-provenance", action="store_true", help="Show node-level provenance availability")
    pk_inspect.add_argument("--format", choices=["json", "text"], default="text")

    pk_status = pk_sub.add_parser("status", help="Show Brainpack status")
    pk_status.add_argument("name", help="Brainpack name")
    pk_status.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_status.add_argument("--format", choices=["json", "text"], default="text")

    pk_context = pk_sub.add_parser("context", help="Render a routed context slice from a compiled Brainpack")
    pk_context.add_argument("name", help="Brainpack name")
    pk_context.add_argument("--target", required=True, help="Target tool such as hermes, codex, cursor, or chatgpt")
    pk_context.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_context.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    pk_context.add_argument("--smart", action="store_true", help="Use smart routing for the target")
    pk_context.add_argument(
        "--policy",
        default="technical",
        choices=list(builtin_policies.keys()),
        help="Disclosure policy when smart routing is disabled",
    )
    pk_context.add_argument("--max-chars", type=int, default=1500, help="Max characters in the rendered context")
    pk_context.add_argument("--format", choices=["json", "text"], default="text")

    pk_mount = pk_sub.add_parser(
        "mount",
        help="Mount a compiled Brainpack directly into AI runtimes and tools",
        description="Write a compiled Brainpack into one or more runtime targets without first attaching it to a Mind.",
    )
    pk_mount.add_argument("name", help="Brainpack name")
    pk_mount.add_argument(
        "--to",
        nargs="+",
        required=True,
        choices=[
            "claude",
            "claude-code",
            "chatgpt",
            "codex",
            "copilot",
            "cursor",
            "gemini",
            "grok",
            "hermes",
            "windsurf",
            "openclaw",
        ],
        help="Mount target(s)",
    )
    pk_mount.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_mount.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    pk_mount.add_argument("--smart", action="store_true", help="Use smart routing when mounting")
    pk_mount.add_argument(
        "--policy",
        default="technical",
        choices=list(builtin_policies.keys()),
        help="Disclosure policy when smart routing is disabled",
    )
    pk_mount.add_argument("--max-chars", type=int, default=1500, help="Max characters per mounted context slice")
    pk_mount.add_argument(
        "--openclaw-store-dir",
        default="",
        help="Optional OpenClaw Cortex store dir if the plugin does not use ~/.openclaw/cortex",
    )
    pk_mount.add_argument("--format", choices=["json", "text"], default="text")

    pk_query = pk_sub.add_parser(
        "query", help="Search a compiled Brainpack across concepts, claims, wiki, and artifacts"
    )
    pk_query.add_argument("name", help="Brainpack name")
    pk_query.add_argument("query", help="Question or search query")
    pk_query.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_query.add_argument(
        "--mode",
        choices=["hybrid", "concepts", "claims", "wiki", "unknowns", "artifacts"],
        default="hybrid",
        help="Limit the search to a specific slice of the pack",
    )
    pk_query.add_argument("--limit", type=int, default=8, help="Maximum number of ranked results")
    pk_query.add_argument("--format", choices=["json", "text"], default="text")

    pk_ask = pk_sub.add_parser(
        "ask", help="Answer a question against a Brainpack and write the result back as an artifact"
    )
    pk_ask.add_argument("name", help="Brainpack name")
    pk_ask.add_argument("question", help="Question to answer")
    pk_ask.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_ask.add_argument("--output", choices=["note", "report", "slides"], default="note", help="Artifact format")
    pk_ask.add_argument("--limit", type=int, default=8, help="Maximum number of supporting ranked results to use")
    pk_ask.add_argument(
        "--no-write-back",
        dest="write_back",
        action="store_false",
        help="Return the generated answer without saving an artifact",
    )
    pk_ask.set_defaults(write_back=True)
    pk_ask.add_argument("--format", choices=["json", "text"], default="text")

    pk_lint = pk_sub.add_parser("lint", help="Run integrity checks over a compiled Brainpack")
    pk_lint.add_argument("name", help="Brainpack name")
    pk_lint.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_lint.add_argument("--stale-days", type=int, default=30, help="Days before a concept is considered stale")
    pk_lint.add_argument(
        "--duplicate-threshold",
        type=float,
        default=0.88,
        help="Similarity threshold for duplicate concept candidates",
    )
    pk_lint.add_argument(
        "--weak-claim-confidence",
        type=float,
        default=0.65,
        help="Confidence threshold below which claims are flagged as weak",
    )
    pk_lint.add_argument(
        "--thin-article-chars",
        type=int,
        default=220,
        help="Minimum source article size before the page is considered thin",
    )
    pk_lint.add_argument("--format", choices=["json", "text"], default="text")

    pk_export = pk_sub.add_parser("export", help="Export a Brainpack as a portable bundle archive")
    pk_export.add_argument("name", help="Brainpack name")
    pk_export.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_export.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output bundle path or directory (for example ./dist/ai-memory.brainpack.zip)",
    )
    pk_export.add_argument("--no-verify", action="store_true", help="Skip post-write bundle verification")
    pk_export.add_argument("--format", choices=["json", "text"], default="text")

    pk_import = pk_sub.add_parser("import", help="Import a Brainpack bundle archive into the local store")
    pk_import.add_argument("archive", help="Path to the Brainpack bundle archive")
    pk_import.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_import.add_argument("--as", dest="as_name", default="", help="Optional new pack name for the imported bundle")
    pk_import.add_argument("--format", choices=["json", "text"], default="text")

    src = sub.add_parser(
        "sources",
        help="Inspect stable source lineage and retract sources from a Mind",
        description="List the canonical sources attached to a Mind and preview or apply source-safe retractions.",
        epilog=(
            "Examples:\n"
            "  cortex sources list --mind ops\n"
            "  cortex sources retract incident-a.md --mind ops --dry-run\n"
            "  cortex sources retract sha256:... --mind ops --confirm\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src_sub = src.add_subparsers(dest="sources_subcommand")

    src_list = src_sub.add_parser("list", help="List canonical sources referenced by a Mind")
    src_list.add_argument("--mind", required=True, help="Mind id")
    src_list.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    src_list.add_argument("--format", choices=["json", "text"], default="text")

    src_retract = src_sub.add_parser("retract", help="Retract a source from a Mind by stable id or label")
    src_retract.add_argument("source_identifier", help="Stable source id or human label")
    src_retract.add_argument("--mind", required=True, help="Mind id")
    src_retract.add_argument("--dry-run", action="store_true", help="Preview the prune set without modifying the Mind")
    src_retract.add_argument("--confirm", action="store_true", help="Apply the retraction to the Mind graph")
    src_retract.add_argument(
        "--keep-orphans",
        action="store_true",
        help="Keep touched nodes and edges even when no source-backed lineage remains",
    )
    src_retract.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    src_retract.add_argument("--format", choices=["json", "text"], default="text")

    aud = sub.add_parser(
        "audience",
        help="Manage first-class audience policies for a Mind",
        description="Add, preview, compile, and audit audience-specific output rules for one Mind.",
        epilog=(
            "Examples:\n"
            "  cortex audience apply-template --mind ops --template executive\n"
            "  cortex audience preview --mind ops --audience executive\n"
            "  cortex audience compile --mind ops --audience executive\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    aud_sub = aud.add_subparsers(dest="audience_subcommand")

    aud_add = aud_sub.add_parser("add", help="Add or replace an audience policy on a Mind")
    aud_add.add_argument("--mind", required=True, help="Mind id")
    aud_add.add_argument("--audience-id", required=True, help="Audience policy id")
    aud_add.add_argument("--display-name", default="", help="Display name for the audience")
    aud_add.add_argument("--allowed-node-types", default="", help="Comma-separated allowed node tags")
    aud_add.add_argument("--blocked-node-types", default="", help="Comma-separated blocked node tags")
    aud_add.add_argument("--confidence-min", type=float, default=0.0, help="Minimum allowed confidence")
    aud_add.add_argument("--confidence-max", type=float, default=1.0, help="Maximum allowed confidence")
    aud_add.add_argument("--redact-fields", default="", help="Comma-separated fields to redact")
    aud_add.add_argument("--output-format", choices=["brief", "pack", "cv", "report", "raw"], required=True)
    aud_add.add_argument("--delivery", choices=["file", "webhook", "stdout"], default="stdout")
    aud_add.add_argument("--delivery-target", help="File path or webhook URL for delivery")
    aud_add.add_argument("--include-provenance", choices=["true", "false"], default="false")
    aud_add.add_argument("--include-contested", choices=["true", "false"], default="false")
    aud_add.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    aud_add.add_argument("--format", choices=["json", "text"], default="text")

    aud_list = aud_sub.add_parser("list", help="List audience policies configured on a Mind")
    aud_list.add_argument("--mind", required=True, help="Mind id")
    aud_list.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    aud_list.add_argument("--format", choices=["json", "text"], default="text")

    aud_preview = aud_sub.add_parser("preview", help="Preview audience compilation without writing output")
    aud_preview.add_argument("--mind", required=True, help="Mind id")
    aud_preview.add_argument("--audience", required=True, help="Audience id")
    aud_preview.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    aud_preview.add_argument("--format", choices=["json", "text"], default="text")

    aud_compile = aud_sub.add_parser("compile", help="Compile a Mind for one configured audience")
    aud_compile.add_argument("--mind", required=True, help="Mind id")
    aud_compile.add_argument("--audience", required=True, help="Audience id")
    aud_compile.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    aud_compile.add_argument("--format", choices=["json", "text"], default="text")

    aud_log = aud_sub.add_parser("log", help="Show compilation history for one audience")
    aud_log.add_argument("--mind", required=True, help="Mind id")
    aud_log.add_argument("--audience", help="Optional audience id filter")
    aud_log.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    aud_log.add_argument("--format", choices=["json", "text"], default="text")

    aud_template = aud_sub.add_parser("apply-template", help="Apply a built-in audience template to a Mind")
    aud_template.add_argument("--mind", required=True, help="Mind id")
    aud_template.add_argument("--template", choices=["executive", "attorney", "onboarding", "audit"], required=True)
    aud_template.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    aud_template.add_argument("--format", choices=["json", "text"], default="text")
