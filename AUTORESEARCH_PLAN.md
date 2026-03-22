# CortexAI Autoresearch Setup Plan

## Goal
Set up Karpathy-style autoresearch for CortexAI so we can iteratively improve `cortex/extract_memory.py` against a fixed labeled corpus and track progress with a single scalar metric.

## Current Status
- Autoresearch bundle is already in repo root:
  - `autoresearch.py`
  - `program.md`
  - `eval.py`
  - `generate_corpus.py`
  - `AUTORESEARCH_README.md`
- Python 3.11 virtualenv is ready at `venv/`
- Generated corpus exists at `corpus/manifest.json`
- Baseline `extraction_score` is `0.4500`

## Setup Steps

### 1. Work from the autoresearch branch
- Use branch `codex/autoresearch-setup`
- Keep autoresearch changes isolated from `main` until the loop is stable

### 2. Use the repo-local Python 3.11 environment
```bash
cd /Users/marcsaint-jour/Desktop/Cortex-AI
source venv/bin/activate
python --version
cortex --help
```

### 3. Confirm required files exist
```bash
ls autoresearch.py program.md eval.py generate_corpus.py AUTORESEARCH_README.md
ls corpus/manifest.json
```

### 4. Regenerate corpus only if needed
- Skip this if `corpus/manifest.json` already exists and you want a stable benchmark
```bash
source venv/bin/activate
python generate_corpus.py
```

### 5. Establish or re-check baseline
```bash
source venv/bin/activate
python eval.py
python eval.py --quiet
```

## Operating Loop

### 6. Run autoresearch in manual mode
- This is the correct mode for Codex right now because `autoresearch.py` only automates `claude` or `manual`
```bash
source venv/bin/activate
python autoresearch.py
```

### 7. For each experiment
- Read `program.md`
- Form one hypothesis
- Edit only `cortex/extract_memory.py`
- Let `autoresearch.py` run evaluation
- Keep the change only if score improves
- Revert if score is flat or worse

### 8. Prioritize likely wins
- Near-duplicate deduplication
- Filler vs. signal filtering
- Recency weighting
- Implicit preference extraction
- Short entity categorization

## Validation

### 9. Use these checks during the loop
```bash
source venv/bin/activate
python eval.py
python eval.py --test test_06_near_duplicates
python eval.py --test test_09_filler_vs_signal
python eval.py --test test_10_preference_drift
```

### 10. Success criteria
- `extraction_score >= 0.92`
- No CLI regressions
- No schema changes to extracted context output
- Only `cortex/extract_memory.py` changes during experiments

## Repo Hygiene
- Keep generated artifacts local:
  - `corpus/`
  - `autoresearch_log.jsonl`
- Do not edit:
  - `eval.py`
  - `corpus/`
  - CLI interface or output schema
  - other core files outside `cortex/extract_memory.py`

## Recommended Next Move
Inspect why baseline recall is `0.0000` across all tests before running many experiments. That suggests the current extractor is not recognizing this synthetic corpus format yet, which is likely the first bottleneck to fix.
