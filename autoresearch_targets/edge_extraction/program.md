# Cortex Autoresearch Program: edge-extraction

## Goal
Improve graph edge discovery by editing only `cortex/edge_extraction.py`.

## Editable Surface
- Editable file: `cortex/edge_extraction.py`
- Do not edit:
  - `autoresearch_targets/edge_extraction/eval.py`
  - `autoresearch_targets/edge_extraction/generate_corpus.py`
  - generated corpus files
  - `cortex/graph.py` or other graph modules

## Corpus
The corpus covers:
- Rule-based typed edges for major category pairs
- Proximity-based `co_mentioned` edges
- Suppression of duplicates when a rule already explains the same pair
- Precision cases with distant mentions and pre-existing edges

## Scoring
`edge_extraction_score` is the mean exact-match F1 across the corpus cases.

## High-Leverage Hypotheses
- Better rule matching and duplicate suppression
- Safer proximity extraction around word boundaries and repeated labels
- Better handling of existing edges already in the graph
- Better directionality for typed relations without harming `co_mentioned`

## Rules For Each Experiment
1. Form exactly one hypothesis.
2. Change only `cortex/edge_extraction.py`.
3. Preserve the existing `Edge` schema and `discover_all_edges()` API.
4. Prefer general logic over special-casing fixture labels.
