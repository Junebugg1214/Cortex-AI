from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from cortex.release import API_VERSION, OPENAPI_VERSION, PROJECT_VERSION, PYTHON_SDK_MODULE, PYTHON_SDK_NAME


def _sdk_info_payload() -> dict[str, Any]:
    return {
        "name": PYTHON_SDK_NAME,
        "module": PYTHON_SDK_MODULE,
        "version": PROJECT_VERSION,
        "api_version": API_VERSION,
        "openapi_version": OPENAPI_VERSION,
    }


class CortexClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        namespace: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.namespace = namespace

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Cortex-Client": f"{PYTHON_SDK_NAME}/{PROJECT_VERSION}",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.namespace:
            headers["X-Cortex-Namespace"] = self.namespace
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
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310 - CortexClient callers choose the API base URL explicitly.
                body = response.read().decode("utf-8")
                if not body:
                    return {}
                try:
                    return json.loads(body)
                except json.JSONDecodeError as error:
                    raise RuntimeError("Invalid JSON response from Cortex server.") from error
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            if body:
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError as error:
                    raise RuntimeError(body) from error
                raise RuntimeError(payload.get("error", body))
            raise RuntimeError(str(exc)) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason if getattr(exc, "reason", None) else str(exc)
            raise RuntimeError(f"Network error while calling Cortex: {reason}") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/v1/health")

    def sdk_info(self) -> dict[str, Any]:
        return _sdk_info_payload()

    def meta(self) -> dict[str, Any]:
        return self._request("GET", "/v1/meta")

    def metrics(self) -> dict[str, Any]:
        return self._request("GET", "/v1/metrics")

    def openapi(self) -> dict[str, Any]:
        return self._request("GET", "/v1/openapi.json")

    def agent_status(self) -> dict[str, Any]:
        return self._request("GET", "/v1/agent/status")

    def agent_monitor_run(
        self,
        *,
        mind_id: str = "",
        auto_resolve_threshold: float = 0.85,
        log_dir: str = "",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/agent/monitor/run",
            payload={
                "mind_id": mind_id,
                "auto_resolve_threshold": auto_resolve_threshold,
                "log_dir": log_dir,
            },
        )

    def agent_compile(
        self,
        *,
        mind_id: str,
        audience_id: str = "",
        output_format: str = "brief",
        delivery: str = "local_file",
        webhook_url: str = "",
        output_dir: str = "",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/agent/compile",
            payload={
                "mind_id": mind_id,
                "audience_id": audience_id,
                "output_format": output_format,
                "delivery": delivery,
                "webhook_url": webhook_url,
                "output_dir": output_dir,
            },
        )

    def agent_dispatch(
        self,
        *,
        event: str,
        payload: dict[str, Any],
        output_dir: str = "",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/agent/dispatch",
            payload={
                "event": event,
                "payload": payload,
                "output_dir": output_dir,
            },
        )

    def agent_schedule(
        self,
        *,
        mind_id: str,
        audience_id: str,
        cron_expression: str,
        output_format: str,
        delivery: str = "local_file",
        webhook_url: str = "",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/agent/schedule",
            payload={
                "mind_id": mind_id,
                "audience_id": audience_id,
                "cron_expression": cron_expression,
                "output_format": output_format,
                "delivery": delivery,
                "webhook_url": webhook_url,
            },
        )

    def agent_review_conflicts(
        self,
        *,
        decisions: list[dict[str, Any]] | None = None,
        log_dir: str = "",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/agent/conflicts/review",
            payload={
                "decisions": decisions or [],
                "log_dir": log_dir,
            },
        )

    def index_status(self, *, ref: str = "HEAD") -> dict[str, Any]:
        return self._request("GET", "/v1/index/status", params={"ref": ref})

    def index_rebuild(self, *, ref: str = "HEAD", all_refs: bool = False) -> dict[str, Any]:
        return self._request("POST", "/v1/index/rebuild", payload={"ref": ref, "all_refs": all_refs})

    def prune_status(self, *, retention_days: int = 7) -> dict[str, Any]:
        return self._request("GET", "/v1/prune/status", params={"retention_days": retention_days})

    def prune(self, *, dry_run: bool = True, retention_days: int = 7) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/prune",
            payload={"dry_run": dry_run, "retention_days": retention_days},
        )

    def prune_audit(self, *, limit: int = 50) -> dict[str, Any]:
        return self._request("GET", "/v1/prune/audit", params={"limit": limit})

    def lookup_nodes(
        self,
        *,
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
        ref: str = "HEAD",
        limit: int = 10,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/nodes",
            params={
                "id": node_id,
                "canonical_id": canonical_id,
                "label": label,
                "ref": ref,
                "limit": limit,
            },
        )

    def get_node(self, node_id: str, *, ref: str = "HEAD") -> dict[str, Any]:
        return self._request("GET", f"/v1/nodes/{urllib.parse.quote(node_id, safe='')}", params={"ref": ref})

    def upsert_node(
        self,
        *,
        node: dict[str, Any],
        ref: str = "HEAD",
        message: str = "",
        source: str = "api.object",
        actor: str = "manual",
        approve: bool = False,
        record_claim: bool = True,
        claim_source: str = "",
        claim_method: str = "nodes.upsert",
        claim_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "node": node,
            "ref": ref,
            "message": message,
            "source": source,
            "actor": actor,
            "approve": approve,
            "record_claim": record_claim,
            "claim_source": claim_source,
            "claim_method": claim_method,
        }
        if claim_metadata is not None:
            payload["claim_metadata"] = claim_metadata
        return self._request("POST", "/v1/nodes/upsert", payload=payload)

    def delete_node(
        self,
        *,
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
        ref: str = "HEAD",
        message: str = "",
        source: str = "api.object",
        actor: str = "manual",
        approve: bool = False,
        record_claim: bool = True,
        claim_source: str = "",
        claim_method: str = "nodes.delete",
        claim_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "node_id": node_id,
            "canonical_id": canonical_id,
            "label": label,
            "ref": ref,
            "message": message,
            "source": source,
            "actor": actor,
            "approve": approve,
            "record_claim": record_claim,
            "claim_source": claim_source,
            "claim_method": claim_method,
        }
        if claim_metadata is not None:
            payload["claim_metadata"] = claim_metadata
        return self._request("POST", "/v1/nodes/delete", payload=payload)

    def lookup_edges(
        self,
        *,
        edge_id: str = "",
        source_id: str = "",
        target_id: str = "",
        relation: str = "",
        ref: str = "HEAD",
        limit: int = 10,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/edges",
            params={
                "id": edge_id,
                "source_id": source_id,
                "target_id": target_id,
                "relation": relation,
                "ref": ref,
                "limit": limit,
            },
        )

    def get_edge(self, edge_id: str, *, ref: str = "HEAD") -> dict[str, Any]:
        return self._request("GET", f"/v1/edges/{urllib.parse.quote(edge_id, safe='')}", params={"ref": ref})

    def upsert_edge(
        self,
        *,
        edge: dict[str, Any],
        ref: str = "HEAD",
        message: str = "",
        source: str = "api.object",
        actor: str = "manual",
        approve: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/edges/upsert",
            payload={
                "edge": edge,
                "ref": ref,
                "message": message,
                "source": source,
                "actor": actor,
                "approve": approve,
            },
        )

    def delete_edge(
        self,
        *,
        edge_id: str = "",
        source_id: str = "",
        target_id: str = "",
        relation: str = "",
        ref: str = "HEAD",
        message: str = "",
        source: str = "api.object",
        actor: str = "manual",
        approve: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/edges/delete",
            payload={
                "edge_id": edge_id,
                "source_id": source_id,
                "target_id": target_id,
                "relation": relation,
                "ref": ref,
                "message": message,
                "source": source,
                "actor": actor,
                "approve": approve,
            },
        )

    def list_claims(
        self,
        *,
        claim_id: str = "",
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
        source: str = "",
        ref: str = "",
        version_ref: str = "",
        op: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/claims",
            params={
                "claim_id": claim_id,
                "node_id": node_id,
                "canonical_id": canonical_id,
                "label": label,
                "source": source,
                "ref": ref,
                "version_ref": version_ref,
                "op": op,
                "limit": limit,
            },
        )

    def assert_claim(
        self,
        *,
        node: dict[str, Any] | None = None,
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
        ref: str = "HEAD",
        materialize: bool = True,
        message: str = "",
        source: str = "api.object",
        method: str = "claims.assert",
        actor: str = "manual",
        approve: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "node_id": node_id,
            "canonical_id": canonical_id,
            "label": label,
            "ref": ref,
            "materialize": materialize,
            "message": message,
            "source": source,
            "method": method,
            "actor": actor,
            "approve": approve,
        }
        if node is not None:
            payload["node"] = node
        if metadata is not None:
            payload["metadata"] = metadata
        return self._request("POST", "/v1/claims/assert", payload=payload)

    def retract_claim(
        self,
        *,
        claim_id: str = "",
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
        ref: str = "HEAD",
        materialize: bool = True,
        message: str = "",
        actor: str = "manual",
        approve: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "claim_id": claim_id,
            "node_id": node_id,
            "canonical_id": canonical_id,
            "label": label,
            "ref": ref,
            "materialize": materialize,
            "message": message,
            "actor": actor,
            "approve": approve,
        }
        if metadata is not None:
            payload["metadata"] = metadata
        return self._request("POST", "/v1/claims/retract", payload=payload)

    def memory_batch(
        self,
        *,
        operations: list[dict[str, Any]],
        ref: str = "HEAD",
        message: str = "",
        source: str = "api.object",
        actor: str = "manual",
        approve: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/memory/batch",
            payload={
                "operations": operations,
                "ref": ref,
                "message": message,
                "source": source,
                "actor": actor,
                "approve": approve,
            },
        )

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


__all__ = ["API_VERSION", "CortexClient", "OPENAPI_VERSION", "PROJECT_VERSION"]
