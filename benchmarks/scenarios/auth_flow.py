"""
Authenticated flow scenario — exercises endpoints that require Bearer tokens.

Targets: /context (full), /context/versions, /context/nodes (CRUD),
         /context/edges, /context/search, /context/stats
Requires --token to be passed via locust CLI.
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


class AuthFlowScenario:
    """Mixin providing authenticated API flow task distribution."""

    def on_start(self):
        self._headers = {}
        self._created_node_ids = []
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

    @task(15)
    def get_full_context(self):
        self._get("/context")

    @task(15)
    def get_versions(self):
        self._get("/context/versions")

    @task(10)
    def get_stats(self):
        self._get("/context/stats")

    @task(10)
    def get_graph_health(self):
        self._get("/context/health")

    @task(10)
    def search_nodes(self):
        self._post(
            "/context/search",
            json={"query": "test", "limit": 5},
        )

    @task(15)
    def create_node(self):
        label = f"bench-auth-{uuid.uuid4().hex[:8]}"
        resp = self._post(
            "/context/nodes",
            json={"label": label, "brief": "auth flow benchmark", "tags": ["benchmark"]},
        )
        if resp.status_code == 201:
            data = resp.json()
            self._created_node_ids.append(data.get("id", ""))

    @task(10)
    def create_edge(self):
        if len(self._created_node_ids) < 2:
            return
        source = self._created_node_ids[-1]
        target = self._created_node_ids[-2]
        self._post(
            "/context/edges",
            json={
                "source_id": source,
                "target_id": target,
                "relation": "auth_benchmark_link",
            },
        )

    @task(10)
    def get_node_neighbors(self):
        if not self._created_node_ids:
            return
        node_id = self._created_node_ids[-1]
        self._get(f"/context/nodes/{node_id}/neighbors")

    @task(5)
    def delete_node(self):
        if not self._created_node_ids:
            return
        node_id = self._created_node_ids.pop(0)
        self._delete(f"/context/nodes/{node_id}")
