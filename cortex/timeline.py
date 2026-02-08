"""
Timeline Generator — Chronological event extraction from CortexGraph (v5.1)

Extracts events from node first_seen/last_seen timestamps and snapshots,
with markdown and HTML output formats.
"""

from __future__ import annotations

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
            - event_type: str ("first_seen", "last_seen", "snapshot")
            - node_id: str
            - label: str
            - tags: list[str]
            - details: dict (extra context depending on event type)

        Returns sorted by timestamp ascending.
        """
        events: list[dict] = []

        for node in graph.nodes.values():
            # first_seen event
            if node.first_seen:
                events.append({
                    "timestamp": node.first_seen,
                    "event_type": "first_seen",
                    "node_id": node.id,
                    "label": node.label,
                    "tags": list(node.tags),
                    "details": {
                        "confidence": node.confidence,
                        "brief": node.brief,
                    },
                })

            # last_seen event (only if different from first_seen)
            if node.last_seen and node.last_seen != node.first_seen:
                events.append({
                    "timestamp": node.last_seen,
                    "event_type": "last_seen",
                    "node_id": node.id,
                    "label": node.label,
                    "tags": list(node.tags),
                    "details": {
                        "confidence": node.confidence,
                        "brief": node.brief,
                    },
                })

            # Snapshot events
            snapshots = node.snapshots if hasattr(node, "snapshots") else []
            for snap in snapshots:
                ts = snap.get("timestamp", "")
                if not ts:
                    continue
                events.append({
                    "timestamp": ts,
                    "event_type": "snapshot",
                    "node_id": node.id,
                    "label": node.label,
                    "tags": snap.get("tags", list(node.tags)),
                    "details": {
                        "source": snap.get("source", "unknown"),
                        "confidence": snap.get("confidence", node.confidence),
                    },
                })

        # Filter by date range
        if from_date:
            events = [e for e in events if e["timestamp"] >= from_date]
        if to_date:
            events = [e for e in events if e["timestamp"] <= to_date]

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
            elif etype == "snapshot":
                source = event["details"].get("source", "unknown")
                conf = event["details"].get("confidence", 0.0)
                lines.append(
                    f"- **{label}** snapshot from {source} "
                    f"(confidence: {conf:.2f}) [{tags}]"
                )

        lines.append("")
        return "\n".join(lines)

    def to_html(self, events: list[dict]) -> str:
        """Render events as simple HTML timeline."""
        if not events:
            return (
                "<html><body><h1>Timeline</h1>"
                "<p>No events found.</p></body></html>"
            )

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
            else:
                source = event["details"].get("source", "unknown")
                conf = event["details"].get("confidence", 0.0)
                desc = (
                    f"<strong>{label}</strong> snapshot from {_html_escape(source)} "
                    f"(confidence: {conf:.2f})"
                )

            parts.append(
                f'<div class="event {etype}">'
                f'{desc} <span class="tags">[{_html_escape(tags)}]</span>'
                f'</div>'
            )

        parts.append("</body></html>")
        return "\n".join(parts)


def _html_escape(s: str) -> str:
    """Basic HTML escaping."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
