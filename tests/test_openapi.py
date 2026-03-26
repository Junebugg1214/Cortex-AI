import json
from pathlib import Path

from cortex.cli import main
from cortex.openapi import build_openapi_spec
from cortex.server import dispatch_api_request
from cortex.service import MemoryService
from cortex.storage import build_sqlite_backend


def test_build_openapi_spec_includes_current_api_surface():
    spec = build_openapi_spec()

    assert spec["openapi"] == "3.1.0"
    assert spec["info"]["title"] == "Cortex Local API"
    assert "/v1/openapi.json" in spec["paths"]
    assert "/v1/index/status" in spec["paths"]
    assert "/v1/index/rebuild" in spec["paths"]
    assert "/v1/query/search" in spec["paths"]
    assert "/v1/conflicts/detect" in spec["paths"]
    assert "/v1/merge-preview" in spec["paths"]
    assert spec["paths"]["/v1/query/search"]["post"]["operationId"] == "querySearch"
    assert spec["paths"]["/v1/index/rebuild"]["post"]["operationId"] == "indexRebuild"
    assert spec["components"]["schemas"]["MergePreviewRequest"]["required"] == ["other_ref"]


def test_openapi_endpoint_uses_request_host(tmp_path):
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
    assert payload["servers"][0]["url"] == "http://cortex.local:8766"
    assert payload["paths"]["/v1/merge/resolve"]["post"]["operationId"] == "mergeResolve"


def test_openapi_cli_writes_expected_contract(tmp_path, capsys):
    output_path = tmp_path / "cortex-api.json"

    rc = main(["openapi", "--output", str(output_path), "--server-url", "http://127.0.0.1:8766"])
    out = capsys.readouterr().out
    spec = json.loads(output_path.read_text(encoding="utf-8"))

    assert rc == 0
    assert "Wrote OpenAPI spec" in out
    assert spec["servers"][0]["url"] == "http://127.0.0.1:8766"
    assert "/v1/conflicts/resolve" in spec["paths"]


def test_committed_openapi_artifact_matches_builder():
    artifact_path = Path("openapi/cortex-api-v1.json")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert artifact == build_openapi_spec()


def test_typescript_sdk_package_points_to_committed_dist_files():
    package_path = Path("sdk/typescript/package.json")
    package = json.loads(package_path.read_text(encoding="utf-8"))

    main_path = package_path.parent / package["main"].removeprefix("./")
    types_path = package_path.parent / package["types"].removeprefix("./")

    assert package["name"] == "@cortex-ai/sdk"
    assert main_path.exists()
    assert types_path.exists()
    assert (package_path.parent / "README.md").exists()
