"""Cortex CaaS — API Key management for shareable memory endpoints."""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cortex.graph import CortexGraph


# ── Builtin policy tag sets ─────────────────────────────────────────

POLICY_TAGS: dict[str, list[str] | None] = {
    "full": None,           # None → no tag filter (all tags)
    "professional": [
        "identity", "professional_context", "business_context",
        "technical_expertise", "active_priorities",
        "work_history", "education_history",
    ],
    "technical": [
        "technical_expertise", "domain_knowledge", "active_priorities",
    ],
    "minimal": [
        "identity", "communication_preferences",
    ],
}


# ── ApiKeyStore ──────────────────────────────────────────────────────

class ApiKeyStore:
    """File-backed JSON store for shareable memory API keys."""

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path else None
        self._keys: dict[str, dict[str, Any]] = {}
        if self._path and self._path.exists():
            self._load()

    # ── persistence ──────────────────────────────────────────────

    def _load(self) -> None:
        if self._path is None:
            return
        try:
            data = json.loads(self._path.read_text())
            self._keys = data.get("keys", {})
        except (json.JSONDecodeError, OSError):
            self._keys = {}
        # Migrate legacy entries that store raw key_secret
        self._migrate_legacy_keys()

    def _migrate_legacy_keys(self) -> None:
        """Migrate old entries with plaintext key_secret to hashed storage."""
        migrated = False
        for entry in self._keys.values():
            if "key_secret" in entry and "key_hash" not in entry:
                raw_secret = entry["key_secret"]
                entry["key_hash"] = hashlib.sha256(raw_secret.encode()).hexdigest()
                del entry["key_secret"]
                migrated = True
        if migrated:
            self._save()

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"keys": self._keys}, indent=2,
                                         default=str))

    # ── CRUD ─────────────────────────────────────────────────────

    def create(self, label: str, policy: str, tags: list[str] | None = None,
               fmt: str = "json") -> dict:
        """Create a new API key. Returns the full key info (secret shown once)."""
        key_id = secrets.token_hex(4)
        key_secret_part = secrets.token_hex(16)
        key_secret = f"cmk_{key_id}_{key_secret_part}"

        now = datetime.now(timezone.utc).isoformat()
        key_hash = hashlib.sha256(key_secret.encode()).hexdigest()
        entry: dict[str, Any] = {
            "key_id": key_id,
            "key_hash": key_hash,
            "label": label,
            "policy": policy,
            "tags": tags or [],
            "format": fmt,
            "created_at": now,
            "last_used": None,
            "active": True,
        }
        self._keys[key_id] = entry
        self._save()
        # Return a copy with the raw secret included (shown once)
        result = dict(entry)
        result["key_secret"] = key_secret
        return result

    def list_keys(self) -> list[dict]:
        """List all keys with hash preview."""
        result = []
        for entry in self._keys.values():
            masked = dict(entry)
            key_hash = masked.get("key_hash", "")
            if key_hash:
                masked["key_hash"] = key_hash[:12] + "..."
            # Remove raw secret if it somehow exists
            masked.pop("key_secret", None)
            result.append(masked)
        return result

    def get_by_secret(self, key_secret: str) -> dict | None:
        """Look up a key by its full secret. Updates last_used. Returns None if revoked.

        Scans all entries and uses constant-time comparison to prevent timing leaks.
        """
        input_hash = hashlib.sha256(key_secret.encode()).hexdigest()
        matched_entry: dict[str, Any] | None = None
        # Scan ALL entries to prevent timing leaks on which entry matched
        for entry in self._keys.values():
            stored_hash = entry.get("key_hash", "")
            if _hmac.compare_digest(input_hash, stored_hash) and entry.get("active"):
                matched_entry = entry
        if matched_entry is not None:
            matched_entry["last_used"] = datetime.now(timezone.utc).isoformat()
            self._save()
            return dict(matched_entry)
        return None

    def revoke(self, key_id: str) -> bool:
        """Mark a key as inactive. Returns True if found."""
        if key_id in self._keys:
            self._keys[key_id]["active"] = False
            self._save()
            return True
        return False


# ── Memory rendering ─────────────────────────────────────────────────

def get_disclosed_graph(graph: CortexGraph, policy_name: str,
                        tags: list[str] | None) -> CortexGraph:
    """Apply disclosure policy to *graph* and return the filtered copy.

    This is the security boundary — all public endpoints should call this
    before exposing any graph data.
    """
    from cortex.upai.disclosure import DisclosurePolicy, apply_disclosure

    if policy_name == "custom" and tags:
        policy = DisclosurePolicy(
            name="custom",
            include_tags=list(tags),
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )
    elif policy_name in POLICY_TAGS:
        include = POLICY_TAGS[policy_name]
        policy = DisclosurePolicy(
            name=policy_name,
            include_tags=include or [],
            exclude_tags=[],
            min_confidence=0.0 if policy_name == "full" else 0.5,
            redact_properties=[],
        )
    else:
        policy = DisclosurePolicy(
            name="full",
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )

    return apply_disclosure(graph, policy)


def render_memory(graph: CortexGraph, policy_name: str,
                  tags: list[str] | None, fmt: str) -> tuple[str, str]:
    """Filter graph by policy/tags and render in the requested format.

    Returns ``(content_string, content_type_header)``.
    """
    filtered = get_disclosed_graph(graph, policy_name, tags)

    if fmt == "json":
        return json.dumps(filtered.export_v5(), indent=2, default=str), "application/json"
    elif fmt == "claude_xml":
        return _render_claude_xml(filtered), "application/xml"
    elif fmt == "system_prompt":
        return _render_system_prompt(filtered), "text/plain"
    elif fmt == "markdown":
        return _render_markdown(filtered), "text/markdown"
    elif fmt == "jsonresume":
        from cortex.caas.jsonresume import graph_to_jsonresume
        resume = graph_to_jsonresume(filtered)
        return json.dumps(resume, indent=2, default=str), "application/json"
    else:
        return json.dumps(filtered.export_v5(), indent=2, default=str), "application/json"


def _render_claude_xml(graph: CortexGraph) -> str:
    """Render graph as Claude-compatible XML."""
    lines = ["<user-context>"]
    for node in graph.nodes.values():
        tags_str = ",".join(node.tags) if node.tags else ""
        brief = f": {node.brief}" if node.brief else ""
        label = node.label or node.id
        lines.append(f'  <fact tags="{tags_str}">{label}{brief}</fact>')
    lines.append("</user-context>")
    return "\n".join(lines)


def _render_system_prompt(graph: CortexGraph) -> str:
    """Render graph as a system-prompt-friendly text block."""
    lines = ["# User Context", ""]
    for node in graph.nodes.values():
        tags_str = " [" + ", ".join(node.tags) + "]" if node.tags else ""
        brief = f" — {node.brief}" if node.brief else ""
        lines.append(f"- {node.label}{brief}{tags_str}")
    return "\n".join(lines)


def _render_markdown(graph: CortexGraph) -> str:
    """Render graph as a Markdown document grouped by tag."""
    categories: dict[str, list[str]] = {}
    for node in graph.nodes.values():
        tag = node.tags[0] if node.tags else "other"
        brief = f" — {node.brief}" if node.brief else ""
        categories.setdefault(tag, []).append(f"- {node.label}{brief}")

    lines = ["# Knowledge Graph", ""]
    for cat, items in sorted(categories.items()):
        lines.append(f"## {cat.replace('_', ' ').title()}")
        lines.extend(items)
        lines.append("")

    return "\n".join(lines)
