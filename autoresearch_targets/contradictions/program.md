# Cortex Autoresearch Program: contradictions

## Goal
Improve contradiction detection quality by editing only `cortex/contradictions.py`.

## Editable Surface
- Editable file: `cortex/contradictions.py`
- Do not edit:
  - `autoresearch_targets/contradictions/eval.py`
  - `autoresearch_targets/contradictions/generate_corpus.py`
  - generated corpus files
  - graph or temporal helpers outside this file

## Corpus
The corpus covers:
- Negation conflicts
- Temporal confidence flips
- Source conflicts across nodes with the same label
- Tag conflicts across snapshots
- Clean graphs that should produce no contradictions
- Multi-conflict cases with several detector types at once

## Scoring
`contradictions_score` is a weighted average of:
- 80% exact-match detection F1
- 20% resolution accuracy for matched contradictions

## High-Leverage Hypotheses
- Better detector precision on clean graphs
- Better conflict deduplication
- Better use of snapshot ordering and metadata
- Better resistance to tiny confidence oscillations that should not count as real flips
- Better matching of source-level disagreement without false positives

## Rules For Each Experiment
1. Form exactly one hypothesis.
2. Change only `cortex/contradictions.py`.
3. Preserve the `Contradiction` schema and `ContradictionEngine.detect_all()` API.
4. Prefer general conflict logic over fixture-specific checks.
