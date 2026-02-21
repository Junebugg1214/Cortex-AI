"""
Read-heavy scenario — 80% reads, 20% writes.

Targets: /health, /context, /context/nodes, /context/stats, /context/search
"""

from __future__ import annotations

import uuid

try:
    from locust import task
except ImportError:
    def task(weight=1):
        """Stub decorator when locust is not installed."""
        def decorator(fn):
            return fn
        if callable(weight):
            return weight
        return decorator


class ReadHeavyScenario:
    """Mixin providing read-heavy task distribution."""

    @task(20)
    def health_check(self):
        self.client.get("/health")

    @task(20)
    def get_context_stats(self):
        self.client.get("/context/stats")

    @task(15)
    def get_context_nodes(self):
        self.client.get("/context/nodes?page=1&page_size=10")

    @task(15)
    def get_context_edges(self):
        self.client.get("/context/edges?page=1&page_size=10")

    @task(10)
    def search_nodes(self):
        self.client.post(
            "/context/search",
            json={"query": "technology", "limit": 10},
        )

    @task(5)
    def create_node(self):
        label = f"bench-node-{uuid.uuid4().hex[:8]}"
        self.client.post(
            "/context/nodes",
            json={"label": label, "brief": "load test node", "tags": ["benchmark"]},
        )
