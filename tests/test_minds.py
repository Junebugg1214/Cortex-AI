from __future__ import annotations

import json
import shutil
import threading
import time

import pytest

import cortex.minds as minds_module
from cortex.cli import main
from cortex.graph import CortexGraph, Node
from cortex.minds import (
    attach_pack_to_mind,
    clear_default_mind,
    compose_mind,
    default_mind_status,
    detach_pack_from_mind,
    ingest_detected_sources_into_mind,
    init_mind,
    list_mind_mounts,
    list_minds,
    load_mind_manifest,
    mind_branch_name,
    mind_mounts_path,
    mind_openclaw_mount_registry_path,
    mind_policies_path,
    mind_status,
    mount_mind,
    remember_on_mind,
    resolve_default_mind,
    set_default_mind,
)
from cortex.packs import compile_pack, graph_path, ingest_pack, init_pack, mount_pack, pack_path
from cortex.portable_runtime import load_portability_state, save_canonical_graph
from cortex.storage import get_storage_backend


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


def _seed_detected_chatgpt_artifact(home_dir, *, know="I use Python and FastAPI.", respond="Be concise."):
    downloads_dir = home_dir / "Downloads" / "Exports" / "ChatGPT"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    artifact = downloads_dir / "custom_instructions.json"
    artifact.write_text(
        json.dumps(
            {
                "what_chatgpt_should_know_about_you": know,
                "how_chatgpt_should_respond": respond,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return artifact


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
    assert status["core_state"]["graph_ref"] == "refs/minds/atlas-agent/branches/main"
    assert status["core_state"]["graph_source"] == "empty_graph"
    assert status["branches"]["current_branch"] == "main"
    assert status["branches"]["default_branch"] == "main"
    assert status["policies"]["default_disclosure"] == "professional"
    assert status["policies"]["approval_rules"]["merge_to_main_requires_review"] is True
    assert "manifest.json" in status["layout"]["files"]
    assert "refs" in status["layout"]["directories"]


def test_mind_namespace_filters_and_enforces_access(tmp_path):
    store_dir = tmp_path / ".cortex"

    init_mind(store_dir, "alpha", kind="person", owner="marc", namespace="team-a")
    init_mind(store_dir, "beta", kind="agent", owner="cortex", namespace="team-b")

    listing = list_minds(store_dir, namespace="team-a")
    status = mind_status(store_dir, "alpha", namespace="team-a")

    assert listing["count"] == 1
    assert listing["minds"][0]["mind"] == "alpha"
    assert listing["minds"][0]["namespace"] == "team-a"
    assert status["namespace"] == "team-a"
    assert status["manifest"]["namespace"] == "team-a"

    with pytest.raises(PermissionError):
        mind_status(store_dir, "beta", namespace="team-a")


def test_default_mind_round_trip(tmp_path):
    store_dir = tmp_path / ".cortex"

    init_mind(store_dir, "marc", kind="person", owner="marc")

    set_payload = set_default_mind(store_dir, "marc")
    status_payload = default_mind_status(store_dir)
    list_payload = list_minds(store_dir)
    mind_payload = mind_status(store_dir, "marc")

    assert set_payload["configured"] is True
    assert status_payload["mind"] == "marc"
    assert resolve_default_mind(store_dir) == "marc"
    assert list_payload["minds"][0]["is_default"] is True
    assert mind_payload["is_default"] is True

    clear_payload = clear_default_mind(store_dir)
    assert clear_payload["configured"] is False
    assert resolve_default_mind(store_dir) is None


def test_unscoped_minds_round_trip_namespace_as_none(tmp_path):
    store_dir = tmp_path / ".cortex"

    init_mind(store_dir, "marc", kind="person", owner="marc")
    status = mind_status(store_dir, "marc")

    assert status["namespace"] is None
    assert status["manifest"]["namespace"] is None


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


def test_concurrent_mind_attachment_updates_preserve_all_records(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")
    for index in range(5):
        init_pack(store_dir, f"pack-{index}", description=f"Pack {index}", owner="marc")

    original_load_attachments = minds_module._load_attachments

    def slow_load_attachments(*args, **kwargs):
        payload = original_load_attachments(*args, **kwargs)
        time.sleep(0.02)
        return payload

    monkeypatch.setattr(minds_module, "_load_attachments", slow_load_attachments)

    errors: list[Exception] = []

    def attach(name: str) -> None:
        try:
            attach_pack_to_mind(store_dir, "marc", name)
        except Exception as exc:  # pragma: no cover - defensive for thread collection
            errors.append(exc)

    threads = [threading.Thread(target=attach, args=(f"pack-{index}",)) for index in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    status = mind_status(store_dir, "marc")
    assert status["attachment_count"] == 5
    assert sorted(item["pack"] for item in status["attached_brainpacks"]) == [f"pack-{index}" for index in range(5)]


def test_mind_ingest_detected_sources_commits_to_mind_branch(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_detected_chatgpt_artifact(home_dir)

    base_graph = CortexGraph()
    base_graph.add_node(Node(id="n-marc", label="Marc", tags=["identity"], confidence=0.96, brief="Name: Marc"))
    state = load_portability_state(store_dir)
    save_canonical_graph(store_dir, base_graph, state=state)

    init_mind(store_dir, "marc", kind="person", owner="marc")
    payload = ingest_detected_sources_into_mind(
        store_dir,
        "marc",
        targets=["chatgpt"],
        project_dir=project_dir,
    )
    status = mind_status(store_dir, "marc")
    compose_payload = compose_mind(store_dir, "marc", target="chatgpt", smart=True, max_chars=900)
    branch_head = get_storage_backend(store_dir).versions.resolve_ref(mind_branch_name("marc", "main"))

    assert payload["mind"] == "marc"
    assert payload["ingested_source_count"] == 1
    assert payload["selected_sources"][0]["target"] == "chatgpt"
    assert payload["graph_ref"] == "refs/minds/marc/branches/main"
    assert payload["base_graph_source"] == "portable_canonical_graph"
    assert branch_head == payload["version_id"]
    assert status["graph_ref"] == "refs/minds/marc/branches/main"
    assert compose_payload["base_graph_source"] in {"mind_branch_ref", "mind_branch"}
    assert "Marc" in compose_payload["labels"]
    assert "Python" in compose_payload["labels"]


def test_mind_compose_merges_core_graph_and_selected_brainpacks(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "brainpack.md"
    fundraising_source = tmp_path / "fundraising.md"
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_source(source)
    fundraising_source.write_text(
        (
            "# Fundraising Notes\n\n"
            "Cortex is preparing investor materials.\n"
            "The fundraising pack should only activate for investor work.\n"
        ),
        encoding="utf-8",
    )

    base_graph = CortexGraph()
    base_graph.add_node(Node(id="n-marc", label="Marc", tags=["identity"], confidence=0.96, brief="Name: Marc"))
    base_graph.add_node(
        Node(
            id="n-preference",
            label="Concise answers",
            tags=["communication_preferences"],
            confidence=0.91,
            brief="Prefers concise answers",
        )
    )
    state = load_portability_state(store_dir)
    save_canonical_graph(store_dir, base_graph, state=state)

    init_mind(store_dir, "marc", kind="person", owner="marc")
    init_pack(store_dir, "ai-memory", description="Portable AI memory research", owner="marc")
    ingest_pack(store_dir, "ai-memory", [str(source)], mode="copy")
    compile_pack(store_dir, "ai-memory", suggest_questions=True, max_summary_chars=240)

    init_pack(store_dir, "fundraising", description="Fundraising strategy", owner="marc")
    ingest_pack(store_dir, "fundraising", [str(fundraising_source)], mode="copy")
    compile_pack(store_dir, "fundraising", suggest_questions=True, max_summary_chars=240)

    attach_pack_to_mind(store_dir, "marc", "ai-memory", targets=["chatgpt"], task_terms=["memory"])
    attach_pack_to_mind(store_dir, "marc", "fundraising", targets=["openclaw"], task_terms=["investor"])

    payload = compose_mind(
        store_dir,
        "marc",
        target="chatgpt",
        task="memory strategy for portable agents",
        smart=True,
        max_chars=900,
    )

    assert payload["mind"] == "marc"
    assert payload["base_graph_source"] == "portable_canonical_graph"
    assert payload["included_brainpack_count"] == 1
    assert [item["pack"] for item in payload["included_brainpacks"]] == ["ai-memory"]
    assert any(
        item["pack"] == "fundraising" and item["selection_reason"] == "target_mismatch"
        for item in payload["skipped_brainpacks"]
    )
    assert payload["fact_count"] >= 2
    assert "Marc" in payload["labels"]
    assert "Portable AI Memory" in payload["context_markdown"] or payload["target_payload"]["combined"]
    assert payload["consume_as"] == "custom_instructions"
    assert payload["composed_graph_node_count"] >= payload["base_graph_node_count"]


def test_mind_mount_materializes_targets_and_persists_mount_records(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "brainpack.md"
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    openclaw_store_dir = tmp_path / "openclaw-store"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_source(source)

    base_graph = CortexGraph()
    base_graph.add_node(Node(id="n-marc", label="Marc", tags=["identity"], confidence=0.96, brief="Name: Marc"))
    state = load_portability_state(store_dir)
    save_canonical_graph(store_dir, base_graph, state=state)

    init_mind(store_dir, "marc", kind="person", owner="marc")
    init_pack(store_dir, "support-pack", description="Support pack", owner="marc")
    ingest_pack(store_dir, "support-pack", [str(source)], mode="copy")
    compile_pack(store_dir, "support-pack", suggest_questions=True, max_summary_chars=240)
    attach_pack_to_mind(
        store_dir,
        "marc",
        "support-pack",
        always_on=True,
        targets=["claude-code", "codex", "cursor", "hermes", "openclaw"],
    )

    payload = mount_mind(
        store_dir,
        "marc",
        targets=["hermes", "claude-code", "codex", "cursor", "openclaw"],
        task="support",
        project_dir=str(project_dir),
        smart=True,
        max_chars=900,
        openclaw_store_dir=str(openclaw_store_dir),
    )
    mounts_payload = list_mind_mounts(store_dir, "marc")
    status = mind_status(store_dir, "marc")
    registry = json.loads(mind_openclaw_mount_registry_path(openclaw_store_dir).read_text(encoding="utf-8"))

    assert payload["mounted_count"] == 5
    assert payload["mount_count"] == 5
    assert {item["target"] for item in payload["targets"]} == {"hermes", "claude-code", "codex", "cursor", "openclaw"}
    assert (home_dir / ".hermes" / "memories" / "USER.md").exists()
    assert (home_dir / ".hermes" / "memories" / "MEMORY.md").exists()
    assert (home_dir / ".hermes" / "config.yaml").exists()
    assert (home_dir / ".claude" / "CLAUDE.md").exists()
    assert (project_dir / "CLAUDE.md").exists()
    assert (project_dir / "AGENTS.md").exists()
    assert (project_dir / ".cursor" / "rules" / "cortex.mdc").exists()
    assert mounts_payload["mount_count"] == 5
    assert set(mounts_payload["mounted_targets"]) == {"hermes", "claude-code", "codex", "cursor", "openclaw"}
    assert status["mount_count"] == 5
    assert set(status["mounted_targets"]) == {"hermes", "claude-code", "codex", "cursor", "openclaw"}
    assert registry["mount_count"] == 1
    assert registry["mounts"][0]["name"] == "marc"
    assert registry["mounts"][0]["activation_target"] == "openclaw"
    assert registry["mounts"][0]["task"] == "support"


def test_mind_remember_updates_core_graph_and_refreshes_mounts(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "brainpack.md"
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    openclaw_store_dir = tmp_path / "openclaw-store"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_source(source)

    base_graph = CortexGraph()
    base_graph.add_node(Node(id="n-marc", label="Marc", tags=["identity"], confidence=0.96, brief="Name: Marc"))
    state = load_portability_state(store_dir)
    save_canonical_graph(store_dir, base_graph, state=state)

    init_mind(store_dir, "marc", kind="person", owner="marc")
    init_pack(store_dir, "support-pack", description="Support pack", owner="marc")
    ingest_pack(store_dir, "support-pack", [str(source)], mode="copy")
    compile_pack(store_dir, "support-pack", suggest_questions=True, max_summary_chars=240)
    attach_pack_to_mind(
        store_dir,
        "marc",
        "support-pack",
        always_on=True,
        targets=["codex", "hermes", "openclaw"],
    )
    mount_mind(
        store_dir,
        "marc",
        targets=["codex", "hermes", "openclaw"],
        task="support",
        project_dir=str(project_dir),
        smart=True,
        max_chars=900,
        openclaw_store_dir=str(openclaw_store_dir),
    )
    before_mounts = {item["target"]: item["mounted_at"] for item in list_mind_mounts(store_dir, "marc")["mounts"]}

    payload = remember_on_mind(
        store_dir,
        "marc",
        statement="I prefer concise, implementation-first responses.",
    )
    compose_payload = compose_mind(
        store_dir,
        "marc",
        target="codex",
        task="support",
        project_dir=str(project_dir),
        smart=True,
    )
    after_mounts = {item["target"]: item["mounted_at"] for item in list_mind_mounts(store_dir, "marc")["mounts"]}
    backend = get_storage_backend(store_dir)

    assert payload["mind"] == "marc"
    assert payload["statement"] == "I prefer concise, implementation-first responses."
    assert payload["refreshed_mount_count"] == 3
    assert {item["target"] for item in payload["targets"]} == {"codex", "hermes", "openclaw"}
    assert payload["graph_ref"] == "refs/minds/marc/branches/main"
    assert backend.versions.resolve_ref(mind_branch_name("marc", "main")) == payload["version_id"]
    assert compose_payload["base_graph_source"] in {"mind_branch_ref", "mind_branch"}
    assert compose_payload["base_graph_node_count"] == 2
    assert all(after_mounts[target] != before_mounts[target] for target in before_mounts)


def test_mind_production_smoke_compose_mount_ingest_remember_and_policy_overrides(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    openclaw_store_dir = tmp_path / "openclaw-store"
    support_source = tmp_path / "support-pack.md"
    investor_source = tmp_path / "investor-pack.md"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_detected_chatgpt_artifact(home_dir, know="I use Python, FastAPI, and Cortex.")
    _seed_source(support_source)
    investor_source.write_text(
        (
            "# Investor Notes\n\n"
            "Cortex is preparing investor materials.\n"
            "This pack should only activate for OpenClaw investor conversations.\n"
        ),
        encoding="utf-8",
    )

    init_mind(store_dir, "marc", kind="person", owner="marc")
    init_pack(store_dir, "support-pack", description="Support pack", owner="marc")
    ingest_pack(store_dir, "support-pack", [str(support_source)], mode="copy")
    compile_pack(store_dir, "support-pack", suggest_questions=True, max_summary_chars=240)
    init_pack(store_dir, "investor-pack", description="Investor pack", owner="marc")
    ingest_pack(store_dir, "investor-pack", [str(investor_source)], mode="copy")
    compile_pack(store_dir, "investor-pack", suggest_questions=True, max_summary_chars=240)

    attach_pack_to_mind(
        store_dir,
        "marc",
        "support-pack",
        always_on=True,
        targets=["chatgpt", "claude-code", "codex", "cursor", "hermes", "openclaw"],
        task_terms=["support", "memory"],
    )
    attach_pack_to_mind(
        store_dir,
        "marc",
        "investor-pack",
        targets=["openclaw"],
        task_terms=["investor"],
    )
    policies_path = mind_policies_path(store_dir, "marc")
    policies_payload = json.loads(policies_path.read_text(encoding="utf-8"))
    policies_payload["target_overrides"] = {"codex": "technical"}
    policies_path.write_text(json.dumps(policies_payload, indent=2), encoding="utf-8")

    ingest_payload = ingest_detected_sources_into_mind(
        store_dir,
        "marc",
        targets=["chatgpt"],
        project_dir=project_dir,
    )
    compose_payload = compose_mind(
        store_dir,
        "marc",
        target="codex",
        task="memory support",
        project_dir=str(project_dir),
        smart=True,
        max_chars=900,
    )
    mount_payload = mount_mind(
        store_dir,
        "marc",
        targets=["hermes", "claude-code", "codex", "cursor", "openclaw"],
        task="support",
        project_dir=str(project_dir),
        smart=True,
        max_chars=900,
        openclaw_store_dir=str(openclaw_store_dir),
    )
    remember_payload = remember_on_mind(store_dir, "marc", statement="We use CockroachDB now.")
    refreshed_compose = compose_mind(
        store_dir,
        "marc",
        target="codex",
        task="support",
        project_dir=str(project_dir),
        smart=True,
        max_chars=900,
    )
    mounts_payload = list_mind_mounts(store_dir, "marc")

    assert ingest_payload["ingested_source_count"] == 1
    assert ingest_payload["base_graph_source"] == "empty_graph"
    assert compose_payload["policy"] == "technical"
    assert compose_payload["included_brainpack_count"] == 1
    assert compose_payload["included_brainpacks"][0]["pack"] == "support-pack"
    assert any(
        item["pack"] == "investor-pack" and item["selection_reason"] == "target_mismatch"
        for item in compose_payload["skipped_brainpacks"]
    )
    assert "Python" in compose_payload["labels"]
    assert mount_payload["mounted_count"] == 5
    assert {item["target"] for item in mount_payload["targets"]} == {
        "hermes",
        "claude-code",
        "codex",
        "cursor",
        "openclaw",
    }
    persisted_mounts = {item["target"]: item for item in mounts_payload["mounts"]}
    assert persisted_mounts["codex"]["policy"] == ""
    assert persisted_mounts["codex"]["effective_policy"] == "technical"
    assert remember_payload["graph_node_count"] > ingest_payload["graph_node_count"]
    assert remember_payload["refreshed_mount_count"] == 5
    assert remember_payload["stale_mount_count"] == 0
    assert remember_payload["refresh_error_count"] == 0
    assert refreshed_compose["composed_graph_node_count"] >= compose_payload["composed_graph_node_count"]


def test_mind_remember_prunes_stale_mount_records_without_failing(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    init_mind(store_dir, "marc", kind="person", owner="marc")
    remember_on_mind(store_dir, "marc", statement="I am Marc Saint-Jour.")
    mount_mind(
        store_dir,
        "marc",
        targets=["codex"],
        task="support",
        project_dir=str(project_dir),
        smart=True,
        max_chars=900,
    )
    mounts_path = mind_mounts_path(store_dir, "marc")
    mounts_payload = json.loads(mounts_path.read_text(encoding="utf-8"))
    mounts_payload["mounts"].extend(
        [
            {"target": "not-a-target", "task": "support", "project_dir": str(project_dir)},
            {"target": "", "task": "support", "project_dir": str(project_dir)},
        ]
    )
    mounts_path.write_text(json.dumps(mounts_payload, indent=2), encoding="utf-8")

    payload = remember_on_mind(store_dir, "marc", statement="I prefer concise updates.")
    refreshed_mounts = list_mind_mounts(store_dir, "marc")

    assert payload["refreshed_mount_count"] == 1
    assert payload["stale_mount_count"] == 2
    assert payload["refresh_error_count"] == 0
    assert {item["reason"] for item in payload["stale_mounts"]} == {"missing_target", "unsupported_target"}
    assert refreshed_mounts["mount_count"] == 1
    assert refreshed_mounts["mounted_targets"] == ["codex"]


def test_mind_compose_handles_missing_pack_and_missing_pack_graph(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    home_dir = tmp_path / "home"
    source = tmp_path / "brainpack.md"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_source(source)

    init_mind(store_dir, "marc", kind="person", owner="marc")
    remember_on_mind(store_dir, "marc", statement="I am Marc Saint-Jour.")

    init_pack(store_dir, "missing-pack", description="Missing pack", owner="marc")
    ingest_pack(store_dir, "missing-pack", [str(source)], mode="copy")
    compile_pack(store_dir, "missing-pack", suggest_questions=True, max_summary_chars=240)
    attach_pack_to_mind(store_dir, "marc", "missing-pack", always_on=True, targets=["codex"])

    init_pack(store_dir, "graphless-pack", description="Graphless pack", owner="marc")
    ingest_pack(store_dir, "graphless-pack", [str(source)], mode="copy")
    compile_pack(store_dir, "graphless-pack", suggest_questions=True, max_summary_chars=240)
    attach_pack_to_mind(store_dir, "marc", "graphless-pack", always_on=True, targets=["codex"])

    graph_path(store_dir, "graphless-pack").unlink()
    shutil.rmtree(pack_path(store_dir, "missing-pack"))

    payload = compose_mind(store_dir, "marc", target="codex", task="support", smart=True, max_chars=900)

    assert payload["included_brainpack_count"] == 0
    assert any(
        item["pack"] == "missing-pack" and item["selection_reason"] == "pack_missing"
        for item in payload["skipped_brainpacks"]
    )
    assert any(
        item["pack"] == "graphless-pack" and item["selection_reason"] == "pack_graph_missing"
        for item in payload["skipped_brainpacks"]
    )


def test_empty_mind_compose_and_mount_are_non_fatal(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    init_mind(store_dir, "marc", kind="person", owner="marc")

    compose_payload = compose_mind(
        store_dir,
        "marc",
        target="codex",
        task="support",
        project_dir=str(project_dir),
        smart=True,
        max_chars=900,
    )
    mount_payload = mount_mind(
        store_dir,
        "marc",
        targets=["codex"],
        task="support",
        project_dir=str(project_dir),
        smart=True,
        max_chars=900,
    )

    assert compose_payload["base_graph_source"] == "empty_graph"
    assert compose_payload["fact_count"] == 0
    assert compose_payload["message"] == "This Mind did not yield routed facts for this target."
    assert mount_payload["mounted_count"] == 1
    assert mount_payload["targets"][0]["target"] == "codex"
    assert mount_payload["targets"][0]["fact_count"] == 0


def test_cli_mind_round_trip_json(tmp_path, capsys, monkeypatch):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "brainpack.md"
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    openclaw_store_dir = tmp_path / "openclaw-store"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_source(source)

    init_rc = main(
        ["mind", "init", "marc", "--kind", "person", "--owner", "marc", "--store-dir", str(store_dir), "--json"]
    )
    init_payload = json.loads(capsys.readouterr().out)

    init_pack(store_dir, "ai-memory", description="Portable AI memory research", owner="marc")
    ingest_pack(store_dir, "ai-memory", [str(source)], mode="copy")
    compile_pack(store_dir, "ai-memory", suggest_questions=True, max_summary_chars=240)

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

    compose_rc = main(
        [
            "mind",
            "compose",
            "marc",
            "--to",
            "chatgpt",
            "--task",
            "memory routing",
            "--store-dir",
            str(store_dir),
            "--json",
        ]
    )
    compose_payload = json.loads(capsys.readouterr().out)

    mount_rc = main(
        [
            "mind",
            "mount",
            "marc",
            "--to",
            "hermes",
            "claude-code",
            "codex",
            "cursor",
            "openclaw",
            "--task",
            "memory routing",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--openclaw-store-dir",
            str(openclaw_store_dir),
            "--smart",
            "--json",
        ]
    )
    mount_payload = json.loads(capsys.readouterr().out)

    mounts_rc = main(["mind", "mounts", "marc", "--store-dir", str(store_dir), "--json"])
    mounts_payload = json.loads(capsys.readouterr().out)

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
    assert compose_rc == 0
    assert compose_payload["mind"] == "marc"
    assert compose_payload["included_brainpack_count"] == 1
    assert compose_payload["included_brainpacks"][0]["pack"] == "ai-memory"
    assert mount_rc == 0
    assert mount_payload["mounted_count"] == 5
    assert {item["target"] for item in mount_payload["targets"]} == {
        "hermes",
        "claude-code",
        "codex",
        "cursor",
        "openclaw",
    }
    assert mounts_rc == 0
    assert mounts_payload["mount_count"] == 5
    assert detach_rc == 0
    assert detach_payload["attachment_count"] == 0


def test_cli_mind_default_round_trip_json(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"

    init_rc = main(
        ["mind", "init", "marc", "--kind", "person", "--owner", "marc", "--store-dir", str(store_dir), "--json"]
    )
    init_payload = json.loads(capsys.readouterr().out)

    set_rc = main(["mind", "default", "marc", "--store-dir", str(store_dir), "--json"])
    set_payload = json.loads(capsys.readouterr().out)

    status_rc = main(["mind", "default", "--store-dir", str(store_dir), "--json"])
    status_payload = json.loads(capsys.readouterr().out)

    clear_rc = main(["mind", "default", "--clear", "--store-dir", str(store_dir), "--json"])
    clear_payload = json.loads(capsys.readouterr().out)

    assert init_rc == 0
    assert init_payload["mind"] == "marc"
    assert set_rc == 0
    assert set_payload["mind"] == "marc"
    assert status_rc == 0
    assert status_payload["configured"] is True
    assert status_payload["mind"] == "marc"
    assert clear_rc == 0
    assert clear_payload["configured"] is False


def test_cli_init_bootstraps_default_store_and_mind_json(tmp_path, capsys, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    init_rc = main(
        [
            "init",
            "--mind",
            "marc",
            "--owner",
            "marc",
            "--label",
            "Marc",
            "--format",
            "json",
        ]
    )
    init_payload = json.loads(capsys.readouterr().out)

    repeat_rc = main(["init", "--mind", "marc", "--format", "json"])
    repeat_payload = json.loads(capsys.readouterr().out)

    store_dir = workspace / ".cortex"
    listing = list_minds(store_dir)

    assert init_rc == 0
    assert init_payload["status"] == "ok"
    assert init_payload["store_dir"] == str(store_dir.resolve())
    assert init_payload["store_source"] == "default"
    assert init_payload["config_created"] is True
    assert init_payload["auth_keys_created"] == 2
    assert init_payload["default_mind"] == "marc"
    assert init_payload["created_mind"] is True
    assert init_payload["created_mind_id"] == "marc"
    assert init_payload["namespace"] == "team"
    assert (store_dir / "config.toml").exists()
    assert listing["count"] == 1
    assert listing["minds"][0]["mind"] == "marc"

    assert repeat_rc == 0
    assert repeat_payload["config_created"] is False
    assert repeat_payload["created_mind"] is False
    assert repeat_payload["default_mind"] == "marc"


def test_cli_mind_ingest_from_detected_json(tmp_path, capsys, monkeypatch):
    store_dir = tmp_path / ".cortex"
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_detected_chatgpt_artifact(home_dir)

    init_rc = main(
        ["mind", "init", "marc", "--kind", "person", "--owner", "marc", "--store-dir", str(store_dir), "--json"]
    )
    init_payload = json.loads(capsys.readouterr().out)

    ingest_rc = main(
        [
            "mind",
            "ingest",
            "marc",
            "--from-detected",
            "chatgpt",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--json",
        ]
    )
    ingest_payload = json.loads(capsys.readouterr().out)

    compose_rc = main(
        [
            "mind",
            "compose",
            "marc",
            "--to",
            "chatgpt",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--json",
        ]
    )
    compose_payload = json.loads(capsys.readouterr().out)

    assert init_rc == 0
    assert init_payload["mind"] == "marc"
    assert ingest_rc == 0
    assert ingest_payload["mind"] == "marc"
    assert ingest_payload["ingested_source_count"] == 1
    assert ingest_payload["selected_sources"][0]["target"] == "chatgpt"
    assert compose_rc == 0
    assert "Python" in compose_payload["labels"]


def test_cli_mind_remember_refreshes_mounts_json(tmp_path, capsys, monkeypatch):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "brainpack.md"
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    openclaw_store_dir = tmp_path / "openclaw-store"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _seed_source(source)

    base_graph = CortexGraph()
    base_graph.add_node(Node(id="n1", label="Marc", tags=["identity"], confidence=0.96))
    state = load_portability_state(store_dir)
    save_canonical_graph(store_dir, base_graph, state=state)

    main(["mind", "init", "marc", "--owner", "marc", "--store-dir", str(store_dir), "--json"])
    capsys.readouterr()
    init_pack(store_dir, "support-pack", description="Support pack", owner="marc")
    ingest_pack(store_dir, "support-pack", [str(source)], mode="copy")
    compile_pack(store_dir, "support-pack", suggest_questions=True, max_summary_chars=240)
    main(
        [
            "mind",
            "attach-pack",
            "marc",
            "support-pack",
            "--always-on",
            "--target",
            "codex",
            "--target",
            "hermes",
            "--target",
            "openclaw",
            "--store-dir",
            str(store_dir),
            "--json",
        ]
    )
    capsys.readouterr()
    main(
        [
            "mind",
            "mount",
            "marc",
            "--to",
            "codex",
            "hermes",
            "openclaw",
            "--task",
            "support",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--openclaw-store-dir",
            str(openclaw_store_dir),
            "--smart",
            "--json",
        ]
    )
    capsys.readouterr()
    before_mounts = {item["target"]: item["mounted_at"] for item in list_mind_mounts(store_dir, "marc")["mounts"]}

    remember_rc = main(
        [
            "mind",
            "remember",
            "marc",
            "I prefer concise, implementation-first responses.",
            "--store-dir",
            str(store_dir),
            "--json",
        ]
    )
    remember_payload = json.loads(capsys.readouterr().out)

    compose_rc = main(
        [
            "mind",
            "compose",
            "marc",
            "--to",
            "codex",
            "--task",
            "support",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--json",
        ]
    )
    compose_payload = json.loads(capsys.readouterr().out)
    after_mounts = {item["target"]: item["mounted_at"] for item in list_mind_mounts(store_dir, "marc")["mounts"]}

    assert remember_rc == 0
    assert remember_payload["mind"] == "marc"
    assert remember_payload["refreshed_mount_count"] == 3
    assert {item["target"] for item in remember_payload["targets"]} == {"codex", "hermes", "openclaw"}
    assert compose_rc == 0
    assert compose_payload["base_graph_node_count"] == 2
    assert all(after_mounts[target] != before_mounts[target] for target in before_mounts)
