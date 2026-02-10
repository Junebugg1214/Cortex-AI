#!/usr/bin/env python3
"""
Tests for Cortex Phase 2: Timeline Generator (v5.1)

Covers:
- Event extraction from node timestamps
- Event extraction from snapshots
- Chronological sorting
- Date range filtering (--from, --to)
- Markdown output format
- HTML output format
- Empty graph produces empty timeline
- Nodes without dates are excluded
"""
from __future__ import annotations

import sys

from cortex.graph import CortexGraph, Node, make_node_id
from cortex.timeline import TimelineGenerator


# ============================================================================
# Helpers
# ============================================================================

def _make_graph(*nodes: Node) -> CortexGraph:
    g = CortexGraph()
    for n in nodes:
        g.add_node(n)
    return g


def _make_node(label: str, first_seen: str = "", last_seen: str = "",
               tags: list[str] | None = None, confidence: float = 0.5,
               snapshots: list[dict] | None = None) -> Node:
    nid = make_node_id(label)
    return Node(
        id=nid, label=label,
        tags=tags or ["technical_expertise"],
        confidence=confidence,
        first_seen=first_seen,
        last_seen=last_seen,
        snapshots=snapshots or [],
    )


# ============================================================================
# Event extraction
# ============================================================================

class TestEventExtraction:

    def test_extract_first_seen_event(self):
        node = _make_node("Python", first_seen="2025-01-15T00:00:00Z")
        g = _make_graph(node)
        gen = TimelineGenerator()
        events = gen.generate(g)
        assert len(events) == 1
        assert events[0]["event_type"] == "first_seen"
        assert events[0]["label"] == "Python"

    def test_extract_both_first_and_last_seen(self):
        node = _make_node("Python",
                          first_seen="2025-01-15T00:00:00Z",
                          last_seen="2025-06-15T00:00:00Z")
        g = _make_graph(node)
        gen = TimelineGenerator()
        events = gen.generate(g)
        assert len(events) == 2
        assert events[0]["event_type"] == "first_seen"
        assert events[1]["event_type"] == "last_seen"

    def test_no_duplicate_when_first_equals_last(self):
        """When first_seen == last_seen, only emit first_seen."""
        node = _make_node("Python",
                          first_seen="2025-01-15T00:00:00Z",
                          last_seen="2025-01-15T00:00:00Z")
        g = _make_graph(node)
        gen = TimelineGenerator()
        events = gen.generate(g)
        assert len(events) == 1
        assert events[0]["event_type"] == "first_seen"

    def test_extract_snapshot_events(self):
        snapshots = [
            {"timestamp": "2025-02-01T00:00:00Z", "source": "extraction",
             "confidence": 0.8, "tags": ["technical_expertise"],
             "properties_hash": "a", "description_hash": "b"},
        ]
        node = _make_node("Python", snapshots=snapshots)
        g = _make_graph(node)
        gen = TimelineGenerator()
        events = gen.generate(g)
        assert len(events) == 1
        assert events[0]["event_type"] == "snapshot"
        assert events[0]["details"]["source"] == "extraction"

    def test_nodes_without_dates_excluded(self):
        """Nodes with no first_seen, last_seen, or snapshots produce no events."""
        node = _make_node("Python")
        g = _make_graph(node)
        gen = TimelineGenerator()
        events = gen.generate(g)
        assert len(events) == 0


# ============================================================================
# Chronological sorting
# ============================================================================

class TestChronologicalSorting:

    def test_events_sorted_chronologically(self):
        node_a = _make_node("Python", first_seen="2025-03-01T00:00:00Z")
        node_b = _make_node("Django", first_seen="2025-01-01T00:00:00Z")
        node_c = _make_node("REST APIs", first_seen="2025-02-01T00:00:00Z")
        g = _make_graph(node_a, node_b, node_c)
        gen = TimelineGenerator()
        events = gen.generate(g)
        timestamps = [e["timestamp"] for e in events]
        assert timestamps == sorted(timestamps)

    def test_mixed_event_types_sorted(self):
        node = _make_node("Python",
                          first_seen="2025-01-01T00:00:00Z",
                          last_seen="2025-06-01T00:00:00Z",
                          snapshots=[
                              {"timestamp": "2025-03-01T00:00:00Z", "source": "merge",
                               "confidence": 0.7, "tags": ["technical_expertise"],
                               "properties_hash": "a", "description_hash": "b"},
                          ])
        g = _make_graph(node)
        gen = TimelineGenerator()
        events = gen.generate(g)
        assert len(events) == 3
        assert events[0]["event_type"] == "first_seen"
        assert events[1]["event_type"] == "snapshot"
        assert events[2]["event_type"] == "last_seen"


