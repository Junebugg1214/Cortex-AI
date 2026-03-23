# Cortex Autoresearch Program: intelligence

## Goal
Improve gap detection and digest quality by editing only `cortex/intelligence.py`.

## Editable Surface
- Editable file: `cortex/intelligence.py`
- Do not edit:
  - `autoresearch_targets/intelligence/eval.py`
  - `autoresearch_targets/intelligence/generate_corpus.py`
  - generated corpus files

## Corpus
The corpus covers:
- stale-node detection from snapshots-only history
- confidence-gap detection for active priorities
- relationship-gap detection for disconnected groups
- digest quality for repeated vs genuinely new contradictions
- digest structural diffs for new nodes, removed nodes, and new edges

## Scoring
`intelligence_score` averages gap and digest case accuracy.

## High-Leverage Hypotheses
- treat snapshots-only nodes as stale when all evidence is old
- diff contradictions against the previous graph before calling them "new"
- preserve existing digest fields while improving precision

## Rules For Each Experiment
1. Form exactly one hypothesis.
2. Change only `cortex/intelligence.py`.
3. Preserve the public APIs for `GapAnalyzer` and `InsightGenerator.digest()`.
