# Cortex Autoresearch Program: search

## Goal
Improve semantic ranking quality by editing only `cortex/search.py`.

## Editable Surface
- Editable file: `cortex/search.py`
- Do not edit:
  - `autoresearch_targets/search/eval.py`
  - `autoresearch_targets/search/generate_corpus.py`
  - generated corpus files

## Corpus
The corpus focuses on ranking mistakes caused by compound labels and weak token normalization:
- camel-case and no-space product names like `GitHubCLI`
- compound API names like `OpenAPISpec`
- dense technical labels like `TimeSeriesDB`
- one positive-control plain-language search case

## Scoring
`search_score` combines:
- top-1 hit rate
- top-3 hit rate
- mean reciprocal rank (MRR)

## High-Leverage Hypotheses
- split compound labels into searchable subterms
- improve token normalization without hurting precision
- preserve strong label weighting while handling condensed technical names

## Rules For Each Experiment
1. Form exactly one hypothesis.
2. Change only `cortex/search.py`.
3. Preserve the public API of `tokenize()` and `TFIDFIndex.search()`.
