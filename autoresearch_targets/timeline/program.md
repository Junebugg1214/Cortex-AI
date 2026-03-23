# Cortex Autoresearch Program: timeline

## Goal
Improve timeline event extraction, ordering, and timestamp normalization by editing only `cortex/timeline.py`.

## Editable Surface
- Editable file: `cortex/timeline.py`
- Do not edit:
  - `autoresearch_targets/timeline/eval.py`
  - `autoresearch_targets/timeline/generate_corpus.py`
  - generated corpus files

## Corpus
The corpus stresses:
- date-only timestamps that should normalize to UTC midnight
- timezone-offset timestamps that must be ordered correctly
- snapshot timestamps that should normalize consistently
- range filtering after normalization, not before

## Scoring
`timeline_score` is a weighted average of:
- 45% event recall/precision
- 25% event ordering accuracy
- 30% timestamp normalization accuracy

## High-Leverage Hypotheses
- normalize timestamps before sorting and filtering
- normalize offsets and date-only strings to a single canonical UTC format
- preserve event recall while avoiding duplicate synthetic events

## Rules For Each Experiment
1. Form exactly one hypothesis.
2. Change only `cortex/timeline.py`.
3. Preserve the public API for `TimelineGenerator.generate()`, `to_markdown()`, and `to_html()`.
