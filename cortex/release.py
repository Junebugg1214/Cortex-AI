from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_VERSION = "1.4.1"
PACKAGE_NAME = "cortex-identity"
API_VERSION = "v1"
OPENAPI_VERSION = "1.0.0"
PYTHON_SDK_NAME = "cortex-python-sdk"
PYTHON_SDK_MODULE = "cortex.client"
TYPESCRIPT_SDK_NAME = "@cortex-ai/sdk"
MCP_SERVER_NAME = "Cortex"
STORAGE_MODEL = "user-owned"
RELEASE_CHANNEL = "self-hosted"
OPENAPI_ARTIFACT_PATH = Path("openapi") / "cortex-api-v1.json"
OPENAPI_COMPAT_PATH = Path("openapi") / "cortex-api-v1-compat.json"


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _normalized_contract_spec(spec: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(spec))
    normalized.pop("servers", None)
    info = normalized.get("info")
    if isinstance(info, dict):
        info.pop("x-cortex-release", None)
    return normalized


def openapi_contract_hash(spec: dict[str, Any]) -> str:
    normalized = _normalized_contract_spec(spec)
    return hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()


def _operation_entries(spec: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path, operations in sorted((spec.get("paths") or {}).items()):
        if not isinstance(operations, dict):
            continue
        for method, operation in sorted(operations.items()):
            if not isinstance(operation, dict):
                continue
            entries.append(
                {
                    "method": method.upper(),
                    "path": str(path),
                    "operation_id": str(operation.get("operationId", "")),
                    "summary": str(operation.get("summary", "")),
                }
            )
    return entries


def build_contract_compatibility_snapshot(spec: dict[str, Any]) -> dict[str, Any]:
    operations = _operation_entries(spec)
    tag_names = sorted(
        {
            str(tag)
            for operation in (item for item in (spec.get("paths") or {}).values() if isinstance(item, dict))
            for entry in operation.values()
            if isinstance(entry, dict)
            for tag in entry.get("tags", [])
        }
    )
    return {
        "api_version": API_VERSION,
        "openapi_version": OPENAPI_VERSION,
        "project_version": PROJECT_VERSION,
        "storage_model": STORAGE_MODEL,
        "release_channel": RELEASE_CHANNEL,
        "path_count": len(spec.get("paths") or {}),
        "operation_count": len(operations),
        "contract_hash": openapi_contract_hash(spec),
        "operations": operations,
        "tags": tag_names,
    }


def build_release_metadata(spec: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "project_version": PROJECT_VERSION,
        "package_name": PACKAGE_NAME,
        "api_version": API_VERSION,
        "openapi_version": OPENAPI_VERSION,
        "python_sdk": {"name": PYTHON_SDK_NAME, "module": PYTHON_SDK_MODULE, "version": PROJECT_VERSION},
        "typescript_sdk": {"name": TYPESCRIPT_SDK_NAME, "version": PROJECT_VERSION},
        "mcp_server": {"name": MCP_SERVER_NAME, "version": PROJECT_VERSION},
        "storage_model": STORAGE_MODEL,
        "release_channel": RELEASE_CHANNEL,
    }
    if spec is not None:
        compatibility = build_contract_compatibility_snapshot(spec)
        payload["contract"] = {
            "hash": compatibility["contract_hash"],
            "path_count": compatibility["path_count"],
            "operation_count": compatibility["operation_count"],
        }
    return payload


def write_contract_compatibility_snapshot(output_path: str | Path, spec: dict[str, Any]) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_contract_compatibility_snapshot(spec), indent=2) + "\n", encoding="utf-8")
    return target


__all__ = [
    "API_VERSION",
    "MCP_SERVER_NAME",
    "OPENAPI_ARTIFACT_PATH",
    "OPENAPI_COMPAT_PATH",
    "OPENAPI_VERSION",
    "PACKAGE_NAME",
    "PROJECT_VERSION",
    "PYTHON_SDK_MODULE",
    "PYTHON_SDK_NAME",
    "RELEASE_CHANNEL",
    "STORAGE_MODEL",
    "TYPESCRIPT_SDK_NAME",
    "build_contract_compatibility_snapshot",
    "build_release_metadata",
    "openapi_contract_hash",
    "write_contract_compatibility_snapshot",
]
