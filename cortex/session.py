from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from cortex.client import CortexClient


def _slug_fragment(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def branch_name_for_task(task: str, *, prefix: str = "tasks", max_length: int = 48) -> str:
    branch_leaf = _slug_fragment(task, fallback="task")[:max_length].rstrip("-")
    if not branch_leaf:
        branch_leaf = "task"
    prefix_parts = [_slug_fragment(part, fallback="task") for part in prefix.split("/") if part.strip()]
    if not prefix_parts:
        return branch_leaf
    return "/".join(prefix_parts + [branch_leaf])


def _truncate(text: str, *, max_chars: int | None) -> str:
    if max_chars is None or len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def _node_summary(node: dict[str, Any]) -> str:
    summary = (
        str(node.get("brief", "")).strip()
        or str(node.get("full_description", "")).strip()
        or str(node.get("description", "")).strip()
    )
    parts: list[str] = []
    if summary:
        parts.append(summary)
    tags = [str(tag) for tag in node.get("tags", []) if str(tag).strip()]
    if tags:
        parts.append(f"tags: {', '.join(tags[:4])}")
    aliases = [str(alias) for alias in node.get("aliases", []) if str(alias).strip()]
    if aliases:
        parts.append(f"aliases: {', '.join(aliases[:3])}")
    return "; ".join(parts)


def render_search_context(
    search_payload: dict[str, Any],
    *,
    max_items: int = 5,
    max_chars: int | None = 1500,
    include_scores: bool = True,
) -> str:
    query = str(search_payload.get("query", "")).strip()
    results = list(search_payload.get("results", []))[:max_items]
    if not results:
        return f"No Cortex memory matched '{query}'." if query else "No Cortex memory matched."

    header = f"Cortex memory matches for '{query}':" if query else "Cortex memory matches:"
    lines = [header]
    for item in results:
        node = item.get("node") or {}
        label = str(node.get("label") or node.get("id") or "Untitled memory").strip()
        line = f"- {label}"
        score = item.get("score")
        if include_scores and isinstance(score, (int, float)):
            line += f" (score {float(score):.3f})"
        summary = _node_summary(node)
        if summary:
            line += f": {summary}"
        lines.append(line)
    return _truncate("\n".join(lines), max_chars=max_chars)


@dataclass(slots=True)
class MemorySession:
    client: CortexClient
    actor: str = "assistant"
    default_ref: str = "HEAD"
    branch_prefix: str = "tasks"
    default_source: str = "sdk.session"
    default_fail_on: str = "blocking"

    @classmethod
    def from_base_url(
        cls,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        namespace: str | None = None,
        actor: str = "assistant",
        default_ref: str = "HEAD",
        branch_prefix: str = "tasks",
        default_source: str = "sdk.session",
        default_fail_on: str = "blocking",
    ) -> "MemorySession":
        client = CortexClient(base_url, api_key=api_key, timeout=timeout, namespace=namespace)
        return cls(
            client=client,
            actor=actor,
            default_ref=default_ref,
            branch_prefix=branch_prefix,
            default_source=default_source,
            default_fail_on=default_fail_on,
        )

    def sdk_info(self) -> dict[str, Any]:
        payload = dict(self.client.sdk_info())
        payload["session"] = {
            "actor": self.actor,
            "default_ref": self.default_ref,
            "branch_prefix": self.branch_prefix,
            "default_source": self.default_source,
            "default_fail_on": self.default_fail_on,
        }
        return payload

    def remember(
        self,
        *,
        label: str = "",
        node: dict[str, Any] | None = None,
        node_id: str = "",
        canonical_id: str = "",
        brief: str = "",
        full_description: str = "",
        tags: Iterable[str] = (),
        aliases: Iterable[str] = (),
        confidence: float = 0.85,
        status: str = "",
        valid_from: str = "",
        valid_to: str = "",
        properties: dict[str, Any] | None = None,
        message: str = "",
        ref: str | None = None,
        source: str | None = None,
        approve: bool = False,
        claim_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        node_payload = dict(node or {})
        if not node_payload:
            if not label:
                raise ValueError("remember() needs either a node payload or a non-empty label.")
            node_payload = {
                "label": label,
                "confidence": confidence,
            }
            if node_id:
                node_payload["id"] = node_id
            if canonical_id:
                node_payload["canonical_id"] = canonical_id
            if brief:
                node_payload["brief"] = brief
            if full_description:
                node_payload["full_description"] = full_description
            if status:
                node_payload["status"] = status
            if valid_from:
                node_payload["valid_from"] = valid_from
            if valid_to:
                node_payload["valid_to"] = valid_to
            aliases_list = [str(alias) for alias in aliases if str(alias).strip()]
            if aliases_list:
                node_payload["aliases"] = aliases_list
            tags_list = [str(tag) for tag in tags if str(tag).strip()]
            if tags_list:
                node_payload["tags"] = tags_list
        if properties:
            node_payload.update(properties)

        return self.client.upsert_node(
            node=node_payload,
            ref=ref or self.default_ref,
            message=message or f"Remember {node_payload.get('label') or node_payload.get('id') or 'memory'}",
            source=source or f"{self.default_source}.remember",
            actor=self.actor,
            approve=approve,
            claim_metadata=claim_metadata,
        )

    def remember_many(
        self,
        *,
        nodes: list[dict[str, Any]],
        message: str = "",
        ref: str | None = None,
        source: str | None = None,
        approve: bool = False,
    ) -> dict[str, Any]:
        operations = [{"op": "upsert_node", "node": dict(node)} for node in nodes]
        return self.client.memory_batch(
            operations=operations,
            ref=ref or self.default_ref,
            message=message or f"Remember {len(nodes)} memory object(s)",
            source=source or f"{self.default_source}.remember_many",
            actor=self.actor,
            approve=approve,
        )

    def link(
        self,
        *,
        source_id: str,
        target_id: str,
        relation: str,
        edge: dict[str, Any] | None = None,
        edge_id: str = "",
        confidence: float = 0.8,
        description: str = "",
        message: str = "",
        ref: str | None = None,
        source: str | None = None,
        approve: bool = False,
    ) -> dict[str, Any]:
        edge_payload = dict(edge or {})
        if not edge_payload:
            edge_payload = {
                "source_id": source_id,
                "target_id": target_id,
                "relation": relation,
                "confidence": confidence,
            }
            if edge_id:
                edge_payload["id"] = edge_id
            if description:
                edge_payload["description"] = description
        return self.client.upsert_edge(
            edge=edge_payload,
            ref=ref or self.default_ref,
            message=message or f"Link {source_id} -> {target_id} ({relation})",
            source=source or f"{self.default_source}.link",
            actor=self.actor,
            approve=approve,
        )

    def search(self, *, query: str, ref: str | None = None, limit: int = 5, min_score: float = 0.0) -> dict[str, Any]:
        return self.client.query_search(
            query=query,
            ref=ref or self.default_ref,
            limit=limit,
            min_score=min_score,
        )

    def search_context(
        self,
        *,
        query: str,
        ref: str | None = None,
        limit: int = 5,
        min_score: float = 0.0,
        max_chars: int | None = 1500,
        include_scores: bool = True,
    ) -> dict[str, Any]:
        payload = self.search(query=query, ref=ref, limit=limit, min_score=min_score)
        payload["context"] = render_search_context(
            payload,
            max_items=limit,
            max_chars=max_chars,
            include_scores=include_scores,
        )
        return payload

    def branch_for_task(
        self,
        task: str,
        *,
        prefix: str | None = None,
        from_ref: str | None = None,
        switch: bool = True,
        approve: bool = False,
    ) -> dict[str, Any]:
        branch_name = branch_name_for_task(task, prefix=prefix or self.branch_prefix)
        payload = self.client.create_branch(
            name=branch_name,
            from_ref=from_ref or self.default_ref,
            switch=switch,
            actor=self.actor,
            approve=approve,
        )
        payload["branch_name"] = branch_name
        payload["task"] = task
        return payload

    def commit_if_review_passes(
        self,
        *,
        graph: dict[str, Any],
        message: str,
        against: str,
        ref: str | None = None,
        fail_on: str | None = None,
        source: str | None = None,
        approve: bool = False,
    ) -> dict[str, Any]:
        review = self.client.review(
            against=against,
            graph=graph,
            ref=ref or self.default_ref,
            fail_on=fail_on or self.default_fail_on,
        )
        if review.get("status") == "fail":
            summary = review.get("summary") or {}
            failure_counts = review.get("failure_counts") or {}
            raise RuntimeError(
                "Review failed before commit: "
                + ", ".join(
                    filter(
                        None,
                        [
                            f"blocking={summary.get('blocking_issues')}" if "blocking_issues" in summary else "",
                            ", ".join(f"{key}={value}" for key, value in failure_counts.items() if value),
                        ],
                    )
                )
            )
        commit = self.client.commit(
            graph=graph,
            message=message,
            source=source or f"{self.default_source}.commit_if_review_passes",
            actor=self.actor,
            approve=approve,
        )
        return {
            "status": "ok",
            "review": review,
            "commit": commit.get("commit", commit),
        }


__all__ = ["MemorySession", "branch_name_for_task", "render_search_context"]
