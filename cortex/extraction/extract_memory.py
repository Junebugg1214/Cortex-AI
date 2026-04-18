#!/usr/bin/env python3
# ruff: noqa: E402
from __future__ import annotations

"""
Chatbot Memory Extractor v4.0

IMPROVEMENTS OVER v3:
- Semantic deduplication (fuzzy matching, not just exact)
- Better hyphenated/compound name handling (O'Brien, Saint-Jour, etc.)
- Time decay (older mentions = reduced confidence boost)
- Topic merging heuristics (combine related topics)
- Improved entity extraction

Usage:
    python extract_memory_v4.py <export_file> [options]
"""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import cortex.extract_memory_context as _extract_memory_context
import cortex.extract_memory_patterns as _extract_memory_patterns
from cortex.extract_memory_loaders import load_file
from cortex.extract_memory_processing import AggressiveExtractionProcessingMixin
from cortex.extract_memory_streams import parse_timestamp
from cortex.extract_memory_text import (
    clean_extracted_text as _clean_extracted_text,
)
from cortex.extract_memory_text import (
    clean_role_phrase as _clean_role_phrase,
)
from cortex.extract_memory_text import (
    extract_entities as _extract_entities,
)
from cortex.extract_memory_text import (
    extract_match_context as _extract_match_context,
)
from cortex.extract_memory_text import (
    extract_numbers as _extract_numbers,
)
from cortex.extract_memory_text import (
    extract_with_context as _extract_with_context,
)
from cortex.extract_memory_text import (
    keyword_search as _keyword_search,
)
from cortex.extract_memory_topics import AggressiveExtractionTopicMixin

ExtractionContext = _extract_memory_context.ExtractionContext
ExtractedMemoryItem = _extract_memory_context.ExtractedMemoryItem
ExtractedTopic = _extract_memory_context.ExtractedTopic
ExtractedFact = _extract_memory_context.ExtractedFact
ExtractedClaim = _extract_memory_context.ExtractedClaim
ExtractedRelationship = _extract_memory_context.ExtractedRelationship
are_similar = _extract_memory_context.are_similar
build_eval_compat_view = _extract_memory_context.build_eval_compat_view
find_best_match = _extract_memory_context.find_best_match
normalize_text = _extract_memory_context.normalize_text

PIIRedactor = _extract_memory_patterns.PIIRedactor
RELATIONSHIP_TYPE_PATTERNS = _extract_memory_patterns.RELATIONSHIP_TYPE_PATTERNS
SKIP_WORDS = _extract_memory_patterns.SKIP_WORDS
STRIP_PREFIXES = _extract_memory_patterns.STRIP_PREFIXES

_KEYWORD_PATTERN_CACHE: dict[str, object] = {}


# ============================================================================
# TEXT UTILITIES
# ============================================================================


def clean_extracted_text(text: str) -> str:
    return _clean_extracted_text(text, strip_prefixes=STRIP_PREFIXES)


def keyword_search(text: str, keyword: str) -> re.Match | None:
    return _keyword_search(text, keyword, cache=_KEYWORD_PATTERN_CACHE)


def extract_match_context(text: str, start: int, end: int, window: int = 50) -> str:
    return _extract_match_context(text, start, end, window)


def clean_role_phrase(text: str) -> str:
    return _clean_role_phrase(text, clean_extracted_text_fn=clean_extracted_text)


def extract_numbers(text: str) -> list[str]:
    return _extract_numbers(text)


def extract_with_context(text: str, keyword: str, window: int = 50) -> str:
    return _extract_with_context(text, keyword, window)


def extract_entities(text: str) -> list[tuple[str, str]]:
    return _extract_entities(text, skip_words=SKIP_WORDS)


# ============================================================================
# EXTRACTOR
# ============================================================================


