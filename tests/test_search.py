"""Tests for cortex.search — TF-IDF semantic search engine."""

import pytest

from cortex.graph import CortexGraph, Node, make_node_id
from cortex.search import STOP_WORDS, TFIDFIndex, tokenize

# ---------------------------------------------------------------------------
# Tokenizer tests
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_basic(self):
        tokens = tokenize("Hello World")
        assert tokens == ["hello", "world"]

    def test_removes_stop_words(self):
        tokens = tokenize("the quick brown fox jumps over the lazy dog")
        assert "the" not in tokens
        assert "over" not in tokens
        assert "quick" in tokens
        assert "brown" in tokens

    def test_empty_string(self):
        assert tokenize("") == []

    def test_numbers(self):
        tokens = tokenize("Python 3.10 released in 2021")
        assert "python" in tokens
        assert "10" in tokens
        assert "2021" in tokens

    def test_hyphenated(self):
        tokens = tokenize("machine-learning is state-of-the-art")
        assert "machine-learning" in tokens

    def test_all_stop_words(self):
        assert tokenize("the and or but") == []


class TestStopWords:
    def test_common_words_present(self):
        for w in ("the", "is", "at", "which", "on", "and", "or"):
            assert w in STOP_WORDS

    def test_count(self):
        assert len(STOP_WORDS) > 100


# ---------------------------------------------------------------------------
# TFIDFIndex tests
# ---------------------------------------------------------------------------


def _make_node(label, brief="", desc="", tags=None, props=None):
    nid = make_node_id(label)
    return Node(
        id=nid,
        label=label,
        tags=tags or [],
        confidence=0.9,
        properties=props or {},
        brief=brief,
        full_description=desc,
    )


@pytest.fixture
def sample_nodes():
    return [
        _make_node("Python", brief="A programming language", tags=["technology"]),
        _make_node(
            "Machine Learning", brief="Subset of AI", desc="Statistical learning algorithms", tags=["technology", "ai"]
        ),
        _make_node("Healthcare", brief="Medical and health services", tags=["domain"]),
        _make_node(
            "Neural Networks",
            brief="Deep learning architecture",
            desc="Layers of interconnected nodes for machine learning",
            tags=["technology", "ai"],
        ),
        _make_node("Coffee", brief="A popular beverage", tags=["lifestyle"]),
    ]


