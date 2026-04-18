import json
from pathlib import Path

from cortex.cli import main
from cortex.openapi import build_openapi_spec
from cortex.release import OPENAPI_VERSION, PROJECT_VERSION, build_contract_compatibility_snapshot
from cortex.server import dispatch_api_request
from cortex.service import MemoryService
from cortex.storage import build_sqlite_backend


def test_build_openapi_spec_includes_current_api_surface():
    spec = build_openapi_spec()

    assert spec["openapi"] == "3.1.0"
    assert spec["info"]["title"] == "Cortex Local API"
    assert spec["info"]["version"] == OPENAPI_VERSION
    assert spec["info"]["x-cortex-release"]["project_version"] == PROJECT_VERSION
    assert "/v1/openapi.json" in spec["paths"]
    assert "/v1/metrics" in spec["paths"]
    assert "/v1/nodes" in spec["paths"]
    assert "/v1/nodes/{node_id}" in spec["paths"]
    assert "/v1/edges" in spec["paths"]
    assert "/v1/claims" in spec["paths"]
    assert "/v1/memory/batch" in spec["paths"]
    assert "/v1/index/status" in spec["paths"]
    assert "/v1/index/rebuild" in spec["paths"]
    assert "/v1/prune/status" in spec["paths"]
    assert "/v1/prune" in spec["paths"]
    assert "/v1/agent/status" in spec["paths"]
    assert "/v1/agent/monitor/run" in spec["paths"]
    assert "/v1/agent/compile" in spec["paths"]
    assert "/v1/agent/dispatch" in spec["paths"]
    assert "/v1/agent/schedule" in spec["paths"]
    assert "/v1/agent/conflicts/review" in spec["paths"]
    assert "/v1/query/search" in spec["paths"]
    assert "/v1/conflicts/detect" in spec["paths"]
    assert "/v1/merge-preview" in spec["paths"]
    assert spec["paths"]["/v1/nodes/upsert"]["post"]["operationId"] == "upsertNode"
    assert spec["paths"]["/v1/agent/status"]["get"]["operationId"] == "agentStatus"
    assert spec["paths"]["/v1/agent/compile"]["post"]["operationId"] == "agentCompile"
    assert spec["paths"]["/v1/memory/batch"]["post"]["operationId"] == "memoryBatch"
    assert spec["paths"]["/v1/query/search"]["post"]["operationId"] == "querySearch"
    assert spec["paths"]["/v1/index/rebuild"]["post"]["operationId"] == "indexRebuild"
    assert spec["paths"]["/v1/prune"]["post"]["operationId"] == "prune"
    assert spec["components"]["schemas"]["MergePreviewRequest"]["required"] == ["other_ref"]


def test_openapi_endpoint_does_not_reflect_request_host(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)

    status, payload = dispatch_api_request(
        service,
        method="GET",
        path="/v1/openapi.json",
        headers={"Host": "cortex.local:8766"},
    )

    assert status == 200
    assert "servers" not in payload
    assert payload["paths"]["/v1/merge/resolve"]["post"]["operationId"] == "mergeResolve"


def test_openapi_endpoint_uses_configured_external_base_url(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)

    status, payload = dispatch_api_request(
        service,
        method="GET",
        path="/v1/openapi.json",
        headers={"Host": "cortex.local:8766"},
        external_base_url="https://api.cortex.example",
    )

    assert status == 200
    assert payload["servers"][0]["url"] == "https://api.cortex.example"


def test_openapi_cli_writes_expected_contract(tmp_path, capsys):
    output_path = tmp_path / "cortex-api.json"
    compat_path = tmp_path / "cortex-api-compat.json"

    rc = main(
        [
            "openapi",
            "--output",
            str(output_path),
            "--server-url",
            "http://127.0.0.1:8766",
            "--compat-output",
            str(compat_path),
        ]
    )
    out = capsys.readouterr().out
    spec = json.loads(output_path.read_text(encoding="utf-8"))
    compat = json.loads(compat_path.read_text(encoding="utf-8"))

    assert rc == 0
    assert "Wrote OpenAPI spec" in out
    assert "compatibility snapshot" in out
    assert spec["servers"][0]["url"] == "http://127.0.0.1:8766"
    assert "/v1/conflicts/resolve" in spec["paths"]
    assert compat["contract_hash"] == build_contract_compatibility_snapshot(build_openapi_spec())["contract_hash"]


def test_committed_openapi_artifact_matches_builder():
    artifact_path = Path("openapi/cortex-api-v1.json")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert artifact == build_openapi_spec()


def test_committed_openapi_compatibility_artifact_matches_builder():
    artifact_path = Path("openapi/cortex-api-v1-compat.json")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert artifact == build_contract_compatibility_snapshot(build_openapi_spec())


def test_typescript_sdk_package_points_to_committed_dist_files():
    package_path = Path("sdk/typescript/package.json")
    package = json.loads(package_path.read_text(encoding="utf-8"))

    main_path = package_path.parent / package["main"].removeprefix("./")
    types_path = package_path.parent / package["types"].removeprefix("./")

    assert package["name"] == "@cortex-ai/sdk"
    assert package["version"] == PROJECT_VERSION
    assert main_path.exists()
    assert types_path.exists()
    assert (package_path.parent / "README.md").exists()


def test_typescript_sdk_dist_includes_agent_runtime_surface():
    js_artifact = Path("sdk/typescript/dist/index.js").read_text(encoding="utf-8")
    types_artifact = Path("sdk/typescript/dist/index.d.ts").read_text(encoding="utf-8")

    assert "agentStatus()" in js_artifact
    assert 'agentMonitorRun({ mindId = "", autoResolveThreshold = 0.85, logDir = "" } = {})' in js_artifact
    assert "agentCompile({" in js_artifact
    assert 'agentDispatch({ event, payload, outputDir = "" })' in js_artifact
    assert "agentSchedule({" in js_artifact
    assert 'agentReviewConflicts({ decisions = [], logDir = "" } = {})' in js_artifact

    assert "export interface AgentMonitorRunParams {" in types_artifact
    assert "export interface AgentCompileParams {" in types_artifact
    assert "export interface AgentDispatchParams {" in types_artifact
    assert "export interface AgentScheduleParams {" in types_artifact
    assert "export interface AgentReviewConflictsParams {" in types_artifact
    assert "agentStatus(): Promise<JsonObject>;" in types_artifact
    assert "agentCompile(params: AgentCompileParams): Promise<JsonObject>;" in types_artifact
    assert "agentReviewConflicts(params?: AgentReviewConflictsParams): Promise<JsonObject>;" in types_artifact


def test_docs_reference_agent_runtime_surface():
    readme = Path("README.md").read_text(encoding="utf-8")
    sdk_readme = Path("sdk/typescript/README.md").read_text(encoding="utf-8")
    self_hosting = Path("docs/SELF_HOSTING.md").read_text(encoding="utf-8")

    assert "`$ cortex admin agent monitor --interval 300`" in readme
    assert "`$ cortex admin agent compile --mind personal --output cv`" in readme
    assert "`$ cortex admin agent status`" in readme

    assert "client.agentStatus()" in sdk_readme
    assert "client.agentCompile({" in sdk_readme
    assert "client.agentReviewConflicts({" in sdk_readme

    assert "GET /v1/agent/status" in self_hosting
    assert "POST /v1/agent/conflicts/review" in self_hosting
    assert "client.agent_status()" in self_hosting
    assert "client.agentStatus()" in self_hosting
