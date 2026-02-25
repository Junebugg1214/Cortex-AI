"""
Mixed scenario — balanced 50/50 reads and writes.

Covers the full API surface: health, context, nodes, edges, search, stats,
versions, graph traversal.
Supports authenticated requests via on_start() token pickup.
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
        self._headers = {}
        try:
            from benchmarks.locustfile import _AUTH_TOKEN
            if _AUTH_TOKEN:
                self._headers = {"Authorization": f"Bearer {_AUTH_TOKEN}"}
        except ImportError:
            pass

    def _get(self, url, **kwargs):
        headers = {**self._headers, **kwargs.pop("headers", {})}
        return self.client.get(url, headers=headers, **kwargs)

    def _post(self, url, **kwargs):
        headers = {**self._headers, **kwargs.pop("headers", {})}
        return self.client.post(url, headers=headers, **kwargs)

    def _delete(self, url, **kwargs):
        headers = {**self._headers, **kwargs.pop("headers", {})}
        return self.client.delete(url, headers=headers, **kwargs)

    @task(8)
    def health_check(self):
        self.client.get("/health")

    @task(8)
    def get_stats(self):
        self._get("/context/stats")

    @task(8)
    def get_nodes(self):
        self._get("/context/nodes?page=1&page_size=20")

    @task(8)
    def get_edges(self):
        self._get("/context/edges?page=1&page_size=20")

    @task(8)
    def search(self):
        self._post(
            "/context/search",
            json={"query": "benchmark test", "limit": 5},
        )

    @task(5)
    def get_versions(self):
        self._get("/context/versions")

    @task(5)
    def get_graph_health(self):
        self._get("/context/health")

    @task(20)
    def create_node(self):
        label = f"bench-mixed-{uuid.uuid4().hex[:8]}"
        resp = self._post(
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
        self._post(
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
        self._delete(f"/context/nodes/{node_id}")
