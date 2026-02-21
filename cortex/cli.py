#!/usr/bin/env python3
"""
Cortex CLI — unified migration tool: extract + import in a single command.

Usage:
    cortex chatgpt-export.zip --to claude
    cortex extract chatgpt-export.zip -o context.json
    cortex import context.json --to notion -o ./output
"""

import argparse
import json
import sys
from pathlib import Path

from cortex.adapters import ADAPTERS
from cortex.compat import upgrade_v4_to_v5
from cortex.contradictions import ContradictionEngine
from cortex.extract_memory import (
    AggressiveExtractor,
    PIIRedactor,
    load_file,
    merge_contexts,
)
from cortex.graph import CortexGraph
from cortex.import_memory import (
    CONFIDENCE_THRESHOLDS,
    NormalizedContext,
    export_claude_memories,
    export_claude_preferences,
    export_full_json,
    export_google_docs,
    export_notion,
    export_notion_database_json,
    export_summary,
    export_system_prompt,
)
from cortex.temporal import drift_score
from cortex.timeline import TimelineGenerator
from cortex.upai.disclosure import BUILTIN_POLICIES
from cortex.upai.identity import UPAIIdentity
from cortex.upai.versioning import VersionStore

# ---------------------------------------------------------------------------
# Platform → format-key mapping
# ---------------------------------------------------------------------------
PLATFORM_FORMATS = {
    "claude":        ["claude-preferences", "claude-memories"],
    "notion":        ["notion", "notion-db"],
    "gdocs":         ["gdocs"],
    "system-prompt": ["system-prompt"],
    "summary":       ["summary"],
    "full":          ["full"],
    "all": [
        "claude-preferences", "claude-memories", "system-prompt",
        "notion", "notion-db", "gdocs", "summary", "full",
    ],
}

