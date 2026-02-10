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
    envelope: dict = {
        "upai_version": "5.2",
        "exported_at": datetime.now(timezone.utc).isoformat(),
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

        # Handle UPAI envelope
        if isinstance(raw, dict) and "data" in raw:
            memories = raw["data"]
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
    """Push: notion_page.md + notion_database.json. Pull: not yet supported."""
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
        raise NotImplementedError("Notion pull not yet supported")


class GDocsAdapter(BaseAdapter):
    """Push: google_docs.html. Pull: not yet supported."""
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
        raise NotImplementedError("GDocs pull not yet supported")


ADAPTERS: dict[str, BaseAdapter] = {
    "claude": ClaudeAdapter(),
    "system-prompt": SystemPromptAdapter(),
    "notion": NotionAdapter(),
    "gdocs": GDocsAdapter(),
}
