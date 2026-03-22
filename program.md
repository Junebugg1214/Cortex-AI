# Cortex Autoresearch — Agent Program

## Objective

Improve `cortex/extract_memory.py` to maximize `extraction_score` on the
labeled evaluation corpus. The score measures three things:

1. **Recall** (50%) — are known entities, preferences, and projects extracted?
2. **Deduplication** (25%) — is the graph free of redundant near-duplicate nodes?
3. **Contradiction detection** (25%) — are seeded conflicts surfaced correctly?

Run `python eval.py` after every change to measure progress.
Commit improvements. Revert regressions.

---

## Evaluation

```bash
python eval.py           # Full breakdown
python eval.py --quiet   # Score only (for scripted loops)
python eval.py --test test_06_near_duplicates  # Single test
```

**Baseline**: record the score from your very first run before making any changes.
**Target**: extraction_score >= 0.92

---

## What You May Change

- Entity classification logic in `cortex/extract_memory.py`
- Node deduplication thresholds and string normalization
- Preference vs. conversational-filler disambiguation heuristics
- Category assignment for extracted nodes (technical_expertise,
  communication_preferences, active_projects, values, domain_knowledge, etc.)
- Confidence scoring for ambiguous extractions
- Recency weighting logic (later statements should override earlier ones)
- Contradiction detection sensitivity

---

## What You Must Not Change

- CLI interface (argument names, flags, output path behavior)
- The `context.json` output schema (node/edge structure must remain stable)
- `graph.py`, `contradictions.py`, `query.py`, `timeline.py` — these are fixed
- `eval.py` — modifying the evaluator invalidates all experiments
- `corpus/` — any change here invalidates the corpus
- Any file outside `cortex/extract_memory.py`

---

## Experiment Discipline

One hypothesis per experiment. State it in the commit message before running eval.

Template:
```
exp N: [hypothesis] — score X.XXXX (delta +/-X.XXXX)
```

Example:
```
exp 7: normalize node labels to lowercase before dedup — score 0.7812 (+0.0340)
```

If the score drops or stays flat: `git checkout cortex/extract_memory.py`, log the result, move on.

---

## Known Weak Areas — Explore These First

These are ordered by likely impact:

1. **Near-duplicate deduplication** (test_06)
   - "Python", "python3", "Python 3.11", "py" are the same entity
   - Current dedup is case-sensitive and exact-match only
   - Fix: normalize labels (lowercase, strip version suffixes, stem) before comparison

2. **Filler vs. signal disambiguation** (test_09)
   - Speculative mentions ("I feel like I should try Rust") are not preferences
   - Hedged language ("maybe", "I guess", "not sure if") should suppress extraction
   - Fix: add hedge-phrase detection; lower confidence on speculative mentions

3. **Recency weighting for contradictions** (test_10)
   - When preferences evolve, the final stated preference should dominate
   - Current behavior may average or concatenate conflicting preferences
   - Fix: timestamp-aware node updates; later statements supersede earlier

4. **Implicit preference extraction** (test_05)
   - Preferences stated as refusals ("I don't use type hints") should be captured
   - Negative statements ("no external libraries") are real preferences
   - Fix: negation-aware extraction patterns

5. **Short entity categorization** (test_03, test_07)
   - Single-word technical entities ("CLI", "API", "IRB") are inconsistently categorized
   - Fix: expand category assignment heuristics for known short-form terms

6. **Cross-turn coreference** (test_01)
   - "I deploy on Linux, always" should link to environment, not just be a raw node
   - Fix: coreference resolution across turns before extraction

---

## Stopping Criteria

Stop and report when any of the following is true:

- `extraction_score >= 0.92` — target reached
- 50 experiments completed with no improvement in last 10 consecutive runs
- CLI returns non-zero exit code on any corpus file (regression in stability)
- A change causes `cortex stats` output to become malformed

---

## Logging

Append each experiment result to `autoresearch_log.jsonl`:

```json
{
  "experiment": 1,
  "timestamp": "2026-03-22T14:00:00",
  "hypothesis": "normalize labels to lowercase before dedup",
  "score": 0.7812,
  "delta": 0.034,
  "kept": true
}
```

---

## Observations from Corpus Design

The 10 test cases are stratified to cover distinct failure modes:

| Test | Primary Signal | Failure Mode Tested |
|------|---------------|---------------------|
| test_01 | Technical stack | Basic entity recall |
| test_02 | Communication style | Preference extraction |
| test_03 | Projects + domain | Multi-category extraction |
| test_04 | Contradictions | Conflict detection |
| test_05 | Implicit preferences | Negation-aware extraction |
| test_06 | Near-duplicates | Deduplication precision |
| test_07 | Professional identity | Role/career extraction |
| test_08 | Values | Abstract concept extraction |
| test_09 | Filler vs. signal | False positive rate |
| test_10 | Preference drift | Recency weighting |

A change that improves test_01 may regress test_09. Check the full corpus
score, not just individual test improvements.
