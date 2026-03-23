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
