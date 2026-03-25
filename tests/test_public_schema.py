from cortex.claims import ClaimEvent
from cortex.governance import GovernanceDecision, GovernanceRule
from cortex.graph import CortexGraph, Node
from cortex.remotes import MemoryRemote
from cortex.schemas.memory_v1 import (
    BranchRecord,
    ClaimRecord,
    CommitRecord,
    GovernanceDecisionRecord,
    GovernanceRuleRecord,
    MemoryGraphRecord,
    RemoteRecord,
)
from cortex.schemas.validation import validate_model
from cortex.upai.versioning import ContextVersion


def test_commit_record_from_context_version_roundtrip():
    version = ContextVersion(
        version_id="abc123",
        parent_id="parent1",
        merge_parent_ids=["merge1"],
        timestamp="2026-03-25T00:00:00Z",
        branch="main",
        source="manual",
        message="Save graph",
        graph_hash="f" * 64,
        node_count=4,
        edge_count=2,
        signature=None,
    )

    record = CommitRecord.from_context_version(version)

    assert record.namespace == "main"
    assert record.message == "Save graph"
    assert validate_model(record) == []


def test_branch_rule_and_remote_records_validate():
    branch = BranchRecord.from_branch_payload({"name": "main", "head": "abc123", "current": True})
    rule = GovernanceRuleRecord.from_governance_rule(
        GovernanceRule(
            name="protect-main",
            effect="allow",
            actor_pattern="agent/*",
            actions=["write"],
            namespaces=["main"],
            require_approval=True,
        )
    )
    decision = GovernanceDecisionRecord.from_governance_decision(
        GovernanceDecision(
            allowed=True,
            require_approval=True,
            actor="agent/coder",
            action="write",
            namespace="main",
            reasons=["Rule requires explicit approval."],
            matched_rules=["protect-main"],
        )
    )
    remote = RemoteRecord.from_memory_remote(MemoryRemote(name="origin", path="/tmp/remote", default_branch="main"))

    assert branch.current is True
    assert rule.require_approval is True
    assert decision.allowed is True
    assert remote.resolved_store_path.endswith(".cortex")
    assert validate_model(branch) == []
    assert validate_model(rule) == []
    assert validate_model(decision) == []
    assert validate_model(remote) == []


def test_graph_and_claim_records_validate():
    graph = CortexGraph()
    node = Node(
        id="n1",
        canonical_id="n1",
        label="PostgreSQL",
        aliases=["postgres"],
        tags=["technical_expertise"],
        confidence=0.9,
        provenance=[{"source": "manual-a", "method": "manual"}],
    )
    graph.add_node(node)

    record = MemoryGraphRecord.from_graph(graph, namespace="feature/db")
    claim = ClaimRecord.from_claim_event(
        ClaimEvent.from_node(
            node,
            op="assert",
            source="manual-a",
            method="manual_set",
            version_id="abc123",
            timestamp="2026-03-25T00:00:00Z",
        ),
        namespace="feature/db",
    )

    assert record.namespace == "feature/db"
    assert record.nodes[0].label == "PostgreSQL"
    assert claim.claim_id
    assert validate_model(record) == []
    assert validate_model(claim) == []
