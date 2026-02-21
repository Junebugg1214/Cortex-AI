"""
Write-heavy scenario — 30% reads, 70% writes.

Targets: node creation, node deletion, edge creation.
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


class WriteHeavyScenario:
    """Mixin providing write-heavy task distribution."""

    def on_start(self):
        self._created_node_ids = []

    @task(15)
    def health_check(self):
        self.client.get("/health")

    @task(15)
    def get_stats(self):
        self.client.get("/context/stats")

    @task(30)
    def create_node(self):
        label = f"bench-write-{uuid.uuid4().hex[:8]}"
        resp = self.client.post(
            "/context/nodes",
            json={"label": label, "brief": "write benchmark", "tags": ["benchmark"]},
        )
        if resp.status_code == 201:
            data = resp.json()
            self._created_node_ids.append(data.get("id", ""))

    @task(20)
    def create_edge(self):
        if len(self._created_node_ids) < 2:
            return
        source = self._created_node_ids[-1]
        target = self._created_node_ids[-2]
        self.client.post(
            "/context/edges",
            json={
                "source_id": source,
                "target_id": target,
                "relation": "benchmark_link",
            },
        )

    @task(20)
    def delete_node(self):
        if not self._created_node_ids:
            return
        node_id = self._created_node_ids.pop(0)
        self.client.delete(f"/context/nodes/{node_id}")
