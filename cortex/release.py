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
DOCKER_IMAGE_NAME = "ghcr.io/junebugg1214/cortex-ai"
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


def build_release_manifest(
    spec: dict[str, Any],
    *,
    tag: str | None = None,
    commit_sha: str | None = None,
) -> dict[str, Any]:
    compatibility = build_contract_compatibility_snapshot(spec)
    return {
        "project_version": PROJECT_VERSION,
        "tag": tag or f"v{PROJECT_VERSION}",
        "commit_sha": commit_sha or "",
        "storage_model": STORAGE_MODEL,
        "release_channel": RELEASE_CHANNEL,
        "api_version": API_VERSION,
        "openapi_version": OPENAPI_VERSION,
        "contract": {
            "hash": compatibility["contract_hash"],
            "path_count": compatibility["path_count"],
            "operation_count": compatibility["operation_count"],
        },
        "artifacts": {
            "python": {
                "package": PACKAGE_NAME,
                "install": f"pip install {PACKAGE_NAME}=={PROJECT_VERSION}",
                "entrypoints": ["cortex", "cortexd", "cortex-mcp", "cortex-bench"],
            },
            "typescript": {
                "package": TYPESCRIPT_SDK_NAME,
                "install": f"npm install {TYPESCRIPT_SDK_NAME}@{PROJECT_VERSION}",
            },
            "docker": {
                "image": DOCKER_IMAGE_NAME,
                "pull": f"docker pull {DOCKER_IMAGE_NAME}:{PROJECT_VERSION}",
                "tags": [PROJECT_VERSION, "latest"],
            },
            "contract": {
                "openapi_json": str(OPENAPI_ARTIFACT_PATH),
                "compatibility_json": str(OPENAPI_COMPAT_PATH),
            },
        },
    }


def build_release_notes(
    spec: dict[str, Any],
    *,
    tag: str | None = None,
    commit_sha: str | None = None,
) -> str:
    manifest = build_release_manifest(spec, tag=tag, commit_sha=commit_sha)
    contract = manifest["contract"]
    python_install = manifest["artifacts"]["python"]["install"]
    typescript_install = manifest["artifacts"]["typescript"]["install"]
    docker_pull = manifest["artifacts"]["docker"]["pull"]
    lines = [
        f"# Cortex {PROJECT_VERSION}",
        "",
        "## Runtime",
        "",
        f"- Tag: `{manifest['tag']}`",
        f"- Storage model: `{STORAGE_MODEL}`",
        f"- Release channel: `{RELEASE_CHANNEL}`",
        f"- API / OpenAPI: `{API_VERSION}` / `{OPENAPI_VERSION}`",
    ]
    if manifest["commit_sha"]:
        lines.append(f"- Commit: `{manifest['commit_sha']}`")
    lines.extend(
        [
            "",
            "## Contract",
            "",
            f"- Contract hash: `{contract['hash']}`",
            f"- Paths: `{contract['path_count']}`",
            f"- Operations: `{contract['operation_count']}`",
            f"- OpenAPI artifact: `{OPENAPI_ARTIFACT_PATH}`",
            f"- Compatibility snapshot: `{OPENAPI_COMPAT_PATH}`",
            "",
            "## Install",
            "",
            f"- Python: `{python_install}`",
            f"- TypeScript: `{typescript_install}`",
            f"- Docker: `{docker_pull}`",
            "",
            "## Self-Host Entry Points",
            "",
            "- Verify the REST server config: `cortexd --config .cortex/config.toml --check`",
            "- Verify the MCP server config: `cortex-mcp --config .cortex/config.toml --check`",
            "- Benchmark a local store: `cortex-bench --store-dir .cortex-bench --iterations 3 --nodes 24`",
        ]
    )
    return "\n".join(lines) + "\n"


def write_contract_compatibility_snapshot(output_path: str | Path, spec: dict[str, Any]) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_contract_compatibility_snapshot(spec), indent=2) + "\n", encoding="utf-8")
    return target


def write_release_manifest(
    output_path: str | Path,
    spec: dict[str, Any],
    *,
    tag: str | None = None,
    commit_sha: str | None = None,
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(build_release_manifest(spec, tag=tag, commit_sha=commit_sha), indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_release_notes(
    output_path: str | Path,
    spec: dict[str, Any],
    *,
    tag: str | None = None,
    commit_sha: str | None = None,
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_release_notes(spec, tag=tag, commit_sha=commit_sha), encoding="utf-8")
    return target


__all__ = [
    "API_VERSION",
    "DOCKER_IMAGE_NAME",
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
    "build_release_manifest",
    "build_release_metadata",
    "build_release_notes",
    "openapi_contract_hash",
    "write_contract_compatibility_snapshot",
    "write_release_manifest",
    "write_release_notes",
]
