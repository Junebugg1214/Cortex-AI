# Cortex Autoresearch Program: query-mapping

## Goal
Improve natural-language query mapping and DSL execution relevance by editing only:
- `cortex/query.py`
- `cortex/query_lang.py`

## Editable Surface
- Editable files:
  - `cortex/query.py`
  - `cortex/query_lang.py`
- Do not edit:
  - `autoresearch_targets/query_mapping/eval.py`
  - `autoresearch_targets/query_mapping/generate_corpus.py`
  - generated corpus files

## Corpus
The corpus covers:
- natural-language category queries like "show my tech stack"
- natural-language path/related/change queries
- DSL parse intent checks
- DSL `SEARCH` relevance on compound labels

## Scoring
`query_mapping_score` averages:
- exact-match AST intent parsing for the DSL
- natural-language intent recognition
- result relevance for NL and DSL execution

## High-Leverage Hypotheses
- broaden NL pattern coverage beyond the current three regexes
- route DSL `SEARCH` through better relevance instead of substring-only matching
- keep output shapes stable while improving query understanding

## Rules For Each Experiment
1. Form exactly one hypothesis.
2. Change only `cortex/query.py` and/or `cortex/query_lang.py`.
3. Preserve the public APIs for `parse_nl_query()`, `parse_query()`, and `execute_query()`.
