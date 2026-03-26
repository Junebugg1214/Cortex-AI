from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _json_object_schema(*, description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": True,
    }
    if description:
        schema["description"] = description
    return schema


def _request_body(schema_ref: str, *, required: bool = True) -> dict[str, Any]:
    return {
        "required": required,
        "content": {
            "application/json": {
                "schema": {"$ref": schema_ref},
            }
        },
    }


def build_openapi_spec(*, server_url: str | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": "Cortex Local API",
            "version": "1.0.0",
            "description": (
                "Local-first REST API for Cortex, the Git-for-AI-Memory runtime. "
                "This surface covers versioning, review, query, conflicts, and merge workflows."
            ),
        },
        "paths": {
            "/v1/health": {
                "get": {
                    "operationId": "health",
                    "summary": "Check API health",
                    "tags": ["meta"],
                    "responses": {
                        "200": {
                            "description": "Service health",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/meta": {
                "get": {
                    "operationId": "meta",
                    "summary": "Read service metadata",
                    "tags": ["meta"],
                    "responses": {
                        "200": {
                            "description": "Service metadata",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/metrics": {
                "get": {
                    "operationId": "metrics",
                    "summary": "Read self-hosted service metrics",
                    "tags": ["meta"],
                    "responses": {
                        "200": {
                            "description": "Service metrics",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/index/status": {
                "get": {
                    "operationId": "indexStatus",
                    "summary": "Read lexical index status for a stored ref",
                    "tags": ["index"],
                    "parameters": [
                        {"name": "ref", "in": "query", "schema": {"type": "string", "default": "HEAD"}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Index status",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/prune/status": {
                "get": {
                    "operationId": "pruneStatus",
                    "summary": "Preview maintenance and pruning work",
                    "tags": ["maintenance"],
                    "parameters": [
                        {"name": "retention_days", "in": "query", "schema": {"type": "integer", "default": 7}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Prune status",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/prune/audit": {
                "get": {
                    "operationId": "pruneAudit",
                    "summary": "Read maintenance audit history",
                    "tags": ["maintenance"],
                    "parameters": [
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Prune audit log",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/openapi.json": {
                "get": {
                    "operationId": "openapi",
                    "summary": "Fetch the OpenAPI contract",
                    "tags": ["meta"],
                    "responses": {
                        "200": {
                            "description": "OpenAPI specification",
                            "content": {
                                "application/json": {"schema": _json_object_schema(description="OpenAPI v1 document")}
                            },
                        }
                    },
                }
            },
            "/v1/nodes": {
                "get": {
                    "operationId": "lookupNodes",
                    "summary": "Lookup memory nodes by id, canonical id, or label",
                    "tags": ["objects"],
                    "parameters": [
                        {"name": "id", "in": "query", "schema": {"type": "string"}},
                        {"name": "canonical_id", "in": "query", "schema": {"type": "string"}},
                        {"name": "label", "in": "query", "schema": {"type": "string"}},
                        {"name": "ref", "in": "query", "schema": {"type": "string", "default": "HEAD"}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 10}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Node lookup result",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/nodes/{node_id}": {
                "get": {
                    "operationId": "getNode",
                    "summary": "Read a memory node by id",
                    "tags": ["objects"],
                    "parameters": [
                        {"name": "node_id", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "ref", "in": "query", "schema": {"type": "string", "default": "HEAD"}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Node detail",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/nodes/upsert": {
                "post": {
                    "operationId": "upsertNode",
                    "summary": "Upsert a memory node and materialize a commit",
                    "tags": ["objects"],
                    "requestBody": _request_body("#/components/schemas/UpsertNodeRequest"),
                    "responses": {
                        "200": {
                            "description": "Upserted node",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/nodes/delete": {
                "post": {
                    "operationId": "deleteNode",
                    "summary": "Delete a memory node and materialize a commit",
                    "tags": ["objects"],
                    "requestBody": _request_body("#/components/schemas/DeleteNodeRequest"),
                    "responses": {
                        "200": {
                            "description": "Deleted node",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/edges": {
                "get": {
                    "operationId": "lookupEdges",
                    "summary": "Lookup memory edges by id or endpoint triple",
                    "tags": ["objects"],
                    "parameters": [
                        {"name": "id", "in": "query", "schema": {"type": "string"}},
                        {"name": "source_id", "in": "query", "schema": {"type": "string"}},
                        {"name": "target_id", "in": "query", "schema": {"type": "string"}},
                        {"name": "relation", "in": "query", "schema": {"type": "string"}},
                        {"name": "ref", "in": "query", "schema": {"type": "string", "default": "HEAD"}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 10}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Edge lookup result",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/edges/{edge_id}": {
                "get": {
                    "operationId": "getEdge",
                    "summary": "Read a memory edge by id",
                    "tags": ["objects"],
                    "parameters": [
                        {"name": "edge_id", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "ref", "in": "query", "schema": {"type": "string", "default": "HEAD"}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Edge detail",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/edges/upsert": {
                "post": {
                    "operationId": "upsertEdge",
                    "summary": "Upsert a memory edge and materialize a commit",
                    "tags": ["objects"],
                    "requestBody": _request_body("#/components/schemas/UpsertEdgeRequest"),
                    "responses": {
                        "200": {
                            "description": "Upserted edge",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/edges/delete": {
                "post": {
                    "operationId": "deleteEdge",
                    "summary": "Delete a memory edge and materialize a commit",
                    "tags": ["objects"],
                    "requestBody": _request_body("#/components/schemas/DeleteEdgeRequest"),
                    "responses": {
                        "200": {
                            "description": "Deleted edge",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/claims": {
                "get": {
                    "operationId": "listClaims",
                    "summary": "List claim events with optional filters",
                    "tags": ["objects"],
                    "parameters": [
                        {"name": "claim_id", "in": "query", "schema": {"type": "string"}},
                        {"name": "node_id", "in": "query", "schema": {"type": "string"}},
                        {"name": "canonical_id", "in": "query", "schema": {"type": "string"}},
                        {"name": "label", "in": "query", "schema": {"type": "string"}},
                        {"name": "source", "in": "query", "schema": {"type": "string"}},
                        {"name": "ref", "in": "query", "schema": {"type": "string"}},
                        {"name": "version_ref", "in": "query", "schema": {"type": "string"}},
                        {"name": "op", "in": "query", "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Claim list",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/claims/assert": {
                "post": {
                    "operationId": "assertClaim",
                    "summary": "Append a claim assertion and optionally materialize it",
                    "tags": ["objects"],
                    "requestBody": _request_body("#/components/schemas/AssertClaimRequest"),
                    "responses": {
                        "200": {
                            "description": "Asserted claim",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/claims/retract": {
                "post": {
                    "operationId": "retractClaim",
                    "summary": "Retract a claim and optionally materialize it",
                    "tags": ["objects"],
                    "requestBody": _request_body("#/components/schemas/RetractClaimRequest"),
                    "responses": {
                        "200": {
                            "description": "Retracted claim",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/memory/batch": {
                "post": {
                    "operationId": "memoryBatch",
                    "summary": "Apply multiple object operations in a single commit-backed batch",
                    "tags": ["objects"],
                    "requestBody": _request_body("#/components/schemas/MemoryBatchRequest"),
                    "responses": {
                        "200": {
                            "description": "Applied memory object batch",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/branches": {
                "get": {
                    "operationId": "listBranches",
                    "summary": "List memory branches",
                    "tags": ["branches"],
                    "responses": {
                        "200": {
                            "description": "Branch list",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                },
                "post": {
                    "operationId": "createBranch",
                    "summary": "Create a branch",
                    "tags": ["branches"],
                    "requestBody": _request_body("#/components/schemas/CreateBranchRequest"),
                    "responses": {
                        "201": {
                            "description": "Branch created",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                },
            },
            "/v1/branches/switch": {
                "post": {
                    "operationId": "switchBranch",
                    "summary": "Switch the active branch",
                    "tags": ["branches"],
                    "requestBody": _request_body("#/components/schemas/SwitchBranchRequest"),
                    "responses": {
                        "200": {
                            "description": "Switched branch",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/commits": {
                "get": {
                    "operationId": "listCommits",
                    "summary": "List commits for a branch or ref",
                    "tags": ["versions"],
                    "parameters": [
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 10}},
                        {"name": "ref", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Commit log",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/commit": {
                "post": {
                    "operationId": "commit",
                    "summary": "Commit a graph snapshot",
                    "tags": ["versions"],
                    "requestBody": _request_body("#/components/schemas/CommitRequest"),
                    "responses": {
                        "201": {
                            "description": "Committed graph",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/checkout": {
                "post": {
                    "operationId": "checkout",
                    "summary": "Checkout a graph version or ref",
                    "tags": ["versions"],
                    "requestBody": _request_body("#/components/schemas/CheckoutRequest"),
                    "responses": {
                        "200": {
                            "description": "Checked out graph",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/diff": {
                "post": {
                    "operationId": "diff",
                    "summary": "Diff two refs or versions",
                    "tags": ["versions"],
                    "requestBody": _request_body("#/components/schemas/DiffRequest"),
                    "responses": {
                        "200": {
                            "description": "Graph diff",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/review": {
                "post": {
                    "operationId": "review",
                    "summary": "Review a graph against a baseline ref",
                    "tags": ["review"],
                    "requestBody": _request_body("#/components/schemas/ReviewRequest"),
                    "responses": {
                        "200": {
                            "description": "Review result",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/blame": {
                "post": {
                    "operationId": "blame",
                    "summary": "Trace why a memory node exists",
                    "tags": ["audit"],
                    "requestBody": _request_body("#/components/schemas/BlameRequest"),
                    "responses": {
                        "200": {
                            "description": "Blame result",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/history": {
                "post": {
                    "operationId": "history",
                    "summary": "Read chronological receipts for a memory node",
                    "tags": ["audit"],
                    "requestBody": _request_body("#/components/schemas/HistoryRequest"),
                    "responses": {
                        "200": {
                            "description": "History result",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/conflicts/detect": {
                "post": {
                    "operationId": "detectConflicts",
                    "summary": "Detect memory conflicts",
                    "tags": ["conflicts"],
                    "requestBody": _request_body("#/components/schemas/DetectConflictsRequest"),
                    "responses": {
                        "200": {
                            "description": "Detected conflicts",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/conflicts/resolve": {
                "post": {
                    "operationId": "resolveConflict",
                    "summary": "Resolve a memory conflict",
                    "tags": ["conflicts"],
                    "requestBody": _request_body("#/components/schemas/ResolveConflictRequest"),
                    "responses": {
                        "200": {
                            "description": "Resolved conflict",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/index/rebuild": {
                "post": {
                    "operationId": "indexRebuild",
                    "summary": "Rebuild persisted lexical indexes",
                    "tags": ["index"],
                    "requestBody": _request_body("#/components/schemas/IndexRebuildRequest"),
                    "responses": {
                        "200": {
                            "description": "Index rebuild result",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/prune": {
                "post": {
                    "operationId": "prune",
                    "summary": "Run safe garbage collection and pruning",
                    "tags": ["maintenance"],
                    "requestBody": _request_body("#/components/schemas/PruneRequest"),
                    "responses": {
                        "200": {
                            "description": "Prune result",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/query/category": {
                "post": {
                    "operationId": "queryCategory",
                    "summary": "Query nodes by tag",
                    "tags": ["query"],
                    "requestBody": _request_body("#/components/schemas/QueryCategoryRequest"),
                    "responses": {
                        "200": {
                            "description": "Category query result",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/query/path": {
                "post": {
                    "operationId": "queryPath",
                    "summary": "Query shortest path between two labels",
                    "tags": ["query"],
                    "requestBody": _request_body("#/components/schemas/QueryPathRequest"),
                    "responses": {
                        "200": {
                            "description": "Path query result",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/query/related": {
                "post": {
                    "operationId": "queryRelated",
                    "summary": "Query related nodes",
                    "tags": ["query"],
                    "requestBody": _request_body("#/components/schemas/QueryRelatedRequest"),
                    "responses": {
                        "200": {
                            "description": "Related-node query result",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/query/search": {
                "post": {
                    "operationId": "querySearch",
                    "summary": "Run semantic graph search",
                    "tags": ["query"],
                    "requestBody": _request_body("#/components/schemas/QuerySearchRequest"),
                    "responses": {
                        "200": {
                            "description": "Search result",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/query/dsl": {
                "post": {
                    "operationId": "queryDsl",
                    "summary": "Run the Cortex query DSL",
                    "tags": ["query"],
                    "requestBody": _request_body("#/components/schemas/QueryDslRequest"),
                    "responses": {
                        "200": {
                            "description": "DSL query result",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/query/nl": {
                "post": {
                    "operationId": "queryNl",
                    "summary": "Run a natural-language query",
                    "tags": ["query"],
                    "requestBody": _request_body("#/components/schemas/QueryNlRequest"),
                    "responses": {
                        "200": {
                            "description": "Natural-language query result",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/merge-preview": {
                "post": {
                    "operationId": "mergePreview",
                    "summary": "Preview a merge between refs",
                    "tags": ["merge"],
                    "requestBody": _request_body("#/components/schemas/MergePreviewRequest"),
                    "responses": {
                        "200": {
                            "description": "Merge preview",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/merge/conflicts": {
                "post": {
                    "operationId": "mergeConflicts",
                    "summary": "Inspect pending merge conflicts",
                    "tags": ["merge"],
                    "requestBody": _request_body("#/components/schemas/EmptyRequest"),
                    "responses": {
                        "200": {
                            "description": "Pending merge state",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/merge/resolve": {
                "post": {
                    "operationId": "mergeResolve",
                    "summary": "Resolve a pending merge conflict",
                    "tags": ["merge"],
                    "requestBody": _request_body("#/components/schemas/MergeResolveRequest"),
                    "responses": {
                        "200": {
                            "description": "Resolved merge conflict",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/merge/commit-resolved": {
                "post": {
                    "operationId": "mergeCommitResolved",
                    "summary": "Commit a resolved merge",
                    "tags": ["merge"],
                    "requestBody": _request_body("#/components/schemas/MergeCommitResolvedRequest"),
                    "responses": {
                        "200": {
                            "description": "Committed merge",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
            "/v1/merge/abort": {
                "post": {
                    "operationId": "mergeAbort",
                    "summary": "Abort a pending merge",
                    "tags": ["merge"],
                    "requestBody": _request_body("#/components/schemas/EmptyRequest"),
                    "responses": {
                        "200": {
                            "description": "Aborted merge",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiResponse"}}},
                        }
                    },
                }
            },
        },
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"},
                "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
            },
            "schemas": {
                "ApiResponse": _json_object_schema(
                    description="Generic JSON response envelope used by the local Cortex API."
                ),
                "ApiError": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["error"]},
                        "error": {"type": "string"},
                    },
                    "required": ["status", "error"],
                    "additionalProperties": True,
                },
                "GraphPayload": _json_object_schema(description="Cortex graph export payload."),
                "EmptyRequest": {"type": "object", "additionalProperties": False},
                "IndexRebuildRequest": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "default": "HEAD"},
                        "all_refs": {"type": "boolean", "default": False},
                    },
                    "additionalProperties": False,
                },
                "PruneRequest": {
                    "type": "object",
                    "properties": {
                        "dry_run": {"type": "boolean", "default": True},
                        "retention_days": {"type": "integer", "default": 7},
                    },
                    "additionalProperties": False,
                },
                "MemoryNodeObject": _json_object_schema(description="Public memory node object payload."),
                "MemoryEdgeObject": _json_object_schema(description="Public memory edge object payload."),
                "MemoryOperation": _json_object_schema(description="Single memory object batch operation."),
                "UpsertNodeRequest": {
                    "type": "object",
                    "properties": {
                        "node": {"$ref": "#/components/schemas/MemoryNodeObject"},
                        "ref": {"type": "string", "default": "HEAD"},
                        "message": {"type": "string", "default": ""},
                        "source": {"type": "string", "default": "api.object"},
                        "actor": {"type": "string", "default": "manual"},
                        "approve": {"type": "boolean", "default": False},
                        "record_claim": {"type": "boolean", "default": True},
                        "claim_source": {"type": "string", "default": ""},
                        "claim_method": {"type": "string", "default": "nodes.upsert"},
                        "claim_metadata": _json_object_schema(),
                    },
                    "required": ["node"],
                    "additionalProperties": False,
                },
                "DeleteNodeRequest": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string", "default": ""},
                        "canonical_id": {"type": "string", "default": ""},
                        "label": {"type": "string", "default": ""},
                        "ref": {"type": "string", "default": "HEAD"},
                        "message": {"type": "string", "default": ""},
                        "source": {"type": "string", "default": "api.object"},
                        "actor": {"type": "string", "default": "manual"},
                        "approve": {"type": "boolean", "default": False},
                        "record_claim": {"type": "boolean", "default": True},
                        "claim_source": {"type": "string", "default": ""},
                        "claim_method": {"type": "string", "default": "nodes.delete"},
                        "claim_metadata": _json_object_schema(),
                    },
                    "additionalProperties": False,
                },
                "UpsertEdgeRequest": {
                    "type": "object",
                    "properties": {
                        "edge": {"$ref": "#/components/schemas/MemoryEdgeObject"},
                        "ref": {"type": "string", "default": "HEAD"},
                        "message": {"type": "string", "default": ""},
                        "source": {"type": "string", "default": "api.object"},
                        "actor": {"type": "string", "default": "manual"},
                        "approve": {"type": "boolean", "default": False},
                    },
                    "required": ["edge"],
                    "additionalProperties": False,
                },
                "DeleteEdgeRequest": {
                    "type": "object",
                    "properties": {
                        "edge_id": {"type": "string", "default": ""},
                        "source_id": {"type": "string", "default": ""},
                        "target_id": {"type": "string", "default": ""},
                        "relation": {"type": "string", "default": ""},
                        "ref": {"type": "string", "default": "HEAD"},
                        "message": {"type": "string", "default": ""},
                        "source": {"type": "string", "default": "api.object"},
                        "actor": {"type": "string", "default": "manual"},
                        "approve": {"type": "boolean", "default": False},
                    },
                    "additionalProperties": False,
                },
                "AssertClaimRequest": {
                    "type": "object",
                    "properties": {
                        "node": {"$ref": "#/components/schemas/MemoryNodeObject"},
                        "node_id": {"type": "string", "default": ""},
                        "canonical_id": {"type": "string", "default": ""},
                        "label": {"type": "string", "default": ""},
                        "ref": {"type": "string", "default": "HEAD"},
                        "materialize": {"type": "boolean", "default": True},
                        "message": {"type": "string", "default": ""},
                        "source": {"type": "string", "default": "api.object"},
                        "method": {"type": "string", "default": "claims.assert"},
                        "actor": {"type": "string", "default": "manual"},
                        "approve": {"type": "boolean", "default": False},
                        "metadata": _json_object_schema(),
                    },
                    "additionalProperties": False,
                },
                "RetractClaimRequest": {
                    "type": "object",
                    "properties": {
                        "claim_id": {"type": "string", "default": ""},
                        "node_id": {"type": "string", "default": ""},
                        "canonical_id": {"type": "string", "default": ""},
                        "label": {"type": "string", "default": ""},
                        "ref": {"type": "string", "default": "HEAD"},
                        "materialize": {"type": "boolean", "default": True},
                        "message": {"type": "string", "default": ""},
                        "actor": {"type": "string", "default": "manual"},
                        "approve": {"type": "boolean", "default": False},
                        "metadata": _json_object_schema(),
                    },
                    "additionalProperties": False,
                },
                "MemoryBatchRequest": {
                    "type": "object",
                    "properties": {
                        "operations": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/MemoryOperation"},
                        },
                        "ref": {"type": "string", "default": "HEAD"},
                        "message": {"type": "string", "default": ""},
                        "source": {"type": "string", "default": "api.object"},
                        "actor": {"type": "string", "default": "manual"},
                        "approve": {"type": "boolean", "default": False},
                    },
                    "required": ["operations"],
                    "additionalProperties": False,
                },
                "CreateBranchRequest": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "from_ref": {"type": "string", "default": "HEAD"},
                        "switch": {"type": "boolean", "default": False},
                        "actor": {"type": "string", "default": "manual"},
                        "approve": {"type": "boolean", "default": False},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                "SwitchBranchRequest": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "actor": {"type": "string", "default": "manual"},
                        "approve": {"type": "boolean", "default": False},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                "CommitRequest": {
                    "type": "object",
                    "properties": {
                        "graph": {"$ref": "#/components/schemas/GraphPayload"},
                        "message": {"type": "string"},
                        "source": {"type": "string", "default": "manual"},
                        "actor": {"type": "string", "default": "manual"},
                        "approve": {"type": "boolean", "default": False},
                    },
                    "required": ["graph", "message"],
                    "additionalProperties": False,
                },
                "CheckoutRequest": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "default": "HEAD"},
                        "verify": {"type": "boolean", "default": True},
                    },
                    "additionalProperties": False,
                },
                "DiffRequest": {
                    "type": "object",
                    "properties": {
                        "version_a": {"type": "string"},
                        "version_b": {"type": "string"},
                    },
                    "required": ["version_a", "version_b"],
                    "additionalProperties": False,
                },
                "ReviewRequest": {
                    "type": "object",
                    "properties": {
                        "against": {"type": "string"},
                        "graph": {"$ref": "#/components/schemas/GraphPayload"},
                        "ref": {"type": "string", "default": "HEAD"},
                        "fail_on": {"type": "string", "default": "blocking"},
                    },
                    "required": ["against"],
                    "additionalProperties": False,
                },
                "BlameRequest": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "default": ""},
                        "node_id": {"type": "string", "default": ""},
                        "graph": {"$ref": "#/components/schemas/GraphPayload"},
                        "ref": {"type": "string", "default": "HEAD"},
                        "source": {"type": "string", "default": ""},
                        "limit": {"type": "integer", "default": 20},
                    },
                    "additionalProperties": False,
                },
                "HistoryRequest": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "default": ""},
                        "node_id": {"type": "string", "default": ""},
                        "graph": {"$ref": "#/components/schemas/GraphPayload"},
                        "ref": {"type": "string", "default": "HEAD"},
                        "source": {"type": "string", "default": ""},
                        "limit": {"type": "integer", "default": 20},
                    },
                    "additionalProperties": False,
                },
                "DetectConflictsRequest": {
                    "type": "object",
                    "properties": {
                        "graph": {"$ref": "#/components/schemas/GraphPayload"},
                        "ref": {"type": "string", "default": "HEAD"},
                        "min_severity": {"type": "number", "default": 0.0},
                    },
                    "additionalProperties": False,
                },
                "ResolveConflictRequest": {
                    "type": "object",
                    "properties": {
                        "conflict_id": {"type": "string"},
                        "action": {"type": "string", "enum": ["accept-new", "keep-old", "merge", "ignore"]},
                        "graph": {"$ref": "#/components/schemas/GraphPayload"},
                        "ref": {"type": "string", "default": "HEAD"},
                    },
                    "required": ["conflict_id", "action"],
                    "additionalProperties": False,
                },
                "QueryCategoryRequest": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "graph": {"$ref": "#/components/schemas/GraphPayload"},
                        "ref": {"type": "string", "default": "HEAD"},
                    },
                    "required": ["tag"],
                    "additionalProperties": False,
                },
                "QueryPathRequest": {
                    "type": "object",
                    "properties": {
                        "from_label": {"type": "string"},
                        "to_label": {"type": "string"},
                        "graph": {"$ref": "#/components/schemas/GraphPayload"},
                        "ref": {"type": "string", "default": "HEAD"},
                    },
                    "required": ["from_label", "to_label"],
                    "additionalProperties": False,
                },
                "QueryRelatedRequest": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "depth": {"type": "integer", "default": 2},
                        "graph": {"$ref": "#/components/schemas/GraphPayload"},
                        "ref": {"type": "string", "default": "HEAD"},
                    },
                    "required": ["label"],
                    "additionalProperties": False,
                },
                "QuerySearchRequest": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "graph": {"$ref": "#/components/schemas/GraphPayload"},
                        "ref": {"type": "string", "default": "HEAD"},
                        "limit": {"type": "integer", "default": 10},
                        "min_score": {"type": "number", "default": 0.0},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                "QueryDslRequest": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "graph": {"$ref": "#/components/schemas/GraphPayload"},
                        "ref": {"type": "string", "default": "HEAD"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                "QueryNlRequest": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "graph": {"$ref": "#/components/schemas/GraphPayload"},
                        "ref": {"type": "string", "default": "HEAD"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                "MergePreviewRequest": {
                    "type": "object",
                    "properties": {
                        "other_ref": {"type": "string"},
                        "current_ref": {"type": "string", "default": "HEAD"},
                        "persist": {"type": "boolean", "default": False},
                    },
                    "required": ["other_ref"],
                    "additionalProperties": False,
                },
                "MergeResolveRequest": {
                    "type": "object",
                    "properties": {
                        "conflict_id": {"type": "string"},
                        "choose": {"type": "string", "enum": ["current", "incoming"]},
                    },
                    "required": ["conflict_id", "choose"],
                    "additionalProperties": False,
                },
                "MergeCommitResolvedRequest": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                        "actor": {"type": "string", "default": "manual"},
                        "approve": {"type": "boolean", "default": False},
                    },
                    "additionalProperties": False,
                },
            },
        },
    }
    if server_url:
        spec["servers"] = [{"url": server_url}]
    return spec


def write_openapi_spec(output_path: str | Path, *, server_url: str | None = None) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_openapi_spec(server_url=server_url), indent=2) + "\n", encoding="utf-8")
    return target


__all__ = ["build_openapi_spec", "write_openapi_spec"]
