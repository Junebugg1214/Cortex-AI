import json
from pathlib import Path

from cortex.cli import main
from cortex.release import (
    DOCKER_IMAGE_NAME,
    OPENAPI_ARTIFACT_PATH,
    OPENAPI_COMPAT_PATH,
    PACKAGE_NAME,
    PROJECT_VERSION,
    TYPESCRIPT_SDK_NAME,
    build_contract_compatibility_snapshot,
    build_release_manifest,
    build_release_notes,
    classify_release_tag,
)
from cortex.service.openapi import build_openapi_spec

try:  # pragma: no cover - Python 3.11+ hits stdlib path in practice
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


def test_build_release_notes_mentions_install_surfaces():
    spec = build_openapi_spec()
    notes = build_release_notes(spec, tag=f"v{PROJECT_VERSION}", commit_sha="abc123")
    compatibility = build_contract_compatibility_snapshot(spec)

    assert f"# Cortex {PROJECT_VERSION}" in notes
    assert f"`pip install {PACKAGE_NAME}=={PROJECT_VERSION}`" in notes
    assert f"`npm install {TYPESCRIPT_SDK_NAME}@{PROJECT_VERSION}`" in notes
    assert f"`docker pull {DOCKER_IMAGE_NAME}:{PROJECT_VERSION}`" in notes
    assert compatibility["contract_hash"] in notes
    assert str(OPENAPI_ARTIFACT_PATH) in notes
    assert str(OPENAPI_COMPAT_PATH) in notes


def test_prerelease_tag_changes_manifest_and_notes():
    spec = build_openapi_spec()
    manifest = build_release_manifest(spec, tag="v1.4.1-rc1", commit_sha="abc123")
    notes = build_release_notes(spec, tag="v1.4.1-rc1", commit_sha="abc123")

    assert manifest["prerelease"] is True
    assert manifest["stage"] == "prerelease"
    assert manifest["artifacts"]["python"]["publish_on_tag"] is False
    assert manifest["artifacts"]["typescript"]["dist_tag"] == "beta"
    assert manifest["artifacts"]["docker"]["tags"] == ["v1.4.1-rc1", "beta"]
    assert "This tag is a prerelease" in notes


def test_build_release_manifest_includes_contract_and_artifacts():
    spec = build_openapi_spec()
    manifest = build_release_manifest(spec, tag="v-test", commit_sha="deadbeef")

    assert manifest["project_version"] == PROJECT_VERSION
    assert manifest["tag"] == "v-test"
    assert manifest["commit_sha"] == "deadbeef"
    assert manifest["contract"]["hash"] == build_contract_compatibility_snapshot(spec)["contract_hash"]
    assert manifest["artifacts"]["python"]["package"] == PACKAGE_NAME
    assert manifest["artifacts"]["typescript"]["package"] == TYPESCRIPT_SDK_NAME
    assert manifest["artifacts"]["docker"]["image"] == DOCKER_IMAGE_NAME


def test_classify_release_tag_handles_stable_and_prerelease_tags():
    stable = classify_release_tag("v1.4.1")
    prerelease = classify_release_tag("v1.4.1-beta1")

    assert stable["prerelease"] is False
    assert stable["publish_registry_packages"] is True
    assert stable["docker_tags"] == ["v1.4.1", PROJECT_VERSION, "latest"]
    assert prerelease["prerelease"] is True
    assert prerelease["publish_registry_packages"] is False
    assert prerelease["docker_tags"] == ["v1.4.1-beta1", "beta"]


def test_release_notes_cli_writes_markdown_and_manifest(tmp_path, capsys):
    notes_path = tmp_path / "release-notes.md"
    manifest_path = tmp_path / "release-manifest.json"

    rc = main(
        [
            "release-notes",
            "--output",
            str(notes_path),
            "--manifest-output",
            str(manifest_path),
            "--tag",
            "v-test",
            "--commit-sha",
            "deadbeef",
        ]
    )
    out = capsys.readouterr().out
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert rc == 0
    assert "Wrote release notes" in out
    assert "Wrote release manifest" in out
    assert notes_path.exists()
    assert manifest["tag"] == "v-test"
    assert manifest["commit_sha"] == "deadbeef"


def test_project_versions_stay_in_sync_with_packaging_metadata():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    package_json = json.loads(Path("sdk/typescript/package.json").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == PROJECT_VERSION
    assert package_json["version"] == PROJECT_VERSION
