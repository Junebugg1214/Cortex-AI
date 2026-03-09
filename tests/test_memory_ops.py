from cortex.graph import CortexGraph, Edge, Node, make_edge_id, make_node_id
from cortex.memory_ops import (
    forget_nodes,
    list_memory_conflicts,
    resolve_memory_conflict,
    set_memory_node,
    show_memory_nodes,
)


def _graph_with_nodes() -> CortexGraph:
    graph = CortexGraph()
    python_id = make_node_id("Python")
    pytest_id = make_node_id("Pytest")
    graph.add_node(Node(id=python_id, label="Python", tags=["technical_expertise"], confidence=0.9))
    graph.add_node(Node(id=pytest_id, label="Pytest", tags=["technical_expertise"], confidence=0.8))
    graph.add_edge(
        Edge(
            id=make_edge_id(python_id, pytest_id, "used_with"),
            source_id=python_id,
            target_id=pytest_id,
            relation="used_with",
        )
    )
    return graph


def test_show_memory_nodes_by_label():
    graph = _graph_with_nodes()
    nodes = show_memory_nodes(graph, label="Python")
    assert len(nodes) == 1
    assert nodes[0]["label"] == "Python"


def test_show_memory_nodes_by_tag():
    graph = _graph_with_nodes()
    nodes = show_memory_nodes(graph, tag="technical_expertise")
    assert len(nodes) == 2


def test_forget_node_by_id_removes_edges():
    graph = _graph_with_nodes()
    result = forget_nodes(graph, node_id=make_node_id("Python"))
    assert result["nodes_removed"] == 1
    assert make_node_id("Python") not in graph.nodes
    assert len(graph.edges) == 0


def test_forget_nodes_by_label():
    graph = _graph_with_nodes()
    result = forget_nodes(graph, label="Pytest")
    assert result["nodes_removed"] == 1
    assert make_node_id("Pytest") not in graph.nodes


def test_forget_nodes_by_tag():
    graph = _graph_with_nodes()
    result = forget_nodes(graph, tag="technical_expertise")
    assert result["nodes_removed"] == 2
    assert not graph.nodes


def test_set_memory_node_creates_new():
    graph = CortexGraph()
    result = set_memory_node(
        graph,
        label="Response Style",
        tags=["communication_preferences"],
        brief="Prefers concise answers",
    )
    assert result["created"] is True
    assert graph.find_nodes(label="Response Style")


def test_set_memory_node_updates_existing():
    graph = CortexGraph()
    graph.add_node(Node(id=make_node_id("Python"), label="Python", tags=["mentions"], confidence=0.5))
    result = set_memory_node(
        graph,
        label="Python",
        tags=["technical_expertise"],
        brief="Primary backend language",
        confidence=0.95,
    )
    assert result["updated"] is True
    node = graph.find_nodes(label="Python")[0]
    assert "technical_expertise" in node.tags
    assert node.brief == "Primary backend language"


def test_list_memory_conflicts_returns_ids():
    graph = CortexGraph()
    graph.add_node(Node(id=make_node_id("Rust"), label="Rust", tags=["technical_expertise", "negations"]))
    conflicts = list_memory_conflicts(graph)
    assert conflicts
    assert conflicts[0].id


def test_resolve_memory_conflict_ignore():
    graph = CortexGraph()
    graph.add_node(Node(id=make_node_id("Rust"), label="Rust", tags=["technical_expertise", "negations"]))
    conflict_id = list_memory_conflicts(graph)[0].id
    result = resolve_memory_conflict(graph, conflict_id, "ignore")
    assert result["status"] == "ok"


def test_resolve_memory_conflict_unknown_id():
    graph = CortexGraph()
    result = resolve_memory_conflict(graph, "missing", "ignore")
    assert result["status"] == "error"
    assert result["error"] == "conflict_not_found"


def test_resolve_tag_conflict_accept_new():
    graph = CortexGraph()
    node = Node(
        id=make_node_id("Java"),
        label="Java",
        tags=["technical_expertise"],
        snapshots=[
            {"timestamp": "2025-01-01T00:00:00Z", "tags": ["technical_expertise"]},
            {"timestamp": "2025-02-01T00:00:00Z", "tags": ["negations"]},
        ],
    )
    graph.add_node(node)
    conflict = list_memory_conflicts(graph)[0]
    result = resolve_memory_conflict(graph, conflict.id, "accept-new")
    assert result["status"] == "ok"
    assert "negations" in graph.get_node(node.id).tags


def test_resolve_temporal_flip_accept_new():
    graph = CortexGraph()
    node = Node(
        id=make_node_id("Python"),
        label="Python",
        tags=["technical_expertise"],
        snapshots=[
            {"timestamp": "2025-01-01T00:00:00Z", "confidence": 0.2, "tags": ["technical_expertise"]},
            {"timestamp": "2025-02-01T00:00:00Z", "confidence": 0.8, "tags": ["technical_expertise"]},
            {"timestamp": "2025-03-01T00:00:00Z", "confidence": 0.3, "tags": ["technical_expertise"]},
            {"timestamp": "2025-04-01T00:00:00Z", "confidence": 0.9, "tags": ["technical_expertise"]},
        ],
    )
    graph.add_node(node)
    conflict = next(item for item in list_memory_conflicts(graph) if item.type == "temporal_flip")
    result = resolve_memory_conflict(graph, conflict.id, "accept-new")
    assert result["status"] == "ok"
    assert graph.get_node(node.id).confidence == 0.9


def test_resolve_source_conflict_merge():
    graph = CortexGraph()
    node_a = Node(
        id=make_node_id("Go"),
        label="Go",
        tags=["technical_expertise"],
        confidence=0.7,
        snapshots=[{"timestamp": "2025-01-01T00:00:00Z", "source": "a", "description_hash": "h1"}],
        source_quotes=["older quote"],
    )
    node_b = Node(
        id=make_node_id("Go") + "x",
        label="Go",
        tags=["domain_knowledge"],
        confidence=0.9,
        snapshots=[{"timestamp": "2025-02-01T00:00:00Z", "source": "b", "description_hash": "h2"}],
        source_quotes=["newer quote"],
    )
    graph.add_node(node_a)
    graph.add_node(node_b)
    conflict = next(item for item in list_memory_conflicts(graph) if item.type == "source_conflict")
    result = resolve_memory_conflict(graph, conflict.id, "merge")
    assert result["status"] == "ok"
    assert len(graph.find_nodes(label="Go")) == 1
