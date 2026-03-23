# Cortex Autoresearch Program: extract-coding

## Goal
Improve behavioral extraction quality for coding sessions by editing only `cortex/coding.py`.

## Editable Surface
- Editable file: `cortex/coding.py`
- Do not edit:
  - `autoresearch_targets/extract_coding/eval.py`
  - `autoresearch_targets/extract_coding/generate_corpus.py`
  - generated corpus files
  - other Cortex modules

## Corpus
The synthetic corpus covers:
- Python planning and test-writing behavior
- TypeScript and Node project extraction
- Infra/devops sessions with Docker, Kubernetes, and AWS CLI
- Multi-session aggregation
- Manifest/license enrichment for Cargo and pyproject projects
- Sparse-session precision cases with minimal signals

## Scoring
`coding_extraction_score` is a weighted average of:
- 55% expected topic recall by category
- 25% enrichment/detail recall from brief/full_description/metrics
- 20% precision on forbidden topics

## High-Leverage Hypotheses
- Better tool_use parsing for Claude Code records
- Stronger file-path to technology mapping
- Better aggregation across multiple sessions
- Better project enrichment from README, manifest, CI, Docker, and license files
- Better plan-mode and test-writing inference
- Better support for modern tooling signals such as `uv` and React/TSX test files
- Better precision for sparse sessions that should not grow extra topics

## Rules For Each Experiment
1. Form exactly one hypothesis.
2. Change only `cortex/coding.py`.
3. Prefer small, local improvements over big rewrites.
4. Preserve the output schema from `session_to_context()`.
5. Do not overfit to one case by adding one-off strings for a single fixture name.

## Exit Condition
The target runner advances when the score goal is reached or the no-improvement limit is hit.
