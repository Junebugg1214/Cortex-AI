from pathlib import Path

from cortex.claims import ClaimEvent, ClaimLedger
from cortex.graph import Node


def test_claim_ledger_append_and_filter(tmp_path: Path):
    ledger = ClaimLedger(tmp_path / ".cortex")
    node = Node(
        id="n1",
        canonical_id="n1",
        label="Project Atlas",
        aliases=["atlas"],
        tags=["active_priorities"],
        confidence=0.9,
        status="active",
        valid_from="2026-03-01T00:00:00Z",
    )
    assert_event = ClaimEvent.from_node(
        node,
        op="assert",
        source="manual-note",
        method="manual_set",
        version_id="abc123",
        message="Add atlas",
        timestamp="2026-03-23T00:00:00Z",
    )
    retract_event = ClaimEvent.from_node(
        node,
        op="retract",
        source="manual-note",
        method="memory_retract",
        version_id="def456",
        message="Remove atlas",
        timestamp="2026-03-24T00:00:00Z",
    )

    ledger.append(assert_event)
    ledger.append(retract_event)

    by_label = ledger.list_events(label="atlas", limit=10)
    assert [event.op for event in by_label] == ["retract", "assert"]

    by_op = ledger.list_events(op="assert", limit=10)
    assert len(by_op) == 1
    assert by_op[0].claim_id == assert_event.claim_id

    claim_history = ledger.get_claim(assert_event.claim_id)
    assert [event.op for event in claim_history] == ["assert", "retract"]


def test_claim_ledger_lineage_for_node(tmp_path: Path):
    ledger = ClaimLedger(tmp_path / ".cortex")
    node = Node(
        id="n1",
        canonical_id="canonical-1",
        label="Project Atlas",
        aliases=["atlas"],
        tags=["active_priorities"],
        confidence=0.9,
    )
    ledger.append(
        ClaimEvent.from_node(
            node,
            op="assert",
            source="extract:notes.txt",
            method="extract",
            version_id="aaa111",
            timestamp="2026-03-23T00:00:00Z",
        )
    )
    ledger.append(
        ClaimEvent.from_node(
            node,
            op="retract",
            source="extract:notes.txt",
            method="memory_retract",
            version_id="bbb222",
            timestamp="2026-03-24T00:00:00Z",
        )
    )

    lineage = ledger.lineage_for_node(node, limit=10)

    assert lineage["event_count"] == 2
    assert lineage["claim_count"] == 1
    assert lineage["assert_count"] == 1
    assert lineage["retract_count"] == 1
    assert lineage["sources"] == ["extract:notes.txt"]
    assert lineage["introduced_at"]["version_id"] == "aaa111"
    assert lineage["latest_event"]["op"] == "retract"


def test_claim_ledger_filters_by_version_prefix_and_source(tmp_path: Path):
    ledger = ClaimLedger(tmp_path / ".cortex")
    node = Node(
        id="n1",
        canonical_id="canonical-1",
        label="Project Atlas",
        tags=["active_priorities"],
    )
    ledger.append(
        ClaimEvent.from_node(
            node,
            op="assert",
            source="extract:notes.txt",
            method="extract",
            version_id="aaa111ffff",
            timestamp="2026-03-23T00:00:00Z",
        )
    )
    ledger.append(
        ClaimEvent.from_node(
            node,
            op="assert",
            source="manual-note",
            method="manual_set",
            version_id="bbb222ffff",
            timestamp="2026-03-24T00:00:00Z",
        )
    )

    filtered = ledger.list_events(source="manual-note", version_ref="bbb222", limit=10)

    assert len(filtered) == 1
    assert filtered[0].source == "manual-note"
    assert filtered[0].version_id == "bbb222ffff"
