"""
Read-heavy scenario — 80% reads, 20% writes.

Targets: /health, /context, /context/nodes, /context/stats, /context/search
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


class ReadHeavyScenario:
    """Mixin providing read-heavy task distribution."""

    def on_start(self):
        self._headers = {}
        try:
            from benchmarks.locustfile import _AUTH_TOKEN
            if _AUTH_TOKEN:
                self._headers = {"Authorization": f"Bearer {_AUTH_TOKEN}"}
        except ImportError:
            pass
        self._etag_cache = {}

    def _get(self, url, **kwargs):
        headers = {**self._headers, **kwargs.pop("headers", {})}
        return self.client.get(url, headers=headers, **kwargs)

    def _post(self, url, **kwargs):
        headers = {**self._headers, **kwargs.pop("headers", {})}
        return self.client.post(url, headers=headers, **kwargs)

    @task(20)
    def health_check(self):
        self.client.get("/health")

    @task(20)
    def get_context_stats(self):
        self._get("/context/stats")

    @task(15)
    def get_context_nodes(self):
        self._get("/context/nodes?page=1&page_size=10")

    @task(15)
    def get_context_edges(self):
        self._get("/context/edges?page=1&page_size=10")

    @task(10)
    def search_nodes(self):
        self._post(
            "/context/search",
            json={"query": "technology", "limit": 10},
        )

    @task(10)
    def get_context_with_etag(self):
        """Test ETag caching — send If-None-Match for 304 responses."""
        headers = dict(self._headers)
        etag = self._etag_cache.get("/context")
        if etag:
            headers["If-None-Match"] = etag
        resp = self.client.get("/context", headers=headers, name="/context [etag]")
        new_etag = resp.headers.get("ETag")
        if new_etag:
            self._etag_cache["/context"] = new_etag

    @task(5)
    def create_node(self):
        label = f"bench-node-{uuid.uuid4().hex[:8]}"
        self._post(
            "/context/nodes",
            json={"label": label, "brief": "load test node", "tags": ["benchmark"]},
        )
