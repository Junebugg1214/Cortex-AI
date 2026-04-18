# Cortex Configuration

Cortex reads configuration from three layers, in this order:

1. Environment variables
2. `config.toml`
   Cortex now discovers `~/.cortex/config.toml` when no explicit store or config path is supplied.
3. Hardcoded defaults in the codebase

## Core paths

- `CORTEX_CONFIG`
  Explicit `config.toml` path.
- `CORTEX_STORE_DIR`
  Explicit store directory.
- `CORTEX_CONTEXT_FILE`
  Default context graph file path.

## Extraction backends

- `CORTEX_HOT_PATH_BACKEND`
  Values: `heuristic` (default), `model`, `hybrid`.
  Warning: `model` makes every `cortex mind remember` call network-latency-bound.
  `embedding` is roadmap only — it currently raises `NotImplementedError`; do not enable it.
- `CORTEX_BULK_BACKEND`
  Values: `model` (default if an API key is configured and the Anthropic client is installed), `heuristic`.
  `embedding` is roadmap only — it currently raises `NotImplementedError`; do not enable it.
- `CORTEX_ANTHROPIC_API_KEY`
  API key for `ModelBackend`.
  Falls back to `ANTHROPIC_API_KEY` if not set.
- `CORTEX_HYBRID_RESCORE_WORKERS`
  Integer. Default: `4`.
  Maximum background threads used by `HybridBackend` rescoring.
- `CORTEX_EMBEDDING_MATCH_THRESHOLD`
  Float. Default: `0.92`.
  Cosine similarity threshold for `EmbeddingBackend.canonical_match_by_similarity()`.
  Has no effect until `EmbeddingBackend` is implemented.
- `EmbeddingBackend`
  Long-term replacement target for both the heuristic extractor and `ModelBackend` canonical matching.
  Intended backbone: LLM-JEPA ([arXiv:2509.14252](https://arxiv.org/abs/2509.14252)).
  Once implemented, it will provide semantic extraction in representation space and vector-similarity deduplication without per-call generative API costs.

## Server runtime

- `CORTEX_SERVER_HOST`
  Bind host. Default: `127.0.0.1`
- `CORTEX_SERVER_PORT`
  Bind port. Default: `8766`
- `CORTEX_EXTERNAL_BASE_URL`
  Public base URL for REST/OpenAPI metadata.
- `CORTEX_RUNTIME_MODE`
  Runtime mode. Allowed values: `local-single-user`, `hosted-service`
- `CORTEX_MCP_NAMESPACE`
  Default namespace for MCP sessions.

## Auth

- `CORTEX_API_KEY`
  Legacy single API key.
- `CORTEX_API_KEY_SCOPES`
  Comma-separated scopes for `CORTEX_API_KEY`.
- `CORTEX_API_KEY_NAMESPACES`
  Comma-separated namespace ACL for `CORTEX_API_KEY`.
- `CORTEX_API_KEYS_JSON`
  JSON array of scoped API key objects.

## Security and ingestion

- `.cortexignore`
  File-based ingestion denylist. The nearest `.cortexignore` discovered from the working directory upward is applied to Brainpack ingestion.
- Pack compilation secret stripping
  Compiled packs strip secret-like nodes by default unless secret inclusion is explicitly requested by the caller.

## Defaults worth knowing

- REST/UI request body limit: `1,048,576` bytes
- REST/UI read timeout: `15` seconds
- Hosted-service rate limiting defaults are defined in `cortex/http_hardening.py`
- Text validation default max length: `200,000` characters
- Path validation default max length: `4,096` characters