class AggressiveExtractor(AggressiveExtractionProcessingMixin, AggressiveExtractionTopicMixin):
    def __init__(self, redactor: PIIRedactor | None = None, extractor_run_id: str | None = None):
        self.context = ExtractionContext()
        self.all_user_text = []
        self._negated_items = set()  # Track negated items for cross-category filtering
        self._redactor = redactor
        self.extractor_run_id = extractor_run_id or self._make_extractor_run_id()

    def _make_extractor_run_id(self) -> str:
        seed = f"{datetime.now(timezone.utc).isoformat()}:{id(self)}"
        return f"extractor-run:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"

    def _finalize_result(self, result: dict) -> dict:
        provenance_entry = {
            "source": "extractor:aggressive",
            "source_id": self.extractor_run_id,
            "reason": "auto",
        }
        result.setdefault("meta", {})["extractor_run_id"] = self.extractor_run_id
        result["meta"]["require_provenance"] = True
        for topics in result.get("categories", {}).values():
            for topic in topics:
                provenance = list(topic.get("_provenance", []))
                if provenance:
                    topic["_provenance"] = provenance
                    continue
                topic["_provenance"] = [dict(provenance_entry)]
        return result

    def process_openai_export(self, data: list | dict) -> dict:
        return self._finalize_result(super().process_openai_export(data))

    def process_messages_list(self, messages: list) -> dict:
        return self._finalize_result(super().process_messages_list(messages))

    def process_plain_text(self, text: str) -> dict:
        return self._finalize_result(super().process_plain_text(text))

    def process_gemini_export(self, data: dict) -> dict:
        return self._finalize_result(super().process_gemini_export(data))

    def process_perplexity_export(self, data: dict) -> dict:
        return self._finalize_result(super().process_perplexity_export(data))

    def process_grok_export(self, data: list | dict) -> dict:
        return self._finalize_result(super().process_grok_export(data))

    def process_cursor_export(self, data: list | dict) -> dict:
        return self._finalize_result(super().process_cursor_export(data))

    def process_windsurf_export(self, data: list | dict) -> dict:
        return self._finalize_result(super().process_windsurf_export(data))

    def process_copilot_export(self, data: list | dict) -> dict:
        return self._finalize_result(super().process_copilot_export(data))

    def process_jsonl_messages(self, messages: list) -> dict:
        return self._finalize_result(super().process_jsonl_messages(messages))

    def process_api_logs(self, data: dict) -> dict:
        return self._finalize_result(super().process_api_logs(data))


# ============================================================================
# FILE HANDLERS
# ============================================================================