# ---------------------------------------------------------------------------
# Export dispatch table: format-key → (export_fn, filename, is_json)
# ---------------------------------------------------------------------------
EXPORT_DISPATCH = {
    "claude-preferences": (export_claude_preferences, "claude_preferences.txt",   False),
    "claude-memories":    (export_claude_memories,     "claude_memories.json",     True),
    "system-prompt":      (export_system_prompt,       "system_prompt.txt",        False),
    "notion":             (export_notion,              "notion_page.md",           False),
    "notion-db":          (export_notion_database_json,"notion_database.json",     True),
    "gdocs":              (export_google_docs,         "google_docs.html",         False),
    "summary":            (export_summary,             "summary.md",              False),
    "full":               (export_full_json,           "full_export.json",         True),
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _run_extraction(extractor, data, fmt):
    """Route *data* through the correct extractor method and return the v4 dict."""
    if fmt == "openai":
        extractor.process_openai_export(data)
    elif fmt == "gemini":
        extractor.process_gemini_export(data)
    elif fmt == "perplexity":
        extractor.process_perplexity_export(data)
    elif fmt == "jsonl":
        extractor.process_jsonl_messages(data)
    elif fmt == "api_logs":
        extractor.process_api_logs(data)
    elif fmt == "messages":
        extractor.process_messages_list(data)
    elif fmt == "text":
        extractor.process_plain_text(data)
    else:
        if isinstance(data, list):
            extractor.process_messages_list(data)
        elif isinstance(data, dict) and "messages" in data:
            extractor.process_messages_list(data["messages"])
        else:
            extractor.process_plain_text(json.dumps(data) if not isinstance(data, str) else data)

    extractor.post_process()
    return extractor.context.export()


def _write_exports(ctx, min_conf, format_keys, output_dir, verbose=False):
    """Write the requested formats to *output_dir*. Returns list of (label, path)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for key in format_keys:
        export_fn, filename, is_json = EXPORT_DISPATCH[key]
        path = output_dir / filename
        result = export_fn(ctx, min_conf)
        if is_json:
            path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        else:
            path.write_text(result, encoding="utf-8")
        outputs.append((key, path))
        if verbose:
            print(f"   wrote {path}")
    return outputs


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="cortex",
        description="Cortex — unified chatbot-memory migration: extract + import in one step.",
    )
    sub = parser.add_subparsers(dest="subcommand")

    # -- migrate (default) --------------------------------------------------
    mig = sub.add_parser("migrate", help="Full pipeline: extract then import")
    mig.add_argument("input_file", help="Path to chat export file")
    mig.add_argument("--to", "-t", dest="to", default="all",
                     choices=list(PLATFORM_FORMATS.keys()),
                     help="Target platform shortcut (default: all)")
    mig.add_argument("--output", "-o", default="./output", help="Output directory")
    mig.add_argument("--input-format", "-F",
                     choices=["auto", "openai", "gemini", "perplexity",
                              "jsonl", "api_logs", "messages", "text", "generic"],
                     default="auto", help="Override input format auto-detection")
    mig.add_argument("--merge", "-m", help="Existing context file to merge with")
    mig.add_argument("--redact", action="store_true", help="Enable PII redaction")
    mig.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    mig.add_argument("--confidence", "-c",
                     choices=["high", "medium", "low", "all"], default="medium")
    mig.add_argument("--dry-run", action="store_true", help="Preview without writing")
    mig.add_argument("--verbose", "-v", action="store_true")
    mig.add_argument("--stats", action="store_true", help="Show category stats")
    mig.add_argument("--schema", choices=["v4", "v5"], default="v4",
                     help="Output schema version (default: v4)")
    mig.add_argument("--discover-edges", action="store_true",
                     help="Run smart edge extraction (pattern + co-occurrence)")
    mig.add_argument("--llm", action="store_true",
                     help="LLM-assisted edge extraction (future, stub)")

    # -- extract ------------------------------------------------------------
    ext = sub.add_parser("extract", help="Extract context from export file")
    ext.add_argument("input_file", help="Path to chat export file")
    ext.add_argument("--output", "-o", help="Output JSON path")
    ext.add_argument("--format", "-f",
                     choices=["auto", "openai", "gemini", "perplexity",
                              "jsonl", "api_logs", "messages", "text", "generic"],
                     default="auto")
    ext.add_argument("--merge", "-m", help="Existing context file to merge with")
    ext.add_argument("--redact", action="store_true")
    ext.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    ext.add_argument("--verbose", "-v", action="store_true")
    ext.add_argument("--stats", action="store_true")

    # -- import -------------------------------------------------------------
    imp = sub.add_parser("import", help="Import context to platform formats")
    imp.add_argument("input_file", help="Path to context JSON file")
    imp.add_argument("--to", "-t", dest="to", default="all",
                     choices=list(PLATFORM_FORMATS.keys()),
                     help="Target platform shortcut (default: all)")
    imp.add_argument("--output", "-o", default="./output", help="Output directory")
    imp.add_argument("--confidence", "-c",
                     choices=["high", "medium", "low", "all"], default="medium")
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--verbose", "-v", action="store_true")

    # -- query (Phase 1 + Phase 5) -----------------------------------------
    qry = sub.add_parser("query", help="Query a context/graph file")
    qry.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    qry.add_argument("--node", help="Look up a node by label")
    qry.add_argument("--neighbors", help="Get neighbors of a node by label")
    qry.add_argument("--category", help="List nodes by tag/category")
    qry.add_argument("--path", nargs=2, metavar=("FROM", "TO"),
                     help="Find shortest path between two labels")
    qry.add_argument("--changed-since", help="Show nodes changed since ISO date")
    qry.add_argument("--strongest", type=int, metavar="N",
                     help="Top N nodes by confidence")
    qry.add_argument("--weakest", type=int, metavar="N",
                     help="Bottom N nodes by confidence")
    qry.add_argument("--isolated", action="store_true",
                     help="List nodes with zero edges")
    qry.add_argument("--related", nargs="?", const="", metavar="LABEL",
                     help="Nodes related to LABEL (default depth=2)")
    qry.add_argument("--related-depth", type=int, default=2,
                     help="Depth for --related traversal (default: 2)")
    qry.add_argument("--components", action="store_true",
                     help="Show connected components")
    qry.add_argument("--nl", metavar="QUERY",
                     help="Natural-language query (limited patterns)")

    # -- stats (Phase 1) ---------------------------------------------------
    st = sub.add_parser("stats", help="Show graph/context statistics")
    st.add_argument("input_file", help="Path to context JSON (v4 or v5)")

    # -- timeline (Phase 2) ------------------------------------------------
    tl = sub.add_parser("timeline", help="Generate timeline from context/graph")
    tl.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    tl.add_argument("--from", dest="from_date", help="Start date (ISO-8601)")
    tl.add_argument("--to", dest="to_date", help="End date (ISO-8601)")
    tl.add_argument("--format", "-f", dest="output_format",
                    choices=["md", "html"], default="md",
                    help="Output format (default: md)")

    # -- contradictions (Phase 2) ------------------------------------------
    ct = sub.add_parser("contradictions", help="Detect contradictions in context/graph")
    ct.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    ct.add_argument("--severity", type=float, default=0.0,
                    help="Minimum severity threshold (0.0-1.0)")
    ct.add_argument("--type", dest="contradiction_type",
                    choices=["negation_conflict", "temporal_flip",
                             "source_conflict", "tag_conflict"],
                    help="Filter by contradiction type")

    # -- drift (Phase 2) ---------------------------------------------------
    dr = sub.add_parser("drift", help="Compute identity drift between two graphs")
    dr.add_argument("input_file", help="Path to first context JSON (v4 or v5)")
    dr.add_argument("--compare", required=True,
                    help="Path to second context JSON to compare against")

    # -- identity (Phase 3) ------------------------------------------------
    ident = sub.add_parser("identity", help="Init/show UPAI identity")
    ident.add_argument("--init", action="store_true", help="Generate new identity")
    ident.add_argument("--name", help="Human-readable name for identity")
    ident.add_argument("--show", action="store_true", help="Show current identity")
    ident.add_argument("--store-dir", default=".cortex",
                       help="Identity store directory (default: .cortex)")
    ident.add_argument("--did-doc", action="store_true",
                       help="Output W3C DID document JSON")
    ident.add_argument("--keychain", action="store_true",
                       help="Show key rotation history and status")

    # -- commit (Phase 3) --------------------------------------------------
    cm = sub.add_parser("commit", help="Version a graph snapshot")
    cm.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    cm.add_argument("-m", "--message", required=True, help="Commit message")
    cm.add_argument("--source", default="manual",
                    help="Source label (extraction, merge, manual)")
    cm.add_argument("--store-dir", default=".cortex",
                    help="Version store directory (default: .cortex)")

    # -- log (Phase 3) -----------------------------------------------------
    lg = sub.add_parser("log", help="Show version history")
    lg.add_argument("--limit", type=int, default=10, help="Max entries to show")
    lg.add_argument("--store-dir", default=".cortex",
                    help="Version store directory (default: .cortex)")

    # -- sync (Phase 3) ----------------------------------------------------
    sy = sub.add_parser("sync", help="Disclosure-filtered export via platform adapters")
    sy.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    sy.add_argument("--to", "-t", required=True,
                    choices=list(ADAPTERS.keys()),
                    help="Target platform adapter")
    sy.add_argument("--policy", "-p", default="full",
                    choices=list(BUILTIN_POLICIES.keys()),
                    help="Disclosure policy (default: full)")
    sy.add_argument("--output", "-o", default="./output",
                    help="Output directory")
    sy.add_argument("--store-dir", default=".cortex",
                    help="Identity store directory (default: .cortex)")

    # -- verify (Phase 3) --------------------------------------------------
    vr = sub.add_parser("verify", help="Verify a signed export")
    vr.add_argument("input_file", help="Path to signed export file")

    # -- gaps (Phase 5) ----------------------------------------------------
    gp = sub.add_parser("gaps", help="Analyze gaps in knowledge graph")
    gp.add_argument("input_file", help="Path to context JSON (v4 or v5)")

    # -- digest (Phase 5) --------------------------------------------------
    dg = sub.add_parser("digest", help="Generate weekly digest (compare two graphs)")
    dg.add_argument("input_file", help="Path to current context JSON (v4 or v5)")
    dg.add_argument("--previous", required=True,
                    help="Path to previous context JSON to compare against")

    # -- viz (Phase 6) -----------------------------------------------------
    vz = sub.add_parser("viz", help="Render graph visualization")
    vz.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    vz.add_argument("--output", "-o", default="graph.html",
                    help="Output file path (default: graph.html)")
    vz.add_argument("--format", "-f", dest="viz_format",
                    choices=["html", "svg"], default="html",
                    help="Output format (default: html)")
    vz.add_argument("--max-nodes", type=int, default=200,
                    help="Max nodes to render (default: 200)")
    vz.add_argument("--width", type=int, default=960, help="Width in pixels")
    vz.add_argument("--height", type=int, default=720, help="Height in pixels")
    vz.add_argument("--iterations", type=int, default=50,
                    help="Layout iterations (default: 50)")
    vz.add_argument("--no-open", action="store_true",
                    help="Don't open in browser after rendering")

    # -- dashboard (Phase 6) -----------------------------------------------
    db = sub.add_parser("dashboard", help="Launch local dashboard")
    db.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    db.add_argument("--port", "-p", type=int, default=8420,
                    help="Server port (default: 8420)")
    db.add_argument("--no-open", action="store_true",
                    help="Don't open browser automatically")

    # -- watch (Phase 6) ---------------------------------------------------
    wa = sub.add_parser("watch", help="Monitor directory for new exports")
    wa.add_argument("watch_dir", help="Directory to monitor for export files")
    wa.add_argument("--graph", "-g", required=True,
                    help="Path to context.json to update")
    wa.add_argument("--interval", type=int, default=30,
                    help="Poll interval in seconds (default: 30)")

    # -- sync-schedule (Phase 6) -------------------------------------------
    ss = sub.add_parser("sync-schedule", help="Run periodic platform sync")
    ss.add_argument("--config", "-c", required=True,
                    help="Path to sync config JSON")
    ss.add_argument("--once", action="store_true",
                    help="Run all syncs once and exit")

    # -- extract-coding (Phase 7) ------------------------------------------
    ec = sub.add_parser("extract-coding",
                        help="Extract identity from coding sessions")
    ec.add_argument("input_file", nargs="?",
                    help="Path to Claude Code session JSONL (omit for --discover)")
    ec.add_argument("--discover", action="store_true",
                    help="Auto-discover Claude Code sessions from ~/.claude/")
    ec.add_argument("--project", "-p",
                    help="Filter discovered sessions by project name substring")
    ec.add_argument("--limit", "-n", type=int, default=10,
                    help="Max sessions to process (default: 10)")
    ec.add_argument("--output", "-o", help="Output JSON path")
    ec.add_argument("--merge", "-m",
                    help="Existing context file to merge results into")
    ec.add_argument("--verbose", "-v", action="store_true")
    ec.add_argument("--stats", action="store_true",
                    help="Print session statistics")
    ec.add_argument("--enrich", action="store_true",
                    help="Read project files (README, manifests) to enrich extraction")
    ec.add_argument("--watch", "-w", action="store_true",
                    help="Watch for new/modified sessions and continuously extract")
    ec.add_argument("--interval", type=int, default=10,
                    help="Watch poll interval in seconds (default: 10)")
    ec.add_argument("--settle", type=float, default=5.0,
                    help="Debounce: seconds to wait after last file write (default: 5)")
    ec.add_argument("--context-refresh", nargs="*", default=None,
                    help="Auto-refresh context for platforms on update "
                         "(e.g., --context-refresh claude-code cursor)")
    ec.add_argument("--context-policy", default=None,
                    choices=list(BUILTIN_POLICIES.keys()),
                    help="Disclosure policy for context refresh")

    # -- context-hook (auto-inject) -------------------------------------------
    ch = sub.add_parser("context-hook",
                        help="Install/manage Cortex context hook for Claude Code")
    ch.add_argument("action", choices=["install", "uninstall", "test", "status"],
                    help="Hook action to perform")
    ch.add_argument("graph_file", nargs="?",
                    help="Path to Cortex graph JSON (required for install)")
    ch.add_argument("--policy", default="technical",
                    choices=list(BUILTIN_POLICIES.keys()),
                    help="Disclosure policy (default: technical)")
    ch.add_argument("--max-chars", type=int, default=1500,
                    help="Max characters for injected context (default: 1500)")

    # -- context-export (one-shot compact export) ------------------------------
    ce = sub.add_parser("context-export",
                        help="Export compact context markdown to stdout")
    ce.add_argument("input_file", help="Path to Cortex graph JSON")
    ce.add_argument("--policy", default="technical",
                    choices=list(BUILTIN_POLICIES.keys()),
                    help="Disclosure policy (default: technical)")
    ce.add_argument("--max-chars", type=int, default=1500,
                    help="Max characters (default: 1500)")

    # -- context-write (cross-platform context files) -------------------------
    cw = sub.add_parser("context-write",
                        help="Write identity context to AI coding tool config files")
    cw.add_argument("input_file", help="Path to Cortex graph JSON")
    cw.add_argument("--platforms", "-p", nargs="+", default=["claude-code"],
                    help="Target platforms: claude-code, claude-code-project, cursor, "
                         "copilot, windsurf, gemini-cli, or 'all' (default: claude-code)")
    cw.add_argument("--project", "-d",
                    help="Project directory for per-project files (default: cwd)")
    cw.add_argument("--policy", default=None,
                    choices=list(BUILTIN_POLICIES.keys()),
                    help="Override disclosure policy for all platforms")
    cw.add_argument("--max-chars", type=int, default=1500,
                    help="Max characters per context (default: 1500)")
    cw.add_argument("--dry-run", action="store_true",
                    help="Preview without writing files")
    cw.add_argument("--watch", action="store_true",
                    help="Watch graph file and auto-refresh on change")
    cw.add_argument("--interval", type=int, default=30,
                    help="Watch poll interval in seconds (default: 30)")

    # -- pull (import from platform export) --------------------------------
    pl = sub.add_parser("pull", help="Import a platform export file back into a graph")
    pl.add_argument("input_file", help="Path to platform export file (.json, .md, .html)")
    pl.add_argument("--from", dest="from_platform", required=True,
                    choices=["notion", "gdocs", "claude", "system-prompt"],
                    help="Source platform adapter")
    pl.add_argument("--output", "-o", default=None,
                    help="Output graph JSON path (default: <input>_graph.json)")

    # -- serve (CaaS API) -------------------------------------------------
    sv = sub.add_parser("serve", help="Start CaaS API server")
    sv.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    sv.add_argument("--config", "-C", default=None,
                    help="Path to cortex.ini config file")
    sv.add_argument("--port", "-p", type=int, default=8421,
                    help="Server port (default: 8421)")
    sv.add_argument("--store-dir", default=".cortex",
                    help="Identity/version store directory (default: .cortex)")
    sv.add_argument("--allowed-origins", nargs="*",
                    help="CORS allowed origins")
    sv.add_argument("--storage", choices=["json", "sqlite", "postgres"], default="json",
                    help="Storage backend (default: json)")
    sv.add_argument("--db-path", default=None,
                    help="SQLite database path (default: <store-dir>/cortex.db)")
    sv.add_argument("--db-url", default=None,
                    help="PostgreSQL connection string (e.g. 'dbname=cortex_dev')")
    sv.add_argument("--oauth-provider", action="append", nargs=3,
                    metavar=("PROVIDER", "CLIENT_ID", "CLIENT_SECRET"),
                    help="Add OAuth provider (e.g. --oauth-provider google ID SECRET)")
    sv.add_argument("--oauth-allowed-email", action="append", metavar="EMAIL",
                    help="Restrict OAuth login to specific email(s)")
    sv.add_argument("--enable-sse", action="store_true",
                    help="Enable Server-Sent Events endpoint (/events)")
    sv.add_argument("--enable-metrics", action="store_true",
                    help="Enable Prometheus metrics endpoint (/metrics)")
    sv.add_argument("--pool-size", type=int, default=None, metavar="N",
                    help="PostgreSQL connection pool max size (default: 10)")
    sv.add_argument("--plugins", nargs="*", default=None, metavar="MODULE",
                    help="Plugin modules to load (e.g. cortex.plugins.example_logger)")
    sv.add_argument("--enable-tracing", action="store_true",
                    help="Enable distributed tracing (console exporter)")
    sv.add_argument("--tracing-exporter", choices=["console", "otlp_http", "noop"],
                    default="console", help="Tracing exporter (default: console)")
    sv.add_argument("--enable-federation", action="store_true",
                    help="Enable federation endpoints (/federation/*)")
    sv.add_argument("--federation-trusted-did", action="append", metavar="DID",
                    help="Add a trusted federation peer DID (repeatable)")
    sv.add_argument("--enable-webapp", action="store_true",
                    help="Enable web UI at /app (Upload, Memory, Share)")

    # -- grant (manage CaaS grants) ----------------------------------------
    gr = sub.add_parser("grant", help="Manage CaaS grant tokens")
    gr.add_argument("--create", action="store_true", help="Create a new grant")
    gr.add_argument("--list", action="store_true", dest="list_grants",
                    help="List all grants")
    gr.add_argument("--revoke", metavar="GRANT_ID", help="Revoke a grant")
    gr.add_argument("--audience", help="Audience for new grant")
    gr.add_argument("--policy", default="professional",
                    choices=list(BUILTIN_POLICIES.keys()),
                    help="Disclosure policy (default: professional)")
    gr.add_argument("--ttl", type=int, default=24,
                    help="Token TTL in hours (default: 24)")
    gr.add_argument("--store-dir", default=".cortex",
                    help="Identity store directory (default: .cortex)")
    gr.add_argument("--storage", choices=["json", "sqlite", "postgres"], default="json",
                    help="Grant storage backend (default: json)")
    gr.add_argument("--db-path", default=None,
                    help="SQLite database path (default: <store-dir>/cortex.db)")
    gr.add_argument("--db-url", default=None,
                    help="PostgreSQL connection string (e.g. 'dbname=cortex_dev')")

    # -- policy (custom disclosure policies) --------------------------------
    po = sub.add_parser("policy", help="Manage custom disclosure policies")
    po.add_argument("--list", action="store_true", dest="list_policies",
                    help="List all policies")
    po.add_argument("--create", action="store_true", help="Create a new policy")
    po.add_argument("--show", metavar="NAME", help="Show policy details")
    po.add_argument("--delete", metavar="NAME", help="Delete a custom policy")
    po.add_argument("--name", help="Policy name for --create")
    po.add_argument("--include-tags", help="Comma-separated include tags")
    po.add_argument("--exclude-tags", help="Comma-separated exclude tags")
    po.add_argument("--min-confidence", type=float, default=0.0,
                    help="Minimum confidence threshold")
    po.add_argument("--redact-properties", help="Comma-separated property keys to redact")
    po.add_argument("--max-nodes", type=int, default=0,
                    help="Max nodes (0 = unlimited)")
    po.add_argument("--store-dir", default=".cortex",
                    help="Identity store directory (default: .cortex)")

    # -- completion (shell autocomplete) ------------------------------------
    cp = sub.add_parser("completion", help="Generate shell completion script")
    cp.add_argument("--shell", "-s", required=True,
                    choices=["bash", "zsh", "fish"],
                    help="Shell type (bash, zsh, fish)")

    # -- rotate (key rotation) ---------------------------------------------
    ro = sub.add_parser("rotate", help="Rotate UPAI identity key")
    ro.add_argument("--store-dir", default=".cortex",
                    help="Identity store directory (default: .cortex)")
    ro.add_argument("--reason", default="rotated",
                    choices=["rotated", "compromised", "expired"],
                    help="Rotation reason (default: rotated)")

    return parser


# ---------------------------------------------------------------------------
# Subcommand runners
# ---------------------------------------------------------------------------

def run_extract(args):
    """Extract context from an export file and save as JSON."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    print(f"Loading: {input_path}")
    try:
        data, detected_format = load_file(input_path)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    fmt = args.format if args.format != "auto" else detected_format
    print(f"Format: {fmt}")

    # PII redactor
    redactor = None
    if args.redact:
        custom_patterns = None
        if args.redact_patterns:
            pp = Path(args.redact_patterns)
            if not pp.exists():
                print(f"Redaction patterns file not found: {pp}")
                return 1
            with open(pp, "r", encoding="utf-8") as f:
                custom_patterns = json.load(f)
        redactor = PIIRedactor(custom_patterns)
        print("PII redaction enabled")

    extractor = AggressiveExtractor(redactor=redactor)

    # Merge
    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            print(f"Merging with existing context: {merge_path}")
            extractor = merge_contexts(merge_path, extractor)
        else:
            print(f"Merge file not found: {merge_path} (proceeding without merge)")

    result = _run_extraction(extractor, data, fmt)

    stats = extractor.context.stats()
    print(f"Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    if args.stats or args.verbose:
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            print(f"   {cat}: {count}")

    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_context.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Saved to: {output_path}")
    return 0


def run_import(args):
    """Import a context JSON file and export to platform formats."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    print(f"Loading: {input_path}")
    ctx = NormalizedContext.load(input_path)
    min_conf = CONFIDENCE_THRESHOLDS[args.confidence]
    format_keys = PLATFORM_FORMATS[args.to]
    output_dir = Path(args.output)

    if args.dry_run:
        print("\nDRY RUN PREVIEW")
        for key in format_keys:
            export_fn, filename, is_json = EXPORT_DISPATCH[key]
            result = export_fn(ctx, min_conf)
            print(f"\n--- {key} ({filename}) ---")
            text = json.dumps(result, indent=2) if is_json else result
            for line in text.split("\n")[:30]:
                print(line)
        return 0

    outputs = _write_exports(ctx, min_conf, format_keys, output_dir, args.verbose)

    print(f"\nExported {len(outputs)} files to {output_dir}/:")
    for key, path in outputs:
        print(f"   {key}: {path.name}")
    return 0


def run_migrate(args):
    """Full pipeline: extract from export file, then import to platform formats."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    # --- Extract phase ---
    print(f"Loading: {input_path}")
    try:
        data, detected_format = load_file(input_path)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    fmt = args.input_format if args.input_format != "auto" else detected_format
    print(f"Format: {fmt}")

    # PII redactor
    redactor = None
    if args.redact:
        custom_patterns = None
        if args.redact_patterns:
            pp = Path(args.redact_patterns)
            if not pp.exists():
                print(f"Redaction patterns file not found: {pp}")
                return 1
            with open(pp, "r", encoding="utf-8") as f:
                custom_patterns = json.load(f)
        redactor = PIIRedactor(custom_patterns)
        print("PII redaction enabled")

    extractor = AggressiveExtractor(redactor=redactor)

    # Merge
    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            print(f"Merging with existing context: {merge_path}")
            extractor = merge_contexts(merge_path, extractor)
        else:
            print(f"Merge file not found: {merge_path} (proceeding without merge)")

    v4_data = _run_extraction(extractor, data, fmt)

    stats = extractor.context.stats()
    print(f"Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    if args.stats or args.verbose:
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            print(f"   {cat}: {count}")

    # --- Save intermediate context.json ---
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.schema == "v5":
        graph = upgrade_v4_to_v5(v4_data)

        # --- Smart edge discovery (Phase 4, opt-in) ---
        if getattr(args, "discover_edges", False):
            from cortex.centrality import apply_centrality_boost, compute_centrality
            from cortex.cooccurrence import discover_edges as discover_cooccurrence
            from cortex.dedup import deduplicate
            from cortex.edge_extraction import discover_all_edges

            messages = getattr(extractor, "all_user_text", None)

            # 1. Pattern-based + proximity edge extraction
            new_edges = discover_all_edges(graph, messages=messages)
            for edge in new_edges:
                graph.add_edge(edge)

            # 2. Co-occurrence edges (if messages available)
            cooc_count = 0
            if messages and len(messages) >= 3:
                cooc_edges = discover_cooccurrence(messages, graph)
                for edge in cooc_edges:
                    graph.add_edge(edge)
                cooc_count = len(cooc_edges)

            # 3. Graph-aware dedup
            merged = deduplicate(graph)

            # 4. Centrality boost
            scores = compute_centrality(graph)
            apply_centrality_boost(graph, scores)

            if args.verbose:
                print(f"   Smart edges: +{len(new_edges)} pattern"
                      f", +{cooc_count} co-occurrence"
                      f", {len(merged)} merges, centrality applied")

            if getattr(args, "llm", False):
                print("   --llm: LLM-assisted extraction not yet implemented (stub)")

        v5_data = graph.export_v5()
        ctx_path = output_dir / "context.json"
        with open(ctx_path, "w", encoding="utf-8") as f:
            json.dump(v5_data, f, indent=2)
        if args.verbose:
            gs = graph.stats()
            print(f"   v5 graph: {gs['node_count']} nodes, {gs['edge_count']} edges")
            print(f"   saved v5 context: {ctx_path}")
    else:
        ctx_path = output_dir / "context.json"
        with open(ctx_path, "w", encoding="utf-8") as f:
            json.dump(v4_data, f, indent=2)
        if args.verbose:
            print(f"   saved intermediate context: {ctx_path}")

    # --- Import phase (in-memory handoff) ---
    ctx = NormalizedContext.from_v4(v4_data)
    min_conf = CONFIDENCE_THRESHOLDS[args.confidence]
    format_keys = PLATFORM_FORMATS[args.to]

    if args.dry_run:
        print("\nDRY RUN PREVIEW")
        for key in format_keys:
            export_fn, filename, is_json = EXPORT_DISPATCH[key]
            result = export_fn(ctx, min_conf)
            print(f"\n--- {key} ({filename}) ---")
            text = json.dumps(result, indent=2) if is_json else result
            for line in text.split("\n")[:30]:
                print(line)
        return 0

    outputs = _write_exports(ctx, min_conf, format_keys, output_dir, args.verbose)

    print(f"\nExported {len(outputs) + 1} files to {output_dir}/:")
    print("   context: context.json")
    for key, path in outputs:
        print(f"   {key}: {path.name}")
    return 0


def run_query(args):
    """Query nodes/neighbors in a context file."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    graph = _load_graph(input_path)

    # --- Phase 1 queries (--node, --neighbors) ---
    if args.node:
        nodes = graph.find_nodes(label=args.node)
        if not nodes:
            print(f"No node found with label '{args.node}'")
            return 0
        for node in nodes:
            print(f"Node: {node.label} (id={node.id})")
            print(f"  Tags: {', '.join(node.tags)}")
            print(f"  Confidence: {node.confidence:.2f}")
            print(f"  Mentions: {node.mention_count}")
            if node.brief:
                print(f"  Brief: {node.brief}")
            if node.full_description:
                print(f"  Description: {node.full_description}")
        return 0

    if args.neighbors:
        nodes = graph.find_nodes(label=args.neighbors)
        if not nodes:
            print(f"No node found with label '{args.neighbors}'")
            return 0
        node = nodes[0]
        neighbors = graph.get_neighbors(node.id)
        if not neighbors:
            print(f"No neighbors for '{node.label}'")
            return 0
        print(f"Neighbors of '{node.label}':")
        for edge, neighbor in neighbors:
            print(f"  --[{edge.relation}]--> {neighbor.label} (conf={neighbor.confidence:.2f})")
        return 0

    # --- Phase 5 queries (QueryEngine) ---
    from cortex.intelligence import GapAnalyzer
    from cortex.query import (
        QueryEngine,
        connected_components,
        parse_nl_query,
    )

    engine = QueryEngine(graph)

    if args.category:
        nodes = engine.query_category(args.category)
        if not nodes:
            print(f"No nodes with tag '{args.category}'")
            return 0
        print(f"Nodes tagged '{args.category}' ({len(nodes)}):")
        for node in nodes:
            print(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.path:
        from_label, to_label = args.path
        paths = engine.query_path(from_label, to_label)
        if not paths:
            print(f"No path from '{from_label}' to '{to_label}'")
            return 0
        print(f"Path from '{from_label}' to '{to_label}':")
        for node in paths[0]:
            print(f"  -> {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.changed_since:
        result = engine.query_changed(args.changed_since)
        print(f"Changes since {result['since']}: {result['total_changed']} total")
        if result["new_nodes"]:
            print(f"\nNew ({len(result['new_nodes'])}):")
            for n in result["new_nodes"]:
                print(f"  + {n['label']} (conf={n['confidence']:.2f})")
        if result["updated_nodes"]:
            print(f"\nUpdated ({len(result['updated_nodes'])}):")
            for n in result["updated_nodes"]:
                print(f"  ~ {n['label']} (conf={n['confidence']:.2f})")
        return 0

    if args.strongest:
        nodes = engine.query_strongest(args.strongest)
        print(f"Top {len(nodes)} by confidence:")
        for node in nodes:
            print(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.weakest:
        nodes = engine.query_weakest(args.weakest)
        print(f"Bottom {len(nodes)} by confidence:")
        for node in nodes:
            print(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.isolated:
        analyzer = GapAnalyzer()
        isolated = analyzer.isolated_nodes(graph)
        if not isolated:
            print("No isolated nodes.")
            return 0
        print(f"Isolated nodes ({len(isolated)}):")
        for node in isolated:
            print(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.related is not None:
        if not args.related:
            print("Specify a label: --related <LABEL>")
            return 1
        nodes = engine.query_related(args.related, depth=args.related_depth)
        if not nodes:
            print(f"No related nodes for '{args.related}'")
            return 0
        print(f"Related to '{args.related}' (depth={args.related_depth}):")
        for node in nodes:
            print(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.components:
        comps = connected_components(graph)
        if not comps:
            print("No components (empty graph).")
            return 0
        print(f"Connected components ({len(comps)}):")
        for i, comp in enumerate(comps, 1):
            labels = sorted(graph.get_node(nid).label for nid in comp if graph.get_node(nid))
            print(f"  {i}. [{len(comp)} nodes] {', '.join(labels[:10])}"
                  f"{'...' if len(labels) > 10 else ''}")
        return 0

    if args.nl:
        result = parse_nl_query(args.nl, engine)
        print(json.dumps(result, indent=2, default=str))
        return 0

    print("Specify a query flag: --node, --neighbors, --category, --path, "
          "--changed-since, --strongest, --weakest, --isolated, --related, "
          "--components, --nl")
    return 1


def _load_graph(input_path: Path) -> CortexGraph:
    """Load a v4, v5, or v6 JSON file and return a CortexGraph."""
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {input_path}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except OSError as exc:
        print(f"Error: cannot read {input_path}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    version = data.get("schema_version", "")
    if version.startswith("5") or version.startswith("6"):
        return CortexGraph.from_v5_json(data)
    return upgrade_v4_to_v5(data)


def run_timeline(args):
    """Generate a timeline from a context/graph file."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    graph = _load_graph(input_path)
    gen = TimelineGenerator()
    events = gen.generate(graph, from_date=args.from_date, to_date=args.to_date)

    if args.output_format == "html":
        print(gen.to_html(events))
    else:
        print(gen.to_markdown(events))
    return 0


def run_contradictions(args):
    """Detect contradictions in a context/graph file."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    graph = _load_graph(input_path)
    engine = ContradictionEngine()
    contradictions = engine.detect_all(graph, min_severity=args.severity)

    if args.contradiction_type:
        contradictions = [c for c in contradictions if c.type == args.contradiction_type]

    if not contradictions:
        print("No contradictions detected.")
        return 0

    print(f"Found {len(contradictions)} contradiction(s):\n")
    for c in contradictions:
        print(f"  [{c.type}] severity={c.severity:.2f}")
        print(f"    {c.description}")
        print(f"    Resolution: {c.resolution}")
        print(f"    Nodes: {', '.join(c.node_ids)}")
        print()
    return 0


def run_drift(args):
    """Compute identity drift between two graph files."""
    input_path = Path(args.input_file)
    compare_path = Path(args.compare)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    if not compare_path.exists():
        print(f"File not found: {compare_path}")
        return 1

    graph_a = _load_graph(input_path)
    graph_b = _load_graph(compare_path)
    result = drift_score(graph_a, graph_b)

    if not result["sufficient_data"]:
        print("Insufficient data for drift analysis.")
        print(f"  Graph A: {result['details']['node_count_a']} nodes")
        print(f"  Graph B: {result['details']['node_count_b']} nodes")
        print("  Need at least 3 nodes in each graph.")
        return 0

    print(f"Identity Drift Score: {result['score']:.4f}")
    print(f"  Label drift:      {result['details']['label_drift']:.4f}")
    print(f"  Tag drift:        {result['details']['tag_drift']:.4f}")
    print(f"  Confidence drift: {result['details']['confidence_drift']:.4f}")
    print(f"  Graph A: {result['details']['node_count_a']} nodes")
    print(f"  Graph B: {result['details']['node_count_b']} nodes")
    return 0


def run_identity(args):
    """Init or show UPAI identity."""
    store_dir = Path(args.store_dir)

    if args.init:
        name = args.name or "Anonymous"
        identity = UPAIIdentity.generate(name)
        identity.save(store_dir)
        print(f"Identity created: {identity.did}")
        print(f"  Name: {identity.name}")
        print(f"  Created: {identity.created_at}")
        print(f"  Stored in: {store_dir}")
        return 0

    if args.show:
        id_path = store_dir / "identity.json"
        if not id_path.exists():
            print(f"No identity found in {store_dir}. Use --init to create one.")
            return 1
        identity = UPAIIdentity.load(store_dir)
        print(f"DID: {identity.did}")
        print(f"Name: {identity.name}")
        print(f"Created: {identity.created_at}")
        print(f"Public Key: {identity.public_key_b64[:32]}...")
        return 0

    if getattr(args, "did_doc", False):
        id_path = store_dir / "identity.json"
        if not id_path.exists():
            print(f"No identity found in {store_dir}. Use --init to create one.")
            return 1
        identity = UPAIIdentity.load(store_dir)
        doc = identity.to_did_document()
        print(json.dumps(doc, indent=2))
        return 0

    if getattr(args, "keychain", False):
        from cortex.upai.keychain import Keychain
        id_path = store_dir / "identity.json"
        if not id_path.exists():
            print(f"No identity found in {store_dir}. Use --init to create one.")
            return 1
        kc = Keychain(store_dir)
        history = kc.get_history()
        if not history:
            print("No key history found.")
            return 0
        errors = kc.verify_rotation_chain()
        chain_status = "VALID" if not errors else "INVALID"
        print(f"Key Rotation History (chain: {chain_status}):")
        for record in history:
            if record.revoked_at:
                status = f"REVOKED ({record.revocation_reason})"
                date_info = f"created={record.created_at}, revoked={record.revoked_at}"
            else:
                status = "ACTIVE"
                date_info = f"created={record.created_at}"
            print(f"  {record.did[:32]}... | {status} | {date_info}")
        if errors:
            print("\nChain errors:")
            for err in errors:
                print(f"  - {err}")
        return 0

    print("Specify --init, --show, --did-doc, or --keychain")
    return 1


def run_commit(args):
    """Version a graph snapshot."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    graph = _load_graph(input_path)
    store_dir = Path(args.store_dir)

    # Load identity if available
    identity = None
    id_path = store_dir / "identity.json"
    if id_path.exists():
        identity = UPAIIdentity.load(store_dir)

    store = VersionStore(store_dir)
    version = store.commit(graph, args.message, source=args.source, identity=identity)

    print(f"Committed: {version.version_id}")
    print(f"  Message: {version.message}")
    print(f"  Source: {version.source}")
    print(f"  Nodes: {version.node_count}, Edges: {version.edge_count}")
    if version.parent_id:
        print(f"  Parent: {version.parent_id}")
    if version.signature:
        print("  Signed: yes")
    return 0


def run_log(args):
    """Show version history."""
    store_dir = Path(args.store_dir)
    store = VersionStore(store_dir)
    versions = store.log(limit=args.limit)

    if not versions:
        print("No version history found.")
        return 0

    for v in versions:
        print(f"  {v.version_id}  {v.timestamp}  [{v.source}]")
        print(f"    {v.message}")
        print(f"    nodes={v.node_count} edges={v.edge_count}", end="")
        if v.signature:
            print("  signed", end="")
        print()
    return 0


def run_sync(args):
    """Disclosure-filtered export via platform adapters."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    graph = _load_graph(input_path)
    adapter = ADAPTERS[args.to]
    policy = BUILTIN_POLICIES[args.policy]
    output_dir = Path(args.output)

    # Load identity if available
    identity = None
    store_dir = Path(args.store_dir)
    id_path = store_dir / "identity.json"
    if id_path.exists():
        identity = UPAIIdentity.load(store_dir)

    paths = adapter.push(graph, policy, identity=identity, output_dir=output_dir)

    print(f"Synced to {args.to} with policy '{args.policy}':")
    for p in paths:
        print(f"  {p}")
    return 0


def run_verify(args):
    """Verify a signed export file."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in {input_path}: {e}")
        return 1

    if not isinstance(data, dict) or "upai_identity" not in data:
        print("Not a UPAI-signed file (no upai_identity block).")
        return 1

    # Check integrity hash
    payload = json.dumps(data["data"], sort_keys=True, ensure_ascii=False).encode("utf-8")
    import hashlib
    computed_hash = hashlib.sha256(payload).hexdigest()
    stored_hash = data.get("integrity_hash", "")

    if computed_hash == stored_hash:
        print("Integrity: PASS (SHA-256 matches)")
    else:
        print("Integrity: FAIL (SHA-256 mismatch)")
        return 1

    # Attempt signature verification
    pub_key = data["upai_identity"].get("public_key_b64", "")
    sig = data.get("signature", "")
    did = data["upai_identity"].get("did", "")

    if did.startswith("did:upai:ed25519:") and sig:
        result = UPAIIdentity.verify(payload, sig, pub_key)
        if result:
            print("Signature: PASS (Ed25519 verified)")
        else:
            print("Signature: FAIL (Ed25519 verification failed)")
            return 1
    elif sig:
        print("Signature: HMAC (requires local secret for verification)")
    else:
        print("Signature: none")

    print(f"Identity: {did}")
    print(f"Name: {data['upai_identity'].get('name', 'unknown')}")
    return 0


def run_gaps(args):
    """Analyze gaps in the knowledge graph."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    from cortex.intelligence import GapAnalyzer

    graph = _load_graph(input_path)
    analyzer = GapAnalyzer()
    gaps = analyzer.all_gaps(graph)

    if gaps["category_gaps"]:
        print(f"Missing categories ({len(gaps['category_gaps'])}):")
        for g in gaps["category_gaps"]:
            print(f"  - {g['category']}")

    if gaps["confidence_gaps"]:
        print(f"\nLow-confidence priorities ({len(gaps['confidence_gaps'])}):")
        for g in gaps["confidence_gaps"]:
            print(f"  - {g['label']} (conf={g['confidence']:.2f})")

    if gaps["relationship_gaps"]:
        print(f"\nUnconnected groups ({len(gaps['relationship_gaps'])}):")
        for g in gaps["relationship_gaps"]:
            print(f"  - {g['tag']}: {g['node_count']} nodes, 0 edges")

    if gaps["isolated_nodes"]:
        print(f"\nIsolated nodes ({len(gaps['isolated_nodes'])}):")
        for g in gaps["isolated_nodes"]:
            print(f"  - {g['label']} (conf={g['confidence']:.2f})")

    if gaps["stale_nodes"]:
        print(f"\nStale nodes ({len(gaps['stale_nodes'])}):")
        for g in gaps["stale_nodes"]:
            print(f"  - {g['label']} (last seen: {g['last_seen']})")

    total = (len(gaps["category_gaps"]) + len(gaps["confidence_gaps"])
             + len(gaps["relationship_gaps"]) + len(gaps["isolated_nodes"])
             + len(gaps["stale_nodes"]))
    if total == 0:
        print("No gaps detected.")
    return 0


def run_digest(args):
    """Generate weekly digest comparing two graph snapshots."""
    input_path = Path(args.input_file)
    previous_path = Path(args.previous)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    if not previous_path.exists():
        print(f"File not found: {previous_path}")
        return 1

    from cortex.intelligence import InsightGenerator

    current = _load_graph(input_path)
    previous = _load_graph(previous_path)
    gen = InsightGenerator()
    digest = gen.digest(current=current, previous=previous)

    if digest["new_nodes"]:
        print(f"New nodes ({len(digest['new_nodes'])}):")
        for n in digest["new_nodes"]:
            print(f"  + {n['label']} (conf={n['confidence']:.2f})")

    if digest["removed_nodes"]:
        print(f"\nRemoved nodes ({len(digest['removed_nodes'])}):")
        for n in digest["removed_nodes"]:
            print(f"  - {n['label']}")

    if digest["confidence_changes"]:
        print(f"\nConfidence changes ({len(digest['confidence_changes'])}):")
        for c in digest["confidence_changes"]:
            direction = "+" if c["delta"] > 0 else ""
            print(f"  {c['label']}: {c['previous']:.2f} -> {c['current']:.2f} ({direction}{c['delta']:.2f})")

    if digest["new_edges"]:
        print(f"\nNew edges ({len(digest['new_edges'])}):")
        for e in digest["new_edges"]:
            print(f"  {e['source']} --[{e['relation']}]--> {e['target']}")

    ds = digest["drift_score"]
    if ds.get("sufficient_data"):
        print(f"\nDrift score: {ds['score']:.4f}")
    else:
        print("\nDrift score: insufficient data")

    if digest["new_contradictions"]:
        print(f"\nContradictions ({len(digest['new_contradictions'])}):")
        for c in digest["new_contradictions"]:
            print(f"  [{c['type']}] {c['description']}")

    gap_count = sum(
        len(v) for v in digest["gaps"].values() if isinstance(v, list)
    )
    print(f"\nGaps: {gap_count} total issues")
    return 0


def run_viz(args):
    """Render graph visualization as HTML or SVG."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    from cortex.viz.layout import fruchterman_reingold
    from cortex.viz.renderer import render_html, render_svg

    graph = _load_graph(input_path)

    def progress(current, total):
        print(f"\rLayout: {current}/{total}", end="", flush=True)

    layout = fruchterman_reingold(
        graph,
        iterations=args.iterations,
        max_nodes=args.max_nodes,
        progress=progress,
    )
    print()  # newline after progress

    output = Path(args.output)
    if args.viz_format == "svg":
        content = render_svg(graph, layout, width=args.width, height=args.height)
    else:
        content = render_html(graph, layout, width=args.width, height=args.height)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
    print(f"Visualization saved to: {output}")

    if args.viz_format == "html" and not args.no_open:
        import webbrowser
        webbrowser.open(str(output.resolve()))
    return 0


def run_dashboard(args):
    """Launch local dashboard server."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    from cortex.dashboard.server import start_dashboard

    graph = _load_graph(input_path)
    print(f"Starting Cortex Dashboard on port {args.port}...")
    print("Press Ctrl+C to stop.")
    try:
        start_dashboard(graph, port=args.port, open_browser=not args.no_open)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    return 0


def run_watch(args):
    """Monitor a directory for new export files."""
    import time as _time

    from cortex.sync.monitor import ExportMonitor

    watch_dir = Path(args.watch_dir)
    graph_path = Path(args.graph)

    if not watch_dir.is_dir():
        print(f"Not a directory: {watch_dir}")
        return 1

    def on_extract(path, graph):
        print(f"  Extracted from: {path.name} ({len(graph.nodes)} nodes)")

    monitor = ExportMonitor(
        watch_dir=watch_dir,
        graph_path=graph_path,
        interval=args.interval,
        on_extract=on_extract,
    )

    print(f"Watching {watch_dir} (interval: {args.interval}s)")
    print(f"Updating: {graph_path}")
    print("Press Ctrl+C to stop.")

    monitor.start()
    try:
        while True:
            _time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop()
        print("\nMonitor stopped.")
    return 0


def run_sync_schedule(args):
    """Run periodic platform sync from config."""
    from cortex.sync.scheduler import SyncConfig, SyncScheduler

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return 1

    config = SyncConfig.from_file(config_path)
    scheduler = SyncScheduler(config)

    if args.once:
        print(f"Running {len(config.schedules)} sync(s)...")
        results = scheduler.run_once()
        for platform, paths in results.items():
            if paths:
                print(f"  {platform}: {', '.join(str(p) for p in paths)}")
            else:
                print(f"  {platform}: no output (check config)")
        return 0

    import time as _time
    print(f"Starting scheduled sync ({len(config.schedules)} schedules)...")
    print("Press Ctrl+C to stop.")
    scheduler.start()
    try:
        while True:
            _time.sleep(1)
    except KeyboardInterrupt:
        scheduler.stop()
        print("\nScheduler stopped.")
    return 0


def run_extract_coding(args):
    """Extract identity signals from coding tool sessions."""
    # Watch mode — continuous extraction
    if getattr(args, "watch", False):
        from cortex.continuous import watch_coding_sessions
        output_path = Path(args.output) if args.output else Path("coding_context.json")
        watch_coding_sessions(
            graph_path=str(output_path),
            project_filter=args.project,
            interval=args.interval,
            settle_seconds=args.settle,
            enrich=getattr(args, "enrich", False),
            context_platforms=args.context_refresh,
            context_policy=args.context_policy,
            verbose=True,
        )
        return 0

    from cortex.coding import (
        aggregate_sessions,
        discover_claude_code_sessions,
        load_claude_code_session,
        parse_claude_code_session,
        session_to_context,
    )

    # Collect session files
    session_paths = []
    if args.discover:
        session_paths = discover_claude_code_sessions(
            project_filter=args.project,
            limit=args.limit,
        )
        if not session_paths:
            print("No Claude Code sessions found.")
            return 1
        if args.verbose:
            print(f"Discovered {len(session_paths)} session(s)")
    elif args.input_file:
        p = Path(args.input_file)
        if not p.exists():
            print(f"File not found: {p}")
            return 1
        session_paths = [p]
    else:
        print("Provide an input file or use --discover")
        return 1

    # Parse all sessions
    sessions = []
    for sp in session_paths:
        if args.verbose:
            print(f"  Parsing: {sp.name}")
        records = load_claude_code_session(sp)
        session = parse_claude_code_session(records)
        sessions.append(session)

    # Aggregate
    if len(sessions) > 1:
        combined = aggregate_sessions(sessions)
    else:
        combined = sessions[0]

    # Enrich with project files if requested
    if getattr(args, "enrich", False) and combined.project_path:
        from cortex.coding import enrich_session
        enrich_session(combined)

    # Stats
    if args.stats or args.verbose:
        print("\nCoding Session Summary:")
        print(f"  Sessions:     {len(sessions)}")
        print(f"  Files touched: {len(combined.files_touched)}")
        print(f"  Technologies: {', '.join(t for t, _ in combined.technologies.most_common(10))}")
        print(f"  Tools (bash): {', '.join(t for t, _ in combined.bash_tools.most_common(10))}")
        print(f"  User prompts: {len(combined.user_prompts)}")
        print(f"  Plan mode:    {'yes' if combined.plan_mode_used else 'no'}")
        print(f"  Test files:   {combined.test_files_written}")
        print(f"  Branches:     {', '.join(sorted(combined.branches)) or 'none'}")
        if combined.project_meta.enriched:
            pm = combined.project_meta
            print(f"  Project:      {pm.name}")
            if pm.description:
                print(f"  Description:  {pm.description[:100]}")
            if pm.license:
                print(f"  License:      {pm.license}")
            if pm.manifest_file:
                print(f"  Manifest:     {pm.manifest_file}")

    # Convert to v4 context
    ctx_data = session_to_context(combined)

    # Merge with existing context if requested
    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            with open(merge_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            # Merge v4 categories from existing into ctx_data
            for category, topics in existing.get("categories", {}).items():
                if category not in ctx_data.setdefault("categories", {}):
                    ctx_data["categories"][category] = []
                existing_keys = {t.get("topic", "").lower() for t in ctx_data["categories"][category]}
                for topic in topics:
                    if topic.get("topic", "").lower() not in existing_keys:
                        ctx_data["categories"][category].append(topic)
            if args.verbose:
                print(f"\nMerged with {merge_path}")

    # Write output
    output_path = Path(args.output) if args.output else Path("coding_context.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(ctx_data, f, indent=2, default=str)
    print(f"\nOutput: {output_path}")

    cat_counts = {k: len(v) for k, v in ctx_data.get("categories", {}).items() if v}
    if cat_counts:
        print(f"Extracted: {cat_counts}")

    return 0


def run_context_hook(args):
    """Install/manage Cortex context hook for Claude Code."""
    from cortex.hooks import (
        generate_compact_context,
        hook_status,
        install_hook,
        load_hook_config,
        uninstall_hook,
    )

    if args.action == "install":
        if not args.graph_file:
            print("Error: graph_file required for install")
            print("Usage: cortex context-hook install <graph.json>")
            return 1
        graph_path = Path(args.graph_file)
        if not graph_path.exists():
            print(f"File not found: {graph_path}")
            return 1
        cfg_path, settings_path = install_hook(
            graph_path=str(graph_path),
            policy=args.policy,
            max_chars=args.max_chars,
        )
        print("Cortex hook installed:")
        print(f"  Config:   {cfg_path}")
        print(f"  Settings: {settings_path}")
        print(f"  Policy:   {args.policy}")
        print("\nRestart Claude Code for the hook to take effect.")
        return 0

    elif args.action == "uninstall":
        removed = uninstall_hook()
        if removed:
            print("Cortex hook uninstalled.")
            print("Restart Claude Code to apply changes.")
        else:
            print("No Cortex hook found to remove.")
        return 0

    elif args.action == "test":
        config = load_hook_config()
        if not config.graph_path:
            print("No hook config found. Install first:")
            print("  python migrate.py context-hook install <graph.json>")
            return 1
        context = generate_compact_context(config)
        if context:
            print("Context that would be injected:\n")
            print(context)
            print(f"\n({len(context)} chars)")
        else:
            print("No context generated (graph may be empty or missing).")
        return 0

    elif args.action == "status":
        status = hook_status()
        print(f"Installed: {'Yes' if status['installed'] else 'No'}")
        print(f"Config:    {status['config_path']}")
        print(f"Settings:  {status['settings_path']}")
        if status['config']['graph_path']:
            print(f"Graph:     {status['config']['graph_path']}")
            print(f"Policy:    {status['config']['policy']}")
            print(f"Max chars: {status['config']['max_chars']}")
        return 0

    return 1


def run_context_export(args):
    """Export compact context markdown to stdout."""
    from cortex.hooks import HookConfig, generate_compact_context

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        return 1

    config = HookConfig(
        graph_path=str(input_path),
        policy=args.policy,
        max_chars=args.max_chars,
    )
    context = generate_compact_context(config)
    if context:
        print(context)
    else:
        print("No context generated (graph may be empty).", file=sys.stderr)
        return 1
    return 0


def run_context_write(args):
    """Write identity context to AI coding tool config files."""
    from cortex.context import CONTEXT_TARGETS, watch_and_refresh, write_context

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    # Validate platform names
    platforms = args.platforms
    if "all" not in platforms:
        for p in platforms:
            if p not in CONTEXT_TARGETS:
                print(f"Unknown platform: {p}")
                print(f"Available: {', '.join(CONTEXT_TARGETS.keys())}, all")
                return 1

    if args.watch:
        watch_and_refresh(
            graph_path=str(input_path),
            platforms=platforms,
            project_dir=args.project,
            policy=args.policy,
            max_chars=args.max_chars,
            interval=args.interval,
        )
        return 0

    results = write_context(
        graph_path=str(input_path),
        platforms=platforms,
        project_dir=args.project,
        policy=args.policy,
        max_chars=args.max_chars,
        dry_run=args.dry_run,
    )

    for name, fpath, status in results:
        if status == "skipped":
            print(f"  {name}: skipped (no context or unknown platform)")
        elif status == "error":
            print(f"  {name}: error writing {fpath}")
        elif status == "dry-run":
            print(f"  {name}: {fpath} (dry-run)")
        else:
            print(f"  {name}: {status} {fpath}")

    return 0


def run_stats(args):
    """Show statistics for a context file."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    version = data.get("schema_version", "")
    if version.startswith("5"):
        graph = CortexGraph.from_v5_json(data)
    else:
        graph = upgrade_v4_to_v5(data)

    st = graph.stats()
    print(f"Nodes: {st['node_count']}")
    print(f"Edges: {st['edge_count']}")
    print(f"Avg degree: {st['avg_degree']}")
    if st.get("isolated_nodes", 0) > 0:
        print(f"Isolated nodes (0 edges): {st['isolated_nodes']}")
    if st["tag_distribution"]:
        print("Tag distribution:")
        for tag, count in sorted(st["tag_distribution"].items(), key=lambda x: -x[1]):
            print(f"  {tag}: {count}")
    if st.get("relation_distribution"):
        print("Relation distribution:")
        for rel, count in sorted(st["relation_distribution"].items(), key=lambda x: -x[1]):
            print(f"  {rel}: {count}")
    if st.get("top_central_nodes"):
        print(f"Top central nodes: {', '.join(st['top_central_nodes'])}")
    return 0


def run_pull(args):
    """Import a platform export file back into a CortexGraph."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    adapter = ADAPTERS.get(args.from_platform)
    if adapter is None:
        print(f"Unknown platform: {args.from_platform}")
        return 1

    try:
        graph = adapter.pull(input_path)
    except Exception as e:
        print(f"Error parsing {input_path}: {e}")
        return 1

    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_graph.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")

    st = graph.stats()
    print(f"Imported from {args.from_platform}: {st['node_count']} nodes, {st['edge_count']} edges")
    print(f"Saved to: {output_path}")
    return 0


# ---------------------------------------------------------------------------
# CaaS: serve, grant, rotate
# ---------------------------------------------------------------------------

def run_serve(args):
    """Start the CaaS API server."""
    from cortex.caas.config import CortexConfig
    from cortex.caas.logging_config import setup_logging
    from cortex.caas.server import start_caas_server

    # Load configuration
    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"Config file not found: {config_path}")
            return 1
        config = CortexConfig.from_file(str(config_path))
    else:
        config = CortexConfig.from_env()

    # Set up structured logging from config
    log_level = config.get("logging", "level", fallback="INFO")
    log_format = config.get("logging", "format", fallback="text")
    setup_logging(level=log_level, fmt=log_format)

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    data = json.loads(input_path.read_text(encoding="utf-8"))
    version = data.get("schema_version", "")
    if version.startswith(("5", "6")):
        graph = CortexGraph.from_v5_json(data)
    else:
        graph = upgrade_v4_to_v5(data)

    store_dir = Path(args.store_dir)
    if not (store_dir / "identity.json").exists():
        print(f"No identity found in {store_dir}. Run: cortex identity --init")
        return 1

    identity = UPAIIdentity.load(store_dir)
    version_store = VersionStore(store_dir)

    allowed_origins = None
    if args.allowed_origins:
        allowed_origins = set(args.allowed_origins)

    grants_path = str(store_dir / "grants.json")
    storage_backend = args.storage
    if storage_backend == "postgres":
        db_path = getattr(args, "db_url", None) or args.db_path or "dbname=cortex_dev"
    else:
        db_path = args.db_path or str(store_dir / "cortex.db")

    # Parse OAuth providers
    oauth_providers = None
    if args.oauth_provider:
        oauth_providers = {}
        for provider_name, client_id, client_secret in args.oauth_provider:
            oauth_providers[provider_name] = {
                "client_id": client_id,
                "client_secret": client_secret,
            }

    oauth_allowed_emails = None
    if args.oauth_allowed_email:
        oauth_allowed_emails = set(args.oauth_allowed_email)

    enable_sse = getattr(args, "enable_sse", False)
    enable_metrics = getattr(args, "enable_metrics", False)
    # Allow config file to enable metrics
    if not enable_metrics and config is not None:
        enable_metrics = config.getbool("metrics", "enabled", fallback=False)
    cred_store_path = str(store_dir / "credentials.json")

    # Plugin system
    plugin_manager = None
    plugin_modules = getattr(args, "plugins", None)
    if plugin_modules:
        from cortex.plugins import PluginManager
        plugin_manager = PluginManager(modules=plugin_modules)

    # Tracing setup
    enable_tracing = getattr(args, "enable_tracing", False)
    if not enable_tracing and config is not None:
        enable_tracing = config.getbool("tracing", "enabled", fallback=False)
    tracing_manager = None
    if enable_tracing:
        from cortex.caas.tracing import TracingManager
        tracing_exporter = getattr(args, "tracing_exporter", "console")
        if config is not None:
            tracing_exporter = config.get("tracing", "exporter", fallback=tracing_exporter)
        tracing_endpoint = None
        if config is not None:
            tracing_endpoint = config.get("tracing", "endpoint", fallback="") or None
        tracing_manager = TracingManager(exporter=tracing_exporter, endpoint=tracing_endpoint)

    print(f"CaaS API: http://127.0.0.1:{args.port}")
    print(f"Identity: {identity.did}")
    print(f"Graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    print(f"Storage: {storage_backend}" + (f" ({db_path})" if storage_backend in ("sqlite", "postgres") else ""))
    if args.config:
        print(f"Config: {args.config}")
    print(f"Logging: level={log_level}, format={log_format}")
    if oauth_providers:
        print(f"OAuth: {', '.join(oauth_providers.keys())}")
    if enable_sse:
        print("SSE: enabled (/events)")
    if enable_metrics:
        print("Metrics: enabled (/metrics)")
    if plugin_manager and plugin_manager.loaded_plugins:
        print(f"Plugins: {', '.join(plugin_manager.loaded_plugins)}")
    if enable_tracing:
        print(f"Tracing: enabled ({getattr(args, 'tracing_exporter', 'console')})")

    # Federation
    enable_federation = getattr(args, "enable_federation", False)
    if not enable_federation and config is not None:
        enable_federation = config.getbool("federation", "enabled", fallback=False)
    federation_trusted_dids = getattr(args, "federation_trusted_did", None) or []
    if not federation_trusted_dids and config is not None:
        federation_trusted_dids = config.getlist("federation", "trusted_dids")
    if enable_federation:
        print(f"Federation: enabled ({len(federation_trusted_dids)} trusted peers)")

    # Webapp
    enable_webapp = getattr(args, "enable_webapp", False)
    if not enable_webapp and config is not None:
        enable_webapp = config.getbool("webapp", "enabled", fallback=False)
    if enable_webapp:
        print(f"Web UI: enabled (/app)")

    print("WARNING: Server running without TLS. Do not expose to untrusted networks.", file=sys.stderr)

    server = start_caas_server(
        graph=graph,
        identity=identity,
        version_store=version_store,
        port=args.port,
        allowed_origins=allowed_origins,
        grants_persist_path=grants_path,
        storage_backend=storage_backend,
        db_path=db_path,
        enable_metrics=enable_metrics,
        oauth_providers=oauth_providers,
        oauth_allowed_emails=oauth_allowed_emails,
        credential_store_path=cred_store_path,
        enable_sse=enable_sse,
        store_dir=str(store_dir),
        config=config,
        plugin_manager=plugin_manager,
        tracing_manager=tracing_manager,
        enable_federation=enable_federation,
        federation_trusted_dids=federation_trusted_dids,
        enable_webapp=enable_webapp,
    )

    # Use ShutdownCoordinator for graceful shutdown if available
    coordinator = getattr(server, '_shutdown_coordinator', None)
    if coordinator:
        coordinator.install_signal_handlers()
        try:
            coordinator.wait_for_shutdown()
        except KeyboardInterrupt:
            print("\nShutting down...")
            server.shutdown()
    else:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")
            server.shutdown()
    return 0


def run_grant(args):
    """Manage CaaS grant tokens."""
    from cortex.upai.tokens import GrantToken

    store_dir = Path(args.store_dir)
    if not (store_dir / "identity.json").exists():
        print(f"No identity found in {store_dir}. Run: cortex identity --init")
        return 1

    identity = UPAIIdentity.load(store_dir)

    # Select grant store backend
    storage = getattr(args, "storage", "json")
    if storage == "sqlite":
        from cortex.caas.sqlite_store import SqliteGrantStore
        db_path = args.db_path or str(Path(store_dir) / "cortex.db")
        gs = SqliteGrantStore(db_path)
    elif storage == "postgres":
        try:
            from cortex.caas.postgres_store import PostgresGrantStore
        except ImportError:
            print('PostgreSQL storage requires psycopg: pip install "psycopg[binary]"')
            return 1
        db_url = getattr(args, "db_url", None) or getattr(args, "db_path", None) or "dbname=cortex_dev"
        gs = PostgresGrantStore(db_url)
    else:
        from cortex.caas.server import GrantStore
        gs = GrantStore(persist_path=str(store_dir / "grants.json"))

    if args.create:
        audience = args.audience
        if not audience:
            print("--audience is required for --create")
            return 1

        token = GrantToken.create(
            identity, audience=audience,
            policy=args.policy, ttl_hours=args.ttl,
        )
        token_str = token.sign(identity)
        gs.add(token.grant_id, token_str, token.to_dict())

        print(f"Grant ID: {token.grant_id}")
        print(f"Audience: {token.audience}")
        print(f"Policy: {token.policy}")
        print(f"Scopes: {', '.join(token.scopes)}")
        print(f"Expires: {token.expires_at}")
        print(f"Storage: {storage}")
        print(f"\nToken:\n{token_str}")
        return 0

    elif args.list_grants:
        grants = gs.list_all()
        if not grants:
            print("No grants found.")
        else:
            for g in grants:
                status = "REVOKED" if g.get("revoked") else "active"
                print(f"  {g['grant_id'][:12]}... | {g.get('audience', '?')} | {g.get('policy', '?')} | {status}")
        return 0

    elif args.revoke:
        if gs.revoke(args.revoke):
            print(f"Revoked grant: {args.revoke}")
        else:
            print(f"Grant not found: {args.revoke}")
            return 1
        return 0

    else:
        print("Specify --create, --list, or --revoke")
        return 1


def run_policy(args):
    """Manage custom disclosure policies."""
    from cortex.upai.disclosure import BUILTIN_POLICIES, DisclosurePolicy

    if args.list_policies:
        print("Built-in policies:")
        for name in BUILTIN_POLICIES:
            p = BUILTIN_POLICIES[name]
            print(f"  {name} (builtin) — min_conf={p.min_confidence}, tags={p.include_tags or 'all'}")
        print("\n(Custom policies require a running CaaS server.)")
        return 0

    if args.show:
        name = args.show
        if name in BUILTIN_POLICIES:
            p = BUILTIN_POLICIES[name]
            print(f"Name: {p.name} (builtin)")
            print(f"  Include tags: {p.include_tags or 'all'}")
            print(f"  Exclude tags: {p.exclude_tags or 'none'}")
            print(f"  Min confidence: {p.min_confidence}")
            print(f"  Redact properties: {p.redact_properties or 'none'}")
            print(f"  Max nodes: {p.max_nodes or 'unlimited'}")
            return 0
        print(f"Policy '{name}' not found in built-in policies.")
        print("Custom policies require a running CaaS server.")
        return 1

    if args.create:
        name = args.name
        if not name:
            print("--name is required for --create")
            return 1
        include_tags = [t.strip() for t in args.include_tags.split(",")] if args.include_tags else []
        exclude_tags = [t.strip() for t in args.exclude_tags.split(",")] if args.exclude_tags else []
        redact_props = [t.strip() for t in args.redact_properties.split(",")] if args.redact_properties else []

        policy = DisclosurePolicy(
            name=name,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
            min_confidence=args.min_confidence,
            redact_properties=redact_props,
            max_nodes=args.max_nodes,
        )
        print(f"Policy definition for '{name}':")
        print(f"  Include tags: {policy.include_tags or 'all'}")
        print(f"  Exclude tags: {policy.exclude_tags or 'none'}")
        print(f"  Min confidence: {policy.min_confidence}")
        print(f"  Redact properties: {policy.redact_properties or 'none'}")
        print(f"  Max nodes: {policy.max_nodes or 'unlimited'}")
        print("\nTo register on a running server, POST to /policies:")
        import json as _json
        body = {
            "name": name,
            "include_tags": policy.include_tags,
            "exclude_tags": policy.exclude_tags,
            "min_confidence": policy.min_confidence,
            "redact_properties": policy.redact_properties,
            "max_nodes": policy.max_nodes,
        }
        print(f"  curl -X POST http://localhost:8421/policies -d '{_json.dumps(body)}'")
        return 0

    if args.delete:
        name = args.delete
        if name in BUILTIN_POLICIES:
            print(f"Cannot delete built-in policy: {name}")
            return 1
        print("To delete on a running server:")
        print(f"  curl -X DELETE http://localhost:8421/policies/{name}")
        return 0

    print("Specify --list, --create, --show <name>, or --delete <name>")
    return 1


def run_rotate(args):
    """Rotate UPAI identity key."""
    from cortex.upai.keychain import Keychain

    store_dir = Path(args.store_dir)
    if not (store_dir / "identity.json").exists():
        print(f"No identity found in {store_dir}. Run: cortex identity --init")
        return 1

    identity = UPAIIdentity.load(store_dir)
    kc = Keychain(store_dir)

    new_identity, proof = kc.rotate(identity, reason=args.reason)
    print(f"Old DID: {identity.did}")
    print(f"New DID: {new_identity.did}")
    print(f"Reason: {args.reason}")
    if proof:
        print(f"Revocation proof: {proof[:32]}...")
    print("Identity rotated successfully.")
    return 0


def run_completion(args):
    """Generate shell completion script."""
    from cortex.completion import generate_completion

    parser = build_parser()
    script = generate_completion(parser, args.shell)
    print(script)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    # Default-subcommand routing: if the first arg is not a known subcommand,
    # treat it as a file path and route to the "migrate" subcommand.
    known_subcommands = (
        "extract", "import", "migrate", "query", "stats",
        "timeline", "contradictions", "drift",
        "identity", "commit", "log", "sync", "verify",
        "gaps", "digest",
        "viz", "dashboard", "watch", "sync-schedule",
        "extract-coding", "context-hook", "context-export", "context-write",
        "serve", "grant", "rotate", "pull", "policy", "completion",
        "-h", "--help",
    )
    if argv and argv[0] not in known_subcommands:
        argv = ["migrate"] + list(argv)

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand is None:
        parser.print_help()
        return 1

    if args.subcommand == "extract":
        return run_extract(args)
    elif args.subcommand == "import":
        return run_import(args)
    elif args.subcommand == "query":
        return run_query(args)
    elif args.subcommand == "stats":
        return run_stats(args)
    elif args.subcommand == "timeline":
        return run_timeline(args)
    elif args.subcommand == "contradictions":
        return run_contradictions(args)
    elif args.subcommand == "drift":
        return run_drift(args)
    elif args.subcommand == "identity":
        return run_identity(args)
    elif args.subcommand == "commit":
        return run_commit(args)
    elif args.subcommand == "log":
        return run_log(args)
    elif args.subcommand == "sync":
        return run_sync(args)
    elif args.subcommand == "verify":
        return run_verify(args)
    elif args.subcommand == "gaps":
        return run_gaps(args)
    elif args.subcommand == "digest":
        return run_digest(args)
    elif args.subcommand == "viz":
        return run_viz(args)
    elif args.subcommand == "dashboard":
        return run_dashboard(args)
    elif args.subcommand == "watch":
        return run_watch(args)
    elif args.subcommand == "sync-schedule":
        return run_sync_schedule(args)
    elif args.subcommand == "extract-coding":
        return run_extract_coding(args)
    elif args.subcommand == "context-hook":
        return run_context_hook(args)
    elif args.subcommand == "context-export":
        return run_context_export(args)
    elif args.subcommand == "pull":
        return run_pull(args)
    elif args.subcommand == "serve":
        return run_serve(args)
    elif args.subcommand == "grant":
        return run_grant(args)
    elif args.subcommand == "rotate":
        return run_rotate(args)
    elif args.subcommand == "policy":
        return run_policy(args)
    elif args.subcommand == "context-write":
        return run_context_write(args)
    elif args.subcommand == "completion":
        return run_completion(args)
    else:
        return run_migrate(args)


if __name__ == "__main__":
    sys.exit(main())