class TestTFIDFIndex:
    def test_build_from_nodes(self, sample_nodes):
        idx = TFIDFIndex()
        idx.build(sample_nodes)
        assert idx.is_built
        assert idx.doc_count == 5

    def test_search_relevant(self, sample_nodes):
        idx = TFIDFIndex()
        idx.build(sample_nodes)
        results = idx.search("machine learning")
        assert len(results) > 0
        # Machine Learning node should be top result
        assert results[0]["node"]["label"] == "Machine Learning"
        assert results[0]["score"] > 0

    def test_search_python(self, sample_nodes):
        idx = TFIDFIndex()
        idx.build(sample_nodes)
        results = idx.search("python programming")
        assert len(results) > 0
        assert results[0]["node"]["label"] == "Python"

    def test_search_healthcare(self, sample_nodes):
        idx = TFIDFIndex()
        idx.build(sample_nodes)
        results = idx.search("medical health")
        assert len(results) > 0
        assert results[0]["node"]["label"] == "Healthcare"

    def test_search_no_results(self, sample_nodes):
        idx = TFIDFIndex()
        idx.build(sample_nodes)
        results = idx.search("quantum computing blockchain")
        assert results == []

    def test_search_empty_query(self, sample_nodes):
        idx = TFIDFIndex()
        idx.build(sample_nodes)
        assert idx.search("") == []

    def test_search_stop_words_only(self, sample_nodes):
        idx = TFIDFIndex()
        idx.build(sample_nodes)
        assert idx.search("the and or") == []

    def test_search_limit(self, sample_nodes):
        idx = TFIDFIndex()
        idx.build(sample_nodes)
        results = idx.search("learning", limit=1)
        assert len(results) <= 1

    def test_search_min_score(self, sample_nodes):
        idx = TFIDFIndex()
        idx.build(sample_nodes)
        results = idx.search("learning", min_score=0.99)
        # Very high min_score should filter most results
        assert len(results) <= 2

    def test_clear(self, sample_nodes):
        idx = TFIDFIndex()
        idx.build(sample_nodes)
        assert idx.is_built
        idx.clear()
        assert not idx.is_built
        assert idx.doc_count == 0

    def test_search_before_build(self):
        idx = TFIDFIndex()
        assert idx.search("anything") == []

    def test_build_with_dicts(self):
        docs = [
            {"id": "a", "label": "Alpha", "brief": "First letter"},
            {"id": "b", "label": "Beta", "brief": "Second letter"},
        ]
        idx = TFIDFIndex()
        idx.build(docs)
        assert idx.doc_count == 2
        results = idx.search("alpha first")
        assert len(results) > 0
        assert results[0]["node"]["id"] == "a"

    def test_scores_decrease(self, sample_nodes):
        idx = TFIDFIndex()
        idx.build(sample_nodes)
        results = idx.search("deep learning neural")
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_label_boosting(self):
        """Label is weighted 3x, so nodes matching on label should rank higher."""
        docs = [
            {"id": "a", "label": "Python", "brief": "A language"},
            {"id": "b", "label": "Other Tool", "brief": "Uses python for scripting"},
            {"id": "c", "label": "Unrelated", "brief": "No match here at all"},
        ]
        idx = TFIDFIndex()
        idx.build(docs)
        results = idx.search("python")
        assert len(results) >= 2
        assert results[0]["node"]["id"] == "a"

    def test_aliases_are_indexed(self):
        docs = [
            {"id": "a", "label": "PostgreSQL", "aliases": ["postgres"], "brief": "Database"},
            {"id": "b", "label": "Redis", "brief": "Cache"},
        ]
        idx = TFIDFIndex()
        idx.build(docs)
        results = idx.search("postgres")
        assert results
        assert results[0]["node"]["id"] == "a"

    def test_rebuild_after_clear(self, sample_nodes):
        idx = TFIDFIndex()
        idx.build(sample_nodes)
        idx.clear()
        idx.build(sample_nodes[:2])
        assert idx.doc_count == 2

    def test_round_trip_serialization(self, sample_nodes):
        idx = TFIDFIndex()
        idx.build(sample_nodes)

        restored = TFIDFIndex.from_dict(idx.to_dict())

        assert restored.is_built
        assert restored.doc_count == idx.doc_count
        assert restored.search("machine learning") == idx.search("machine learning")


# ---------------------------------------------------------------------------
# CortexGraph integration
# ---------------------------------------------------------------------------


class TestGraphSemanticSearch:
    def test_semantic_search_method(self, sample_nodes):
        graph = CortexGraph()
        for n in sample_nodes:
            graph.add_node(n)
        results = graph.semantic_search("machine learning")
        assert len(results) > 0
        assert hasattr(results[0]["node"], "label")  # Returns Node objects

    def test_semantic_search_cached(self, sample_nodes):
        graph = CortexGraph()
        for n in sample_nodes:
            graph.add_node(n)
        # First search builds the index
        r1 = graph.semantic_search("python")
        # Second search uses the cached index
        r2 = graph.semantic_search("python")
        assert len(r1) == len(r2)

    def test_invalidation_on_add_node(self, sample_nodes):
        graph = CortexGraph()
        for n in sample_nodes:
            graph.add_node(n)
        graph.semantic_search("python")  # build index
        assert graph._search_index.is_built
        graph.add_node(_make_node("Rust", brief="Systems programming language"))
        assert not graph._search_index.is_built

    def test_invalidation_on_remove_node(self, sample_nodes):
        graph = CortexGraph()
        for n in sample_nodes:
            graph.add_node(n)
        graph.semantic_search("python")
        graph.remove_node(sample_nodes[0].id)
        assert not graph._search_index.is_built

    def test_invalidation_on_update_node(self, sample_nodes):
        graph = CortexGraph()
        for n in sample_nodes:
            graph.add_node(n)
        graph.semantic_search("python")
        graph.update_node(sample_nodes[0].id, {"brief": "Updated description"})
        assert not graph._search_index.is_built

    def test_empty_graph(self):
        graph = CortexGraph()
        results = graph.semantic_search("anything")
        assert results == []

    def test_alias_exact_match_boost(self):
        graph = CortexGraph()
        graph.add_node(Node(id="a", label="PostgreSQL", aliases=["postgres"], tags=["db"], confidence=0.9))
        graph.add_node(Node(id="b", label="Redis", tags=["db"], confidence=0.9))
        results = graph.semantic_search("postgres")
        assert results
        assert results[0]["node"].label == "PostgreSQL"
