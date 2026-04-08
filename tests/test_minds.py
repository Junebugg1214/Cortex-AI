from __future__ import annotations

import json

from cortex.cli import main
from cortex.minds import init_mind, list_minds, load_mind_manifest, mind_status


def test_mind_init_creates_manifest_and_layout(tmp_path):
    store_dir = tmp_path / ".cortex"

    payload = init_mind(
        store_dir,
        "marc",
        kind="person",
        label="Marc",
        owner="marc",
        default_policy="professional",
    )
    manifest = load_mind_manifest(store_dir, "marc")

    assert payload["created"] is True
    assert (store_dir / "minds" / "marc" / "manifest.json").exists()
    assert (store_dir / "minds" / "marc" / "core_state.json").exists()
    assert (store_dir / "minds" / "marc" / "attachments.json").exists()
    assert (store_dir / "minds" / "marc" / "branches.json").exists()
    assert (store_dir / "minds" / "marc" / "policies.json").exists()
    assert (store_dir / "minds" / "marc" / "mounts.json").exists()
    assert (store_dir / "minds" / "marc" / "compositions").exists()
    assert (store_dir / "minds" / "marc" / "refs").exists()
    assert manifest.id == "marc"
    assert manifest.label == "Marc"
    assert manifest.kind == "person"
    assert manifest.default_branch == "main"
    assert manifest.current_branch == "main"


def test_mind_list_and_status_round_trip(tmp_path):
    store_dir = tmp_path / ".cortex"

    init_mind(store_dir, "marc", kind="person", owner="marc")
    init_mind(store_dir, "atlas-agent", kind="agent", label="Atlas", owner="cortex")

    listing = list_minds(store_dir)
    status = mind_status(store_dir, "atlas-agent")

    assert listing["count"] == 2
    assert [item["mind"] for item in listing["minds"]] == ["atlas-agent", "marc"]
    assert status["mind"] == "atlas-agent"
    assert status["manifest"]["label"] == "Atlas"
    assert status["manifest"]["kind"] == "agent"
    assert status["graph_ref"] == "refs/minds/atlas-agent/branches/main"
    assert status["attachment_count"] == 0
    assert status["branch_count"] == 1
    assert status["mount_count"] == 0
    assert "manifest.json" in status["layout"]["files"]
    assert "refs" in status["layout"]["directories"]


def test_cli_mind_round_trip_json(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"

    init_rc = main(
        [
            "mind",
            "init",
            "marc",
            "--kind",
            "person",
            "--owner",
            "marc",
            "--store-dir",
            str(store_dir),
            "--json",
        ]
    )
    init_payload = json.loads(capsys.readouterr().out)

    list_rc = main(["mind", "list", "--store-dir", str(store_dir), "--json"])
    list_payload = json.loads(capsys.readouterr().out)

    status_rc = main(["mind", "status", "marc", "--store-dir", str(store_dir), "--json"])
    status_payload = json.loads(capsys.readouterr().out)

    assert init_rc == 0
    assert init_payload["mind"] == "marc"
    assert list_rc == 0
    assert list_payload["count"] == 1
    assert list_payload["minds"][0]["mind"] == "marc"
    assert status_rc == 0
    assert status_payload["mind"] == "marc"
    assert status_payload["manifest"]["label"] == "Marc"
