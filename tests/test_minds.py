from __future__ import annotations

import json

from cortex.cli import main
from cortex.minds import (
    attach_pack_to_mind,
    detach_pack_from_mind,
    init_mind,
    list_minds,
    load_mind_manifest,
    mind_status,
)
from cortex.packs import compile_pack, ingest_pack, init_pack, mount_pack


def _seed_source(path):
    path.write_text(
        (
            "# Portable AI Memory\n\n"
            "I am Marc Saint-Jour.\n"
            "I use Python, FastAPI, and Cortex.\n"
            "I am building portable brain-state infrastructure for agents.\n"
        ),
        encoding="utf-8",
    )


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
    assert status["attached_mounted_targets"] == []
    assert "manifest.json" in status["layout"]["files"]
    assert "refs" in status["layout"]["directories"]


def test_mind_attach_and_detach_pack_updates_status_metadata(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    project_dir = tmp_path / "project"
    source = tmp_path / "brainpack.md"
    home_dir = tmp_path / "home"
    project_dir.mkdir()
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_source(source)

    init_mind(store_dir, "marc", kind="person", owner="marc")
    init_pack(store_dir, "ai-memory", description="Portable AI memory research", owner="marc")
    ingest_pack(store_dir, "ai-memory", [str(source)], mode="copy")
    compile_pack(store_dir, "ai-memory", suggest_questions=True, max_summary_chars=240)
    mount_pack(
        store_dir,
        "ai-memory",
        targets=["codex"],
        project_dir=str(project_dir),
        smart=True,
        max_chars=900,
    )

    attach_payload = attach_pack_to_mind(
        store_dir,
        "marc",
        "ai-memory",
        priority=120,
        always_on=True,
        targets=["codex", "claude-code"],
        task_terms=["memory", "context"],
    )
    status = mind_status(store_dir, "marc")

    assert attach_payload["attached"] is True
    assert attach_payload["attachment_count"] == 1
    assert status["attachment_count"] == 1
    assert status["attached_mount_count"] == 1
    assert status["attached_mounted_targets"] == ["codex"]
    assert status["attached_brainpacks"][0]["pack"] == "ai-memory"
    assert status["attached_brainpacks"][0]["compile_status"] == "compiled"
    assert status["attached_brainpacks"][0]["pack_mount_count"] == 1
    assert status["attached_brainpacks"][0]["activation"]["always_on"] is True
    assert status["attached_brainpacks"][0]["activation"]["targets"] == ["codex", "claude-code"]
    assert status["attached_brainpacks"][0]["activation"]["task_terms"] == ["memory", "context"]

    detach_payload = detach_pack_from_mind(store_dir, "marc", "ai-memory")
    detached = mind_status(store_dir, "marc")

    assert detach_payload["detached"] is True
    assert detach_payload["attachment_count"] == 0
    assert detached["attachment_count"] == 0
    assert detached["attached_brainpacks"] == []
    assert detached["attached_mounted_targets"] == []


def test_cli_mind_round_trip_json(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "brainpack.md"
    _seed_source(source)

    init_rc = main(
        ["mind", "init", "marc", "--kind", "person", "--owner", "marc", "--store-dir", str(store_dir), "--json"]
    )
    init_payload = json.loads(capsys.readouterr().out)

    init_pack(store_dir, "ai-memory", description="Portable AI memory research", owner="marc")
    ingest_pack(store_dir, "ai-memory", [str(source)], mode="copy")

    attach_rc = main(
        [
            "mind",
            "attach-pack",
            "marc",
            "ai-memory",
            "--always-on",
            "--target",
            "chatgpt",
            "--task-term",
            "memory",
            "--store-dir",
            str(store_dir),
            "--json",
        ]
    )
    attach_payload = json.loads(capsys.readouterr().out)

    list_rc = main(["mind", "list", "--store-dir", str(store_dir), "--json"])
    list_payload = json.loads(capsys.readouterr().out)

    status_rc = main(["mind", "status", "marc", "--store-dir", str(store_dir), "--json"])
    status_payload = json.loads(capsys.readouterr().out)

    detach_rc = main(["mind", "detach-pack", "marc", "ai-memory", "--store-dir", str(store_dir), "--json"])
    detach_payload = json.loads(capsys.readouterr().out)

    assert init_rc == 0
    assert init_payload["mind"] == "marc"
    assert attach_rc == 0
    assert attach_payload["pack"] == "ai-memory"
    assert list_rc == 0
    assert list_payload["count"] == 1
    assert list_payload["minds"][0]["mind"] == "marc"
    assert status_rc == 0
    assert status_payload["mind"] == "marc"
    assert status_payload["manifest"]["label"] == "Marc"
    assert status_payload["attachment_count"] == 1
    assert status_payload["attached_brainpacks"][0]["activation"]["always_on"] is True
    assert status_payload["attached_brainpacks"][0]["activation"]["targets"] == ["chatgpt"]
    assert detach_rc == 0
    assert detach_payload["attachment_count"] == 0
