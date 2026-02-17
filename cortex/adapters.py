"""
Platform Adapters — Disclosure-filtered export to Claude, SystemPrompt, Notion, GDocs.

Each adapter wraps existing import_memory.py export functions with disclosure filtering.
Push flow: graph -> apply_disclosure(policy) -> downgrade to v4 categories -> call exporter.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from cortex.graph import CortexGraph
from cortex.compat import downgrade_v5_to_v4
from cortex.upai.disclosure import DisclosurePolicy, apply_disclosure

from cortex.import_memory import (
    NormalizedContext,
    export_claude_preferences,
    export_claude_memories,
    export_system_prompt,
    export_notion,
    export_notion_database_json,
    export_google_docs,
)

if TYPE_CHECKING:
    from cortex.upai.identity import UPAIIdentity


def _graph_to_normalized(graph: CortexGraph, policy: DisclosurePolicy) -> NormalizedContext:
    """Apply disclosure, downgrade to v4, and load as NormalizedContext."""
    filtered = apply_disclosure(graph, policy)
    v4 = downgrade_v5_to_v4(filtered)
    return NormalizedContext.from_v4(v4)


def _add_upai_envelope(data: dict | list, identity: UPAIIdentity | None) -> dict:
    """Wrap data with UPAI metadata and optional signature."""
    import secrets as _secrets

    exported_at = datetime.now(timezone.utc).isoformat()
    envelope: dict = {
        "upai_version": "5.2",
        "exported_at": exported_at,
        "nonce": _secrets.token_hex(16),
        "iat": exported_at,
        "data": data,
    }
    if identity is not None:
        payload = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
        envelope["upai_identity"] = identity.to_public_dict()
        envelope["integrity_hash"] = identity.integrity_hash(payload)
        envelope["signature"] = identity.sign(payload)
    return envelope


class BaseAdapter(ABC):
    name: str

    @abstractmethod
    def push(
        self,
        graph: CortexGraph,
        policy: DisclosurePolicy,
        identity: UPAIIdentity | None = None,
        output_dir: Path = Path("."),
    ) -> list[Path]:
        """Generate platform-specific files with disclosure + optional signing."""

    @abstractmethod
    def pull(self, file_path: Path) -> CortexGraph:
        """Parse platform export back into a graph (where supported)."""


class ClaudeAdapter(BaseAdapter):
    """Push: preferences.txt + memories.json. Pull: parse memories JSON back to nodes."""
    name = "claude"

    def push(
        self,
        graph: CortexGraph,
        policy: DisclosurePolicy,
        identity: UPAIIdentity | None = None,
        output_dir: Path = Path("."),
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        ctx = _graph_to_normalized(graph, policy)
        paths = []

        # Preferences text
        prefs = export_claude_preferences(ctx, policy.min_confidence)
        prefs_path = output_dir / "claude_preferences.txt"
        prefs_path.write_text(prefs, encoding="utf-8")
        paths.append(prefs_path)

        # Memories JSON
        memories = export_claude_memories(ctx, policy.min_confidence)
        mem_path = output_dir / "claude_memories.json"
        if identity is not None:
            envelope = _add_upai_envelope(memories, identity)
            mem_path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        else:
            mem_path.write_text(json.dumps(memories, indent=2), encoding="utf-8")
        paths.append(mem_path)

        return paths

    def pull(self, file_path: Path) -> CortexGraph:
        """Parse Claude memories JSON back into a CortexGraph."""
        from cortex.compat import upgrade_v4_to_v5

        raw = json.loads(file_path.read_text(encoding="utf-8"))

        # Handle UPAI envelope — verify integrity hash if present (#6)
        if isinstance(raw, dict) and "data" in raw:
            memories = raw["data"]
            expected_hash = raw.get("integrity_hash")
            if expected_hash:
                import hashlib
                actual_hash = hashlib.sha256(
                    json.dumps(memories, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest()
                if actual_hash != expected_hash:
                    import sys
                    print(
                        f"WARNING: Integrity hash mismatch in {file_path.name}. "
                        "Data may have been tampered with.",
                        file=sys.stderr,
                    )
        else:
            memories = raw

        if not isinstance(memories, list):
            raise ValueError("Expected a list of memory objects")

        ctx = NormalizedContext.from_claude_memories(memories)
        # Build v4 dict from NormalizedContext
        v4: dict = {
            "schema_version": "4.0",
            "meta": ctx.meta,
            "categories": {},
        }
        for cat, topics in ctx.categories.items():
            v4["categories"][cat] = [
                {
                    "topic": t.topic,
                    "brief": t.brief,
                    "full_description": t.full_description,
                    "confidence": t.confidence,
                    "mention_count": t.mention_count,
                    "extraction_method": getattr(t, "extraction_method", "mentioned"),
                    "metrics": getattr(t, "metrics", []),
                    "relationships": getattr(t, "relationships", []),
                    "timeline": getattr(t, "timeline", []),
                    "source_quotes": getattr(t, "source_quotes", []),
                    "first_seen": getattr(t, "first_seen", None),
                    "last_seen": getattr(t, "last_seen", None),
                    "relationship_type": getattr(t, "relationship_type", ""),
                }
                for t in topics
            ]
        return upgrade_v4_to_v5(v4)


class SystemPromptAdapter(BaseAdapter):
    """Push: system_prompt.txt. Pull: parse XML back to nodes."""
    name = "system-prompt"

    def push(
        self,
        graph: CortexGraph,
        policy: DisclosurePolicy,
        identity: UPAIIdentity | None = None,
        output_dir: Path = Path("."),
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        ctx = _graph_to_normalized(graph, policy)
        prompt = export_system_prompt(ctx, policy.min_confidence)

        if identity is not None:
            prompt += f"\n<!-- UPAI DID: {identity.did} -->"

        path = output_dir / "system_prompt.txt"
        path.write_text(prompt, encoding="utf-8")
        return [path]

    def pull(self, file_path: Path) -> CortexGraph:
        """Parse XML system prompt back into a CortexGraph (basic)."""
        from cortex.graph import Node, make_node_id
        from cortex.compat import upgrade_v4_to_v5

        text = file_path.read_text(encoding="utf-8")
        v4_categories: dict[str, list[dict]] = {}

        # Parse <category>...</category> blocks (skip structural wrappers)
        import re
        _WRAPPER_TAGS = {"user_context", "context", "system", "prompt"}
        pattern = r"<(\w+)>(.*?)</\1>"
        for match in re.finditer(pattern, text, re.DOTALL):
            category = match.group(1)
            if category in _WRAPPER_TAGS:
                continue
            content = match.group(2)
            items = []
            for line in content.strip().split("\n"):
                line = line.strip()
                if line.startswith("- ") or line.startswith("["):
                    topic = line.lstrip("- [").rstrip("]")
                    if topic and not topic.startswith("<!--"):
                        items.append({
                            "topic": topic,
                            "brief": topic,
                            "confidence": 0.7,
                        })
            if items:
                v4_categories[category] = items

        v4 = {"schema_version": "4.0", "meta": {}, "categories": v4_categories}
        return upgrade_v4_to_v5(v4)


class NotionAdapter(BaseAdapter):
    """Push: notion_page.md + notion_database.json. Pull: parse .json or .md back to nodes."""
    name = "notion"

    def push(
        self,
        graph: CortexGraph,
        policy: DisclosurePolicy,
        identity: UPAIIdentity | None = None,
        output_dir: Path = Path("."),
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        ctx = _graph_to_normalized(graph, policy)
        paths = []

        md = export_notion(ctx, policy.min_confidence)
        md_path = output_dir / "notion_page.md"
        md_path.write_text(md, encoding="utf-8")
        paths.append(md_path)

        db = export_notion_database_json(ctx, policy.min_confidence)
        db_path = output_dir / "notion_database.json"
        db_path.write_text(json.dumps(db, indent=2), encoding="utf-8")
        paths.append(db_path)

        return paths

    def pull(self, file_path: Path) -> CortexGraph:
        """Parse Notion export back into a CortexGraph.

        Detects format by extension:
        - .json  -> database rows (notion_database.json)
        - .md    -> markdown page (notion_page.md)
        """
        from cortex.compat import upgrade_v4_to_v5

        # Build reverse map: label -> category key
        from cortex.import_memory import CATEGORY_LABELS
        _label_to_cat: dict[str, str] = {v: k for k, v in CATEGORY_LABELS.items()}

        v4_categories: dict[str, list[dict]] = {}

        if file_path.suffix == ".json":
            # ---- Database JSON format ----
            raw = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("Expected a JSON list of row objects")

            for row in raw:
                label = row.get("Category", "mentions")
                category = _label_to_cat.get(label, label)
                topic_name = row.get("Topic", "").strip()
                if not topic_name:
                    continue

                brief = row.get("Brief", "") or ""
                full_desc = row.get("Full Description", "") or ""
                confidence = row.get("Confidence", 0.7)
                if not isinstance(confidence, (int, float)):
                    confidence = 0.7
                mention_count = row.get("Mention Count", 1)
                if not isinstance(mention_count, int):
                    mention_count = 1
                metrics = row.get("Metrics", []) or []
                if isinstance(metrics, str):
                    metrics = [m.strip() for m in metrics.split(",") if m.strip()]
                relationships = row.get("Relationships", []) or []
                if isinstance(relationships, str):
                    relationships = [r.strip() for r in relationships.split(",") if r.strip()]
                timeline_raw = row.get("Timeline", "") or ""
                timeline = [t.strip() for t in timeline_raw.split(",") if t.strip()] if isinstance(timeline_raw, str) else timeline_raw

                entry = {
                    "topic": topic_name,
                    "brief": brief if brief else topic_name,
                    "full_description": full_desc,
                    "confidence": confidence,
                    "mention_count": mention_count,
                    "extraction_method": "mentioned",
                    "metrics": metrics,
                    "relationships": relationships,
                    "timeline": timeline,
                    "source_quotes": [],
                    "first_seen": None,
                    "last_seen": None,
                    "relationship_type": "",
                }
                v4_categories.setdefault(category, []).append(entry)

        else:
            # ---- Markdown page format ----
            text = file_path.read_text(encoding="utf-8")
            current_category: str | None = None

            # Strip emoji prefixes used in headings (single codepoint or multi-byte)
            _emoji_strip = re.compile(
                r"^[\U0001f300-\U0001faff\u2600-\u27bf\u2700-\u27bf\u00a9\u00ae\u203c-\u3299\ufe0f\u200d\u20e3]*\s*"
            )

            for line in text.split("\n"):
                stripped = line.strip()

                # Category heading: ## {emoji} {Label}
                m_cat = re.match(r"^##\s+(.+)$", stripped)
                if m_cat and not stripped.startswith("###"):
                    heading_text = _emoji_strip.sub("", m_cat.group(1)).strip()
                    # Skip non-category headings
                    if heading_text in ("Summary", "Database Template"):
                        current_category = None
                        continue
                    category = _label_to_cat.get(heading_text, heading_text)
                    current_category = category
                    continue

                if current_category is None:
                    continue

                # Full-detail topic: ### {badge} {topic}
                m_full = re.match(r"^###\s+.?\s*(.+)$", stripped)
                if m_full:
                    topic_name = _emoji_strip.sub("", m_full.group(1)).strip()
                    if topic_name:
                        entry = {
                            "topic": topic_name,
                            "brief": topic_name,
                            "full_description": "",
                            "confidence": 0.9,
                            "mention_count": 1,
                            "extraction_method": "mentioned",
                            "metrics": [],
                            "relationships": [],
                            "timeline": [],
                            "source_quotes": [],
                            "first_seen": None,
                            "last_seen": None,
                            "relationship_type": "",
                        }
                        v4_categories.setdefault(current_category, []).append(entry)
                    continue

                # Description line right after a ### heading (no bullet/heading prefix)
                if (
                    not stripped.startswith("#")
                    and not stripped.startswith("-")
                    and not stripped.startswith("|")
                    and not stripped.startswith(">")
                    and stripped
                    and current_category in v4_categories
                    and v4_categories[current_category]
                ):
                    last = v4_categories[current_category][-1]
                    # Only fill if description is still empty and brief == topic
                    if not last["full_description"] and last["brief"] == last["topic"]:
                        last["full_description"] = stripped
                        last["brief"] = stripped
                        continue

                # Moderate-detail bullet: - {badge} **{topic}**: {brief}
                m_mod = re.match(r"^-\s+.?\s*\*\*(.+?)\*\*:\s*(.+)$", stripped)
                if m_mod:
                    topic_name = m_mod.group(1).strip()
                    brief = m_mod.group(2).strip()
                    if topic_name:
                        entry = {
                            "topic": topic_name,
                            "brief": brief,
                            "full_description": "",
                            "confidence": 0.7,
                            "mention_count": 1,
                            "extraction_method": "mentioned",
                            "metrics": [],
                            "relationships": [],
                            "timeline": [],
                            "source_quotes": [],
                            "first_seen": None,
                            "last_seen": None,
                            "relationship_type": "",
                        }
                        v4_categories.setdefault(current_category, []).append(entry)
                    continue

                # Minimal-detail bullet: - {badge} {topic}
                m_min = re.match(r"^-\s+.?\s*(.+)$", stripped)
                if m_min:
                    topic_name = _emoji_strip.sub("", m_min.group(1)).strip()
                    # Skip metadata bullets (Metrics:, Related:, Timeline:)
                    if topic_name.startswith("**Metrics:**") or topic_name.startswith("**Related:**") or topic_name.startswith("**Timeline:**"):
                        # Extract metadata into the last entry
                        if current_category in v4_categories and v4_categories[current_category]:
                            last = v4_categories[current_category][-1]
                            if topic_name.startswith("**Metrics:**"):
                                val = topic_name.split("**Metrics:**", 1)[1].strip()
                                last["metrics"] = [m.strip() for m in val.split(",") if m.strip()]
                            elif topic_name.startswith("**Related:**"):
                                val = topic_name.split("**Related:**", 1)[1].strip()
                                last["relationships"] = [r.strip() for r in val.split(",") if r.strip()]
                            elif topic_name.startswith("**Timeline:**"):
                                val = topic_name.split("**Timeline:**", 1)[1].strip()
                                last["timeline"] = [t.strip() for t in val.split(",") if t.strip()]
                        continue
                    if topic_name:
                        entry = {
                            "topic": topic_name,
                            "brief": topic_name,
                            "full_description": "",
                            "confidence": 0.5,
                            "mention_count": 1,
                            "extraction_method": "mentioned",
                            "metrics": [],
                            "relationships": [],
                            "timeline": [],
                            "source_quotes": [],
                            "first_seen": None,
                            "last_seen": None,
                            "relationship_type": "",
                        }
                        v4_categories.setdefault(current_category, []).append(entry)

        v4 = {"schema_version": "4.0", "meta": {}, "categories": v4_categories}
        return upgrade_v4_to_v5(v4)


class GDocsAdapter(BaseAdapter):
    """Push: google_docs.html. Pull: parse HTML back to nodes."""
    name = "gdocs"

    def push(
        self,
        graph: CortexGraph,
        policy: DisclosurePolicy,
        identity: UPAIIdentity | None = None,
        output_dir: Path = Path("."),
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        ctx = _graph_to_normalized(graph, policy)

        html = export_google_docs(ctx, policy.min_confidence)
        path = output_dir / "google_docs.html"
        path.write_text(html, encoding="utf-8")
        return [path]

    def pull(self, file_path: Path) -> CortexGraph:
        """Parse Google Docs HTML export back into a CortexGraph.

        Parses the HTML produced by export_google_docs():
        - <h2> tags -> category headings
        - <h3> tags -> high-confidence topics
        - <p><strong>...</strong>: ...</p> -> medium-confidence topics
        - <p class='low'>...</p> -> low-confidence topics
        """
        from cortex.compat import upgrade_v4_to_v5
        from cortex.import_memory import CATEGORY_LABELS

        _label_to_cat: dict[str, str] = {v: k for k, v in CATEGORY_LABELS.items()}

        text = file_path.read_text(encoding="utf-8")
        v4_categories: dict[str, list[dict]] = {}
        current_category: str | None = None

        # Helper to strip HTML tags from a string
        def _strip_tags(s: str) -> str:
            return re.sub(r"<[^>]+>", "", s).strip()

        for line in text.split("\n"):
            stripped = line.strip()

            # Category heading: <h2>Label</h2>
            m_h2 = re.match(r"<h2>(.+?)</h2>", stripped)
            if m_h2:
                label = _strip_tags(m_h2.group(1)).strip()
                if label == "Summary":
                    current_category = None
                    continue
                category = _label_to_cat.get(label, label)
                current_category = category
                continue

            if current_category is None:
                continue

            # High-confidence topic: <h3>{topic} <span...>High</span></h3>
            m_h3 = re.match(r"<h3>(.+?)\s*<span[^>]*>.*?</span></h3>", stripped)
            if m_h3:
                topic_name = _strip_tags(m_h3.group(1)).strip()
                if topic_name:
                    entry = {
                        "topic": topic_name,
                        "brief": topic_name,
                        "full_description": "",
                        "confidence": 0.9,
                        "mention_count": 1,
                        "extraction_method": "mentioned",
                        "metrics": [],
                        "relationships": [],
                        "timeline": [],
                        "source_quotes": [],
                        "first_seen": None,
                        "last_seen": None,
                        "relationship_type": "",
                    }
                    v4_categories.setdefault(current_category, []).append(entry)
                continue

            # Description paragraph after <h3> (no <strong>, no class='low')
            m_desc = re.match(r"<p>([^<]+)</p>", stripped)
            if m_desc and "class=" not in stripped and "<strong>" not in stripped:
                desc = m_desc.group(1).strip()
                if current_category in v4_categories and v4_categories[current_category]:
                    last = v4_categories[current_category][-1]
                    if not last["full_description"] and last["brief"] == last["topic"]:
                        last["full_description"] = desc
                        last["brief"] = desc
                continue

            # Metrics line: <p><strong>Metrics:</strong> ...
            m_metrics = re.match(r"<p><strong>Metrics:</strong>\s*", stripped)
            if m_metrics and current_category in v4_categories and v4_categories[current_category]:
                last = v4_categories[current_category][-1]
                metrics_text = re.findall(r"<span class='metric'>(.+?)</span>", stripped)
                last["metrics"] = [_strip_tags(m) for m in metrics_text]
                continue

            # Related line: <p><strong>Related:</strong> ...
            m_rel = re.match(r"<p><strong>Related:</strong>\s*(.+?)</p>", stripped)
            if m_rel and current_category in v4_categories and v4_categories[current_category]:
                last = v4_categories[current_category][-1]
                val = _strip_tags(m_rel.group(1))
                last["relationships"] = [r.strip() for r in val.split(",") if r.strip()]
                continue

            # Timeline line: <p><strong>Timeline:</strong> ...
            m_tl = re.match(r"<p><strong>Timeline:</strong>\s*(.+?)</p>", stripped)
            if m_tl and current_category in v4_categories and v4_categories[current_category]:
                last = v4_categories[current_category][-1]
                val = _strip_tags(m_tl.group(1))
                last["timeline"] = [t.strip() for t in val.split(",") if t.strip()]
                continue

            # Medium-confidence topic: <p><strong>{topic}</strong> <span...>Medium</span>: {brief}</p>
            m_med = re.match(r"<p><strong>(.+?)</strong>\s*<span[^>]*>.*?</span>:\s*(.+?)</p>", stripped)
            if m_med:
                topic_name = _strip_tags(m_med.group(1)).strip()
                brief = _strip_tags(m_med.group(2)).strip()
                if topic_name:
                    entry = {
                        "topic": topic_name,
                        "brief": brief,
                        "full_description": "",
                        "confidence": 0.7,
                        "mention_count": 1,
                        "extraction_method": "mentioned",
                        "metrics": [],
                        "relationships": [],
                        "timeline": [],
                        "source_quotes": [],
                        "first_seen": None,
                        "last_seen": None,
                        "relationship_type": "",
                    }
                    v4_categories.setdefault(current_category, []).append(entry)
                continue

            # Low-confidence topic: <p class='low'>{topic} <span...>Low</span></p>
            m_low = re.match(r"<p class='low'>(.+?)\s*<span[^>]*>.*?</span></p>", stripped)
            if m_low:
                topic_name = _strip_tags(m_low.group(1)).strip()
                if topic_name:
                    entry = {
                        "topic": topic_name,
                        "brief": topic_name,
                        "full_description": "",
                        "confidence": 0.5,
                        "mention_count": 1,
                        "extraction_method": "mentioned",
                        "metrics": [],
                        "relationships": [],
                        "timeline": [],
                        "source_quotes": [],
                        "first_seen": None,
                        "last_seen": None,
                        "relationship_type": "",
                    }
                    v4_categories.setdefault(current_category, []).append(entry)
                continue

        v4 = {"schema_version": "4.0", "meta": {}, "categories": v4_categories}
        return upgrade_v4_to_v5(v4)


ADAPTERS: dict[str, BaseAdapter] = {
    "claude": ClaudeAdapter(),
    "system-prompt": SystemPromptAdapter(),
    "notion": NotionAdapter(),
    "gdocs": GDocsAdapter(),
}
