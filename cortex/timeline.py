"""
Timeline Generator — Chronological event extraction from CortexGraph (v5.1)

Extracts events from node first_seen/last_seen timestamps and snapshots,
with markdown and HTML output formats.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cortex.graph import CortexGraph


class TimelineGenerator:
    """Generate chronological timelines from a CortexGraph."""

    def generate(
        self,
        graph: CortexGraph,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict]:
        """Extract chronological events from node timestamps and snapshots.

        Each event dict has:
            - timestamp: str (ISO-8601)
            - event_type: str ("first_seen", "last_seen", "valid_from", "valid_to", "snapshot")
            - node_id: str
            - label: str
            - tags: list[str]
            - details: dict (extra context depending on event type)

        Returns sorted by timestamp ascending.
        """
        events: list[dict] = []
        normalized_from = _normalize_timestamp(from_date) if from_date else None
        normalized_to = _normalize_timestamp(to_date) if to_date else None

        for node in graph.nodes.values():
            first_seen = _normalize_timestamp(node.first_seen) if node.first_seen else ""
            last_seen = _normalize_timestamp(node.last_seen) if node.last_seen else ""

            # first_seen event
            if first_seen:
                events.append(
                    {
                        "timestamp": first_seen,
                        "event_type": "first_seen",
                        "node_id": node.id,
                        "label": node.label,
                        "tags": list(node.tags),
                        "details": {
                            "confidence": node.confidence,
                            "brief": node.brief,
                        },
                    }
                )

            # last_seen event (only if different from first_seen)
            if last_seen and last_seen != first_seen:
                events.append(
                    {
                        "timestamp": last_seen,
                        "event_type": "last_seen",
                        "node_id": node.id,
                        "label": node.label,
                        "tags": list(node.tags),
                        "details": {
                            "confidence": node.confidence,
                            "brief": node.brief,
                        },
                    }
                )

            valid_from = _normalize_timestamp(node.valid_from) if getattr(node, "valid_from", "") else ""
            valid_to = _normalize_timestamp(node.valid_to) if getattr(node, "valid_to", "") else ""

            if valid_from and valid_from not in {first_seen, last_seen}:
                events.append(
                    {
                        "timestamp": valid_from,
                        "event_type": "valid_from",
                        "node_id": node.id,
                        "label": node.label,
                        "tags": list(node.tags),
                        "details": {
                            "status": getattr(node, "status", ""),
                            "confidence": node.confidence,
                        },
                    }
                )

            if valid_to and valid_to not in {first_seen, last_seen, valid_from}:
                events.append(
                    {
                        "timestamp": valid_to,
                        "event_type": "valid_to",
                        "node_id": node.id,
                        "label": node.label,
                        "tags": list(node.tags),
                        "details": {
                            "status": getattr(node, "status", ""),
                            "confidence": node.confidence,
                        },
                    }
                )

            # Snapshot events
            snapshots = node.snapshots if hasattr(node, "snapshots") else []
            for snap in snapshots:
                ts = _normalize_timestamp(snap.get("timestamp", ""))
                if not ts:
                    continue
                events.append(
                    {
                        "timestamp": ts,
                        "event_type": "snapshot",
                        "node_id": node.id,
                        "label": node.label,
                        "tags": snap.get("tags", list(node.tags)),
                        "details": {
                            "source": snap.get("source", "unknown"),
                            "confidence": snap.get("confidence", node.confidence),
                        },
                    }
                )

        # Filter by date range
        if normalized_from:
            events = [e for e in events if e["timestamp"] >= normalized_from]
        if normalized_to:
            events = [e for e in events if e["timestamp"] <= normalized_to]

        # Sort chronologically
        events.sort(key=lambda e: e["timestamp"])
        return events

    def to_markdown(self, events: list[dict]) -> str:
        """Render events as a markdown timeline."""
        if not events:
            return "# Timeline\n\nNo events found.\n"

        lines = ["# Timeline", ""]
        current_date = ""

        for event in events:
            ts = event["timestamp"]
            date_part = ts[:10] if len(ts) >= 10 else ts

            if date_part != current_date:
                current_date = date_part
                lines.append(f"## {current_date}")
                lines.append("")

            etype = event["event_type"]
            label = event["label"]
            tags = ", ".join(event["tags"]) if event["tags"] else "untagged"

            if etype == "first_seen":
                lines.append(f"- **{label}** first appeared [{tags}]")
            elif etype == "last_seen":
                lines.append(f"- **{label}** last seen [{tags}]")
            elif etype == "valid_from":
                status = event["details"].get("status", "active") or "active"
                lines.append(f"- **{label}** became valid as {status} [{tags}]")
            elif etype == "valid_to":
                status = event["details"].get("status", "historical") or "historical"
                lines.append(f"- **{label}** stopped being valid as {status} [{tags}]")
            elif etype == "snapshot":
                source = event["details"].get("source", "unknown")
                conf = event["details"].get("confidence", 0.0)
                lines.append(f"- **{label}** snapshot from {source} (confidence: {conf:.2f}) [{tags}]")

        lines.append("")
        return "\n".join(lines)

    def to_html(self, events: list[dict]) -> str:
        """Render events as simple HTML timeline."""
        if not events:
            return "<html><body><h1>Timeline</h1><p>No events found.</p></body></html>"

        parts = [
            "<html><head><style>",
            "body { font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }",
            ".event { border-left: 3px solid #4a90d9; padding: 8px 16px; margin: 8px 0; }",
            ".date { font-weight: bold; color: #333; margin-top: 16px; }",
            ".tags { color: #666; font-size: 0.9em; }",
            ".first_seen { border-left-color: #2ecc71; }",
            ".last_seen { border-left-color: #e74c3c; }",
            ".snapshot { border-left-color: #f39c12; }",
            "</style></head><body>",
            "<h1>Timeline</h1>",
        ]

        current_date = ""
        for event in events:
            ts = event["timestamp"]
            date_part = ts[:10] if len(ts) >= 10 else ts

            if date_part != current_date:
                current_date = date_part
                parts.append(f'<div class="date">{current_date}</div>')

            etype = event["event_type"]
            label = _html_escape(event["label"])
            tags = ", ".join(event["tags"]) if event["tags"] else "untagged"

            if etype == "first_seen":
                desc = f"<strong>{label}</strong> first appeared"
            elif etype == "last_seen":
                desc = f"<strong>{label}</strong> last seen"
            elif etype == "valid_from":
                status = _html_escape(event["details"].get("status", "active") or "active")
                desc = f"<strong>{label}</strong> became valid as {status}"
            elif etype == "valid_to":
                status = _html_escape(event["details"].get("status", "historical") or "historical")
                desc = f"<strong>{label}</strong> stopped being valid as {status}"
            else:
                source = event["details"].get("source", "unknown")
                conf = event["details"].get("confidence", 0.0)
                desc = f"<strong>{label}</strong> snapshot from {_html_escape(source)} (confidence: {conf:.2f})"

            parts.append(f'<div class="event {etype}">{desc} <span class="tags">[{_html_escape(tags)}]</span></div>')

        parts.append("</body></html>")
        return "\n".join(parts)


def _html_escape(s: str) -> str:
    """Basic HTML escaping."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _normalize_timestamp(timestamp: str | None) -> str:
    """Normalize supported ISO-8601 timestamps to canonical UTC."""
    if not timestamp:
        return ""

    value = timestamp.strip()
    if not value:
        return ""

    try:
        normalized = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value

    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    else:
        normalized = normalized.astimezone(timezone.utc)

    return normalized.isoformat().replace("+00:00", "Z")
