# Cortex Autoresearch

Applies Karpathy's autoresearch pattern to `cortex/extract_memory.py`.
An agent iterates on extraction logic overnight, scored against a labeled corpus.

## Files

| File | Purpose |
|------|---------|
| `generate_corpus.py` | Generates 10 labeled test conversations with ground truth |
| `eval.py` | Computes `extraction_score` (0.0–1.0) across the corpus |
| `program.md` | Agent instructions: what to change, what not to touch, stopping criteria |
| `autoresearch.py` | Loop runner: eval → commit or revert → repeat |

## Quickstart

```bash
# 1. From your Cortex-AI repo root, copy these files in
cp generate_corpus.py eval.py program.md autoresearch.py .

# 2. Install Cortex in dev mode if not already
pip install -e ".[dev]"

# 3. Generate the labeled corpus
python generate_corpus.py

# 4. Run eval to establish your baseline
python eval.py

# 5. Start the loop (manual mode — you or an agent applies each change)
python autoresearch.py

# Or with Claude Code as the agent
python autoresearch.py --agent claude
```

## The Three Primitives

| Primitive | CortexAI Implementation |
|-----------|------------------------|
| Editable artifact | `cortex/extract_memory.py` |
| Scalar metric | `extraction_score` (recall + dedup + contradiction detection) |
| Time-boxed cycle | ~10 seconds per eval run on the labeled corpus |

## Scoring Breakdown

```
extraction_score = 0.50 × recall
                 + 0.25 × dedup_score
                 + 0.25 × contradiction_detection
```

- **Recall**: fraction of known entities/preferences recovered from labeled conversations
- **Dedup score**: penalizes near-duplicate nodes (Python/python3/py → should be one node)
- **Contradiction detection**: rewards surfacing seeded conflicts in test cases

## Corpus: 10 Labeled Test Cases

| Test | What It Measures |
|------|-----------------|
| test_01_technical_preferences | Basic entity recall — tech stack |
| test_02_communication_style | Preference extraction |
| test_03_projects_and_domain | Multi-category extraction |
| test_04_contradictions | Conflict detection (seeded) |
| test_05_implicit_preferences | Negation-aware extraction |
| test_06_near_duplicates | Deduplication precision |
| test_07_professional_identity | Role and career extraction |
| test_08_values_working_style | Abstract concept extraction |
| test_09_filler_vs_signal | False positive rate |
| test_10_preference_drift | Recency weighting |

## Known Weak Areas (Start Here)

From `program.md`, ordered by likely impact:

1. **Near-duplicate dedup** — "Python" / "python3" / "py" should collapse to one node
2. **Filler vs. signal** — speculative mentions ("maybe I'll try Rust") should not be extracted
3. **Recency weighting** — later preference statements should override earlier ones
4. **Implicit preferences** — "I don't use type hints" is a preference, not just negation
5. **Short entity categorization** — "CLI", "API" inconsistently categorized

## Experiment Log

Each run appends to `autoresearch_log.jsonl`:

```json
{"experiment": 7, "timestamp": "...", "hypothesis": "normalize labels to lowercase", "score": 0.7812, "delta": 0.034, "kept": true}
```

## Target

`extraction_score >= 0.92`

Karpathy's overnight run on nanochat produced ~12 experiments/hour.
At ~10 seconds/eval, Cortex autoresearch runs ~360 experiments/hour.
