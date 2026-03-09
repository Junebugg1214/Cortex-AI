"""
TF-IDF semantic search engine for the Cortex knowledge graph.

Provides relevance-ranked search across node text fields using
term frequency–inverse document frequency cosine similarity.
Stdlib-only — no external dependencies.

Usage::

    from cortex.search import TFIDFIndex

    index = TFIDFIndex()
    index.build(graph.nodes.values())
    results = index.search("machine learning", limit=10)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

# ---------------------------------------------------------------------------
# Stop words — common English words to exclude from indexing
# ---------------------------------------------------------------------------

STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "aren't",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "can't",
        "cannot",
        "could",
        "couldn't",
        "did",
        "didn't",
        "do",
        "does",
        "doesn't",
        "doing",
        "don't",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "get",
        "got",
        "had",
        "hadn't",
        "has",
        "hasn't",
        "have",
        "haven't",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "isn't",
        "it",
        "it's",
        "its",
        "itself",
        "just",
        "let's",
        "me",
        "might",
        "more",
        "most",
        "mustn't",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "ought",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "shan't",
        "she",
        "should",
        "shouldn't",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "wasn't",
        "we",
        "were",
        "weren't",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "won't",
        "would",
        "wouldn't",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
    }
)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    """Lowercase, split into alphanumeric tokens, remove stop words."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOP_WORDS]


# ---------------------------------------------------------------------------
# TF-IDF Index
# ---------------------------------------------------------------------------


class TFIDFIndex:
    """In-memory TF-IDF index over node text fields.

    Build once, search many times.  Invalidate (``clear()``) on graph mutation
    and rebuild lazily.
    """

    def __init__(self) -> None:
        # doc_id -> term frequency vector (Counter)
        self._tf: dict[str, Counter] = {}
        # term -> number of documents containing it
        self._df: Counter = Counter()
        # doc_id -> L2 norm of TF-IDF vector
        self._norms: dict[str, float] = {}
        # total documents
        self._n: int = 0
        # doc_id -> node dict (for returning results)
        self._docs: dict[str, dict] = {}
        self._built = False

    @property
    def is_built(self) -> bool:
        return self._built

    @property
    def doc_count(self) -> int:
        return self._n

    def build(self, nodes: Iterable) -> None:
        """Build the index from an iterable of Node objects (or dicts).

        Indexes: label, brief, full_description, and string property values.
        """
        self.clear()

        for node in nodes:
            if hasattr(node, "to_dict"):
                d = node.to_dict()
            else:
                d = dict(node)

            doc_id = d.get("id", "")
            if not doc_id:
                continue

            # Collect all text fields
            parts: list[str] = []
            if d.get("label"):
                # Weight label 3x
                parts.extend([d["label"]] * 3)
            if d.get("brief"):
                parts.append(d["brief"])
            if d.get("full_description"):
                parts.append(d["full_description"])
            for v in (d.get("properties") or {}).values():
                if isinstance(v, str):
                    parts.append(v)
            for tag in d.get("tags", []):
                parts.append(tag)

            text = " ".join(parts)
            tokens = tokenize(text)
            if not tokens:
                continue

            tf = Counter(tokens)
            self._tf[doc_id] = tf
            self._docs[doc_id] = d

            for term in tf:
                self._df[term] += 1

        self._n = len(self._tf)

        # Precompute L2 norms
        for doc_id, tf in self._tf.items():
            norm_sq = 0.0
            for term, count in tf.items():
                tfidf = self._tfidf(term, count)
                norm_sq += tfidf * tfidf
            self._norms[doc_id] = math.sqrt(norm_sq) if norm_sq > 0 else 1.0

        self._built = True

    def clear(self) -> None:
        """Clear the index."""
        self._tf.clear()
        self._df.clear()
        self._norms.clear()
        self._docs.clear()
        self._n = 0
        self._built = False

    def search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[dict]:
        """Search for nodes matching the query.

        Returns a list of dicts: ``{"node": <node_dict>, "score": <float>}``
        sorted by descending relevance score.
        """
        if not self._built or not query:
            return []

        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        q_tf = Counter(q_tokens)

        # Query vector norm
        q_norm_sq = 0.0
        for term, count in q_tf.items():
            w = self._tfidf(term, count)
            q_norm_sq += w * w
        q_norm = math.sqrt(q_norm_sq) if q_norm_sq > 0 else 1.0

        # Score each document
        scores: list[tuple[str, float]] = []
        for doc_id, tf in self._tf.items():
            dot = 0.0
            for term, q_count in q_tf.items():
                if term in tf:
                    q_w = self._tfidf(term, q_count)
                    d_w = self._tfidf(term, tf[term])
                    dot += q_w * d_w
            if dot <= 0:
                continue
            cos_sim = dot / (q_norm * self._norms[doc_id])
            if cos_sim >= min_score:
                scores.append((doc_id, cos_sim))

        # Sort by score descending, then by doc_id for stability
        scores.sort(key=lambda x: (-x[1], x[0]))

        results = []
        for doc_id, score in scores[:limit]:
            results.append({"node": self._docs[doc_id], "score": round(score, 4)})
        return results

    def _tfidf(self, term: str, tf_count: int) -> float:
        """Compute TF-IDF weight for a term."""
        if self._n == 0:
            return 0.0
        df = self._df.get(term, 0)
        if df == 0:
            return 0.0
        tf = 1 + math.log(tf_count) if tf_count > 0 else 0.0
        idf = math.log(self._n / df)
        return tf * idf
