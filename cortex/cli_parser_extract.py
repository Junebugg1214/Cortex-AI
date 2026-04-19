from __future__ import annotations


def add_extract_pipeline_parsers(sub, *, platform_formats, builtin_policies):
    mig = sub.add_parser("migrate", help="Full pipeline: extract then import")
    mig.add_argument("input_file", help="Path to chat export file")
    mig.add_argument(
        "--to",
        "-t",
        dest="to",
        default="all",
        choices=list(platform_formats.keys()),
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

    rc = sub.add_parser("extract-refresh-cache", help="Refresh model replay cache from an extraction corpus")
    rc.add_argument(
        "--corpus",
        default="tests/extraction/corpus",
        help="Extraction corpus directory (default: tests/extraction/corpus)",
    )
    rc.add_argument(
        "--prompt-version",
        default="corpus-v1",
        help="Prompt version to include in replay cache keys (default: corpus-v1)",
    )
    rc.add_argument(
        "--replay-dir",
        help="Replay cache directory (default: CORPUS/replay)",
    )
    rc.add_argument("--model", help="Anthropic model id to use while refreshing the cache")

    ev = sub.add_parser("extract-eval", help="Run extraction eval corpus and compare with baseline")
    ev.add_argument(
        "--corpus",
        default="tests/extraction/corpus",
        help="Extraction corpus directory (default: tests/extraction/corpus)",
    )
    ev.add_argument(
        "--backend",
        choices=["heuristic", "model", "hybrid"],
        default="heuristic",
        help="Extraction backend to evaluate (default: heuristic)",
    )
    ev.add_argument(
        "--output",
        default="extraction-eval-report.json",
        help="JSON report path (default: extraction-eval-report.json)",
    )
    ev.add_argument(
        "--tolerance",
        type=float,
        default=0.01,
        help="Allowed metric regression from baseline before failing (default: 0.01)",
    )
    ev.add_argument(
        "--prompt-version",
        default="corpus-v1",
        help="Prompt version to include in model replay keys (default: corpus-v1)",
    )
    ev.add_argument(
        "--replay-dir",
        help="Replay cache directory for model/hybrid evals (default: CORPUS/replay)",
    )
    ev.add_argument("--update-baseline", action="store_true", help="Write current results to CORPUS/baseline.json")

    rv = sub.add_parser("extract-review", help="Review extraction eval failures and patch gold labels")
    rv.add_argument("report", help="Extraction eval report JSON")
    rv.add_argument(
        "--docs-dir",
        default="docs/extraction-reviews",
        help="Directory for markdown review summaries (default: docs/extraction-reviews)",
    )

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

    imp = sub.add_parser("import", help="Import context to platform formats")
    imp.add_argument("input_file", help="Path to context JSON file")
    imp.add_argument(
        "--to",
        "-t",
        dest="to",
        default="all",
        choices=list(platform_formats.keys()),
        help="Target platform shortcut (default: all)",
    )
    imp.add_argument("--output", "-o", default="./output", help="Output directory")
    imp.add_argument("--confidence", "-c", choices=["high", "medium", "low", "all"], default="medium")
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--verbose", "-v", action="store_true")

    st = sub.add_parser("stats", help="Show graph/context statistics")
    st.add_argument("input_file", help="Path to context JSON (v4 or v5)")

    tl = sub.add_parser("timeline", help="Generate timeline from context/graph")
    tl.add_argument("input_file", nargs="?", help="Path to context JSON (v4 or v5), or `review` for queue inspection")
    tl.add_argument("--from", dest="from_date", help="Start date (ISO-8601)")
    tl.add_argument("--to", dest="to_date", help="End date (ISO-8601)")
    tl.add_argument("--mind", help="Mind id when using `cortex timeline review`")
    tl.add_argument(
        "--min-confidence",
        type=float,
        default=0.5,
        help="Temporal review threshold when using `cortex timeline review` (default: 0.5)",
    )
    tl.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    tl.add_argument(
        "--format", "-f", dest="output_format", choices=["md", "html"], default="md", help="Output format (default: md)"
    )

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

    dr = sub.add_parser("drift", help="Compute identity drift between two graphs")
    dr.add_argument("input_file", help="Path to first context JSON (v4 or v5)")
    dr.add_argument("--compare", required=True, help="Path to second context JSON to compare against")

    gp = sub.add_parser("gaps", help="Analyze gaps in knowledge graph")
    gp.add_argument("input_file", help="Path to context JSON (v4 or v5)")

    dg = sub.add_parser("digest", help="Generate weekly digest (compare two graphs)")
    dg.add_argument("input_file", help="Path to current context JSON (v4 or v5)")
    dg.add_argument("--previous", required=True, help="Path to previous context JSON to compare against")

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

    wa = sub.add_parser("watch", help="Monitor directory for new exports")
    wa.add_argument("watch_dir", help="Directory to monitor for export files")
    wa.add_argument("--graph", "-g", required=True, help="Path to context.json to update")
    wa.add_argument("--interval", type=int, default=30, help="Poll interval in seconds (default: 30)")

    ss = sub.add_parser("sync-schedule", help="Run periodic platform sync")
    ss.add_argument("--config", "-c", required=True, help="Path to sync config JSON")
    ss.add_argument("--once", action="store_true", help="Run all syncs once and exit")

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
        choices=list(builtin_policies.keys()),
        help="Disclosure policy for context refresh",
    )

    ch = sub.add_parser("context-hook", help="Install/manage Cortex context hook for Claude Code")
    ch.add_argument("action", choices=["install", "uninstall", "test", "status"], help="Hook action to perform")
    ch.add_argument("graph_file", nargs="?", help="Path to Cortex graph JSON (required for install)")
    ch.add_argument(
        "--policy",
        default="technical",
        choices=list(builtin_policies.keys()),
        help="Disclosure policy (default: technical)",
    )
    ch.add_argument("--max-chars", type=int, default=1500, help="Max characters for injected context (default: 1500)")

    ce = sub.add_parser("context-export", help="Export compact context markdown to stdout")
    ce.add_argument("input_file", help="Path to Cortex graph JSON")
    ce.add_argument(
        "--policy",
        default="technical",
        choices=list(builtin_policies.keys()),
        help="Disclosure policy (default: technical)",
    )
    ce.add_argument("--max-chars", type=int, default=1500, help="Max characters (default: 1500)")

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
        choices=list(builtin_policies.keys()),
        help="Override disclosure policy for all platforms",
    )
    cw.add_argument("--max-chars", type=int, default=1500, help="Max characters per context (default: 1500)")
    cw.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    cw.add_argument("--watch", action="store_true", help="Watch graph file and auto-refresh on change")
    cw.add_argument("--interval", type=int, default=30, help="Watch poll interval in seconds (default: 30)")

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
