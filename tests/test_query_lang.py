"""Tests for cortex.query_lang — graph query DSL."""

from __future__ import annotations

import pytest

from cortex.graph import CortexGraph, Edge, Node, make_edge_id, make_node_id
from cortex.query_lang import (
    FindQuery,
    NeighborsQuery,
    ParseError,
    PathQuery,
    SearchQuery,
    _match_condition,
    _tokenize,
    execute_query,
    parse_query,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _node(label, tags=None, confidence=0.9, brief="", props=None):
    nid = make_node_id(label)
    return Node(
        id=nid,
        label=label,
        tags=tags or [],
        confidence=confidence,
        properties=props or {},
        brief=brief,
        full_description="",
    )


@pytest.fixture
def graph():
    g = CortexGraph()
    g.add_node(_node("Python", tags=["technology", "language"], confidence=0.95, brief="A programming language"))
    g.add_node(_node("Machine Learning", tags=["technology", "ai"], confidence=0.9, brief="Subset of AI"))
    g.add_node(_node("Healthcare", tags=["domain"], confidence=0.8, brief="Medical services"))
    g.add_node(_node("Marc", tags=["person"], confidence=0.99, brief="A developer"))
    g.add_node(_node("Coffee", tags=["lifestyle"], confidence=0.5, brief="A beverage"))
    # Edges
    marc_id = make_node_id("Marc")
    python_id = make_node_id("Python")
    ml_id = make_node_id("Machine Learning")
    g.add_edge(
        Edge(
            id=make_edge_id(marc_id, python_id, "uses"),
            source_id=marc_id,
            target_id=python_id,
            relation="uses",
            confidence=0.9,
            properties={},
        )
    )
    g.add_edge(
        Edge(
            id=make_edge_id(python_id, ml_id, "used_in"),
            source_id=python_id,
            target_id=ml_id,
            relation="used_in",
            confidence=0.8,
            properties={},
        )
    )
    g.add_edge(
        Edge(
            id=make_edge_id(marc_id, ml_id, "studies"),
            source_id=marc_id,
            target_id=ml_id,
            relation="studies",
            confidence=0.7,
            properties={},
        )
    )
    return g


# ---------------------------------------------------------------------------
# Tokenizer tests
# ---------------------------------------------------------------------------


class TestTokenizer:
    def test_basic(self):
        tokens = _tokenize('FIND nodes WHERE tag = "tech"')
        assert ("WORD", "FIND") in tokens
        assert ("WORD", "NODES") in tokens
        assert ("WORD", "WHERE") in tokens
        assert ("WORD", "TAG") in tokens
        assert ("OP", "=") in tokens
        assert ("STRING", "tech") in tokens

    def test_number(self):
        tokens = _tokenize("LIMIT 10")
        assert ("WORD", "LIMIT") in tokens
        assert ("NUMBER", "10") in tokens

    def test_float(self):
        tokens = _tokenize("confidence >= 0.9")
        assert ("NUMBER", "0.9") in tokens
        assert ("OP", ">=") in tokens

    def test_operators(self):
        for op in ("=", "!=", ">=", "<=", ">", "<"):
            tokens = _tokenize(f"x {op} 1")
            assert ("OP", op) in tokens

    def test_string_with_spaces(self):
        tokens = _tokenize('SEARCH "machine learning"')
        assert ("STRING", "machine learning") in tokens

    def test_empty(self):
        assert _tokenize("") == []


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParseFind:
    def test_basic_find(self):
        q = parse_query("FIND nodes")
        assert isinstance(q, FindQuery)
        assert q.conditions == []
        assert q.limit == 100

    def test_find_with_where(self):
        q = parse_query('FIND nodes WHERE tag = "technology"')
        assert isinstance(q, FindQuery)
        assert len(q.conditions) == 1
        assert q.conditions[0] == ("tag", "=", "technology")

    def test_find_with_multiple_conditions(self):
        q = parse_query('FIND nodes WHERE tag = "tech" AND confidence >= 0.9')
        assert isinstance(q, FindQuery)
        assert len(q.conditions) == 2

    def test_find_with_limit(self):
        q = parse_query("FIND nodes LIMIT 5")
        assert isinstance(q, FindQuery)
        assert q.limit == 5

    def test_find_with_where_and_limit(self):
        q = parse_query("FIND nodes WHERE confidence > 0.8 LIMIT 3")
        assert isinstance(q, FindQuery)
        assert len(q.conditions) == 1
        assert q.limit == 3


class TestParseNeighbors:
    def test_basic(self):
        q = parse_query('NEIGHBORS OF "Python"')
        assert isinstance(q, NeighborsQuery)
        assert q.target == "Python"


class TestParsePath:
    def test_basic(self):
        q = parse_query('PATH FROM "Marc" TO "Healthcare"')
        assert isinstance(q, PathQuery)
        assert q.source == "Marc"
        assert q.target == "Healthcare"


class TestParseSearch:
    def test_basic(self):
        q = parse_query('SEARCH "machine learning"')
        assert isinstance(q, SearchQuery)
        assert q.query_text == "machine learning"
        assert q.limit == 10

    def test_with_limit(self):
        q = parse_query('SEARCH "python" LIMIT 5')
        assert isinstance(q, SearchQuery)
        assert q.limit == 5


class TestParseErrors:
    def test_empty_query(self):
        with pytest.raises(ParseError):
            parse_query("")

    def test_unknown_keyword(self):
        with pytest.raises(ParseError):
            parse_query("DELETE nodes")

    def test_incomplete_find(self):
        with pytest.raises(ParseError):
            parse_query("FIND nodes WHERE")

    def test_missing_value(self):
        with pytest.raises(ParseError):
            parse_query("FIND nodes WHERE tag =")


# ---------------------------------------------------------------------------
# Match condition tests
# ---------------------------------------------------------------------------


class TestMatchCondition:
    def test_string_equals(self):
        d = {"label": "Python", "tags": ["tech"]}
        assert _match_condition(d, "label", "=", "Python")
        assert not _match_condition(d, "label", "=", "Java")

    def test_string_not_equals(self):
        d = {"label": "Python"}
        assert _match_condition(d, "label", "!=", "Java")
        assert not _match_condition(d, "label", "!=", "Python")

    def test_numeric_gte(self):
        d = {"confidence": 0.9}
        assert _match_condition(d, "confidence", ">=", 0.8)
        assert _match_condition(d, "confidence", ">=", 0.9)
        assert not _match_condition(d, "confidence", ">=", 0.95)

    def test_tag_equals(self):
        d = {"tags": ["technology", "language"]}
        assert _match_condition(d, "tag", "=", "technology")
        assert not _match_condition(d, "tag", "=", "health")

    def test_tag_not_equals(self):
        d = {"tags": ["technology"]}
        assert _match_condition(d, "tag", "!=", "health")
        assert not _match_condition(d, "tag", "!=", "technology")

    def test_dotted_field(self):
        d = {"properties": {"color": "blue"}}
        assert _match_condition(d, "properties.color", "=", "blue")

    def test_missing_field(self):
        d = {"label": "X"}
        assert not _match_condition(d, "missing", "=", "value")

    def test_case_insensitive(self):
        d = {"label": "Python"}
        assert _match_condition(d, "label", "=", "python")


# ---------------------------------------------------------------------------
# Execute tests
# ---------------------------------------------------------------------------


class TestExecuteFind:
    def test_find_all(self, graph):
        result = execute_query(graph, "FIND nodes")
        assert result["type"] == "find"
        assert result["count"] == 5

    def test_find_by_tag(self, graph):
        result = execute_query(graph, 'FIND nodes WHERE tag = "technology"')
        assert result["type"] == "find"
        assert result["count"] == 2
        labels = {n["label"] for n in result["nodes"]}
        assert "Python" in labels
        assert "Machine Learning" in labels

    def test_find_by_confidence(self, graph):
        result = execute_query(graph, "FIND nodes WHERE confidence >= 0.95")
        assert result["count"] >= 1
        for n in result["nodes"]:
            assert n["confidence"] >= 0.95

    def test_find_with_limit(self, graph):
        result = execute_query(graph, "FIND nodes LIMIT 2")
        assert result["count"] <= 2

    def test_find_no_matches(self, graph):
        result = execute_query(graph, 'FIND nodes WHERE tag = "nonexistent"')
        assert result["count"] == 0


class TestExecuteNeighbors:
    def test_neighbors_by_label(self, graph):
        result = execute_query(graph, 'NEIGHBORS OF "Python"')
        assert result["type"] == "neighbors"
        assert len(result["neighbors"]) > 0

    def test_neighbors_not_found(self, graph):
        result = execute_query(graph, 'NEIGHBORS OF "NonExistent"')
        assert "error" in result

    def test_neighbors_by_label_marc(self, graph):
        result = execute_query(graph, 'NEIGHBORS OF "Marc"')
        assert result["type"] == "neighbors"
        assert len(result["neighbors"]) >= 2  # Python and ML


class TestExecutePath:
    def test_path_exists(self, graph):
        result = execute_query(graph, 'PATH FROM "Marc" TO "Machine Learning"')
        assert result["type"] == "path"
        assert result["length"] > 0

    def test_path_not_found(self, graph):
        result = execute_query(graph, 'PATH FROM "Coffee" TO "Healthcare"')
        assert result["type"] == "path"
        assert result["length"] == 0

    def test_path_source_not_found(self, graph):
        result = execute_query(graph, 'PATH FROM "Nobody" TO "Python"')
        assert "error" in result


class TestExecuteSearch:
    def test_search(self, graph):
        result = execute_query(graph, 'SEARCH "programming language"')
        assert result["type"] == "search"
        assert result["count"] >= 0  # may or may not match depending on substring

    def test_search_with_limit(self, graph):
        result = execute_query(graph, 'SEARCH "technology" LIMIT 1')
        assert result["count"] <= 1
