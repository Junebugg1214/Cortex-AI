"""
CortexClient — Python SDK for the CaaS API.

Uses only urllib.request (stdlib). Maps HTTP errors to typed exceptions.
Supports auto-paginating generators for list endpoints.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Iterator

from cortex.sdk.exceptions import (
    AuthenticationError,
    CortexSDKError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)


class CortexClient:
    """Synchronous Python client for the UPAI CaaS API."""

    def __init__(
        self,
        base_url: str = "http://localhost:8421",
        token: str = "",
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    # -----------------------------------------------------------------
    # Discovery
    # -----------------------------------------------------------------

    def info(self) -> dict:
        """GET / — server info."""
        data, _ = self._request("GET", "/", auth=False)
        return data

    def discovery(self) -> dict:
        """GET /.well-known/upai-configuration — UPAI discovery."""
        data, _ = self._request("GET", "/.well-known/upai-configuration", auth=False)
        return data

    def health(self) -> dict:
        """GET /health — health check (no auth)."""
        data, _ = self._request("GET", "/health", auth=False)
        return data

    def identity(self) -> dict:
        """GET /identity — W3C DID Document."""
        data, _ = self._request("GET", "/identity", auth=False)
        return data

    # -----------------------------------------------------------------
    # Context
    # -----------------------------------------------------------------

    def context(self) -> dict:
        """GET /context — full signed graph (filtered by token policy)."""
        data, _ = self._request("GET", "/context")
        return data

    def context_compact(self) -> str:
        """GET /context/compact — markdown summary."""
        data, _ = self._request("GET", "/context/compact", raw=True)
        return data

    def nodes(self, limit: int = 20) -> Iterator[dict]:
        """Auto-paginating generator over /context/nodes."""
        return self._paginate("/context/nodes", limit=limit)

    def node(self, node_id: str) -> dict:
        """GET /context/nodes/<node_id> — single node."""
        data, _ = self._request("GET", f"/context/nodes/{node_id}")
        return data

    def edges(self, limit: int = 20) -> Iterator[dict]:
        """Auto-paginating generator over /context/edges."""
        return self._paginate("/context/edges", limit=limit)

    def stats(self) -> dict:
        """GET /context/stats — graph statistics."""
        data, _ = self._request("GET", "/context/stats")
        return data

    # -----------------------------------------------------------------
    # Versions
    # -----------------------------------------------------------------

    def versions(self, limit: int = 20) -> Iterator[dict]:
        """Auto-paginating generator over /versions."""
        return self._paginate("/versions", limit=limit)

    def version(self, version_id: str) -> dict:
        """GET /versions/<version_id> — single version snapshot."""
        data, _ = self._request("GET", f"/versions/{version_id}")
        return data

    def version_diff(self, a: str, b: str) -> dict:
        """GET /versions/diff?a=...&b=... — diff two versions."""
        data, _ = self._request("GET", f"/versions/diff?a={a}&b={b}")
        return data

    # -----------------------------------------------------------------
    # Grants
    # -----------------------------------------------------------------

    def create_grant(
        self,
        audience: str,
        policy: str = "professional",
        scopes: list[str] | None = None,
        ttl_hours: int = 24,
    ) -> dict:
        """POST /grants — create a new grant token."""
        body: dict[str, Any] = {
            "audience": audience,
            "policy": policy,
            "ttl_hours": ttl_hours,
        }
        if scopes is not None:
            body["scopes"] = scopes
        data, _ = self._request("POST", "/grants", body=body)
        return data

    def list_grants(self) -> list[dict]:
        """GET /grants — list all grants."""
        data, _ = self._request("GET", "/grants")
        return data.get("grants", [])

    def revoke_grant(self, grant_id: str) -> dict:
        """DELETE /grants/<grant_id> — revoke a grant."""
        data, _ = self._request("DELETE", f"/grants/{grant_id}")
        return data

    # -----------------------------------------------------------------
    # Webhooks
    # -----------------------------------------------------------------

    def create_webhook(self, url: str, events: list[str] | None = None) -> dict:
        """POST /webhooks — register a webhook."""
        body: dict[str, Any] = {"url": url}
        if events is not None:
            body["events"] = events
        data, _ = self._request("POST", "/webhooks", body=body)
        return data

    def list_webhooks(self) -> list[dict]:
        """GET /webhooks — list all webhooks."""
        data, _ = self._request("GET", "/webhooks")
        return data.get("webhooks", [])

    def delete_webhook(self, webhook_id: str) -> dict:
        """DELETE /webhooks/<webhook_id> — delete a webhook."""
        data, _ = self._request("DELETE", f"/webhooks/{webhook_id}")
        return data

    # -----------------------------------------------------------------
    # Policies (WP-3.3)
    # -----------------------------------------------------------------

    def list_policies(self) -> list[dict]:
        """GET /policies — list all disclosure policies."""
        data, _ = self._request("GET", "/policies")
        return data.get("policies", [])

    def create_policy(self, name: str, **kwargs: Any) -> dict:
        """POST /policies — create a custom policy."""
        body = {"name": name, **kwargs}
        data, _ = self._request("POST", "/policies", body=body)
        return data

    def get_policy(self, name: str) -> dict:
        """GET /policies/<name> — get a single policy."""
        data, _ = self._request("GET", f"/policies/{name}")
        return data

    def delete_policy(self, name: str) -> dict:
        """DELETE /policies/<name> — delete a custom policy."""
        data, _ = self._request("DELETE", f"/policies/{name}")
        return data

    # -----------------------------------------------------------------
    # Metrics
    # -----------------------------------------------------------------

    def metrics(self) -> str:
        """GET /metrics — Prometheus text exposition (raw string)."""
        data, _ = self._request("GET", "/metrics", auth=False, raw=True)
        return data

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        auth: bool = True,
        raw: bool = False,
    ) -> tuple[Any, int]:
        """Make an HTTP request and return (parsed_body, status_code)."""
        url = self.base_url + path
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")

        if auth and self.token:
            req.add_header("Authorization", f"Bearer {self.token}")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_body = resp.read()
                if raw:
                    return resp_body.decode("utf-8"), resp.status
                return json.loads(resp_body), resp.status
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                err_body = json.loads(e.read())
            except (json.JSONDecodeError, ValueError):
                err_body = {}

            msg = ""
            if "error" in err_body and isinstance(err_body["error"], dict):
                msg = err_body["error"].get("message", str(status))
            else:
                msg = err_body.get("error", str(status))

            if status == 401:
                raise AuthenticationError(msg, status, err_body)
            elif status == 403:
                raise ForbiddenError(msg, status, err_body)
            elif status == 404:
                raise NotFoundError(msg, status, err_body)
            elif status == 429:
                raise RateLimitError(msg, status, err_body)
            elif status == 400:
                raise ValidationError(msg, status, err_body)
            elif status >= 500:
                raise ServerError(msg, status, err_body)
            else:
                raise CortexSDKError(msg, status, err_body)
        except urllib.error.URLError as e:
            raise CortexSDKError(f"Connection error: {e.reason}") from e

    def _paginate(self, path: str, limit: int = 20) -> Iterator[dict]:
        """Auto-follow cursor pagination, yielding individual items."""
        cursor = None
        while True:
            qs = f"?limit={limit}"
            if cursor:
                qs += f"&cursor={cursor}"
            data, _ = self._request("GET", path + qs)
            items = data.get("items", [])
            for item in items:
                yield item
            if not data.get("has_more", False):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
