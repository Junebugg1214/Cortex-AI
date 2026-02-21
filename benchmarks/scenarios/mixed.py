"""
Mixed scenario — balanced 50/50 reads and writes.

Covers the full API surface: health, context, nodes, edges, search, stats.
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


class MixedScenario:
    """Mixin providing balanced read/write task distribution."""

    def on_start(self):
        self._node_ids = []

    @task(10)
    def health_check(self):
        self.client.get("/health")

    @task(10)
    def get_stats(self):
        self.client.get("/context/stats")

    @task(10)
    def get_nodes(self):
        self.client.get("/context/nodes?page=1&page_size=20")

    @task(10)
    def get_edges(self):
        self.client.get("/context/edges?page=1&page_size=20")

    @task(10)
    def search(self):
        self.client.post(
            "/context/search",
            json={"query": "benchmark test", "limit": 5},
        )

    @task(20)
    def create_node(self):
        label = f"bench-mixed-{uuid.uuid4().hex[:8]}"
        resp = self.client.post(
            "/context/nodes",
            json={"label": label, "brief": "mixed benchmark", "tags": ["benchmark"]},
        )
        if resp.status_code == 201:
            data = resp.json()
            self._node_ids.append(data.get("id", ""))

    @task(15)
    def create_edge(self):
        if len(self._node_ids) < 2:
            return
        source = self._node_ids[-1]
        target = self._node_ids[-2]
        self.client.post(
            "/context/edges",
            json={
                "source_id": source,
                "target_id": target,
                "relation": "benchmark_link",
            },
        )

    @task(15)
    def delete_node(self):
        if not self._node_ids:
            return
        node_id = self._node_ids.pop(0)
        self.client.delete(f"/context/nodes/{node_id}")
