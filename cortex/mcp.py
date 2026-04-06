from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from cortex.config import format_startup_diagnostics, load_selfhost_config
from cortex.release import API_VERSION, MCP_SERVER_NAME, OPENAPI_VERSION, PROJECT_VERSION
from cortex.service import MemoryService

JSONRPC_VERSION = "2.0"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-05", "2025-11-25")

_JSON_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
}


def _string_property(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _number_property(description: str) -> dict[str, Any]:
    return {"type": "number", "description": description}


def _integer_property(description: str) -> dict[str, Any]:
    return {"type": "integer", "description": description}


def _boolean_property(description: str) -> dict[str, Any]:
    return {"type": "boolean", "description": description}


def _array_property(description: str, items: dict[str, Any] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "array", "description": description}
    if items is not None:
        schema["items"] = items
    return schema


def _object_schema(
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
    include_namespace: bool = True,
) -> dict[str, Any]:
    schema_properties = dict(properties)
    if include_namespace:
        schema_properties["namespace"] = _string_property(
            "Optional namespace scope. When the MCP server is launched with --namespace, it will enforce that scope."
        )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": schema_properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, *, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass(slots=True)
class ToolDefinition:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    annotations: dict[str, Any] | None = None

    def as_payload(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
        if self.annotations:
            payload["annotations"] = self.annotations
        return payload


class CortexMCPServer:
    def __init__(
        self,
        *,
        store_dir: str | Path = ".cortex",
        context_file: str | Path | None = None,
        namespace: str | None = None,
        service: MemoryService | None = None,
    ) -> None:
        self.service = service or MemoryService(store_dir=store_dir, context_file=context_file)
        self.store_dir = Path(store_dir)
        self.context_file = Path(context_file).resolve() if context_file else None
        self.namespace = (namespace or "").strip() or None
        self.protocol_version: str | None = None
        self.client_info: dict[str, Any] = {}
        self._initialize_seen = False
        self._client_ready = False
        self._tools = {tool.name: tool for tool in self._build_tools()}

    def _instructions(self) -> str:
        namespace_message = (
            f"This session is pinned to namespace '{self.namespace}'."
            if self.namespace
            else "Pass a namespace argument when you want namespace-scoped operations."
        )
        return (
            "Cortex exposes local-first, user-owned AI memory over MCP. "
            "Use portability, node, edge, claim, query, branch, merge, blame, history, index, and prune tools "
            "to work with versioned memory without shelling out. "
            f"Release {PROJECT_VERSION} speaks API {API_VERSION} / OpenAPI {OPENAPI_VERSION}. "
            f"{namespace_message}"
        )

    def _effective_namespace(self, requested: Any | None) -> str | None:
        requested_namespace = str(requested or "").strip() or None
        if self.namespace is None:
            return requested_namespace
        if requested_namespace and requested_namespace != self.namespace:
            raise PermissionError(
                f"This MCP session is pinned to namespace '{self.namespace}', not '{requested_namespace}'."
            )
        return self.namespace

    def _service_tool(
        self,
        *,
        name: str,
        title: str,
        description: str,
        method_name: str,
        input_schema: dict[str, Any],
        read_only: bool,
        destructive: bool = False,
        namespace_param: bool = True,
    ) -> ToolDefinition:
        def handler(arguments: dict[str, Any]) -> dict[str, Any]:
            payload = dict(arguments)
            requested_namespace = payload.pop("namespace", None)
            if namespace_param:
                namespace = self._effective_namespace(requested_namespace)
                if namespace is not None:
                    payload["namespace"] = namespace
            return getattr(self.service, method_name)(**payload)

        annotations = {
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
            "idempotentHint": read_only,
        }
        return ToolDefinition(
            name=name,
            title=title,
            description=description,
            input_schema=input_schema,
            handler=handler,
            annotations=annotations,
        )

    def _build_tools(self) -> list[ToolDefinition]:
        node_schema = {"type": "object", "description": "Memory node payload.", "additionalProperties": True}
        edge_schema = {"type": "object", "description": "Memory edge payload.", "additionalProperties": True}
        graph_schema = {"type": "object", "description": "Cortex graph payload.", "additionalProperties": True}
        batch_operation_schema = {
            "type": "object",
            "description": "Memory batch operation payload.",
            "additionalProperties": True,
        }
        return [
            self._service_tool(
                name="health",
                title="Health Check",
                description="Inspect the local Cortex runtime and backend status.",
                method_name="health",
                input_schema=_object_schema({}, include_namespace=False),
                read_only=True,
                namespace_param=False,
            ),
            self._service_tool(
                name="meta",
                title="Runtime Metadata",
                description="Read server metadata such as current branch, embedding provider, and log path.",
                method_name="meta",
                input_schema=_object_schema({}, include_namespace=False),
                read_only=True,
                namespace_param=False,
            ),
            self._service_tool(
                name="portability_context",
                title="Live Portability Context",
                description=(
                    "Return the current routed context slice for a target AI tool so agents can consume Cortex "
                    "live instead of relying on stale instruction files."
                ),
                method_name="portability_context",
                input_schema=_object_schema(
                    {
                        "target": _string_property(
                            "Portability target such as claude-code, codex, cursor, copilot, gemini, windsurf, claude, chatgpt, or grok."
                        ),
                        "project_dir": _string_property(
                            "Optional working directory used to focus project-relevant context."
                        ),
                        "smart": _boolean_property(
                            "When true, return the target-specific routed slice. Defaults to the stored sync mode or smart routing."
                        ),
                        "policy": _string_property(
                            "Disclosure policy to use when smart is false or no stored mode exists."
                        ),
                        "max_chars": _integer_property("Maximum size of the rendered context markdown."),
                    },
                    required=("target",),
                    include_namespace=False,
                ),
                read_only=True,
                namespace_param=False,
            ),
            ToolDefinition(
                name="portability_scan",
                title="Portability Scan",
                description=(
                    "Audit which supported AI tools are configured and detectable from the local machine. "
                    "MCP scans are metadata-only by default and do not expose absolute paths or parsed local content."
                ),
                input_schema=_object_schema(
                    {
                        "project_dir": _string_property(
                            "Project directory to inspect. Defaults to the current working directory."
                        ),
                    },
                    include_namespace=False,
                ),
                handler=lambda arguments: self.service.portability_scan(
                    project_dir=str(arguments.get("project_dir", "")),
                    metadata_only=True,
                ),
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                },
            ),
            self._service_tool(
                name="portability_status",
                title="Portability Status",
                description="Inspect which configured tools are stale, missing facts, or missing files.",
                method_name="portability_status",
                input_schema=_object_schema(
                    {
                        "project_dir": _string_property(
                            "Project directory to inspect. Defaults to the current working directory."
                        ),
                    },
                    include_namespace=False,
                ),
                read_only=True,
                namespace_param=False,
            ),
            self._service_tool(
                name="portability_audit",
                title="Portability Audit",
                description="Detect cross-tool drift, missing files, and context divergence across the portability surface.",
                method_name="portability_audit",
                input_schema=_object_schema(
                    {
                        "project_dir": _string_property(
                            "Project directory to inspect. Defaults to the current working directory."
                        ),
                    },
                    include_namespace=False,
                ),
                read_only=True,
                namespace_param=False,
            ),
            self._service_tool(
                name="pack_list",
                title="List Brainpacks",
                description="List local Brainpacks compiled and stored inside the Cortex workspace.",
                method_name="pack_list",
                input_schema=_object_schema({}, include_namespace=False),
                read_only=True,
                namespace_param=False,
            ),
            self._service_tool(
                name="pack_status",
                title="Brainpack Status",
                description="Inspect one Brainpack: source counts, compile status, wiki size, graph size, and unknowns.",
                method_name="pack_status",
                input_schema=_object_schema(
                    {
                        "name": _string_property("Brainpack name."),
                    },
                    required=("name",),
                    include_namespace=False,
                ),
                read_only=True,
                namespace_param=False,
            ),
            self._service_tool(
                name="pack_context",
                title="Brainpack Context",
                description="Render a routed context slice from a compiled Brainpack for a specific target runtime.",
                method_name="pack_context",
                input_schema=_object_schema(
                    {
                        "name": _string_property("Brainpack name."),
                        "target": _string_property("Target tool such as hermes, codex, cursor, claude-code, or chatgpt."),
                        "project_dir": _string_property(
                            "Optional working directory used to focus project-relevant context."
                        ),
                        "smart": _boolean_property("When true, use the target's smart routed slice."),
                        "policy": _string_property("Disclosure policy to use when smart routing is disabled."),
                        "max_chars": _integer_property("Maximum size of the rendered context markdown."),
                    },
                    required=("name", "target"),
                    include_namespace=False,
                ),
                read_only=True,
                namespace_param=False,
            ),
            self._service_tool(
                name="pack_compile",
                title="Compile Brainpack",
                description="Compile a Brainpack into wiki pages, a graph, claim candidates, and unknowns.",
                method_name="pack_compile",
                input_schema=_object_schema(
                    {
                        "name": _string_property("Brainpack name."),
                        "incremental": _boolean_property("Record this compile as incremental."),
                        "suggest_questions": _boolean_property("Suggest follow-up unknowns while compiling."),
                        "max_summary_chars": _integer_property("Summary length cap for generated wiki pages."),
                    },
                    required=("name",),
                    include_namespace=False,
                ),
                read_only=False,
                namespace_param=False,
            ),
            self._service_tool(
                name="channel_prepare_turn",
                title="Prepare Channel Turn",
                description=(
                    "Resolve a messaging-platform event into shared Cortex identity, routed live context, "
                    "and a durable write plan for per-user and per-thread memory."
                ),
                method_name="channel_prepare_turn",
                input_schema=_object_schema(
                    {
                        "message": {
                            "type": "object",
                            "description": "Normalized channel message payload.",
                            "additionalProperties": True,
                        },
                        "target": _string_property(
                            "Optional portability target such as chatgpt, claude, codex, cursor, copilot, gemini, grok, or windsurf."
                        ),
                        "smart": _boolean_property("Whether to use smart routing for the live context slice."),
                        "max_chars": _integer_property("Maximum rendered context markdown length."),
                        "project_dir": _string_property("Optional project directory used to focus project context."),
                    },
                    required=("message",),
                    include_namespace=False,
                ),
                read_only=True,
                namespace_param=False,
            ),
            self._service_tool(
                name="channel_seed_turn_memory",
                title="Seed Channel Memory",
                description=(
                    "Materialize the prepared Cortex per-user and per-thread memory scaffolds for a messaging turn."
                ),
                method_name="channel_seed_turn_memory",
                input_schema=_object_schema(
                    {
                        "turn": {
                            "type": "object",
                            "description": "Prepared channel turn envelope previously returned by channel_prepare_turn.",
                            "additionalProperties": True,
                        },
                        "ref": _string_property("Target ref or branch. Defaults to HEAD."),
                        "source": _string_property("Source label for the durable memory writes."),
                        "approve": _boolean_property("Whether to mark the write batch as approved."),
                    },
                    required=("turn",),
                    include_namespace=False,
                ),
                read_only=False,
                namespace_param=False,
            ),
            self._service_tool(
                name="index_status",
                title="Index Status",
                description="Inspect lexical index status and lag for a ref.",
                method_name="index_status",
                input_schema=_object_schema({"ref": _string_property("Ref to inspect. Defaults to HEAD.")}),
                read_only=True,
            ),
            self._service_tool(
                name="index_rebuild",
                title="Rebuild Index",
                description="Rebuild the persistent lexical index for a ref or for all refs.",
                method_name="index_rebuild",
                input_schema=_object_schema(
                    {
                        "ref": _string_property("Ref to rebuild. Defaults to HEAD."),
                        "all_refs": _boolean_property("Rebuild indexes for every known ref."),
                    }
                ),
                read_only=False,
            ),
            self._service_tool(
                name="prune_status",
                title="Prune Status",
                description="Inspect GC/pruning status without modifying the store.",
                method_name="prune_status",
                input_schema=_object_schema(
                    {"retention_days": _integer_property("Retention window, in days, used for maintenance decisions.")},
                    include_namespace=False,
                ),
                read_only=True,
                namespace_param=False,
            ),
            self._service_tool(
                name="prune",
                title="Run Prune",
                description="Run GC/pruning safely. Use dry_run=true first to inspect the plan.",
                method_name="prune",
                input_schema=_object_schema(
                    {
                        "dry_run": _boolean_property("When true, only preview the pruning plan."),
                        "retention_days": _integer_property("Retention window, in days, used for pruning."),
                    },
                    include_namespace=False,
                ),
                read_only=False,
                destructive=True,
                namespace_param=False,
            ),
            self._service_tool(
                name="prune_audit",
                title="Prune Audit Log",
                description="Inspect recent prune audit entries.",
                method_name="prune_audit",
                input_schema=_object_schema(
                    {"limit": _integer_property("Maximum number of audit entries to return.")},
                    include_namespace=False,
                ),
                read_only=True,
                namespace_param=False,
            ),
            self._service_tool(
                name="nodes_lookup",
                title="Lookup Nodes",
                description="Find nodes by id, canonical id, or label.",
                method_name="lookup_nodes",
                input_schema=_object_schema(
                    {
                        "node_id": _string_property("Exact node id."),
                        "canonical_id": _string_property("Canonical id to match."),
                        "label": _string_property("Label or alias to match."),
                        "ref": _string_property("Ref to query. Defaults to HEAD."),
                        "limit": _integer_property("Maximum number of matches."),
                    }
                ),
                read_only=True,
            ),
            self._service_tool(
                name="node_get",
                title="Get Node",
                description="Fetch one node with connected edges and claim lineage.",
                method_name="get_node",
                input_schema=_object_schema(
                    {
                        "node_id": _string_property("Node id to fetch."),
                        "ref": _string_property("Ref to inspect. Defaults to HEAD."),
                    },
                    required=("node_id",),
                ),
                read_only=True,
            ),
            self._service_tool(
                name="node_upsert",
                title="Upsert Node",
                description="Create or update a node and commit the change.",
                method_name="upsert_node",
                input_schema=_object_schema(
                    {
                        "node": node_schema,
                        "ref": _string_property("Write ref. Must resolve to HEAD or the current branch head."),
                        "message": _string_property("Commit message."),
                        "source": _string_property("Source label recorded on the commit."),
                        "actor": _string_property("Actor recorded for governance."),
                        "approve": _boolean_property("Approve governance-gated writes."),
                        "record_claim": _boolean_property("Append a provenance claim event for the mutation."),
                        "claim_source": _string_property("Explicit claim source."),
                        "claim_method": _string_property("Claim method label."),
                        "claim_metadata": dict(_JSON_OBJECT_SCHEMA, description="Extra claim metadata."),
                    },
                    required=("node",),
                ),
                read_only=False,
            ),
            self._service_tool(
                name="node_delete",
                title="Delete Node",
                description="Delete a node by id, canonical id, or label and commit the change.",
                method_name="delete_node",
                input_schema=_object_schema(
                    {
                        "node_id": _string_property("Node id to delete."),
                        "canonical_id": _string_property("Canonical id to delete."),
                        "label": _string_property("Label to match for deletion."),
                        "ref": _string_property("Write ref. Must resolve to HEAD or the current branch head."),
                        "message": _string_property("Commit message."),
                        "source": _string_property("Source label recorded on the commit."),
                        "actor": _string_property("Actor recorded for governance."),
                        "approve": _boolean_property("Approve governance-gated writes."),
                        "record_claim": _boolean_property("Append a provenance claim event for the mutation."),
                        "claim_source": _string_property("Explicit claim source."),
                        "claim_method": _string_property("Claim method label."),
                        "claim_metadata": dict(_JSON_OBJECT_SCHEMA, description="Extra claim metadata."),
                    }
                ),
                read_only=False,
                destructive=True,
            ),
            self._service_tool(
                name="edges_lookup",
                title="Lookup Edges",
                description="Find edges by id or source/target/relation.",
                method_name="lookup_edges",
                input_schema=_object_schema(
                    {
                        "edge_id": _string_property("Exact edge id."),
                        "source_id": _string_property("Source node id."),
                        "target_id": _string_property("Target node id."),
                        "relation": _string_property("Relation to match."),
                        "ref": _string_property("Ref to query. Defaults to HEAD."),
                        "limit": _integer_property("Maximum number of matches."),
                    }
                ),
                read_only=True,
            ),
            self._service_tool(
                name="edge_get",
                title="Get Edge",
                description="Fetch one edge with its source and target nodes.",
                method_name="get_edge",
                input_schema=_object_schema(
                    {
                        "edge_id": _string_property("Edge id to fetch."),
                        "ref": _string_property("Ref to inspect. Defaults to HEAD."),
                    },
                    required=("edge_id",),
                ),
                read_only=True,
            ),
            self._service_tool(
                name="edge_upsert",
                title="Upsert Edge",
                description="Create or update an edge and commit the change.",
                method_name="upsert_edge",
                input_schema=_object_schema(
                    {
                        "edge": edge_schema,
                        "ref": _string_property("Write ref. Must resolve to HEAD or the current branch head."),
                        "message": _string_property("Commit message."),
                        "source": _string_property("Source label recorded on the commit."),
                        "actor": _string_property("Actor recorded for governance."),
                        "approve": _boolean_property("Approve governance-gated writes."),
                    },
                    required=("edge",),
                ),
                read_only=False,
            ),
            self._service_tool(
                name="edge_delete",
                title="Delete Edge",
                description="Delete an edge by id or source/target/relation and commit the change.",
                method_name="delete_edge",
                input_schema=_object_schema(
                    {
                        "edge_id": _string_property("Edge id to delete."),
                        "source_id": _string_property("Source node id."),
                        "target_id": _string_property("Target node id."),
                        "relation": _string_property("Relation to match for deletion."),
                        "ref": _string_property("Write ref. Must resolve to HEAD or the current branch head."),
                        "message": _string_property("Commit message."),
                        "source": _string_property("Source label recorded on the commit."),
                        "actor": _string_property("Actor recorded for governance."),
                        "approve": _boolean_property("Approve governance-gated writes."),
                    }
                ),
                read_only=False,
                destructive=True,
            ),
            self._service_tool(
                name="claims_list",
                title="List Claims",
                description="List claim events by claim id, node identity, label, source, or op.",
                method_name="list_claims",
                input_schema=_object_schema(
                    {
                        "claim_id": _string_property("Claim id to inspect."),
                        "node_id": _string_property("Node id to inspect."),
                        "canonical_id": _string_property("Canonical id to inspect."),
                        "label": _string_property("Node label to inspect."),
                        "source": _string_property("Claim source to filter by."),
                        "ref": _string_property("Resolve claims through a ref first."),
                        "version_ref": _string_property("Explicit version ref filter."),
                        "op": _string_property("Filter by claim op, such as assert or retract."),
                        "limit": _integer_property("Maximum number of claim events."),
                    }
                ),
                read_only=True,
            ),
            self._service_tool(
                name="claim_assert",
                title="Assert Claim",
                description="Append a claim event and optionally materialize the node into the graph.",
                method_name="assert_claim",
                input_schema=_object_schema(
                    {
                        "node": node_schema,
                        "node_id": _string_property("Existing node id."),
                        "canonical_id": _string_property("Existing canonical id."),
                        "label": _string_property("Existing label."),
                        "ref": _string_property("Write ref. Must resolve to HEAD or the current branch head."),
                        "materialize": _boolean_property("When true, also write the node change into the graph."),
                        "message": _string_property("Commit or claim message."),
                        "source": _string_property("Source label recorded on the claim/commit."),
                        "method": _string_property("Claim method label."),
                        "actor": _string_property("Actor recorded for governance."),
                        "approve": _boolean_property("Approve governance-gated writes."),
                        "metadata": dict(_JSON_OBJECT_SCHEMA, description="Extra claim metadata."),
                    }
                ),
                read_only=False,
            ),
            self._service_tool(
                name="claim_retract",
                title="Retract Claim",
                description="Retract a claim event and optionally materialize removal from the graph.",
                method_name="retract_claim",
                input_schema=_object_schema(
                    {
                        "claim_id": _string_property("Claim id to retract."),
                        "node_id": _string_property("Node id linked to the claim."),
                        "canonical_id": _string_property("Canonical id linked to the claim."),
                        "label": _string_property("Node label linked to the claim."),
                        "ref": _string_property("Write ref. Must resolve to HEAD or the current branch head."),
                        "materialize": _boolean_property(
                            "When true, also remove the corresponding node from the graph."
                        ),
                        "message": _string_property("Commit or claim message."),
                        "actor": _string_property("Actor recorded for governance."),
                        "approve": _boolean_property("Approve governance-gated writes."),
                        "metadata": dict(_JSON_OBJECT_SCHEMA, description="Extra claim metadata."),
                    }
                ),
                read_only=False,
                destructive=True,
            ),
            self._service_tool(
                name="memory_batch",
                title="Memory Batch",
                description="Apply multiple object operations in one immutable commit.",
                method_name="memory_batch",
                input_schema=_object_schema(
                    {
                        "operations": _array_property(
                            "Ordered list of memory operations.", items=batch_operation_schema
                        ),
                        "ref": _string_property("Write ref. Must resolve to HEAD or the current branch head."),
                        "message": _string_property("Commit message."),
                        "source": _string_property("Source label recorded on the commit."),
                        "actor": _string_property("Actor recorded for governance."),
                        "approve": _boolean_property("Approve governance-gated writes."),
                    },
                    required=("operations",),
                ),
                read_only=False,
            ),
            self._service_tool(
                name="commits_log",
                title="Commit Log",
                description="Inspect the version history for a ref or namespace.",
                method_name="log",
                input_schema=_object_schema(
                    {
                        "limit": _integer_property("Maximum number of versions."),
                        "ref": _string_property("Optional ref to log."),
                    }
                ),
                read_only=True,
            ),
            self._service_tool(
                name="branches_list",
                title="List Branches",
                description="List branches visible to the session namespace.",
                method_name="list_branches",
                input_schema=_object_schema({}),
                read_only=True,
            ),
            self._service_tool(
                name="branch_create",
                title="Create Branch",
                description="Create a new branch from a ref.",
                method_name="create_branch",
                input_schema=_object_schema(
                    {
                        "name": _string_property("Branch name to create."),
                        "from_ref": _string_property("Ref to branch from."),
                        "switch": _boolean_property("Switch to the branch after creation."),
                        "actor": _string_property("Actor recorded for governance."),
                        "approve": _boolean_property("Approve governance-gated writes."),
                    },
                    required=("name",),
                ),
                read_only=False,
            ),
            self._service_tool(
                name="branch_switch",
                title="Switch Branch",
                description="Switch the active branch for the local store.",
                method_name="switch_branch",
                input_schema=_object_schema(
                    {
                        "name": _string_property("Branch name to switch to."),
                        "actor": _string_property("Actor recorded for governance."),
                        "approve": _boolean_property("Approve governance-gated writes."),
                    },
                    required=("name",),
                ),
                read_only=False,
            ),
            self._service_tool(
                name="checkout",
                title="Checkout Graph",
                description="Checkout a graph snapshot for a ref.",
                method_name="checkout",
                input_schema=_object_schema(
                    {
                        "ref": _string_property("Ref to checkout."),
                        "verify": _boolean_property("Verify graph signatures during checkout."),
                    }
                ),
                read_only=True,
            ),
            self._service_tool(
                name="diff",
                title="Diff Versions",
                description="Diff two versions or refs.",
                method_name="diff",
                input_schema=_object_schema(
                    {
                        "version_a": _string_property("Base version or ref."),
                        "version_b": _string_property("Target version or ref."),
                    },
                    required=("version_a", "version_b"),
                ),
                read_only=True,
            ),
            self._service_tool(
                name="commit",
                title="Commit Graph",
                description="Commit a full graph payload as an immutable version.",
                method_name="commit",
                input_schema=_object_schema(
                    {
                        "graph": graph_schema,
                        "message": _string_property("Commit message."),
                        "source": _string_property("Source label recorded on the commit."),
                        "actor": _string_property("Actor recorded for governance."),
                        "approve": _boolean_property("Approve governance-gated writes."),
                    },
                    required=("graph", "message"),
                ),
                read_only=False,
            ),
            self._service_tool(
                name="review",
                title="Review Memory",
                description="Compare a graph or ref against a baseline and surface review failures.",
                method_name="review",
                input_schema=_object_schema(
                    {
                        "against": _string_property("Baseline ref."),
                        "graph": graph_schema,
                        "ref": _string_property("Ref to review when graph is not supplied."),
                        "fail_on": _string_property("Review gate policies."),
                    },
                    required=("against",),
                ),
                read_only=True,
            ),
            self._service_tool(
                name="blame",
                title="Blame Memory",
                description="Explain which versions and claim events introduced a memory node.",
                method_name="blame",
                input_schema=_object_schema(
                    {
                        "label": _string_property("Node label to blame."),
                        "node_id": _string_property("Node id to blame."),
                        "graph": graph_schema,
                        "ref": _string_property("Ref to inspect."),
                        "source": _string_property("Optional source filter."),
                        "limit": _integer_property("Maximum number of versions to inspect."),
                    }
                ),
                read_only=True,
            ),
            self._service_tool(
                name="history",
                title="Node History",
                description="Inspect node history across versions with the same semantics as blame.",
                method_name="history",
                input_schema=_object_schema(
                    {
                        "label": _string_property("Node label to inspect."),
                        "node_id": _string_property("Node id to inspect."),
                        "graph": graph_schema,
                        "ref": _string_property("Ref to inspect."),
                        "source": _string_property("Optional source filter."),
                        "limit": _integer_property("Maximum number of versions to inspect."),
                    }
                ),
                read_only=True,
            ),
            self._service_tool(
                name="query_category",
                title="Query Category",
                description="Return nodes that carry a given tag.",
                method_name="query_category",
                input_schema=_object_schema(
                    {
                        "tag": _string_property("Tag to match."),
                        "graph": graph_schema,
                        "ref": _string_property("Ref to query. Defaults to HEAD."),
                    },
                    required=("tag",),
                ),
                read_only=True,
            ),
            self._service_tool(
                name="query_path",
                title="Query Path",
                description="Find graph paths between two labels.",
                method_name="query_path",
                input_schema=_object_schema(
                    {
                        "from_label": _string_property("Source label."),
                        "to_label": _string_property("Target label."),
                        "graph": graph_schema,
                        "ref": _string_property("Ref to query. Defaults to HEAD."),
                    },
                    required=("from_label", "to_label"),
                ),
                read_only=True,
            ),
            self._service_tool(
                name="query_related",
                title="Query Related",
                description="Traverse related nodes from a label with bounded depth.",
                method_name="query_related",
                input_schema=_object_schema(
                    {
                        "label": _string_property("Label to expand from."),
                        "depth": _integer_property("Traversal depth."),
                        "graph": graph_schema,
                        "ref": _string_property("Ref to query. Defaults to HEAD."),
                    },
                    required=("label",),
                ),
                read_only=True,
            ),
            self._service_tool(
                name="query_search",
                title="Query Search",
                description="Run lexical or hybrid search over a stored ref or graph payload.",
                method_name="query_search",
                input_schema=_object_schema(
                    {
                        "query": _string_property("Search query."),
                        "graph": graph_schema,
                        "ref": _string_property("Ref to query. Defaults to HEAD."),
                        "limit": _integer_property("Maximum number of results."),
                        "min_score": _number_property("Minimum score threshold."),
                    },
                    required=("query",),
                ),
                read_only=True,
            ),
            self._service_tool(
                name="query_dsl",
                title="Query DSL",
                description="Run the Cortex DSL query language against a graph or ref.",
                method_name="query_dsl",
                input_schema=_object_schema(
                    {
                        "query": _string_property("DSL query string."),
                        "graph": graph_schema,
                        "ref": _string_property("Ref to query. Defaults to HEAD."),
                    },
                    required=("query",),
                ),
                read_only=True,
            ),
            self._service_tool(
                name="query_nl",
                title="Natural Language Query",
                description="Run the built-in natural language query adapter against a graph or ref.",
                method_name="query_nl",
                input_schema=_object_schema(
                    {
                        "query": _string_property("Natural language query string."),
                        "graph": graph_schema,
                        "ref": _string_property("Ref to query. Defaults to HEAD."),
                    },
                    required=("query",),
                ),
                read_only=True,
            ),
            self._service_tool(
                name="conflicts_detect",
                title="Detect Conflicts",
                description="Detect semantic conflicts in a graph or ref without mutating it.",
                method_name="detect_conflicts",
                input_schema=_object_schema(
                    {
                        "graph": graph_schema,
                        "ref": _string_property("Ref to inspect. Defaults to HEAD."),
                        "min_severity": _number_property("Minimum severity threshold."),
                    }
                ),
                read_only=True,
            ),
            self._service_tool(
                name="conflict_resolve",
                title="Resolve Conflict",
                description="Resolve a semantic conflict in a graph payload or ref preview.",
                method_name="resolve_conflict",
                input_schema=_object_schema(
                    {
                        "conflict_id": _string_property("Conflict id to resolve."),
                        "action": _string_property("Resolution action: accept-new, keep-old, merge, or ignore."),
                        "graph": graph_schema,
                        "ref": _string_property("Ref to inspect. Defaults to HEAD."),
                    },
                    required=("conflict_id", "action"),
                ),
                read_only=False,
            ),
            self._service_tool(
                name="merge_preview",
                title="Merge Preview",
                description="Preview a merge between refs and optionally persist the merge worktree.",
                method_name="merge_preview",
                input_schema=_object_schema(
                    {
                        "other_ref": _string_property("Incoming ref to merge."),
                        "current_ref": _string_property("Current ref to merge into. Defaults to HEAD."),
                        "persist": _boolean_property("Persist pending merge state for later conflict resolution."),
                    },
                    required=("other_ref",),
                ),
                read_only=False,
            ),
            self._service_tool(
                name="merge_conflicts",
                title="Pending Merge Conflicts",
                description="Inspect pending merge state and unresolved merge conflicts.",
                method_name="merge_conflicts",
                input_schema=_object_schema({}),
                read_only=True,
            ),
            self._service_tool(
                name="merge_resolve",
                title="Resolve Merge Conflict",
                description="Resolve one pending merge conflict in the persisted merge worktree.",
                method_name="merge_resolve",
                input_schema=_object_schema(
                    {
                        "conflict_id": _string_property("Pending merge conflict id."),
                        "choose": _string_property("Resolution choice: current or incoming."),
                    },
                    required=("conflict_id", "choose"),
                ),
                read_only=False,
            ),
            self._service_tool(
                name="merge_commit_resolved",
                title="Commit Resolved Merge",
                description="Commit a persisted merge after all pending conflicts are resolved.",
                method_name="merge_commit_resolved",
                input_schema=_object_schema(
                    {
                        "message": _string_property("Optional merge commit message."),
                        "actor": _string_property("Actor recorded for governance."),
                        "approve": _boolean_property("Approve governance-gated merges."),
                    }
                ),
                read_only=False,
            ),
            self._service_tool(
                name="merge_abort",
                title="Abort Merge",
                description="Abort the pending merge worktree without creating a commit.",
                method_name="merge_abort",
                input_schema=_object_schema({}),
                read_only=False,
                destructive=True,
            ),
        ]

    def _validate_tool_arguments(self, tool: ToolDefinition, arguments: dict[str, Any]) -> None:
        schema = tool.input_schema
        required = schema.get("required", [])
        missing = [name for name in required if name not in arguments]
        if missing:
            joined = ", ".join(sorted(missing))
            raise JsonRpcError(-32602, f"Missing required argument(s) for tool '{tool.name}': {joined}")
        allowed = set(schema.get("properties", {}).keys())
        if not schema.get("additionalProperties", True):
            unknown = sorted(set(arguments) - allowed)
            if unknown:
                joined = ", ".join(unknown)
                raise JsonRpcError(-32602, f"Unknown argument(s) for tool '{tool.name}': {joined}")

    def _success_response(self, request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": result,
        }

    def _error_response(self, request_id: Any, error: JsonRpcError) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": error.code, "message": error.message},
        }
        if error.data is not None:
            payload["error"]["data"] = error.data
        return payload

    def _tool_result(self, result: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}],
            "structuredContent": result,
            "isError": is_error,
        }

    def _handle_initialize(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        protocol_version = params.get("protocolVersion")
        if not isinstance(protocol_version, str) or not protocol_version.strip():
            raise JsonRpcError(-32602, "initialize requires a string protocolVersion")
        self.protocol_version = (
            protocol_version if protocol_version in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[-1]
        )
        self.client_info = dict(params.get("clientInfo") or {})
        self._initialize_seen = True
        result = {
            "protocolVersion": self.protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": MCP_SERVER_NAME, "version": PROJECT_VERSION},
            "instructions": self._instructions(),
        }
        return self._success_response(request_id, result)

    def _handle_tools_list(self, request_id: Any) -> dict[str, Any]:
        return self._success_response(request_id, {"tools": [tool.as_payload() for tool in self._tools.values()]})

    def _handle_tools_call(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = params.get("name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise JsonRpcError(-32602, "tools/call requires a string tool name")
        tool = self._tools.get(tool_name)
        if tool is None:
            raise JsonRpcError(-32601, f"Unknown tool: {tool_name}")
        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(-32602, f"Tool '{tool_name}' arguments must be an object")
        self._validate_tool_arguments(tool, arguments)
        try:
            result = tool.handler(arguments)
            return self._success_response(request_id, self._tool_result(result))
        except JsonRpcError:
            raise
        except Exception as exc:
            error_payload = {"status": "error", "error": str(exc), "tool": tool_name}
            return self._success_response(request_id, self._tool_result(error_payload, is_error=True))

    def _dispatch_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if request.get("jsonrpc") != JSONRPC_VERSION:
            raise JsonRpcError(-32600, "Only JSON-RPC 2.0 messages are supported")
        if "method" not in request or not isinstance(request["method"], str):
            raise JsonRpcError(-32600, "Request is missing a string method")

        request_id = request.get("id")
        method = request["method"]
        params = request.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise JsonRpcError(-32602, "Request params must be an object")

        if method == "initialize":
            return self._handle_initialize(request_id, params)
        if method == "notifications/initialized":
            self._client_ready = True
            return None
        if method == "notifications/cancelled":
            return None
        if method == "ping":
            return None if request_id is None else self._success_response(request_id, {})

        if not self._initialize_seen:
            raise JsonRpcError(-32002, "Cortex MCP server must be initialized before calling tools")

        if method == "tools/list":
            return None if request_id is None else self._handle_tools_list(request_id)
        if method == "tools/call":
            return None if request_id is None else self._handle_tools_call(request_id, params)

        raise JsonRpcError(-32601, f"Method not found: {method}")

    def handle_message(self, message: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
        if isinstance(message, list):
            if not message:
                return self._error_response(None, JsonRpcError(-32600, "JSON-RPC batch must not be empty"))
            responses: list[dict[str, Any]] = []
            for item in message:
                if not isinstance(item, dict):
                    responses.append(self._error_response(None, JsonRpcError(-32600, "Batch items must be objects")))
                    continue
                try:
                    response = self._dispatch_request(item)
                except JsonRpcError as exc:
                    response = self._error_response(item.get("id"), exc)
                if response is not None:
                    responses.append(response)
            return responses or None

        if not isinstance(message, dict):
            return self._error_response(None, JsonRpcError(-32600, "JSON-RPC message must be an object"))

        try:
            return self._dispatch_request(message)
        except JsonRpcError as exc:
            return self._error_response(message.get("id"), exc)

    def serve_streams(self, input_stream: TextIO, output_stream: TextIO) -> int:
        for raw_line in input_stream:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                response = self._error_response(None, JsonRpcError(-32700, f"Parse error: {exc.msg}"))
            else:
                response = self.handle_message(payload)
            if response is None:
                continue
            output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
            output_stream.flush()
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cortex-mcp", description="Run Cortex as a local MCP tool server over stdio.")
    parser.add_argument("--store-dir", default=None, help="Storage directory (default from config or .cortex)")
    parser.add_argument("--context-file", help="Optional default context graph file")
    parser.add_argument(
        "--namespace",
        help="Optional namespace prefix to pin the MCP session to, such as 'team' or 'team/atlas'",
    )
    parser.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    parser.add_argument("--check", action="store_true", help="Print startup diagnostics and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_selfhost_config(
            store_dir=args.store_dir,
            context_file=args.context_file,
            config_path=args.config,
            mcp_namespace=args.namespace,
        )
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    diagnostics = format_startup_diagnostics(config, mode="mcp")
    if args.check:
        print(diagnostics)
        return 0

    server = CortexMCPServer(
        store_dir=config.store_dir,
        context_file=config.context_file,
        namespace=config.mcp_namespace,
    )
    return server.serve_streams(sys.stdin, sys.stdout)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
