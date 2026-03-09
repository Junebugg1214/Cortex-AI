#!/usr/bin/env python3
"""
Chatbot Memory — end-to-end example.

Demonstrates the full Cortex pipeline:
1. Extract context from a chat export
2. Load it into a graph
3. Query the knowledge graph

Prerequisites:
    pip install cortex-ai

Usage:
    python examples/chatbot-memory/main.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


def create_sample_export() -> Path:
    """Create a minimal chat export for demonstration."""
    export = {
        "conversations": [
            {
                "title": "Tech Discussion",
                "messages": [
                    {"role": "user", "content": "I've been learning Python for 3 years now"},
                    {"role": "assistant", "content": "That's great! Python is versatile."},
                    {"role": "user", "content": "I work at Acme Corp as a senior developer"},
                    {"role": "assistant", "content": "Senior developer roles involve architecture decisions."},
                    {"role": "user", "content": "I'm interested in machine learning and NLP"},
                    {"role": "assistant", "content": "ML and NLP are exciting fields."},
                ],
            },
        ]
    }
    tmp = Path(tempfile.mkdtemp()) / "chat_export.json"
    tmp.write_text(json.dumps(export, indent=2))
    return tmp


def main():
    from cortex.extract_memory import extract_context
    from cortex.graph import CortexGraph

    # Step 1: Create sample data
    export_path = create_sample_export()
    print(f"1. Created sample export: {export_path}")

    # Step 2: Extract context
    data = json.loads(export_path.read_text())
    context = extract_context(data, source_format="auto")
    print(f"2. Extracted context: {len(context.get('nodes', []))} nodes, {len(context.get('edges', []))} edges")

    # Step 3: Load into graph
    graph = CortexGraph.from_v5_json(context)
    print(f"3. Graph loaded: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    # Step 4: Search
    results = graph.search_nodes("Python")
    print(f"4. Search 'Python': {len(results)} results")
    for node in results[:3]:
        print(f"   - {node.label}: {node.brief}")

    # Step 5: Stats
    stats = graph.get_stats()
    print(f"5. Stats: {stats}")

    print("\nDone! To continue with the CLI, run:")
    print(f"  cortex extract {export_path} -o context.json")


if __name__ == "__main__":
    main()
