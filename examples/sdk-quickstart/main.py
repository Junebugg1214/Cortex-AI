#!/usr/bin/env python3
"""
SDK Quickstart — Python SDK usage examples.

Demonstrates the Python SDK client for interacting with a running
CaaS server. Covers both sync operations and pagination.

Prerequisites:
    pip install cortex-ai-sdk
    # Start a CaaS server first:
    cortex serve context.json

Usage:
    python examples/sdk-quickstart/main.py
"""

from __future__ import annotations

# NOTE: This example requires a running CaaS server.
# It shows the API surface — uncomment to run against a live server.


def sync_example():
    """Demonstrate synchronous SDK usage."""
    from cortex_sdk import CortexClient

    # Connect to a local CaaS server
    client = CortexClient(base_url="http://localhost:8421", token="YOUR_GRANT_TOKEN")

    # Server info
    info = client.info()
    print(f"Server: {info.get('name', 'unknown')} v{info.get('version', '?')}")

    # Health check (no auth required)
    health = client.health()
    print(f"Health: {health['status']}")

    # Get context stats
    stats = client.stats()
    print(f"Stats: {stats['node_count']} nodes, {stats['edge_count']} edges")

    # Paginated nodes
    for page in client.nodes(page_size=10):
        for node in page.get("items", []):
            print(f"  Node: {node['label']}")

    # Single node
    # node = client.node("node-id-here")

    # Create a webhook
    # webhook = client.create_webhook(url="https://example.com/hook", events=["context.node.created"])

    print("\nDone!")


def pagination_example():
    """Demonstrate paginated iteration."""
    from cortex_sdk import CortexClient
    from cortex_sdk.pagination import PaginatedIterator

    client = CortexClient(base_url="http://localhost:8421", token="YOUR_TOKEN")

    # Iterate through all nodes (auto-pagination)
    print("All nodes:")
    for page in client.nodes(page_size=5):
        items = page.get("items", [])
        print(f"  Page with {len(items)} items")


def main():
    print("Cortex Python SDK Quickstart")
    print("=" * 40)
    print()
    print("This example requires a running CaaS server.")
    print("Start one with: cortex serve context.json")
    print()
    print("Example API calls (copy into your code):")
    print()
    print("  from cortex_sdk import CortexClient")
    print("  client = CortexClient(token='your-grant-token')")
    print("  health = client.health()")
    print("  stats = client.stats()")
    print("  for page in client.nodes():")
    print("      print(page)")
    print()

    # Uncomment to run against a live server:
    # sync_example()
    # pagination_example()


if __name__ == "__main__":
    main()
