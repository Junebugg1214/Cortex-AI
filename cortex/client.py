from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class CortexClient:
    def __init__(self, base_url: str, *, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}{query}",
            data=data,
            headers=self._headers(),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            if body:
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError as error:
                    raise RuntimeError(body) from error
                raise RuntimeError(payload.get("error", body))
            raise RuntimeError(str(exc)) from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/v1/health")

    def meta(self) -> dict[str, Any]:
        return self._request("GET", "/v1/meta")

    def openapi(self) -> dict[str, Any]:
        return self._request("GET", "/v1/openapi.json")

    def index_status(self, *, ref: str = "HEAD") -> dict[str, Any]:
        return self._request("GET", "/v1/index/status", params={"ref": ref})

    def index_rebuild(self, *, ref: str = "HEAD", all_refs: bool = False) -> dict[str, Any]:
        return self._request("POST", "/v1/index/rebuild", payload={"ref": ref, "all_refs": all_refs})

    def log(self, *, limit: int = 10, ref: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if ref is not None:
            params["ref"] = ref
        return self._request("GET", "/v1/commits", params=params)

    def list_branches(self) -> dict[str, Any]:
        return self._request("GET", "/v1/branches")

    def create_branch(
        self,
        *,
        name: str,
        from_ref: str = "HEAD",
        switch: bool = False,
        actor: str = "manual",
        approve: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/branches",
            payload={
                "name": name,
                "from_ref": from_ref,
                "switch": switch,
                "actor": actor,
                "approve": approve,
            },
        )

    def switch_branch(self, *, name: str, actor: str = "manual", approve: bool = False) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/branches/switch",
            payload={"name": name, "actor": actor, "approve": approve},
        )

    def checkout(self, *, ref: str = "HEAD", verify: bool = True) -> dict[str, Any]:
        return self._request("POST", "/v1/checkout", payload={"ref": ref, "verify": verify})

    def diff(self, *, version_a: str, version_b: str) -> dict[str, Any]:
        return self._request("POST", "/v1/diff", payload={"version_a": version_a, "version_b": version_b})

    def commit(
        self,
        *,
        graph: dict[str, Any],
        message: str,
        source: str = "manual",
        actor: str = "manual",
        approve: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/commit",
            payload={
                "graph": graph,
                "message": message,
                "source": source,
                "actor": actor,
                "approve": approve,
            },
        )

    def review(
        self,
        *,
        against: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        fail_on: str = "blocking",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"against": against, "ref": ref, "fail_on": fail_on}
        if graph is not None:
            payload["graph"] = graph
        return self._request("POST", "/v1/review", payload=payload)

    def blame(
        self,
        *,
        label: str = "",
        node_id: str = "",
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        source: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "label": label,
            "node_id": node_id,
            "ref": ref,
            "source": source,
            "limit": limit,
        }
        if graph is not None:
            payload["graph"] = graph
        return self._request("POST", "/v1/blame", payload=payload)

    def history(
        self,
        *,
        label: str = "",
        node_id: str = "",
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        source: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "label": label,
            "node_id": node_id,
            "ref": ref,
            "source": source,
            "limit": limit,
        }
        if graph is not None:
            payload["graph"] = graph
        return self._request("POST", "/v1/history", payload=payload)

    def detect_conflicts(
        self,
        *,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        min_severity: float = 0.0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ref": ref,
            "min_severity": min_severity,
        }
        if graph is not None:
            payload["graph"] = graph
        return self._request("POST", "/v1/conflicts/detect", payload=payload)

    def resolve_conflict(
        self,
        *,
        conflict_id: str,
        action: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "conflict_id": conflict_id,
            "action": action,
            "ref": ref,
        }
        if graph is not None:
            payload["graph"] = graph
        return self._request("POST", "/v1/conflicts/resolve", payload=payload)

    def merge_preview(
        self,
        *,
        other_ref: str,
        current_ref: str = "HEAD",
        persist: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/merge-preview",
            payload={
                "other_ref": other_ref,
                "current_ref": current_ref,
                "persist": persist,
            },
        )

    def merge_conflicts(self) -> dict[str, Any]:
        return self._request("POST", "/v1/merge/conflicts", payload={})

    def merge_resolve(self, *, conflict_id: str, choose: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/merge/resolve",
            payload={"conflict_id": conflict_id, "choose": choose},
        )

    def merge_commit_resolved(
        self,
        *,
        message: str | None = None,
        actor: str = "manual",
        approve: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "actor": actor,
            "approve": approve,
        }
        if message is not None:
            payload["message"] = message
        return self._request("POST", "/v1/merge/commit-resolved", payload=payload)

    def merge_abort(self) -> dict[str, Any]:
        return self._request("POST", "/v1/merge/abort", payload={})

    def query_category(
        self,
        *,
        tag: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"tag": tag, "ref": ref}
        if graph is not None:
            payload["graph"] = graph
        return self._request("POST", "/v1/query/category", payload=payload)

    def query_path(
        self,
        *,
        from_label: str,
        to_label: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "from_label": from_label,
            "to_label": to_label,
            "ref": ref,
        }
        if graph is not None:
            payload["graph"] = graph
        return self._request("POST", "/v1/query/path", payload=payload)

    def query_related(
        self,
        *,
        label: str,
        depth: int = 2,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "label": label,
            "depth": depth,
            "ref": ref,
        }
        if graph is not None:
            payload["graph"] = graph
        return self._request("POST", "/v1/query/related", payload=payload)

    def query_search(
        self,
        *,
        query: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        limit: int = 10,
        min_score: float = 0.0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": query,
            "ref": ref,
            "limit": limit,
            "min_score": min_score,
        }
        if graph is not None:
            payload["graph"] = graph
        return self._request("POST", "/v1/query/search", payload=payload)

    def query_dsl(
        self,
        *,
        query: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query, "ref": ref}
        if graph is not None:
            payload["graph"] = graph
        return self._request("POST", "/v1/query/dsl", payload=payload)

    def query_nl(
        self,
        *,
        query: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query, "ref": ref}
        if graph is not None:
            payload["graph"] = graph
        return self._request("POST", "/v1/query/nl", payload=payload)
