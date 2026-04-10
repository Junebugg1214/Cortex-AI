import json
from pathlib import Path

from cortex.claims import ClaimEvent, ClaimLedger
from cortex.cli import main
from cortex.compat import upgrade_v4_to_v5
from cortex.graph import CortexGraph, Node, make_node_id
from cortex.remote_trust import _normalize_store_path
from cortex.upai.identity import UPAIIdentity
from cortex.upai.versioning import VersionStore


def _write_graph(path, graph: CortexGraph) -> None:
    path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def test_query_search_uses_alias(tmp_path, capsys):
    graph = CortexGraph()
    graph.add_node(
        Node(
            id=make_node_id("PostgreSQL"),
            label="PostgreSQL",
            aliases=["postgres"],
            tags=["technical_expertise"],
            confidence=0.9,
        )
    )
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    rc = main(["query", str(graph_path), "--search", "postgres"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "PostgreSQL" in out
    assert "aliases: postgres" in out


def test_query_node_supports_json_output(tmp_path, capsys):
    graph = CortexGraph()
    graph.add_node(Node(id=make_node_id("Python"), label="Python", tags=["technical_expertise"], confidence=0.9))
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    rc = main(["query", str(graph_path), "--node", "Python", "--format", "json"])
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert out["query"] == "node"
    assert out["nodes"][0]["label"] == "Python"


def test_query_at_filters_temporal_graph(tmp_path, capsys):
    graph = CortexGraph()
    graph.add_node(
        Node(
            id=make_node_id("Current Project"),
            label="Current Project",
            tags=["active_priorities"],
            confidence=0.9,
            status="active",
            valid_from="2026-01-01T00:00:00Z",
            valid_to="2026-12-31T00:00:00Z",
        )
    )
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    present_rc = main(["query", str(graph_path), "--node", "Current Project", "--at", "2026-06-01T00:00:00Z"])
    present_out = capsys.readouterr().out
    missing_rc = main(["query", str(graph_path), "--node", "Current Project", "--at", "2027-06-01T00:00:00Z"])
    missing_out = capsys.readouterr().out

    assert present_rc == 0
    assert "Current Project" in present_out
    assert missing_rc == 0
    assert "No node found" in missing_out


def test_blame_json_includes_provenance_and_version_history(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    store = VersionStore(store_dir)
    ledger = ClaimLedger(store_dir)

    graph_v1 = CortexGraph()
    graph_v1.add_node(
        Node(
            id="n1",
            label="PostgreSQL",
            aliases=["postgres"],
            tags=["technical_expertise"],
            confidence=0.8,
            provenance=[{"source": "import-a", "method": "extract"}],
        )
    )
    store.commit(graph_v1, "initial postgres", source="extraction")

    graph_v2 = CortexGraph()
    current_node = Node(
        id="n1",
        canonical_id="n1",
        label="PostgreSQL",
        aliases=["postgres"],
        tags=["technical_expertise"],
        confidence=0.95,
        provenance=[{"source": "manual-a", "method": "manual"}],
        status="active",
    )
    graph_v2.add_node(current_node)
    store.commit(graph_v2, "refine postgres", source="manual")
    ledger.append(
        ClaimEvent.from_node(
            current_node,
            op="assert",
            source="manual-a",
            method="manual_set",
            version_id="claimv1",
            timestamp="2026-03-23T00:00:00Z",
        )
    )

    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph_v2)

    rc = main(
        [
            "blame",
            str(graph_path),
            "--label",
            "postgres",
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert out["nodes"][0]["node"]["label"] == "PostgreSQL"
    assert out["nodes"][0]["provenance_sources"] == ["manual-a"]
    assert out["nodes"][0]["history"]["versions_seen"] == 2
    assert out["nodes"][0]["history"]["introduced_in"]["message"] == "initial postgres"
    assert out["nodes"][0]["claim_lineage"]["event_count"] == 1
    assert out["nodes"][0]["claim_lineage"]["sources"] == ["manual-a"]


def test_blame_history_filters_by_source_and_ref(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    store = VersionStore(store_dir)
    ledger = ClaimLedger(store_dir)

    base_graph = CortexGraph()
    base_graph.add_node(
        Node(
            id="n1",
            label="PostgreSQL",
            aliases=["postgres"],
            tags=["technical_expertise"],
            provenance=[{"source": "import-a", "method": "extract"}],
        )
    )
    store.commit(base_graph, "base postgres")

    store.create_branch("feature/db")
    store.switch_branch("feature/db")
    feature_node = Node(
        id="n1",
        canonical_id="n1",
        label="PostgreSQL",
        aliases=["postgres"],
        tags=["technical_expertise"],
        confidence=0.95,
        provenance=[{"source": "manual-a", "method": "manual"}],
        status="active",
    )
    feature_graph = CortexGraph()
    feature_graph.add_node(feature_node)
    feature_version = store.commit(feature_graph, "feature postgres", source="manual")
    ledger.append(
        ClaimEvent.from_node(
            feature_node,
            op="assert",
            source="manual-a",
            method="manual_set",
            version_id=feature_version.version_id,
            timestamp="2026-03-23T00:00:00Z",
        )
    )

    store.switch_branch("main")
    main_graph = CortexGraph()
    main_graph.add_node(
        Node(
            id="n1",
            label="PostgreSQL",
            aliases=["postgres"],
            tags=["technical_expertise"],
            provenance=[{"source": "import-a", "method": "extract"}],
        )
    )
    store.commit(main_graph, "main postgres", source="extraction")

    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, feature_graph)

    blame_rc = main(
        [
            "blame",
            str(graph_path),
            "--label",
            "postgres",
            "--store-dir",
            str(store_dir),
            "--ref",
            "feature/db",
            "--source",
            "manual-a",
            "--format",
            "json",
        ]
    )
    blame_out = json.loads(capsys.readouterr().out)

    assert blame_rc == 0
    assert blame_out["nodes"][0]["provenance_sources"] == ["manual-a"]
    assert blame_out["nodes"][0]["history"]["versions_seen"] == 1
    assert blame_out["nodes"][0]["claim_lineage"]["sources"] == ["manual-a"]

    history_rc = main(
        [
            "history",
            str(graph_path),
            "--label",
            "postgres",
            "--store-dir",
            str(store_dir),
            "--ref",
            "feature/db",
            "--source",
            "manual-a",
            "--format",
            "json",
        ]
    )
    history_out = json.loads(capsys.readouterr().out)

    assert history_rc == 0
    assert history_out["ref"] == "feature/db"
    assert history_out["source"] == "manual-a"
    assert history_out["nodes"][0]["history"]["introduced_in"]["message"] == "feature postgres"


def test_memory_set_supports_alias_temporal_and_provenance(tmp_path):
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, CortexGraph())

    rc = main(
        [
            "memory",
            "set",
            str(graph_path),
            "--label",
            "PostgreSQL",
            "--tag",
            "technical_expertise",
            "--alias",
            "postgres",
            "--valid-from",
            "2026-01-01T00:00:00Z",
            "--status",
            "active",
            "--source",
            "manual-test",
        ]
    )

    assert rc == 0
    saved = CortexGraph.from_v5_json(json.loads(graph_path.read_text(encoding="utf-8")))
    node = saved.find_nodes(label="postgres")[0]
    assert node.label == "PostgreSQL"
    assert node.valid_from == "2026-01-01T00:00:00Z"
    assert node.status == "active"
    assert node.provenance[0]["source"] == "manual-test"


def test_memory_set_records_claim_event(tmp_path, capsys):
    graph_path = tmp_path / "context.json"
    store_dir = tmp_path / ".cortex"
    _write_graph(graph_path, CortexGraph())

    rc = main(
        [
            "memory",
            "set",
            str(graph_path),
            "--label",
            "Project Atlas",
            "--tag",
            "active_priorities",
            "--status",
            "active",
            "--source",
            "manual-note",
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["claim_id"]

    log_rc = main(
        [
            "claim",
            "log",
            "--store-dir",
            str(store_dir),
            "--label",
            "Project Atlas",
            "--format",
            "json",
        ]
    )
    log_out = json.loads(capsys.readouterr().out)
    assert log_rc == 0
    assert log_out["events"][0]["op"] == "assert"
    assert log_out["events"][0]["claim_id"] == out["claim_id"]

    show_rc = main(["claim", "show", out["claim_id"], "--store-dir", str(store_dir), "--format", "json"])
    show_out = json.loads(capsys.readouterr().out)
    assert show_rc == 0
    assert show_out["events"][0]["label"] == "Project Atlas"


def test_memory_retract_records_claim_event(tmp_path, capsys):
    graph = CortexGraph()
    graph.add_node(
        Node(
            id=make_node_id("Project Atlas"),
            label="Project Atlas",
            tags=["active_priorities"],
            provenance=[{"source": "manual-note", "method": "manual"}],
        )
    )
    graph_path = tmp_path / "context.json"
    store_dir = tmp_path / ".cortex"
    _write_graph(graph_path, graph)

    rc = main(
        [
            "memory",
            "retract",
            str(graph_path),
            "--source",
            "manual-note",
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["claim_event_ids"]

    log_rc = main(
        [
            "claim",
            "log",
            "--store-dir",
            str(store_dir),
            "--source",
            "manual-note",
            "--op",
            "retract",
            "--format",
            "json",
        ]
    )
    log_out = json.loads(capsys.readouterr().out)
    assert log_rc == 0
    assert log_out["events"][0]["op"] == "retract"
    assert log_out["events"][0]["label"] == "Project Atlas"


def test_claim_accept_reject_and_supersede_update_graph_and_ledger(tmp_path, capsys):
    graph_path = tmp_path / "context.json"
    store_dir = tmp_path / ".cortex"
    _write_graph(graph_path, CortexGraph())

    set_rc = main(
        [
            "memory",
            "set",
            str(graph_path),
            "--label",
            "Project Atlas",
            "--tag",
            "active_priorities",
            "--status",
            "planned",
            "--source",
            "manual-note",
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    set_out = json.loads(capsys.readouterr().out)
    assert set_rc == 0
    claim_id = set_out["claim_id"]

    reject_rc = main(
        [
            "claim",
            "reject",
            str(graph_path),
            claim_id,
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    reject_out = json.loads(capsys.readouterr().out)
    assert reject_rc == 0
    assert reject_out["claim_id"] == claim_id
    graph_after_reject = CortexGraph.from_v5_json(json.loads(graph_path.read_text(encoding="utf-8")))
    assert not graph_after_reject.nodes

    accept_rc = main(
        [
            "claim",
            "accept",
            str(graph_path),
            claim_id,
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    accept_out = json.loads(capsys.readouterr().out)
    assert accept_rc == 0
    assert accept_out["restored"] is True
    graph_after_accept = CortexGraph.from_v5_json(json.loads(graph_path.read_text(encoding="utf-8")))
    assert "Project Atlas" in {node.label for node in graph_after_accept.nodes.values()}

    supersede_rc = main(
        [
            "claim",
            "supersede",
            str(graph_path),
            claim_id,
            "--label",
            "Project Atlas v2",
            "--status",
            "active",
            "--tag",
            "active_priorities",
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    supersede_out = json.loads(capsys.readouterr().out)
    assert supersede_rc == 0
    assert supersede_out["superseded_claim_id"] == claim_id
    assert supersede_out["new_claim_id"] != claim_id
    graph_after_supersede = CortexGraph.from_v5_json(json.loads(graph_path.read_text(encoding="utf-8")))
    assert "Project Atlas v2" in {node.label for node in graph_after_supersede.nodes.values()}

    show_rc = main(["claim", "show", claim_id, "--store-dir", str(store_dir), "--format", "json"])
    show_out = json.loads(capsys.readouterr().out)
    assert show_rc == 0
    assert [event["op"] for event in show_out["events"]] == ["assert", "reject", "accept", "supersede"]


def test_extract_records_claim_events_and_provenance(tmp_path, capsys):
    input_path = tmp_path / "notes.txt"
    output_path = tmp_path / "context.json"
    store_dir = tmp_path / ".cortex"
    input_path.write_text("I use Python for backend services.", encoding="utf-8")

    rc = main(
        [
            "extract",
            str(input_path),
            "--format",
            "text",
            "--output",
            str(output_path),
            "--store-dir",
            str(store_dir),
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Recorded" in out

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    graph = upgrade_v4_to_v5(saved)
    python_nodes = graph.find_nodes(label="Python")
    assert python_nodes
    assert python_nodes[0].provenance[0]["source"] == "extract:notes.txt"

    log_rc = main(
        [
            "claim",
            "log",
            "--store-dir",
            str(store_dir),
            "--source",
            "extract:notes.txt",
            "--format",
            "json",
        ]
    )
    log_out = json.loads(capsys.readouterr().out)
    assert log_rc == 0
    assert log_out["events"]
    assert all(event["source"] == "extract:notes.txt" for event in log_out["events"])


def test_extract_no_claims_skips_ledger(tmp_path, capsys):
    input_path = tmp_path / "notes.txt"
    output_path = tmp_path / "context.json"
    store_dir = tmp_path / ".cortex"
    input_path.write_text("I use Python for backend services.", encoding="utf-8")

    rc = main(
        [
            "extract",
            str(input_path),
            "--format",
            "text",
            "--output",
            str(output_path),
            "--store-dir",
            str(store_dir),
            "--no-claims",
        ]
    )
    capsys.readouterr()

    assert rc == 0
    assert not (store_dir / "claims.jsonl").exists()

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    graph = upgrade_v4_to_v5(saved)
    python_nodes = graph.find_nodes(label="Python")
    assert python_nodes
    assert python_nodes[0].provenance == []


def test_version_diff_and_checkout_cli(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    store = VersionStore(store_dir)

    graph_a = CortexGraph()
    graph_a.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.8))
    version_a = store.commit(graph_a, "first")

    graph_b = CortexGraph()
    graph_b.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.9))
    graph_b.add_node(Node(id="n2", label="Rust", tags=["technical_expertise"], confidence=0.7))
    version_b = store.commit(graph_b, "second")

    diff_rc = main(
        ["diff", version_a.version_id[:8], version_b.version_id[:8], "--store-dir", str(store_dir), "--format", "json"]
    )
    diff_out = json.loads(capsys.readouterr().out)
    assert diff_rc == 0
    assert "n2" in diff_out["added"]
    assert diff_out["modified"][0]["node_id"] == "n1"

    output_path = tmp_path / "checked_out.json"
    checkout_rc = main(
        [
            "checkout",
            version_b.version_id[:8],
            "--store-dir",
            str(store_dir),
            "--output",
            str(output_path),
        ]
    )
    assert checkout_rc == 0
    checked_out = CortexGraph.from_v5_json(json.loads(output_path.read_text(encoding="utf-8")))
    assert "n2" in checked_out.nodes


def test_branch_switch_and_ref_checkout_cli(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    graph_path = tmp_path / "context.json"

    base_graph = CortexGraph()
    base_graph.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.8))
    _write_graph(graph_path, base_graph)

    commit_main_rc = main(
        [
            "commit",
            str(graph_path),
            "-m",
            "main base",
            "--store-dir",
            str(store_dir),
        ]
    )
    commit_main_out = capsys.readouterr().out
    assert commit_main_rc == 0
    assert "Branch: main" in commit_main_out

    branch_rc = main(["branch", "feature/atlas", "--store-dir", str(store_dir), "--format", "json"])
    branch_out = json.loads(capsys.readouterr().out)
    assert branch_rc == 0
    assert branch_out["branch"] == "feature/atlas"

    switch_rc = main(["switch", "feature/atlas", "--store-dir", str(store_dir)])
    switch_out = capsys.readouterr().out
    assert switch_rc == 0
    assert "Switched to feature/atlas" in switch_out

    feature_graph = CortexGraph()
    feature_graph.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.8))
    feature_graph.add_node(Node(id="n2", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    _write_graph(graph_path, feature_graph)

    commit_feature_rc = main(
        [
            "commit",
            str(graph_path),
            "-m",
            "feature add atlas",
            "--store-dir",
            str(store_dir),
        ]
    )
    capsys.readouterr()
    assert commit_feature_rc == 0

    log_rc = main(["log", "--store-dir", str(store_dir), "--branch", "feature/atlas"])
    log_out = capsys.readouterr().out
    assert log_rc == 0
    assert "feature add atlas" in log_out
    assert "(feature/atlas)" in log_out

    diff_rc = main(["diff", "main", "feature/atlas", "--store-dir", str(store_dir), "--format", "json"])
    diff_out = json.loads(capsys.readouterr().out)
    assert diff_rc == 0
    assert "n2" in diff_out["added"]

    output_path = tmp_path / "feature_checked_out.json"
    checkout_rc = main(
        [
            "checkout",
            "feature/atlas",
            "--store-dir",
            str(store_dir),
            "--output",
            str(output_path),
        ]
    )
    capsys.readouterr()
    assert checkout_rc == 0
    checked_out = CortexGraph.from_v5_json(json.loads(output_path.read_text(encoding="utf-8")))
    assert "n2" in checked_out.nodes


def test_merge_cli_merges_branch_into_current(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    graph_path = tmp_path / "context.json"

    base_graph = CortexGraph()
    base_graph.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.8))
    _write_graph(graph_path, base_graph)
    assert main(["commit", str(graph_path), "-m", "base", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()

    assert main(["branch", "feature/atlas", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()
    assert main(["switch", "feature/atlas", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()

    feature_graph = CortexGraph()
    feature_graph.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.8))
    feature_graph.add_node(Node(id="n2", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    _write_graph(graph_path, feature_graph)
    assert main(["commit", str(graph_path), "-m", "feature add atlas", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()

    assert main(["switch", "main", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()

    merge_rc = main(["merge", "feature/atlas", "--store-dir", str(store_dir), "--format", "json"])
    merge_out = json.loads(capsys.readouterr().out)
    assert merge_rc == 0
    assert merge_out["commit_id"]
    assert not merge_out["conflicts"]

    main_head = VersionStore(store_dir).head("main")
    assert main_head is not None
    assert main_head.source == "merge"
    assert "Project Atlas" in {
        node.label for node in VersionStore(store_dir).checkout(main_head.version_id).nodes.values()
    }


def test_merge_cli_conflict_resolution_flow(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    graph_path = tmp_path / "context.json"

    base_graph = CortexGraph()
    base_graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], status="planned"))
    _write_graph(graph_path, base_graph)
    assert main(["commit", str(graph_path), "-m", "base", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()

    assert main(["branch", "feature/activate", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()
    assert main(["switch", "feature/activate", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()

    feature_graph = CortexGraph()
    feature_graph.add_node(
        Node(
            id="n1",
            label="Project Atlas",
            tags=["active_priorities"],
            status="active",
            valid_from="2026-03-01T00:00:00Z",
        )
    )
    _write_graph(graph_path, feature_graph)
    assert main(["commit", str(graph_path), "-m", "activate atlas", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()

    assert main(["switch", "main", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()

    current_graph = CortexGraph()
    current_graph.add_node(
        Node(
            id="n1",
            label="Project Atlas",
            tags=["active_priorities"],
            status="historical",
            valid_to="2026-02-01T00:00:00Z",
        )
    )
    _write_graph(graph_path, current_graph)
    assert main(["commit", str(graph_path), "-m", "archive atlas", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()

    merge_rc = main(["merge", "feature/activate", "--store-dir", str(store_dir), "--format", "json"])
    merge_out = json.loads(capsys.readouterr().out)
    assert merge_rc == 1
    assert merge_out["pending_merge"] is True
    conflict_id = merge_out["conflicts"][0]["id"]

    conflicts_rc = main(["merge", "--conflicts", "--store-dir", str(store_dir), "--format", "json"])
    conflicts_out = json.loads(capsys.readouterr().out)
    assert conflicts_rc == 0
    assert conflicts_out["pending"] is True
    assert conflicts_out["conflicts"][0]["id"] == conflict_id

    resolve_rc = main(
        [
            "merge",
            "--resolve",
            conflict_id,
            "--choose",
            "incoming",
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    resolve_out = json.loads(capsys.readouterr().out)
    assert resolve_rc == 0
    assert resolve_out["remaining_conflicts"] == 0

    commit_rc = main(["merge", "--commit-resolved", "--store-dir", str(store_dir), "--format", "json"])
    commit_out = json.loads(capsys.readouterr().out)
    assert commit_rc == 0
    assert commit_out["commit_id"]
    head = VersionStore(store_dir).head("main")
    assert head is not None
    graph = VersionStore(store_dir).checkout(head.version_id)
    assert graph.nodes["n1"].status == "active"

    conflicts_after_rc = main(["merge", "--conflicts", "--store-dir", str(store_dir), "--format", "json"])
    conflicts_after = json.loads(capsys.readouterr().out)
    assert conflicts_after_rc == 0
    assert conflicts_after["pending"] is False


def test_review_cli_reports_added_nodes_and_risks(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    baseline_graph = CortexGraph()
    baseline_graph.add_node(
        Node(
            id="n1",
            label="Project Atlas",
            tags=["active_priorities"],
            confidence=0.9,
            status="planned",
            valid_from="2026-03-01T00:00:00Z",
        )
    )
    baseline_path = tmp_path / "baseline.json"
    _write_graph(baseline_path, baseline_graph)
    assert main(["commit", str(baseline_path), "-m", "baseline", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()

    current_graph = CortexGraph()
    current_graph.add_node(
        Node(
            id="n1",
            label="Project Atlas",
            tags=["active_priorities", "negations"],
            confidence=0.4,
            status="active",
            valid_from="2026-03-01T00:00:00Z",
            valid_to="2026-02-01T00:00:00Z",
        )
    )
    current_graph.add_node(Node(id="n2", label="Rust", tags=["technical_expertise"], confidence=0.8))
    current_path = tmp_path / "current.json"
    _write_graph(current_path, current_graph)

    review_rc = main(
        [
            "review",
            str(current_path),
            "--against",
            "HEAD",
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    review_out = json.loads(capsys.readouterr().out)

    assert review_rc == 1
    assert review_out["summary"]["added_nodes"] == 1
    assert review_out["summary"]["new_contradictions"] >= 1
    assert review_out["summary"]["new_temporal_gaps"] >= 1


def test_review_cli_supports_markdown_and_custom_fail_on(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    baseline_graph = CortexGraph()
    baseline_graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    baseline_path = tmp_path / "baseline.json"
    _write_graph(baseline_path, baseline_graph)
    assert main(["commit", str(baseline_path), "-m", "baseline", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()

    current_graph = CortexGraph()
    current_graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.4))
    current_path = tmp_path / "current.json"
    _write_graph(current_path, current_graph)

    review_rc = main(
        [
            "review",
            str(current_path),
            "--against",
            "HEAD",
            "--store-dir",
            str(store_dir),
            "--fail-on",
            "low_confidence",
            "--format",
            "md",
        ]
    )
    review_out = capsys.readouterr().out

    assert review_rc == 1
    assert "# Memory Review" in review_out
    assert "Status: `fail`" in review_out

    relaxed_rc = main(
        [
            "review",
            str(current_path),
            "--against",
            "HEAD",
            "--store-dir",
            str(store_dir),
            "--fail-on",
            "none",
            "--format",
            "json",
        ]
    )
    relaxed_out = json.loads(capsys.readouterr().out)

    assert relaxed_rc == 0
    assert relaxed_out["status"] == "pass"
    assert relaxed_out["fail_on"] == ["none"]


def test_commit_requires_approval_under_governance(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.4))
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    assert (
        main(
            [
                "governance",
                "allow",
                "protect-main",
                "--actor",
                "agent/*",
                "--action",
                "write",
                "--namespace",
                "main",
                "--approval-below-confidence",
                "0.75",
                "--store-dir",
                str(store_dir),
            ]
        )
        == 0
    )
    capsys.readouterr()

    blocked_rc = main(
        [
            "commit",
            str(graph_path),
            "-m",
            "low confidence write",
            "--store-dir",
            str(store_dir),
            "--actor",
            "agent/coder",
        ]
    )
    blocked_out = capsys.readouterr().out

    assert blocked_rc == 1
    assert "Approval required" in blocked_out

    approved_rc = main(
        [
            "commit",
            str(graph_path),
            "-m",
            "approved write",
            "--store-dir",
            str(store_dir),
            "--actor",
            "agent/coder",
            "--approve",
        ]
    )
    approved_out = capsys.readouterr().out

    assert approved_rc == 0
    assert "Committed:" in approved_out


def test_diff_json_includes_semantic_changes(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    baseline = CortexGraph()
    baseline.add_node(
        Node(
            id="n1",
            label="Project Atlas",
            tags=["active_priorities"],
            status="planned",
            valid_from="2026-01-01T00:00:00Z",
        )
    )
    updated = CortexGraph()
    updated.add_node(
        Node(
            id="n1",
            label="Project Atlas",
            tags=["active_priorities"],
            status="active",
            valid_from="2026-02-01T00:00:00Z",
            valid_to="2026-12-31T00:00:00Z",
        )
    )

    baseline_path = tmp_path / "baseline.json"
    updated_path = tmp_path / "updated.json"
    _write_graph(baseline_path, baseline)
    _write_graph(updated_path, updated)
    assert main(["commit", str(baseline_path), "-m", "baseline", "--store-dir", str(store_dir)]) == 0
    baseline_commit = capsys.readouterr().out.splitlines()[0].split()[-1]
    assert main(["commit", str(updated_path), "-m", "updated", "--store-dir", str(store_dir)]) == 0
    updated_commit = capsys.readouterr().out.splitlines()[0].split()[-1]

    rc = main(
        [
            "diff",
            baseline_commit,
            updated_commit,
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert out["semantic_summary"]["total"] >= 1
    assert any(change["type"] == "lifecycle_shift" for change in out["semantic_changes"])


def test_rollback_restores_previous_version_without_rewriting_history(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    graph_v1 = CortexGraph()
    graph_v1.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.9))
    graph_v2 = CortexGraph()
    graph_v2.add_node(Node(id="n1", label="Rust", tags=["technical_expertise"], confidence=0.9))

    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph_v1)
    assert main(["commit", str(graph_path), "-m", "v1", "--store-dir", str(store_dir)]) == 0
    first_out = capsys.readouterr().out
    first_commit = first_out.splitlines()[0].split()[-1]

    _write_graph(graph_path, graph_v2)
    assert main(["commit", str(graph_path), "-m", "v2", "--store-dir", str(store_dir)]) == 0
    capsys.readouterr()

    rollback_rc = main(
        [
            "rollback",
            str(graph_path),
            "--to",
            first_commit,
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    rollback_out = json.loads(capsys.readouterr().out)

    assert rollback_rc == 0
    restored = CortexGraph.from_v5_json(json.loads(graph_path.read_text(encoding="utf-8")))
    assert restored.nodes["n1"].label == "Python"

    store = VersionStore(store_dir)
    history = store.log(limit=10)
    assert len(history) == 3
    assert history[0].version_id == rollback_out["rollback_commit"]


def test_remote_push_pull_and_fork_workflows(tmp_path, capsys):
    local_store_dir = tmp_path / "local" / ".cortex"
    remote_root = tmp_path / "remote"
    local_graph = CortexGraph()
    local_graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    graph_path = tmp_path / "local" / "context.json"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    _write_graph(graph_path, local_graph)

    assert main(["commit", str(graph_path), "-m", "local baseline", "--store-dir", str(local_store_dir)]) == 0
    local_commit = capsys.readouterr().out.splitlines()[0].split()[-1]

    assert main(["remote", "add", "origin", str(remote_root), "--store-dir", str(local_store_dir)]) == 0
    capsys.readouterr()
    push_rc = main(
        ["remote", "push", "origin", "--branch", "main", "--store-dir", str(local_store_dir), "--format", "json"]
    )
    push_out = json.loads(capsys.readouterr().out)

    assert push_rc == 0
    assert push_out["head"] == local_commit
    assert push_out["trusted_remote_did"]
    assert push_out["allowed_namespaces"] == ["main"]
    assert Path(push_out["receipt_path"]).exists()

    clone_store_dir = tmp_path / "clone" / ".cortex"
    assert main(["remote", "add", "origin", str(remote_root), "--store-dir", str(clone_store_dir)]) == 0
    capsys.readouterr()
    pull_rc = main(
        [
            "remote",
            "pull",
            "origin",
            "--branch",
            "main",
            "--into-branch",
            "imported/main",
            "--store-dir",
            str(clone_store_dir),
            "--format",
            "json",
        ]
    )
    pull_out = json.loads(capsys.readouterr().out)
    assert pull_rc == 0
    assert pull_out["branch"] == "imported/main"
    assert Path(pull_out["receipt_path"]).exists()
    assert VersionStore(clone_store_dir).resolve_ref("imported/main") == local_commit

    fork_rc = main(
        [
            "remote",
            "fork",
            "origin",
            "agent/experiment",
            "--remote-branch",
            "main",
            "--store-dir",
            str(clone_store_dir),
            "--format",
            "json",
        ]
    )
    fork_out = json.loads(capsys.readouterr().out)
    assert fork_rc == 0
    assert fork_out["forked"] is True
    assert Path(fork_out["receipt_path"]).exists()
    assert VersionStore(clone_store_dir).resolve_ref("agent/experiment") == local_commit


def test_remote_push_rejects_namespace_outside_allowlist(tmp_path, capsys):
    local_store_dir = tmp_path / "local" / ".cortex"
    remote_root = tmp_path / "remote"
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    assert main(["commit", str(graph_path), "-m", "baseline", "--store-dir", str(local_store_dir)]) == 0
    capsys.readouterr()
    assert main(["branch", "team/atlas", "--store-dir", str(local_store_dir)]) == 0
    capsys.readouterr()
    assert main(["remote", "add", "origin", str(remote_root), "--store-dir", str(local_store_dir)]) == 0
    capsys.readouterr()

    push_rc = main(
        ["remote", "push", "origin", "--branch", "team/atlas", "--store-dir", str(local_store_dir), "--format", "json"]
    )
    push_out = capsys.readouterr().out

    assert push_rc == 1
    assert "does not allow namespace 'team/atlas'" in push_out


def test_remote_push_rejects_remote_identity_drift(tmp_path, capsys):
    local_store_dir = tmp_path / "local" / ".cortex"
    remote_root = tmp_path / "remote"
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    assert main(["commit", str(graph_path), "-m", "baseline", "--store-dir", str(local_store_dir)]) == 0
    capsys.readouterr()
    assert main(["remote", "add", "origin", str(remote_root), "--store-dir", str(local_store_dir)]) == 0
    capsys.readouterr()

    UPAIIdentity.generate("Drifted Remote").save(_normalize_store_path(remote_root))

    push_rc = main(["remote", "push", "origin", "--branch", "main", "--store-dir", str(local_store_dir)])
    push_out = capsys.readouterr().out

    assert push_rc == 1
    assert "identity mismatch" in push_out
