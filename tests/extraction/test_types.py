from __future__ import annotations

from cortex.extraction import BackendExtractionResult as ExtractionResult
from cortex.extraction import ExtractedEdge, ExtractedNode


def test_extracted_node_defaults():
    node = ExtractedNode(label="Python", category="technical_expertise", value="Python", confidence=0.9)
    assert node.canonical_match is None
    assert node.match_confidence is None
    assert node.needs_review is False
    assert node.embedding is None


def test_extracted_node_all_fields():
    node = ExtractedNode(
        label="OpenAI",
        category="business_context",
        value="OpenAI research partner",
        confidence=0.83,
        canonical_match="node-123",
        match_confidence=0.97,
        needs_review=True,
        embedding=[0.1, 0.2, 0.3],
    )
    assert node.canonical_match == "node-123"
    assert node.match_confidence == 0.97
    assert node.needs_review is True
    assert node.embedding == [0.1, 0.2, 0.3]


def test_extracted_node_embedding_can_be_none():
    node = ExtractedNode(label="Rust", category="technical_expertise", value="Rust", confidence=0.8)
    assert node.embedding is None


def test_extracted_edge_defaults():
    edge = ExtractedEdge(source="A", target="B", relationship="uses", direction_confidence=0.7)
    assert edge.needs_review is False


def test_extracted_edge_all_fields():
    edge = ExtractedEdge(
        source="Alice",
        target="Project Atlas",
        relationship="works_on",
        direction_confidence=0.52,
        needs_review=True,
    )
    assert edge.source == "Alice"
    assert edge.target == "Project Atlas"
    assert edge.relationship == "works_on"
    assert edge.direction_confidence == 0.52
    assert edge.needs_review is True


def test_extraction_result_defaults():
    result = ExtractionResult()
    assert result.nodes == []
    assert result.edges == []
    assert result.extraction_method == "heuristic"
    assert result.raw_source == ""
    assert result.warnings == []
    assert result.rescore_pending is False


def test_extraction_result_all_fields():
    node = ExtractedNode(label="A", category="identity", value="A", confidence=0.9)
    edge = ExtractedEdge(source="A", target="B", relationship="knows", direction_confidence=0.8)
    result = ExtractionResult(
        nodes=[node],
        edges=[edge],
        extraction_method="hybrid",
        raw_source="A knows B",
        warnings=["ambiguous direction"],
        rescore_pending=True,
    )
    assert result.nodes == [node]
    assert result.edges == [edge]
    assert result.extraction_method == "hybrid"
    assert result.raw_source == "A knows B"
    assert result.warnings == ["ambiguous direction"]
    assert result.rescore_pending is True


def test_extraction_result_warning_list_isolated():
    left = ExtractionResult()
    right = ExtractionResult()
    left.warnings.append("left-only")
    assert right.warnings == []


def test_extraction_result_node_list_isolated():
    left = ExtractionResult()
    right = ExtractionResult()
    left.nodes.append(ExtractedNode(label="A", category="identity", value="A", confidence=1.0))
    assert right.nodes == []


def test_extraction_result_edge_list_isolated():
    left = ExtractionResult()
    right = ExtractionResult()
    left.edges.append(ExtractedEdge(source="A", target="B", relationship="knows", direction_confidence=0.8))
    assert right.edges == []


def test_extraction_result_rescore_pending_defaults_false():
    assert ExtractionResult().rescore_pending is False
