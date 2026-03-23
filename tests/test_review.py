from cortex.graph import CortexGraph, Node
from cortex.review import parse_failure_policies, review_graphs


def _graph_with(*nodes: Node) -> CortexGraph:
    graph = CortexGraph()
    for node in nodes:
        graph.add_node(node)
    return graph


def test_review_graphs_reports_new_risks():
    baseline = _graph_with(
        Node(
            id="n1",
            label="Project Atlas",
            tags=["active_priorities"],
            confidence=0.9,
            status="planned",
            valid_from="2026-03-01T00:00:00Z",
        )
    )
    current = _graph_with(
        Node(
            id="n1",
            label="Project Atlas",
            tags=["active_priorities", "negations"],
            confidence=0.4,
            status="active",
            valid_from="2026-03-01T00:00:00Z",
            valid_to="2026-02-01T00:00:00Z",
        ),
        Node(id="n2", label="Rust", tags=["technical_expertise"], confidence=0.8),
    )
    current.meta["retractions"] = [
        {
            "source": "planning-doc-v1",
            "prune_orphans": True,
            "nodes_removed": 1,
            "edges_removed": 0,
        }
    ]

    result = review_graphs(current, baseline, current_label="current", against_label="base").to_dict()

    assert result["summary"]["added_nodes"] == 1
    assert result["summary"]["modified_nodes"] == 1
    assert result["summary"]["new_contradictions"] >= 1
    assert result["summary"]["new_temporal_gaps"] >= 1
    assert result["summary"]["introduced_low_confidence_active_priorities"] == 1
    assert result["summary"]["new_retractions"] == 1


def test_review_graphs_reports_resolved_risks():
    baseline = _graph_with(
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
    current = _graph_with(
        Node(
            id="n1",
            label="Project Atlas",
            tags=["active_priorities"],
            confidence=0.9,
            status="active",
            valid_from="2026-03-01T00:00:00Z",
            valid_to="2026-12-01T00:00:00Z",
        )
    )

    result = review_graphs(current, baseline, current_label="current", against_label="base").to_dict()

    assert result["resolved_contradictions"]
    assert result["resolved_temporal_gaps"]
    assert result["summary"]["blocking_issues"] == 0


def test_review_markdown_and_failure_policies():
    baseline = _graph_with(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    current = _graph_with(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.4))

    review = review_graphs(current, baseline, current_label="current", against_label="base")
    should_fail, counts = review.should_fail(parse_failure_policies("low_confidence"))
    markdown = review.to_markdown(parse_failure_policies("low_confidence"))

    assert should_fail
    assert counts["low_confidence"] == 1
    assert "# Memory Review" in markdown
    assert "Status: `fail`" in markdown


def test_parse_failure_policies_rejects_invalid_values():
    try:
        parse_failure_policies("blocking,nope")
    except ValueError as exc:
        assert "Unknown review failure policy" in str(exc)
    else:
        raise AssertionError("expected parse_failure_policies to raise")
