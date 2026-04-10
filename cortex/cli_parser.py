#!/usr/bin/env python3
"""Argparse assembly for the Cortex CLI."""

from __future__ import annotations

import argparse

from cortex import cli_runtime as cli_runtime_module
from cortex import cli_surface as cli_surface_module
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

    # -- migrate (default) --------------------------------------------------
    mig = sub.add_parser("migrate", help="Full pipeline: extract then import")
    mig.add_argument("input_file", help="Path to chat export file")
    mig.add_argument(
        "--to",
        "-t",
        dest="to",
        default="all",
        choices=list(PLATFORM_FORMATS.keys()),
        help="Target platform shortcut (default: all)",
    )
    mig.add_argument("--output", "-o", default="./output", help="Output directory")
    mig.add_argument(
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
        help="Override input format auto-detection",
    )
    mig.add_argument("--merge", "-m", help="Existing context file to merge with")
    mig.add_argument("--redact", action="store_true", help="Enable PII redaction")
    mig.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    mig.add_argument("--confidence", "-c", choices=["high", "medium", "low", "all"], default="medium")
    mig.add_argument("--dry-run", action="store_true", help="Preview without writing")
    mig.add_argument("--verbose", "-v", action="store_true")
    mig.add_argument("--stats", action="store_true", help="Show category stats")
    mig.add_argument(
        "--schema",
        choices=["v5", "v4"],
        default="v5",
        help="Output context.json schema version (default: v5; v4 is deprecated)",
    )
    mig.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    mig.add_argument("--no-claims", action="store_true", help="Skip provenance stamping and claim-ledger recording")
    mig.add_argument(
        "--discover-edges", action="store_true", help="Run smart edge extraction (pattern + co-occurrence)"
    )
    mig.add_argument("--llm", action="store_true", help="LLM-assisted edge extraction (future, stub)")

    # -- extract ------------------------------------------------------------
    ext = sub.add_parser("extract", help="Extract context from export file")
    ext.add_argument("input_file", nargs="?", help="Path to chat export file")
    ext.add_argument("--output", "-o", help="Output JSON path")
    ext.add_argument(
        "--format",
        "-f",
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
    )
    ext.add_argument("--merge", "-m", help="Existing context file to merge with")
    ext.add_argument("--redact", action="store_true")
    ext.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    ext.add_argument("--verbose", "-v", action="store_true")
    ext.add_argument("--stats", action="store_true")
    ext.add_argument(
        "--from-detected",
        nargs="+",
        help="Explicitly adopt detected local platform sources instead of a raw export file",
    )
    ext.add_argument("--project", "-d", help="Project directory for detected local sources (default: cwd)")
    ext.add_argument(
        "--search-root",
        action="append",
        default=[],
        help="Extra directory to search for detected exports (repeatable)",
    )
    ext.add_argument(
        "--include-config-metadata",
        action="store_true",
        help="Also ingest detected MCP config metadata; config files are metadata-only by default",
    )
    ext.add_argument(
        "--include-unmanaged-text",
        action="store_true",
        help="Also ingest unmanaged text outside Cortex markers from detected instruction files",
    )
    ext.add_argument(
        "--no-redact-detected",
        action="store_true",
        help="Disable the default PII redaction applied to detected local source adoption",
    )
    ext.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    ext.add_argument("--no-claims", action="store_true", help="Skip provenance stamping and claim-ledger recording")

    # -- ingest -------------------------------------------------------------
    ing = sub.add_parser("ingest", help="Normalize GitHub/Slack/docs sources and extract memory")
    ing.add_argument("kind", choices=["github", "slack", "docs"], help="Connector kind")
    ing.add_argument("input_file", help="Path to connector export file or directory")
    ing.add_argument("--output", "-o", help="Output JSON path")
    ing.add_argument("--merge", "-m", help="Existing context file to merge with")
    ing.add_argument("--redact", action="store_true")
    ing.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    ing.add_argument("--preview", action="store_true", help="Print normalized connector text without extracting")
    ing.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    ing.add_argument("--no-claims", action="store_true", help="Skip provenance stamping and claim-ledger recording")

    # -- import -------------------------------------------------------------
    imp = sub.add_parser("import", help="Import context to platform formats")
    imp.add_argument("input_file", help="Path to context JSON file")
    imp.add_argument(
        "--to",
        "-t",
        dest="to",
        default="all",
        choices=list(PLATFORM_FORMATS.keys()),
        help="Target platform shortcut (default: all)",
    )
    imp.add_argument("--output", "-o", default="./output", help="Output directory")
    imp.add_argument("--confidence", "-c", choices=["high", "medium", "low", "all"], default="medium")
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--verbose", "-v", action="store_true")

    mem = sub.add_parser("memory", help="Inspect and edit local memory graph")
    mem_sub = mem.add_subparsers(dest="memory_subcommand")

    mem_conf = mem_sub.add_parser("conflicts", help="List memory conflicts")
    mem_conf.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    mem_conf.add_argument("--severity", type=float, default=0.0, help="Minimum severity threshold (0.0-1.0)")
    mem_conf.add_argument("--format", choices=["json", "text"], default="text")

    mem_show = mem_sub.add_parser("show", help="Show memory nodes")
    mem_show.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    mem_show.add_argument("--label", help="Exact node label")
    mem_show.add_argument("--tag", help="Filter by tag")
    mem_show.add_argument("--limit", type=int, default=20, help="Max nodes to show")
    mem_show.add_argument("--format", choices=["json", "text"], default="text")

    mem_forget = mem_sub.add_parser("forget", help="Forget memory nodes")
    mem_forget.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    mem_forget.add_argument("--node-id", help="Delete by node ID")
    mem_forget.add_argument("--label", help="Delete by exact label")
    mem_forget.add_argument("--tag", help="Delete all nodes with tag")
    mem_forget.add_argument("--dry-run", action="store_true", help="Preview without writing")
    mem_forget.add_argument("--commit-message", help="Optional version commit message")
    mem_forget.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    mem_forget.add_argument("--format", choices=["json", "text"], default="text")

    mem_retract = mem_sub.add_parser("retract", help="Retract memory evidence by provenance source")
    mem_retract.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    mem_retract.add_argument("--source", required=True, help="Provenance source label to retract")
    mem_retract.add_argument("--dry-run", action="store_true", help="Preview without writing")
    mem_retract.add_argument(
        "--keep-orphans",
        action="store_true",
        help="Keep touched nodes and edges even if they no longer have any source-backed evidence",
    )
    mem_retract.add_argument("--commit-message", help="Optional version commit message")
    mem_retract.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    mem_retract.add_argument("--format", choices=["json", "text"], default="text")

    mem_set = mem_sub.add_parser("set", help="Create or update a memory node")
    mem_set.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    mem_set.add_argument("--label", required=True, help="Node label")
    mem_set.add_argument("--tag", action="append", required=True, help="Tag to apply (repeatable)")
    mem_set.add_argument("--brief", default="", help="Short summary")
    mem_set.add_argument("--description", default="", help="Long description")
    mem_set.add_argument("--property", action="append", help="Node property key=value (repeatable)")
    mem_set.add_argument("--alias", action="append", help="Alternate label/alias (repeatable)")
    mem_set.add_argument("--confidence", type=float, default=0.95, help="Confidence score")
    mem_set.add_argument("--valid-from", default="", help="Validity start timestamp (ISO-8601)")
    mem_set.add_argument("--valid-to", default="", help="Validity end timestamp (ISO-8601)")
    mem_set.add_argument("--status", default="", help="Lifecycle status such as active, planned, or historical")
    mem_set.add_argument("--source", default="", help="Provenance source label for this manual edit")
    mem_set.add_argument("--replace-label", help="Update first node matching this label")
    mem_set.add_argument("--commit-message", help="Optional version commit message")
    mem_set.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    mem_set.add_argument("--format", choices=["json", "text"], default="text")

    mem_resolve = mem_sub.add_parser("resolve", help="Resolve a memory conflict")
    mem_resolve.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    mem_resolve.add_argument("--conflict-id", required=True, help="Conflict ID from memory conflicts")
    mem_resolve.add_argument(
        "--action",
        required=True,
        choices=["accept-new", "keep-old", "merge", "ignore"],
        help="Resolution action",
    )
    mem_resolve.add_argument("--commit-message", help="Optional version commit message")
    mem_resolve.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    mem_resolve.add_argument("--format", choices=["json", "text"], default="text")

    # -- query (Phase 1 + Phase 5) -----------------------------------------
    qry = sub.add_parser("query", help="Query a context/graph file")
    qry.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    qry.add_argument("--node", help="Look up a node by label")
    qry.add_argument("--neighbors", help="Get neighbors of a node by label")
    qry.add_argument("--category", help="List nodes by tag/category")
    qry.add_argument("--path", nargs=2, metavar=("FROM", "TO"), help="Find shortest path between two labels")
    qry.add_argument("--changed-since", help="Show nodes changed since ISO date")
    qry.add_argument("--strongest", type=int, metavar="N", help="Top N nodes by confidence")
    qry.add_argument("--weakest", type=int, metavar="N", help="Bottom N nodes by confidence")
    qry.add_argument("--isolated", action="store_true", help="List nodes with zero edges")
    qry.add_argument("--related", nargs="?", const="", metavar="LABEL", help="Nodes related to LABEL (default depth=2)")
    qry.add_argument("--related-depth", type=int, default=2, help="Depth for --related traversal (default: 2)")
    qry.add_argument("--components", action="store_true", help="Show connected components")
    qry.add_argument("--search", metavar="QUERY", help="Hybrid search across labels, aliases, and descriptions")
    qry.add_argument("--limit", type=int, default=10, help="Result limit for --search or --dsl SEARCH (default: 10)")
    qry.add_argument("--dsl", metavar="QUERY", help="Run the Cortex query DSL directly")
    qry.add_argument("--nl", metavar="QUERY", help="Natural-language query (limited patterns)")
    qry.add_argument("--at", help="Query the graph as-of an ISO timestamp using validity windows and snapshots")
    qry.add_argument("--format", choices=["json", "text"], default="text", help="Output format (default: text)")

    # -- stats (Phase 1) ---------------------------------------------------
    st = sub.add_parser("stats", help="Show graph/context statistics")
    st.add_argument("input_file", help="Path to context JSON (v4 or v5)")

    # -- timeline (Phase 2) ------------------------------------------------
    tl = sub.add_parser("timeline", help="Generate timeline from context/graph")
    tl.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    tl.add_argument("--from", dest="from_date", help="Start date (ISO-8601)")
    tl.add_argument("--to", dest="to_date", help="End date (ISO-8601)")
    tl.add_argument(
        "--format", "-f", dest="output_format", choices=["md", "html"], default="md", help="Output format (default: md)"
    )

    # -- contradictions (Phase 2) ------------------------------------------
    ct = sub.add_parser("contradictions", help="Detect contradictions in context/graph")
    ct.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    ct.add_argument("--severity", type=float, default=0.0, help="Minimum severity threshold (0.0-1.0)")
    ct.add_argument(
        "--type",
        dest="contradiction_type",
        choices=["negation_conflict", "temporal_flip", "source_conflict", "tag_conflict", "temporal_claim_conflict"],
        help="Filter by contradiction type",
    )
    ct.add_argument("--format", choices=["json", "text"], default="text", help="Output format (default: text)")

    # -- drift (Phase 2) ---------------------------------------------------
    dr = sub.add_parser("drift", help="Compute identity drift between two graphs")
    dr.add_argument("input_file", help="Path to first context JSON (v4 or v5)")
    dr.add_argument("--compare", required=True, help="Path to second context JSON to compare against")

    # -- diff (version history) --------------------------------------------
    df = sub.add_parser("diff", help="Compare two stored graph versions")
    df.add_argument("version_a", help="Base version ID, unique prefix, branch name, or HEAD")
    df.add_argument("version_b", help="Target version ID, unique prefix, branch name, or HEAD")
    df.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    df.add_argument("--format", choices=["json", "text"], default="text")
    df.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- blame (memory receipts) -------------------------------------------
    bl = sub.add_parser("blame", help="Explain where a memory claim came from")
    bl.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    bl_target = bl.add_mutually_exclusive_group(required=True)
    bl_target.add_argument("--label", help="Node label or alias to trace")
    bl_target.add_argument("--node-id", help="Node ID to trace")
    bl.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    bl.add_argument("--ref", default="HEAD", help="Branch/ref/version ancestry to inspect (default: HEAD)")
    bl.add_argument("--source", help="Filter receipts to a specific source label")
    bl.add_argument("--limit", type=int, default=20, help="Max versions to scan for blame history (default: 20)")
    bl.add_argument("--format", choices=["json", "text"], default="text")
    bl.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- history (receipts timeline) --------------------------------------
    hs = sub.add_parser("history", help="Show chronological memory receipts for a node")
    hs.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    hs_target = hs.add_mutually_exclusive_group(required=True)
    hs_target.add_argument("--label", help="Node label or alias to trace")
    hs_target.add_argument("--node-id", help="Node ID to trace")
    hs.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    hs.add_argument("--ref", default="HEAD", help="Branch/ref/version ancestry to inspect (default: HEAD)")
    hs.add_argument("--source", help="Filter receipts to a specific source label")
    hs.add_argument("--limit", type=int, default=20, help="Max versions to scan (default: 20)")
    hs.add_argument("--format", choices=["json", "text"], default="text")
    hs.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- claim (ledger) ----------------------------------------------------
    clm = sub.add_parser("claim", help="Inspect the local claim ledger")
    clm_sub = clm.add_subparsers(dest="claim_subcommand")

    clm_log = clm_sub.add_parser("log", help="List recent claim events")
    clm_log.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    clm_log.add_argument("--label", help="Filter by label or alias")
    clm_log.add_argument("--node-id", help="Filter by node id")
    clm_log.add_argument("--source", help="Filter by source")
    clm_log.add_argument("--version", help="Filter by version id prefix")
    clm_log.add_argument(
        "--op", choices=["assert", "retract", "accept", "reject", "supersede"], help="Filter by operation"
    )
    clm_log.add_argument("--limit", type=int, default=20, help="Max events to return (default: 20)")
    clm_log.add_argument("--format", choices=["json", "text"], default="text")

    clm_show = clm_sub.add_parser("show", help="Show all events for a claim id")
    clm_show.add_argument("claim_id", help="Claim id")
    clm_show.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    clm_show.add_argument("--format", choices=["json", "text"], default="text")

    clm_accept = clm_sub.add_parser("accept", help="Accept a claim and restore it into the graph if needed")
    clm_accept.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    clm_accept.add_argument("claim_id", help="Claim id")
    clm_accept.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    clm_accept.add_argument("--commit-message", help="Optional version commit message")
    clm_accept.add_argument("--format", choices=["json", "text"], default="text")

    clm_reject = clm_sub.add_parser("reject", help="Reject a claim and remove its graph support")
    clm_reject.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    clm_reject.add_argument("claim_id", help="Claim id")
    clm_reject.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    clm_reject.add_argument("--commit-message", help="Optional version commit message")
    clm_reject.add_argument("--format", choices=["json", "text"], default="text")

    clm_sup = clm_sub.add_parser("supersede", help="Supersede a claim with an updated claim state")
    clm_sup.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    clm_sup.add_argument("claim_id", help="Claim id")
    clm_sup.add_argument("--label", help="Override label")
    clm_sup.add_argument("--tag", action="append", dest="tags", default=[], help="Replacement tag (repeatable)")
    clm_sup.add_argument("--alias", action="append", default=[], help="Alias to keep on the superseding claim")
    clm_sup.add_argument("--status", help="Override status")
    clm_sup.add_argument("--valid-from", default="", help="Override valid_from timestamp")
    clm_sup.add_argument("--valid-to", default="", help="Override valid_to timestamp")
    clm_sup.add_argument("--confidence", type=float, help="Override confidence")
    clm_sup.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    clm_sup.add_argument("--commit-message", help="Optional version commit message")
    clm_sup.add_argument("--format", choices=["json", "text"], default="text")

    # -- checkout (version history) ----------------------------------------
    ck = sub.add_parser("checkout", help="Write a stored graph version to a file")
    ck.add_argument("version_id", help="Version ID, unique prefix, branch name, or HEAD")
    ck.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    ck.add_argument("--output", "-o", help="Output file path (default: <version>.json)")
    ck.add_argument("--no-verify", action="store_true", help="Skip snapshot integrity verification")
    ck.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- rollback (version history) ----------------------------------------
    rb = sub.add_parser("rollback", help="Restore a prior memory state as a new commit")
    rb.add_argument("input_file", help="Path to context JSON (v4 or v5) to overwrite with the restored graph")
    rb_target = rb.add_mutually_exclusive_group(required=True)
    rb_target.add_argument("--to", dest="target_ref", help="Version ID, unique prefix, branch name, or HEAD")
    rb_target.add_argument(
        "--at", dest="target_time", help="Restore the latest version at or before this ISO timestamp"
    )
    rb.add_argument("--ref", default="HEAD", help="Restrict --at lookup to this branch/ref (default: HEAD)")
    rb.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rb.add_argument("--message", help="Optional rollback commit message")
    rb.add_argument("--format", choices=["json", "text"], default="text")
    rb.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")
    rb.add_argument("--approve", action="store_true", help="Explicitly approve a gated rollback")

    # -- identity (Phase 3) ------------------------------------------------
    ident = sub.add_parser("identity", help="Init/show UPAI identity")
    ident.add_argument("--init", action="store_true", help="Generate new identity")
    ident.add_argument("--name", help="Human-readable name for identity")
    ident.add_argument("--show", action="store_true", help="Show current identity")
    ident.add_argument("--store-dir", default=".cortex", help="Identity store directory (default: .cortex)")
    ident.add_argument("--did-doc", action="store_true", help="Output W3C DID document JSON")
    ident.add_argument("--keychain", action="store_true", help="Show key rotation history and status")

    # -- commit (Phase 3) --------------------------------------------------
    cm = sub.add_parser("commit", help="Version a graph snapshot")
    cm.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    cm.add_argument("-m", "--message", required=True, help="Commit message")
    cm.add_argument("--source", default="manual", help="Source label (extraction, merge, manual)")
    cm.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    cm.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")
    cm.add_argument("--approve", action="store_true", help="Explicitly approve a gated commit")

    # -- branch (Git-for-AI-Memory) ---------------------------------------
    br = sub.add_parser("branch", help="List or create memory branches")
    br.add_argument("branch_name", nargs="?", help="Branch name to create")
    br.add_argument("--from", dest="from_ref", default="HEAD", help="Start point ref (default: HEAD)")
    br.add_argument("--switch", action="store_true", help="Switch to the new branch after creating it")
    br.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    br.add_argument("--format", choices=["json", "text"], default="text")
    br.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- switch (Git-for-AI-Memory) ---------------------------------------
    sw = sub.add_parser("switch", help="Switch the active memory branch or migrate context to another AI tool")
    sw.add_argument("branch_name", nargs="?", help="Branch name to switch to")
    sw.add_argument("-c", "--create", action="store_true", help="Create the branch if it does not exist")
    sw.add_argument(
        "--from", dest="from_ref", default="HEAD", help="Start point when creating a branch (default: HEAD)"
    )
    sw.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    sw.add_argument(
        "--to",
        dest="to_platform",
        choices=[
            "claude",
            "claude-code",
            "chatgpt",
            "codex",
            "copilot",
            "gemini",
            "grok",
            "hermes",
            "windsurf",
            "cursor",
        ],
        help="Portable platform switch target. When set, --from is treated as the source export/context path.",
    )
    sw.add_argument("--output", "-o", help="Output directory for generated switch artifacts")
    sw.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    sw.add_argument(
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
        help="Override input format detection when using portable switch mode",
    )
    sw.add_argument(
        "--policy",
        default="technical",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy for portable switch mode",
    )
    sw.add_argument("--max-chars", type=int, default=1500, help="Max characters per written context file")
    sw.add_argument("--dry-run", action="store_true", help="Preview portable switch without writing files")

    # -- merge (Git-for-AI-Memory) ----------------------------------------
    mg = sub.add_parser("merge", help="Merge another memory branch/ref into the current branch")
    mg.add_argument("ref_name", nargs="?", help="Branch or ref to merge into the current branch")
    mg.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    mg.add_argument("--message", help="Custom merge commit message")
    mg.add_argument("--dry-run", action="store_true", help="Compute merge result without committing")
    mg.add_argument("--output", "-o", help="Optional path to write the merged graph snapshot")
    mg.add_argument("--format", choices=["json", "text"], default="text")
    mg.add_argument("--conflicts", action="store_true", help="Show pending merge conflicts")
    mg.add_argument("--resolve", metavar="CONFLICT_ID", help="Resolve a pending merge conflict")
    mg.add_argument("--choose", choices=["current", "incoming"], help="Conflict resolution choice")
    mg.add_argument("--commit-resolved", action="store_true", help="Commit the current resolved merge state")
    mg.add_argument("--abort", action="store_true", help="Abort the pending merge state")
    mg.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")
    mg.add_argument("--approve", action="store_true", help="Explicitly approve a gated merge")

    # -- review (Git-for-AI-Memory) ---------------------------------------
    rvw = sub.add_parser("review", help="Review a memory graph against a stored ref")
    rvw.add_argument("input_file", nargs="?", help="Optional context JSON to review instead of a stored ref")
    rvw.add_argument("--against", required=True, help="Baseline branch/ref/version to compare against")
    rvw.add_argument("--ref", default="HEAD", help="Current branch/ref/version when no input file is provided")
    rvw.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rvw.add_argument(
        "--fail-on",
        default="blocking",
        help="Comma-separated review gates: blocking, contradictions, temporal_gaps, low_confidence, retractions, changes, none",
    )
    rvw.add_argument("--format", choices=["json", "text", "md"], default="text")

    # -- log (Phase 3) -----------------------------------------------------
    lg = sub.add_parser("log", help="Show version history")
    lg.add_argument("--limit", type=int, default=10, help="Max entries to show")
    lg.add_argument("--branch", help="Branch/ref to inspect (default: current branch)")
    lg.add_argument("--all", action="store_true", help="Show global history instead of branch ancestry")
    lg.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    lg.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- governance --------------------------------------------------------
    gov = sub.add_parser("governance", help="Manage access control and approval policies")
    gov_sub = gov.add_subparsers(dest="governance_subcommand")

    gov_list = gov_sub.add_parser("list", help="List governance rules")
    gov_list.add_argument("--store-dir", default=".cortex", help="Governance store directory (default: .cortex)")
    gov_list.add_argument("--format", choices=["json", "text"], default="text")

    gov_add = gov_sub.add_parser("allow", help="Create or replace an allow rule")
    gov_add.add_argument("name", help="Rule name")
    gov_add.add_argument("--actor", dest="actor_pattern", default="*", help="Actor glob pattern")
    gov_add.add_argument("--action", action="append", required=True, help="Action to allow (repeatable or '*')")
    gov_add.add_argument("--namespace", action="append", required=True, help="Namespace/branch glob pattern")
    gov_add.add_argument("--require-approval", action="store_true", help="Always require approval for this rule")
    gov_add.add_argument("--approval-below-confidence", type=float, help="Require approval below this confidence")
    gov_add.add_argument("--approval-tag", action="append", default=[], help="Tag that requires approval when changed")
    gov_add.add_argument(
        "--approval-change", action="append", default=[], help="Semantic change type requiring approval"
    )
    gov_add.add_argument("--description", default="", help="Optional rule description")
    gov_add.add_argument("--store-dir", default=".cortex", help="Governance store directory (default: .cortex)")
    gov_add.add_argument("--format", choices=["json", "text"], default="text")

    gov_deny = gov_sub.add_parser("deny", help="Create or replace a deny rule")
    gov_deny.add_argument("name", help="Rule name")
    gov_deny.add_argument("--actor", dest="actor_pattern", default="*", help="Actor glob pattern")
    gov_deny.add_argument("--action", action="append", required=True, help="Action to deny (repeatable or '*')")
    gov_deny.add_argument("--namespace", action="append", required=True, help="Namespace/branch glob pattern")
    gov_deny.add_argument("--description", default="", help="Optional rule description")
    gov_deny.add_argument("--store-dir", default=".cortex", help="Governance store directory (default: .cortex)")
    gov_deny.add_argument("--format", choices=["json", "text"], default="text")

    gov_rm = gov_sub.add_parser("delete", help="Delete a governance rule")
    gov_rm.add_argument("name", help="Rule name")
    gov_rm.add_argument("--store-dir", default=".cortex", help="Governance store directory (default: .cortex)")
    gov_rm.add_argument("--format", choices=["json", "text"], default="text")

    gov_check = gov_sub.add_parser("check", help="Check whether an actor may perform an action")
    gov_check.add_argument("--actor", required=True, help="Actor identity")
    gov_check.add_argument(
        "--action",
        required=True,
        choices=GOVERNANCE_ACTION_CHOICES,
        help="Action to evaluate",
    )
    gov_check.add_argument("--namespace", required=True, help="Namespace or branch name")
    gov_check.add_argument("--input-file", help="Optional current graph to evaluate for approval gating")
    gov_check.add_argument("--against", help="Optional baseline ref for semantic diff/approval gating")
    gov_check.add_argument("--store-dir", default=".cortex", help="Governance store directory (default: .cortex)")
    gov_check.add_argument("--format", choices=["json", "text"], default="text")

    # -- remote ------------------------------------------------------------
    rem = sub.add_parser("remote", help="Manage remote memory stores and sync branches")
    rem_sub = rem.add_subparsers(dest="remote_subcommand")

    rem_list = rem_sub.add_parser("list", help="List configured remotes")
    rem_list.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rem_list.add_argument("--format", choices=["json", "text"], default="text")

    rem_add = rem_sub.add_parser("add", help="Add or replace a remote memory store")
    rem_add.add_argument("name", help="Remote name")
    rem_add.add_argument("path", help="Path to another .cortex store or its parent directory")
    rem_add.add_argument("--default-branch", default="main", help="Default remote branch (default: main)")
    rem_add.add_argument(
        "--allow-namespace",
        action="append",
        default=[],
        help="Allowed remote namespace/branch prefix for sync operations (repeatable; default: remote default branch)",
    )
    rem_add.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rem_add.add_argument("--format", choices=["json", "text"], default="text")

    rem_rm = rem_sub.add_parser("remove", help="Remove a remote definition")
    rem_rm.add_argument("name", help="Remote name")
    rem_rm.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rem_rm.add_argument("--format", choices=["json", "text"], default="text")

    rem_push = rem_sub.add_parser("push", help="Push a memory branch to a remote store")
    rem_push.add_argument("name", help="Remote name")
    rem_push.add_argument("--branch", default="HEAD", help="Local branch/ref to push (default: HEAD)")
    rem_push.add_argument("--to-branch", help="Remote branch name (default: same as source branch)")
    rem_push.add_argument("--force", action="store_true", help="Allow non-fast-forward remote updates")
    rem_push.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rem_push.add_argument("--format", choices=["json", "text"], default="text")
    rem_push.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    rem_pull = rem_sub.add_parser("pull", help="Pull a remote branch into a local branch")
    rem_pull.add_argument("name", help="Remote name")
    rem_pull.add_argument("--branch", help="Remote branch to pull (default: remote default branch)")
    rem_pull.add_argument("--into-branch", help="Local branch to update (default: remotes/<name>/<branch>)")
    rem_pull.add_argument("--switch", action="store_true", help="Switch to the updated branch after pulling")
    rem_pull.add_argument("--force", action="store_true", help="Allow non-fast-forward local updates")
    rem_pull.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rem_pull.add_argument("--format", choices=["json", "text"], default="text")
    rem_pull.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    rem_fork = rem_sub.add_parser("fork", help="Fork a remote branch into a new local branch")
    rem_fork.add_argument("name", help="Remote name")
    rem_fork.add_argument("branch_name", help="New local branch name")
    rem_fork.add_argument("--remote-branch", help="Remote branch to fork (default: remote default branch)")
    rem_fork.add_argument("--switch", action="store_true", help="Switch to the new local branch after forking")
    rem_fork.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rem_fork.add_argument("--format", choices=["json", "text"], default="text")
    rem_fork.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- sync (Phase 3) ----------------------------------------------------
    sy = sub.add_parser("sync", help="Disclosure-filtered export or smart context propagation")
    sy.add_argument("input_file", nargs="?", help="Path to context JSON (v4 or v5)")
    sy.add_argument("--to", "-t", help="Target platform adapter (legacy mode)")
    sy.add_argument(
        "--policy",
        "-p",
        default="full",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy (default: full)",
    )
    sy.add_argument("--output", "-o", default="./output", help="Output directory")
    sy.add_argument("--store-dir", default=".cortex", help="Identity store directory (default: .cortex)")
    sy.add_argument("--smart", action="store_true", help="Route the right context slice to each supported AI tool")
    sy.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    sy.add_argument("--max-chars", type=int, default=1500, help="Max characters per written context file")
    sy.add_argument("--format", choices=["json", "text"], default="text")

    # -- verify (Phase 3) --------------------------------------------------
    vr = sub.add_parser("verify", help="Verify a signed export")
    vr.add_argument("input_file", help="Path to signed export file")

    # -- gaps (Phase 5) ----------------------------------------------------
    gp = sub.add_parser("gaps", help="Analyze gaps in knowledge graph")
    gp.add_argument("input_file", help="Path to context JSON (v4 or v5)")

    # -- digest (Phase 5) --------------------------------------------------
    dg = sub.add_parser("digest", help="Generate weekly digest (compare two graphs)")
    dg.add_argument("input_file", help="Path to current context JSON (v4 or v5)")
    dg.add_argument("--previous", required=True, help="Path to previous context JSON to compare against")

    # -- viz (Phase 6) -----------------------------------------------------
    vz = sub.add_parser("viz", help="Render graph visualization")
    vz.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    vz.add_argument("--output", "-o", default="graph.html", help="Output file path (default: graph.html)")
    vz.add_argument(
        "--format",
        "-f",
        dest="viz_format",
        choices=["html", "svg"],
        default="html",
        help="Output format (default: html)",
    )
    vz.add_argument("--max-nodes", type=int, default=200, help="Max nodes to render (default: 200)")
    vz.add_argument("--width", type=int, default=960, help="Width in pixels")
    vz.add_argument("--height", type=int, default=720, help="Height in pixels")
    vz.add_argument("--iterations", type=int, default=50, help="Layout iterations (default: 50)")
    vz.add_argument("--no-open", action="store_true", help="Don't open in browser after rendering")

    # -- watch (Phase 6) ---------------------------------------------------
    wa = sub.add_parser("watch", help="Monitor directory for new exports")
    wa.add_argument("watch_dir", help="Directory to monitor for export files")
    wa.add_argument("--graph", "-g", required=True, help="Path to context.json to update")
    wa.add_argument("--interval", type=int, default=30, help="Poll interval in seconds (default: 30)")

    # -- sync-schedule (Phase 6) -------------------------------------------
    ss = sub.add_parser("sync-schedule", help="Run periodic platform sync")
    ss.add_argument("--config", "-c", required=True, help="Path to sync config JSON")
    ss.add_argument("--once", action="store_true", help="Run all syncs once and exit")

    # -- extract-coding (Phase 7) ------------------------------------------
    ec = sub.add_parser("extract-coding", help="Extract identity from coding sessions")
    ec.add_argument("input_file", nargs="?", help="Path to Claude Code session JSONL (omit for --discover)")
    ec.add_argument("--discover", action="store_true", help="Auto-discover Claude Code sessions from ~/.claude/")
    ec.add_argument("--project", "-p", help="Filter discovered sessions by project name substring")
    ec.add_argument("--limit", "-n", type=int, default=10, help="Max sessions to process (default: 10)")
    ec.add_argument("--output", "-o", help="Output JSON path")
    ec.add_argument("--merge", "-m", help="Existing context file to merge results into")
    ec.add_argument("--verbose", "-v", action="store_true")
    ec.add_argument("--stats", action="store_true", help="Print session statistics")
    ec.add_argument("--enrich", action="store_true", help="Read project files (README, manifests) to enrich extraction")
    ec.add_argument(
        "--watch", "-w", action="store_true", help="Watch for new/modified sessions and continuously extract"
    )
    ec.add_argument("--interval", type=int, default=10, help="Watch poll interval in seconds (default: 10)")
    ec.add_argument(
        "--settle", type=float, default=5.0, help="Debounce: seconds to wait after last file write (default: 5)"
    )
    ec.add_argument(
        "--context-refresh",
        nargs="*",
        default=None,
        help="Auto-refresh context for platforms on update (e.g., --context-refresh claude-code cursor)",
    )
    ec.add_argument(
        "--context-policy",
        default=None,
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy for context refresh",
    )

    # -- context-hook (auto-inject) -------------------------------------------
    ch = sub.add_parser("context-hook", help="Install/manage Cortex context hook for Claude Code")
    ch.add_argument("action", choices=["install", "uninstall", "test", "status"], help="Hook action to perform")
    ch.add_argument("graph_file", nargs="?", help="Path to Cortex graph JSON (required for install)")
    ch.add_argument(
        "--policy",
        default="technical",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy (default: technical)",
    )
    ch.add_argument("--max-chars", type=int, default=1500, help="Max characters for injected context (default: 1500)")

    # -- context-export (one-shot compact export) ------------------------------
    ce = sub.add_parser("context-export", help="Export compact context markdown to stdout")
    ce.add_argument("input_file", help="Path to Cortex graph JSON")
    ce.add_argument(
        "--policy",
        default="technical",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy (default: technical)",
    )
    ce.add_argument("--max-chars", type=int, default=1500, help="Max characters (default: 1500)")

    # -- context-write (cross-platform context files) -------------------------
    cw = sub.add_parser("context-write", help="Write identity context to AI coding tool config files")
    cw.add_argument("input_file", help="Path to Cortex graph JSON")
    cw.add_argument(
        "--platforms",
        "-p",
        nargs="+",
        default=["claude-code"],
        help="Target platforms: claude-code, claude-code-project, codex, cursor, "
        "copilot, windsurf, gemini or gemini-cli, or 'all' (default: claude-code)",
    )
    cw.add_argument("--project", "-d", help="Project directory for per-project files (default: cwd)")
    cw.add_argument(
        "--policy",
        default=None,
        choices=list(BUILTIN_POLICIES.keys()),
        help="Override disclosure policy for all platforms",
    )
    cw.add_argument("--max-chars", type=int, default=1500, help="Max characters per context (default: 1500)")
    cw.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    cw.add_argument("--watch", action="store_true", help="Watch graph file and auto-refresh on change")
    cw.add_argument("--interval", type=int, default=30, help="Watch poll interval in seconds (default: 30)")

    # -- portable (one-command cross-tool context) -------------------------
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
        choices=list(BUILTIN_POLICIES.keys()),
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
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy when propagating remembered context",
    )
    rem.add_argument("--max-chars", type=int, default=1500, help="Max characters per written context file")
    rem.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    rem.add_argument("--format", choices=["json", "text"], default="text")

    sts = sub.add_parser(
        "status",
        help="Operational command to inspect stale or missing runtime context",
        description="Operational command to inspect stale or missing runtime context.",
    )
    sts.add_argument("--store-dir", default=".cortex", help="Portability state directory (default: .cortex)")
    sts.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    sts.add_argument("--format", choices=["json", "text"], default="text")

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
        choices=list(BUILTIN_POLICIES.keys()),
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

    # -- mind (top-level portable minds) ----------------------------------
    mind = sub.add_parser(
        "mind",
        help="Manage Cortex Minds: portable, versioned, composable agent minds",
        description="Manage Cortex Minds: durable identity, memory, composition, and mounts.",
        epilog=MIND_HELP_EPILOG,
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
        choices=list(BUILTIN_POLICIES.keys()),
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
        choices=[""] + list(BUILTIN_POLICIES.keys()),
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

    mind_mount = mind_sub.add_parser("mount", help="Mount a Cortex Mind into supported runtimes and tools")
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
        choices=[""] + list(BUILTIN_POLICIES.keys()),
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

    # -- pack (Brainpacks) -------------------------------------------------
    pk = sub.add_parser(
        "pack",
        help="Manage Brainpacks: portable, mountable domain minds",
        description="Manage Brainpacks: reusable specialist knowledge that can attach to a Mind.",
        epilog=PACK_HELP_EPILOG,
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
    pk_compile.add_argument("--format", choices=["json", "text"], default="text")

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
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy when smart routing is disabled",
    )
    pk_context.add_argument("--max-chars", type=int, default=1500, help="Max characters in the rendered context")
    pk_context.add_argument("--format", choices=["json", "text"], default="text")

    pk_mount = pk_sub.add_parser("mount", help="Mount a compiled Brainpack directly into AI runtimes and tools")
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
        choices=list(BUILTIN_POLICIES.keys()),
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

    # -- ui (local web interface) -----------------------------------------
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
    _add_runtime_security_args(ui)
    ui.add_argument("--open", action="store_true", help="Open the UI in your browser automatically")
    ui.add_argument("--check", action="store_true", help="Print startup diagnostics and exit")
    ui.add_argument("--format", choices=["json", "text"], default="text")

    # -- openapi (contract export) ----------------------------------------
    oa = sub.add_parser("openapi", help="Write the Cortex OpenAPI contract")
    oa.add_argument("--output", "-o", default="openapi/cortex-api-v1.json", help="Output path for the OpenAPI JSON")
    oa.add_argument("--server-url", help="Optional server URL to include in the contract")
    oa.add_argument("--compat-output", help="Optional output path for the API compatibility snapshot JSON")

    # -- release-notes (release metadata export) --------------------------
    rn = sub.add_parser("release-notes", help="Write release notes and a release manifest")
    rn.add_argument("--output", "-o", default="dist/release-notes.md", help="Output path for the Markdown notes")
    rn.add_argument(
        "--manifest-output",
        default="dist/release-manifest.json",
        help="Output path for the JSON release manifest",
    )
    rn.add_argument("--tag", help="Optional git tag or release label to include in the notes")
    rn.add_argument("--commit-sha", help="Optional commit SHA to include in the notes")

    # -- benchmark (release soak harness) ---------------------------------
    bench = sub.add_parser("benchmark", help="Run the lightweight self-host benchmark harness")
    bench.add_argument(
        "--store-dir", default=".cortex-bench", help="Benchmark store directory (default: .cortex-bench)"
    )
    bench.add_argument("--iterations", type=int, default=3, help="Number of benchmark iterations (default: 3)")
    bench.add_argument("--nodes", type=int, default=24, help="Nodes per generated graph (default: 24)")
    bench.add_argument("--output", "-o", help="Optional JSON output path")

    # -- server (local REST API) -----------------------------------------
    srv = sub.add_parser(
        "server",
        help="Compatibility alias for `cortex serve api`",
        description="Compatibility alias for `cortex serve api`.",
    )
    srv.add_argument("--store-dir", default=None, help="Storage directory (default from config or .cortex)")
    srv.add_argument("--context-file", help="Optional default context graph file")
    srv.add_argument("--host", default=None, help="Bind host (default from config or 127.0.0.1)")
    srv.add_argument("--port", type=int, default=None, help="Bind port (default from config or 8766)")
    _add_runtime_security_args(srv)
    srv.add_argument("--api-key", help="Optional API key required for requests")
    srv.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    srv.add_argument("--check", action="store_true", help="Print startup diagnostics and exit")
    srv.add_argument("--format", choices=["json", "text"], default="text")

    # -- mcp (local Model Context Protocol server) -----------------------
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

    # -- backup (export / verify / restore) ------------------------------
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

    # -- pull (import from platform export) --------------------------------
    pl = sub.add_parser("pull", help="Import a platform export file back into a graph")
    pl.add_argument("input_file", help="Path to platform export file (.json, .md, .html)")
    pl.add_argument(
        "--from",
        dest="from_platform",
        required=True,
        choices=["notion", "gdocs", "claude", "system-prompt"],
        help="Source platform adapter",
    )
    pl.add_argument("--output", "-o", default=None, help="Output graph JSON path (default: <input>_graph.json)")

    # -- completion (shell autocomplete) ------------------------------------
    cp = sub.add_parser("completion", help="Generate shell completion script")
    cp.add_argument(
        "--shell", "-s", required=True, choices=["bash", "zsh", "fish"], help="Shell type (bash, zsh, fish)"
    )

    # -- rotate (key rotation) ---------------------------------------------
    ro = sub.add_parser("rotate", help="Rotate UPAI identity key")
    ro.add_argument("--store-dir", default=".cortex", help="Identity store directory (default: .cortex)")
    ro.add_argument(
        "--reason",
        default="rotated",
        choices=["rotated", "compromised", "expired"],
        help="Rotation reason (default: rotated)",
    )

    return parser


__all__ = [
    "ADVANCED_HELP_NOTE",
    "CONNECT_RUNTIME_TARGETS",
    "FIRST_CLASS_COMMANDS",
    "GOVERNANCE_ACTION_CHOICES",
    "PLATFORM_FORMATS",
    "build_parser",
]
