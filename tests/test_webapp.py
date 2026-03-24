import json

from cortex.claims import ClaimEvent, ClaimLedger
from cortex.graph import CortexGraph, Node
from cortex.upai.versioning import VersionStore
from cortex.webapp import UI_HTML, MemoryUIBackend


def _write_graph(path, graph: CortexGraph) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def test_webapp_html_mentions_all_major_surfaces():
    assert "Review" in UI_HTML
    assert "Blame" in UI_HTML
    assert "History" in UI_HTML
    assert "Governance" in UI_HTML
    assert "Remote" in UI_HTML


def test_webapp_backend_meta_review_and_blame(tmp_path):
    store_dir = tmp_path / ".cortex"
    store = VersionStore(store_dir)
    context_path = tmp_path / "context.json"

    baseline = CortexGraph()
    baseline.add_node(
        Node(
            id="n1",
            label="PostgreSQL",
            aliases=["postgres"],
            tags=["technical_expertise"],
            confidence=0.7,
            provenance=[{"source": "import-a", "method": "extract"}],
            status="planned",
        )
    )
    baseline_version = store.commit(baseline, "baseline")

    current = CortexGraph()
    node = Node(
        id="n1",
        canonical_id="n1",
        label="PostgreSQL",
        aliases=["postgres"],
        tags=["technical_expertise"],
        confidence=0.95,
        provenance=[{"source": "manual-a", "method": "manual"}],
        status="active",
        valid_from="2026-03-23T00:00:00Z",
    )
    current.add_node(node)
    _write_graph(context_path, current)

    ledger = ClaimLedger(store_dir)
    ledger.append(
        ClaimEvent.from_node(
            node,
            op="assert",
            source="manual-a",
            method="manual_set",
            version_id=baseline_version.version_id,
            timestamp="2026-03-23T00:00:00Z",
        )
    )

    backend = MemoryUIBackend(store_dir=store_dir, context_file=context_path)
    meta = backend.meta()
    review = backend.review(input_file=str(context_path), against="HEAD", fail_on="blocking")
    blame = backend.blame(input_file=str(context_path), label="postgres", ref="HEAD", limit=10)
    history = backend.history(input_file=str(context_path), label="postgres", ref="HEAD", limit=10)

    assert meta["current_branch"] == "main"
    assert meta["context_file"] == str(context_path.resolve())
    assert review["summary"]["semantic_changes"] >= 1
    assert any(change["type"] == "lifecycle_shift" for change in review["semantic_changes"])
    assert blame["nodes"][0]["node"]["label"] == "PostgreSQL"
    assert blame["nodes"][0]["claim_lineage"]["event_count"] == 1
    assert history["nodes"][0]["history"]["versions_seen"] == 1


def test_webapp_backend_governance_and_remotes(tmp_path):
    local_store_dir = tmp_path / "local" / ".cortex"
    remote_root = tmp_path / "remote"
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    context_path = tmp_path / "local" / "context.json"
    _write_graph(context_path, graph)
    local_commit = VersionStore(local_store_dir).commit(graph, "baseline").version_id

    backend = MemoryUIBackend(store_dir=local_store_dir, context_file=context_path)
    allow = backend.save_governance_rule(
        effect="allow",
        payload={
            "name": "protect-main",
            "actor_pattern": "agent/*",
            "actions": ["write"],
            "namespaces": ["main"],
            "require_approval": True,
        },
    )
    rules = backend.list_governance_rules()
    check = backend.check_governance(actor="agent/coder", action="write", namespace="main")

    remote_add = backend.add_remote(name="origin", path=str(remote_root), default_branch="main")
    remote_list = backend.list_remotes()
    push = backend.remote_push(name="origin", branch="main")

    clone_store_dir = tmp_path / "clone" / ".cortex"
    clone_backend = MemoryUIBackend(store_dir=clone_store_dir)
    clone_backend.add_remote(name="origin", path=str(remote_root), default_branch="main")
    pull = clone_backend.remote_pull(name="origin", branch="main", into_branch="imported/main")
    fork = clone_backend.remote_fork(name="origin", branch_name="agent/experiment", remote_branch="main")

    assert allow["rule"]["name"] == "protect-main"
    assert rules["rules"][0]["name"] == "protect-main"
    assert check["allowed"] is True
    assert check["require_approval"] is True
    assert remote_add["remote"]["name"] == "origin"
    assert remote_list["remotes"][0]["name"] == "origin"
    assert push["head"] == local_commit
    assert pull["branch"] == "imported/main"
    assert fork["forked"] is True
