"""
CortexClient — Python SDK for the CaaS API.

Uses ``urllib.request`` (stdlib) for HTTP. Maps HTTP errors to typed
exceptions. Supports iterator-based pagination for list endpoints.

Usage::

    from cortex_sdk import CortexClient

    client = CortexClient(base_url="http://localhost:8421", token="...")
    info = client.info()
    for node in client.nodes():
        print(node["label"])
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterator

from .exceptions import (
    AuthenticationError,
    CortexSDKError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from .pagination import PaginatedIterator


class CortexClient:
    """Synchronous Python client for the Cortex CaaS API.

    Args:
        base_url: Base URL of the CaaS server (default: ``http://localhost:8421``).
        token: Bearer token for authentication.
        timeout: Request timeout in seconds (default: 10).
    """

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
    # Discovery (no auth)
    # -----------------------------------------------------------------

    def info(self) -> dict:
        """GET / — server info."""
        return self._request("GET", "/", auth=False)

    def discovery(self) -> dict:
        """GET /.well-known/upai-configuration — UPAI discovery."""
        return self._request("GET", "/.well-known/upai-configuration", auth=False)

    def health(self) -> dict:
        """GET /health — health check (no auth)."""
        return self._request("GET", "/health", auth=False)

    def identity(self) -> dict:
        """GET /identity — W3C DID Document."""
        return self._request("GET", "/identity", auth=False)

    # -----------------------------------------------------------------
    # Context
    # -----------------------------------------------------------------

    def context(self) -> dict:
        """GET /context — full signed graph (filtered by token policy)."""
        return self._request("GET", "/context")

    def context_compact(self) -> str:
        """GET /context/compact — markdown summary."""
        return self._request("GET", "/context/compact", raw=True)

    def nodes(self, limit: int = 20) -> Iterator[dict]:
        """Auto-paginating iterator over /context/nodes."""
        return PaginatedIterator(self._request, "GET", "/context/nodes", limit)

    def node(self, node_id: str) -> dict:
        """GET /context/nodes/:id — single node."""
        return self._request("GET", f"/context/nodes/{node_id}")

    def edges(self, limit: int = 20) -> Iterator[dict]:
        """Auto-paginating iterator over /context/edges."""
        return PaginatedIterator(self._request, "GET", "/context/edges", limit)

    def stats(self) -> dict:
        """GET /context/stats — graph statistics."""
        return self._request("GET", "/context/stats")

    # -----------------------------------------------------------------
    # Versions
    # -----------------------------------------------------------------

    def versions(self, limit: int = 20) -> Iterator[dict]:
        """Auto-paginating iterator over /versions."""
        return PaginatedIterator(self._request, "GET", "/versions", limit)

    def version(self, version_id: str) -> dict:
        """GET /versions/:id — single version snapshot."""
        return self._request("GET", f"/versions/{version_id}")

    def version_diff(self, a: str, b: str) -> dict:
        """GET /versions/diff?a=...&b=... — diff two versions."""
        return self._request("GET", f"/versions/diff?a={a}&b={b}")

    # -----------------------------------------------------------------
    # Grants
    # -----------------------------------------------------------------

    def create_grant(
        self,
        audience: str,
        policy: str = "professional",
        ttl_hours: int = 24,
        scopes: list[str] | None = None,
    ) -> dict:
        """POST /grants — create a new grant token."""
        body: dict[str, Any] = {
            "audience": audience,
            "policy": policy,
            "ttl_hours": ttl_hours,
        }
        if scopes:
            body["scopes"] = scopes
        return self._request("POST", "/grants", body=body)

    def list_grants(self) -> list[dict]:
        """GET /grants — list all grants."""
        data = self._request("GET", "/grants")
        return data.get("grants", [])

    def revoke_grant(self, grant_id: str) -> dict:
        """DELETE /grants/:id — revoke a grant."""
        return self._request("DELETE", f"/grants/{grant_id}")

    # -----------------------------------------------------------------
    # Webhooks
    # -----------------------------------------------------------------

    def create_webhook(self, url: str, events: list[str] | None = None) -> dict:
        """POST /webhooks — register a webhook."""
        body: dict[str, Any] = {"url": url}
        if events:
            body["events"] = events
        return self._request("POST", "/webhooks", body=body)

    def list_webhooks(self) -> list[dict]:
        """GET /webhooks — list all webhooks."""
        data = self._request("GET", "/webhooks")
        return data.get("webhooks", [])

    def delete_webhook(self, webhook_id: str) -> dict:
        """DELETE /webhooks/:id — delete a webhook."""
        return self._request("DELETE", f"/webhooks/{webhook_id}")

    # -----------------------------------------------------------------
    # Policies
    # -----------------------------------------------------------------

    def list_policies(self) -> list[dict]:
        """GET /policies — list all disclosure policies."""
        data = self._request("GET", "/policies")
        return data.get("policies", [])

    def create_policy(self, name: str, **options: Any) -> dict:
        """POST /policies — create a custom policy."""
        body = {"name": name, **options}
        return self._request("POST", "/policies", body=body)

    def get_policy(self, name: str) -> dict:
        """GET /policies/:name — get a single policy."""
        return self._request("GET", f"/policies/{name}")

    def delete_policy(self, name: str) -> dict:
        """DELETE /policies/:name — delete a custom policy."""
        return self._request("DELETE", f"/policies/{name}")

    # -----------------------------------------------------------------
    # Metrics
    # -----------------------------------------------------------------

    def metrics(self) -> str:
        """GET /metrics — Prometheus text exposition (raw string)."""
        return self._request("GET", "/metrics", auth=False, raw=True)

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        auth: bool = True,
        raw: bool = False,
    ) -> Any:
        """Make an HTTP request to the CaaS server.

        Args:
            method: HTTP method (GET, POST, DELETE).
            path: URL path (may include query string).
            body: JSON body for POST requests.
            auth: Whether to include the Authorization header.
            raw: If True, return the response body as a string.

        Returns:
            Parsed JSON dict, or raw string if ``raw=True``.

        Raises:
            CortexSDKError: On connection, timeout, or HTTP errors.
        """
        url = self.base_url + path
        data = json.dumps(body).encode("utf-8") if body else None

        headers = {"Content-Type": "application/json"}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_body = resp.read().decode("utf-8")
                if raw:
                    return resp_body
                return json.loads(resp_body)
        except urllib.error.HTTPError as e:
            err_body: dict = {}
            try:
                err_body = json.loads(e.read().decode("utf-8"))
            except Exception:
                pass

            msg = self._extract_error_message(err_body, e.code)
            status = e.code
            if status == 401:
                raise AuthenticationError(msg, status, err_body)
            elif status == 403:
                raise ForbiddenError(msg, status, err_body)
            elif status == 404:
                raise NotFoundError(msg, status, err_body)
            elif status == 400:
                raise ValidationError(msg, status, err_body)
            elif status == 429:
                raise RateLimitError(msg, status, err_body)
            elif status >= 500:
                raise ServerError(msg, status, err_body)
            else:
                raise CortexSDKError(msg, status, err_body)
        except urllib.error.URLError as e:
            raise CortexSDKError(f"Connection error: {e.reason}")
        except TimeoutError:
            raise CortexSDKError(f"Request timeout after {self.timeout}s")

    @staticmethod
    def _extract_error_message(err_body: dict, status_code: int) -> str:
        """Extract human-readable error message from response body."""
        err = err_body.get("error")
        if isinstance(err, dict) and "message" in err:
            return str(err["message"])
        if isinstance(err, str):
            return err
        return str(status_code)
