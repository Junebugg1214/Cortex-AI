"""
Cortex Query Language — simple DSL for the knowledge graph.

Read-only queries.  Supports four statement types::

    FIND nodes WHERE tag = "identity" AND confidence >= 0.9 LIMIT 10
    NEIGHBORS OF "Python"
    PATH FROM "source-id" TO "target-id"
    SEARCH "machine learning"

Grammar (simplified EBNF)::

    statement   = find_stmt | neighbors_stmt | path_stmt | search_stmt
    find_stmt   = "FIND" "nodes" [ "WHERE" condition { "AND" condition } ] [ "LIMIT" INT ]
    condition   = field OP value
    field       = IDENT ( "." IDENT )*
    OP          = "=" | "!=" | ">=" | "<=" | ">" | "<" | "CONTAINS"
    value       = STRING | NUMBER
    neighbors   = "NEIGHBORS" "OF" STRING
    path_stmt   = "PATH" "FROM" STRING "TO" STRING
    search_stmt = "SEARCH" STRING [ "LIMIT" INT ]

Usage::

    from cortex.graph.query_lang import execute_query

    results = execute_query(graph, 'FIND nodes WHERE tag = "tech" LIMIT 5')
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cortex.graph.graph import CortexGraph

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""(?x)
    (?P<STRING>"[^"]*")
    | (?P<NUMBER>-?\d+(?:\.\d+)?)
    | (?P<OP>>=|<=|!=|>|<|=)
    | (?P<WORD>[A-Za-z_][\w\-.]*)
    """
)


def _tokenize(query: str) -> list[tuple[str, str]]:
    """Return a list of (token_type, value) tuples."""
    tokens: list[tuple[str, str]] = []
    for m in _TOKEN_RE.finditer(query):
        if m.group("STRING"):
            tokens.append(("STRING", m.group("STRING").strip('"')))
        elif m.group("NUMBER"):
            tokens.append(("NUMBER", m.group("NUMBER")))
        elif m.group("OP"):
            tokens.append(("OP", m.group("OP")))
        elif m.group("WORD"):
            tokens.append(("WORD", m.group("WORD").upper()))
    return tokens


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------


class FindQuery:
    """FIND nodes [WHERE ...] [LIMIT n]"""

    def __init__(self) -> None:
        self.conditions: list[tuple[str, str, Any]] = []  # (field, op, value)
        self.limit: int = 100


class NeighborsQuery:
    """NEIGHBORS OF "node-label-or-id" """

    def __init__(self, target: str) -> None:
        self.target = target


class PathQuery:
    """PATH FROM "source" TO "target" """

    def __init__(self, source: str, target: str) -> None:
        self.source = source
        self.target = target


class SearchQuery:
    """SEARCH "query text" [LIMIT n]"""

    def __init__(self, query_text: str, limit: int = 10) -> None:
        self.query_text = query_text
        self.limit = limit


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class ParseError(Exception):
    """Raised when the query cannot be parsed."""


class _Parser:
    """Simple recursive-descent parser for the query DSL."""

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> tuple[str, str] | None:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _advance(self) -> tuple[str, str]:
        if self._pos >= len(self._tokens):
            raise ParseError("Unexpected end of query")
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, ttype: str, value: str | None = None) -> tuple[str, str]:
        tok = self._advance()
        if tok[0] != ttype or (value is not None and tok[1] != value):
            expected = f"{ttype}({value})" if value else ttype
            raise ParseError(f"Expected {expected}, got {tok[0]}({tok[1]})")
        return tok

    def _match(self, ttype: str, value: str | None = None) -> tuple[str, str] | None:
        tok = self._peek()
        if tok and tok[0] == ttype and (value is None or tok[1] == value):
            return self._advance()
        return None

    def parse(self) -> FindQuery | NeighborsQuery | PathQuery | SearchQuery:
        tok = self._peek()
        if tok is None:
            raise ParseError("Empty query")

        keyword = tok[1] if tok[0] == "WORD" else ""

        if keyword == "FIND":
            return self._parse_find()
        elif keyword == "NEIGHBORS":
            return self._parse_neighbors()
        elif keyword == "PATH":
            return self._parse_path()
        elif keyword == "SEARCH":
            return self._parse_search()
        else:
            raise ParseError(f"Unknown statement type: {tok[1]}")

    def _parse_find(self) -> FindQuery:
        self._expect("WORD", "FIND")
        self._expect("WORD", "NODES")
        q = FindQuery()

        if self._match("WORD", "WHERE"):
            q.conditions.append(self._parse_condition())
            while self._match("WORD", "AND"):
                q.conditions.append(self._parse_condition())

        if self._match("WORD", "LIMIT"):
            _, val = self._expect("NUMBER")
            q.limit = int(val)

        return q

    def _parse_condition(self) -> tuple[str, str, Any]:
        _, field = self._advance()  # field name
        field = field.lower()
        _, op = self._expect("OP")
        val_tok = self._advance()
        if val_tok[0] == "STRING":
            value: Any = val_tok[1]
        elif val_tok[0] == "NUMBER":
            value = float(val_tok[1]) if "." in val_tok[1] else int(val_tok[1])
        elif val_tok[0] == "WORD":
            # Handle CONTAINS as operator (re-interpret)
            # For simplicity, treat unquoted words as strings
            value = val_tok[1].lower()
        else:
            raise ParseError(f"Expected value, got {val_tok}")
        return (field, op, value)

    def _parse_neighbors(self) -> NeighborsQuery:
        self._expect("WORD", "NEIGHBORS")
        self._expect("WORD", "OF")
        _, target = self._expect("STRING")
        return NeighborsQuery(target)

    def _parse_path(self) -> PathQuery:
        self._expect("WORD", "PATH")
        self._expect("WORD", "FROM")
        _, source = self._expect("STRING")
        self._expect("WORD", "TO")
        _, target = self._expect("STRING")
        return PathQuery(source, target)

    def _parse_search(self) -> SearchQuery:
        self._expect("WORD", "SEARCH")
        _, query_text = self._expect("STRING")
        limit = 10
        if self._match("WORD", "LIMIT"):
            _, val = self._expect("NUMBER")
            limit = int(val)
        return SearchQuery(query_text, limit)


