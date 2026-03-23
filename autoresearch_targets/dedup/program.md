# Cortex Autoresearch Program: dedup

## Goal
Improve duplicate detection and merge quality by editing only `cortex/dedup.py`.

## Editable Surface
- Editable file: `cortex/dedup.py`
- Do not edit:
  - `autoresearch_targets/dedup/eval.py`
  - `autoresearch_targets/dedup/generate_corpus.py`
  - generated corpus files

## Corpus
The corpus focuses on:
- alias handling like `K8s` vs `Kubernetes`
- abbreviation handling like `JS` vs `JavaScript`
- version suffixes and punctuation variants
- false-positive protection on superficially similar labels

## Scoring
`dedup_score` combines:
- duplicate-pair detection F1
- merge execution correctness after `deduplicate()`

## High-Leverage Hypotheses
- normalize common aliases before text similarity
- improve thresholds without causing false merges
- use graph context to rescue alias pairs that share neighbors

## Rules For Each Experiment
1. Form exactly one hypothesis.
2. Change only `cortex/dedup.py`.
3. Preserve the public APIs for `find_duplicates()` and `deduplicate()`.