def merge_contexts(existing_path: Path, extractor: "AggressiveExtractor") -> "AggressiveExtractor":
    """Merge new extraction with existing v4 context file.

    Loads topics from existing context file and adds them to the new extraction.
    Uses add_topic() which handles deduplication via find_best_match.
    """
    try:
        with open(existing_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        import sys

        print(f"[cortex] Warning: could not load merge file {existing_path.name}: {exc}", file=sys.stderr)
        return extractor

    # Load existing topics into the new context
    for category, topics in existing.get("categories", {}).items():
        for topic_data in topics:
            extractor.context.add_topic(
                category=category,
                topic=topic_data.get("topic", ""),
                brief=topic_data.get("brief", ""),
                full_description=topic_data.get("full_description", ""),
                confidence=topic_data.get("confidence", 0.5),
                extraction_method=topic_data.get("extraction_method", "mentioned"),
                metrics=topic_data.get("metrics", []),
                relationships=topic_data.get("relationships", []),
                timeline=topic_data.get("timeline", []),
                source_quote=topic_data.get("source_quotes", [""])[0] if topic_data.get("source_quotes") else "",
                timestamp=parse_timestamp(topic_data.get("last_seen")),
                relationship_type=topic_data.get("relationship_type", ""),
            )

    # Re-run merge for deduplication
    extractor.context.merge_similar_topics()

    return extractor


def main():
    parser = argparse.ArgumentParser(description="Aggressive memory extraction v4")
    parser.add_argument("input_file", help="Path to export file")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument(
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
    parser.add_argument("--merge", "-m", help="Existing context file to merge with (incremental extraction)")
    parser.add_argument("--redact", action="store_true", help="Enable PII redaction (emails, phones, SSNs, etc.)")
    parser.add_argument("--redact-patterns", help='Path to JSON file with custom redaction patterns {"LABEL": "regex"}')
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
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

    # Build optional PII redactor
    redactor = None
    if args.redact:
        custom_patterns = None
        if args.redact_patterns:
            patterns_path = Path(args.redact_patterns)
            if patterns_path.exists():
                with open(patterns_path, "r", encoding="utf-8") as f:
                    custom_patterns = json.load(f)
                print(f"🔒 Loaded {len(custom_patterns)} custom redaction patterns from {patterns_path}")
            else:
                print(f"⚠️  Redaction patterns file not found: {patterns_path}")
                return 1
        redactor = PIIRedactor(custom_patterns)
        print("🔒 PII redaction enabled")

    extractor = AggressiveExtractor(redactor=redactor)

    # Handle merge with existing context file
    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            print(f"📎 Merging with existing context: {merge_path}")
            extractor = merge_contexts(merge_path, extractor)
        else:
            print(f"⚠️  Merge file not found: {merge_path} (proceeding without merge)")

    print("Extracting (semantic dedup, time decay, topic merging, conflict detection, typed relationships)...")

    if fmt == "openai":
        result = extractor.process_openai_export(data)
    elif fmt == "gemini":
        result = extractor.process_gemini_export(data)
    elif fmt == "perplexity":
        result = extractor.process_perplexity_export(data)
    elif fmt == "grok":
        result = extractor.process_grok_export(data)
    elif fmt == "cursor":
        result = extractor.process_cursor_export(data)
    elif fmt == "windsurf":
        result = extractor.process_windsurf_export(data)
    elif fmt == "copilot":
        result = extractor.process_copilot_export(data)
    elif fmt in ("jsonl", "claude_code"):
        result = extractor.process_jsonl_messages(data)
    elif fmt == "api_logs":
        result = extractor.process_api_logs(data)
    elif fmt == "messages":
        result = extractor.process_messages_list(data)
    elif fmt == "text":
        result = extractor.process_plain_text(data)
    else:
        if isinstance(data, list):
            result = extractor.process_messages_list(data)
        elif isinstance(data, dict) and "messages" in data:
            result = extractor.process_messages_list(data["messages"])
        else:
            result = extractor.process_plain_text(json.dumps(data))

    stats = extractor.context.stats()
    print(f"✅ Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    typed = stats.get("by_type", {})
    print(
        f"   Typed output: {typed.get('facts', 0)} facts, "
        f"{typed.get('claims', 0)} claims, "
        f"{typed.get('relationships', 0)} relationships"
    )
    print(
        f"   By confidence: {stats['by_confidence']['high']} high, {stats['by_confidence']['medium']} medium, {stats['by_confidence']['low']} low"
    )

    if args.stats or args.verbose:
        print("\n📊 By category:")
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            print(f"   {cat}: {count}")

    if args.verbose:
        print("\n🔎 Sample extractions:")
        for cat, topics in list(result["categories"].items())[:5]:
            print(f"\n  [{cat}]")
            for topic in topics[:3]:
                rel_type = topic.get("relationship_type", "")
                rel_str = f", type: {rel_type}" if rel_type else ""
                print(
                    f"    • {topic['topic']} (conf: {topic['confidence']}, mentions: {topic['mention_count']}{rel_str})"
                )

        # Show conflicts if any
        if result.get("conflicts"):
            print(f"\n⚠️  Detected {len(result['conflicts'])} conflicts:")
            for conflict in result["conflicts"][:5]:
                print(
                    f"    • {conflict['positive_category']}: '{conflict['positive_topic']}' vs negation '{conflict['negative_topic']}' → {conflict['resolution']}"
                )

    # Show redaction summary
    if result.get("redaction_summary"):
        summary = result["redaction_summary"]
        print(f"\n🔒 Redaction: {summary['total_redactions']} items redacted")
        if args.verbose and summary["by_type"]:
            for pii_type, count in sorted(summary["by_type"].items()):
                print(f"   {pii_type}: {count}")

    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_context.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"\n💾 Saved to: {output_path}")
    return 0


if __name__ == "__main__":
    exit(main())