def parse_query(query: str) -> FindQuery | NeighborsQuery | PathQuery | SearchQuery:
    """Parse a query string into an AST node."""
    tokens = _tokenize(query)
    if not tokens:
        raise ParseError("Empty query")
    parser = _Parser(tokens)
    return parser.parse()


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def _match_condition(node_dict: dict, field: str, op: str, value: Any) -> bool:
    """Check if a node dict matches a single condition."""
    # Special handling for 'tag' field — check if value is in tags list
    if field == "tag" and isinstance(node_dict.get("tags"), list):
        if op == "=":
            return value in node_dict["tags"]
        elif op == "!=":
            return value not in node_dict["tags"]
        return False

    # Handle dotted field access (e.g. properties.name)
    parts = field.split(".")
    obj: Any = node_dict
    for part in parts:
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return False
    if obj is None:
        return False

    # Comparison
    if op == "=":
        if isinstance(obj, (int, float)) and isinstance(value, (int, float)):
            return obj == value
        return str(obj).lower() == str(value).lower()
    elif op == "!=":
        return str(obj).lower() != str(value).lower()
    elif op in (">=", "<=", ">", "<"):
        try:
            obj_f, val_f = float(obj), float(value)
        except (ValueError, TypeError):
            return False  # Non-numeric comparison fails
        if op == ">=":
            return obj_f >= val_f
        elif op == "<=":
            return obj_f <= val_f
        elif op == ">":
            return obj_f > val_f
        else:  # op == "<"
            return obj_f < val_f
    return False


def _resolve_node_id(graph: CortexGraph, label_or_id: str) -> str | None:
    """Resolve a label or ID to a node ID."""
    if label_or_id in graph.nodes:
        return label_or_id
    matches = graph.find_node_ids_by_label(label_or_id)
    return matches[0] if matches else None


def execute_query(
    graph: CortexGraph,
    query: str,
) -> dict[str, Any]:
    """Parse and execute a query against the graph.

    Returns a dict with query-type-specific results:
    - FIND: ``{"type": "find", "nodes": [...], "count": N}``
    - NEIGHBORS: ``{"type": "neighbors", "node_id": ..., "neighbors": [...]}``
    - PATH: ``{"type": "path", "path": [...], "length": N}``
    - SEARCH: ``{"type": "search", "results": [...], "count": N}``
    """
    ast = parse_query(query)

    if isinstance(ast, FindQuery):
        return _exec_find(graph, ast)
    elif isinstance(ast, NeighborsQuery):
        return _exec_neighbors(graph, ast)
    elif isinstance(ast, PathQuery):
        return _exec_path(graph, ast)
    elif isinstance(ast, SearchQuery):
        return _exec_search(graph, ast)
    else:
        raise ParseError(f"Unknown query type: {type(ast)}")


def _exec_find(graph: CortexGraph, q: FindQuery) -> dict:
    results = []
    for node in graph.nodes.values():
        d = node.to_dict()
        if all(_match_condition(d, f, op, v) for f, op, v in q.conditions):
            results.append(d)
        if len(results) >= q.limit:
            break
    return {"type": "find", "nodes": results, "count": len(results)}


def _exec_neighbors(graph: CortexGraph, q: NeighborsQuery) -> dict:
    node_id = _resolve_node_id(graph, q.target)
    if node_id is None:
        return {"type": "neighbors", "node_id": None, "neighbors": [], "error": f"Node not found: {q.target}"}
    pairs = graph.get_neighbors(node_id)
    neighbors = [{"edge": e.to_dict(), "node": n.to_dict()} for e, n in pairs]
    return {"type": "neighbors", "node_id": node_id, "neighbors": neighbors}


def _exec_path(graph: CortexGraph, q: PathQuery) -> dict:
    source_id = _resolve_node_id(graph, q.source)
    target_id = _resolve_node_id(graph, q.target)
    if source_id is None:
        return {"type": "path", "path": [], "length": 0, "error": f"Source not found: {q.source}"}
    if target_id is None:
        return {"type": "path", "path": [], "length": 0, "error": f"Target not found: {q.target}"}
    path = graph.shortest_path(source_id, target_id)
    return {"type": "path", "path": path, "length": len(path)}


def _exec_search(graph: CortexGraph, q: SearchQuery) -> dict:
    results = []
    if hasattr(graph, "semantic_search"):
        semantic_results = graph.semantic_search(q.query_text, limit=q.limit)
        for item in semantic_results:
            node = item.get("node")
            if hasattr(node, "to_dict"):
                results.append(node.to_dict())
            elif isinstance(node, dict):
                results.append(node)
    if not results:
        results = [n.to_dict() for n in graph.search_nodes(q.query_text, limit=q.limit)]
    return {
        "type": "search",
        "results": results,
        "count": len(results),
    }
