# Extraction Eval Harness

Cortex keeps extraction quality gated by a small offline corpus in
`tests/extraction/corpus`. The eval command runs each case through one backend,
computes the extraction metrics, writes a JSON report, and compares aggregate
scores against `tests/extraction/corpus/baseline.json`.

## Run Locally

```bash
cortex extract eval \
  --corpus tests/extraction/corpus \
  --backend heuristic \
  --output extraction-eval-report.json
```

The command exits non-zero if any metric regresses by more than the default
tolerance of `0.01`. Use `--tolerance` to tighten or relax the gate for local
experiments.

Model and hybrid evals read Anthropic responses from the committed replay cache
under `tests/extraction/corpus/replay`:

```bash
CORTEX_EXTRACTION_REPLAY=read \
CORTEX_EXTRACTION_REPLAY_DIR=tests/extraction/corpus/replay \
cortex extract eval --backend model
```

## Rebaseline

Refresh the model replay cache when prompt text, schema shape, or corpus inputs
change, then update the committed baseline:

```bash
cortex extract refresh-cache && cortex extract eval --update-baseline
```

For a fully explicit refresh:

```bash
cortex extract refresh-cache \
  --corpus tests/extraction/corpus \
  --replay-dir tests/extraction/corpus/replay

cortex extract eval \
  --corpus tests/extraction/corpus \
  --backend heuristic \
  --output extraction-eval-report.json \
  --update-baseline
```

Review the changed `baseline.json`, replay files, and report before opening the
PR. Rebaselines should explain why the score movement is expected.

## CI Gate

The `extract-eval` GitHub Actions job runs after the test matrix. It uses
`CORTEX_EXTRACTION_REPLAY=read` and fails the workflow when any committed
baseline metric drops by more than `0.01`.