# ============================================================================
# Date range filtering
# ============================================================================

class TestDateRangeFiltering:

    def test_from_date_filter(self):
        node_a = _make_node("Python", first_seen="2025-01-01T00:00:00Z")
        node_b = _make_node("Django", first_seen="2025-06-01T00:00:00Z")
        g = _make_graph(node_a, node_b)
        gen = TimelineGenerator()
        events = gen.generate(g, from_date="2025-03-01T00:00:00Z")
        assert len(events) == 1
        assert events[0]["label"] == "Django"

    def test_to_date_filter(self):
        node_a = _make_node("Python", first_seen="2025-01-01T00:00:00Z")
        node_b = _make_node("Django", first_seen="2025-06-01T00:00:00Z")
        g = _make_graph(node_a, node_b)
        gen = TimelineGenerator()
        events = gen.generate(g, to_date="2025-03-01T00:00:00Z")
        assert len(events) == 1
        assert events[0]["label"] == "Python"

    def test_from_and_to_date_filter(self):
        node_a = _make_node("Python", first_seen="2025-01-01T00:00:00Z")
        node_b = _make_node("Django", first_seen="2025-03-01T00:00:00Z")
        node_c = _make_node("REST APIs", first_seen="2025-06-01T00:00:00Z")
        g = _make_graph(node_a, node_b, node_c)
        gen = TimelineGenerator()
        events = gen.generate(g,
                              from_date="2025-02-01T00:00:00Z",
                              to_date="2025-04-01T00:00:00Z")
        assert len(events) == 1
        assert events[0]["label"] == "Django"


# ============================================================================
# Markdown output
# ============================================================================

class TestMarkdownOutput:

    def test_markdown_output_basic(self):
        node = _make_node("Python", first_seen="2025-01-15T00:00:00Z")
        g = _make_graph(node)
        gen = TimelineGenerator()
        events = gen.generate(g)
        md = gen.to_markdown(events)
        assert "# Timeline" in md
        assert "## 2025-01-15" in md
        assert "**Python**" in md
        assert "first appeared" in md

    def test_markdown_empty_events(self):
        gen = TimelineGenerator()
        md = gen.to_markdown([])
        assert "# Timeline" in md
        assert "No events found" in md

    def test_markdown_snapshot_event(self):
        events = [{
            "timestamp": "2025-02-01T00:00:00Z",
            "event_type": "snapshot",
            "node_id": "abc",
            "label": "Python",
            "tags": ["technical_expertise"],
            "details": {"source": "extraction", "confidence": 0.85},
        }]
        gen = TimelineGenerator()
        md = gen.to_markdown(events)
        assert "snapshot from extraction" in md
        assert "0.85" in md


# ============================================================================
# HTML output
# ============================================================================

class TestHTMLOutput:

    def test_html_output_basic(self):
        node = _make_node("Python", first_seen="2025-01-15T00:00:00Z")
        g = _make_graph(node)
        gen = TimelineGenerator()
        events = gen.generate(g)
        html = gen.to_html(events)
        assert "<html>" in html
        assert "Timeline" in html
        assert "Python" in html
        assert "first_seen" in html  # CSS class

    def test_html_empty_events(self):
        gen = TimelineGenerator()
        html = gen.to_html([])
        assert "<html>" in html
        assert "No events found" in html

    def test_html_escapes_special_chars(self):
        events = [{
            "timestamp": "2025-01-01T00:00:00Z",
            "event_type": "first_seen",
            "node_id": "abc",
            "label": "C++ & <Templates>",
            "tags": ["technical_expertise"],
            "details": {"confidence": 0.5, "brief": ""},
        }]
        gen = TimelineGenerator()
        html = gen.to_html(events)
        assert "&amp;" in html
        assert "&lt;Templates&gt;" in html


# ============================================================================
# Empty graph
# ============================================================================

class TestEmptyGraph:

    def test_empty_graph_produces_no_events(self):
        g = CortexGraph()
        gen = TimelineGenerator()
        events = gen.generate(g)
        assert events == []


# ============================================================================
# Run with pytest or standalone
# ============================================================================

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
