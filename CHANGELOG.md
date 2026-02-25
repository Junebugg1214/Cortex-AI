# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [v1.5.0] — 2026-02-24

### Added
- **Graph health dashboard** — Stale node detection, orphan analysis, confidence distribution charts, and graph changelog page in the admin dashboard (6 pages total)
- **Graph diff/changelog API** — `diff_graphs()` and `graph_health()` operations for programmatic graph comparison and health analysis
- **ZIP archive export/import** — Export and import full graph archives as `.zip` files from the Settings dashboard page
- **Multi-profile support** — Create and manage multiple public profiles per identity, each with its own disclosure policy
- **Public profile URLs** — Shareable `/p/{handle}` routes for public-facing profile pages
- **QR code sharing** — Generate QR codes for public profile URLs directly from the web app
- **`profile.viewed` webhook event** — Fires when a public profile is viewed by an external visitor

### Changed
- Dashboard page count increased from 5 to 6 (added Health page)
- Web app now includes a Profile page alongside Upload, Memory, and Share

### Test Coverage
- **2,361 tests** across 90+ files (+ 35 skipped PostgreSQL tests)

---

## [v1.4.1] — 2026-02-18

### Added
- **PDF resume import** — Upload PDF resumes via web UI or API; extracts identity, roles, companies, skills, education
- **DOCX resume import** — Word document parsing from XML (no external dependencies)
- **LinkedIn data export import** — Upload `.zip` from LinkedIn Settings for full profile, positions, skills, education, certifications
- **GitHub repo import** — Paste repo URL + optional token for languages, topics, stars, forks, README content
- **Shareable memory API** — Generate API keys with disclosure policies (`full`, `professional`, `technical`, `minimal`, `custom`) and output formats (`json`, `claude_xml`, `system_prompt`, `markdown`)
- **Public memory endpoint** — `GET /api/memory/{key}` serves filtered context to external tools without authentication

### Test Coverage
- **2,138 tests** across 75+ files (+ 35 skipped PostgreSQL tests)

---

## [v1.4.0] — 2026-02-15

### Added
- **Consumer web UI** — Served at `/app` with `--enable-webapp` flag
  - **Upload page** — Drag-and-drop file import (JSON, PDF, DOCX, zip), GitHub and LinkedIn URL import cards
  - **My Memory page** — Interactive canvas graph with force-directed layout, zoom/pan, click-to-select, tag-colored nodes, search and filters
  - **Share page** — Export to Claude, Notion, Google Docs, or system prompt format with privacy level selection and live preview

### Test Coverage
- **2,063 tests** (+ 35 skipped PostgreSQL tests)

---

## [v1.3.0] — 2026-02-12

### Added
- **Semantic search** — TF-IDF ranked search across all node fields (stdlib-only)
- **Plugin system** — 12 hook points for extending server behavior
- **Graph query language** — `FIND`, `NEIGHBORS`, `PATH`, `SEARCH` DSL for graph traversal
- **Cross-instance federation** — Export/import graphs between Cortex instances with peer management
- **Python SDK** — Stdlib-only client library (`cortex.sdk.client.CortexClient`)
- **Helm chart** — Kubernetes deployment at `deploy/helm/cortex/`
- **Terraform modules** — AWS ECS Fargate + GCP Cloud Run at `deploy/terraform/`
- **Distributed tracing** — W3C Trace Context spans with OTLP export
- **Swagger UI** — Interactive API documentation at `/docs`
- **Error hints** — Structured error responses with actionable suggestions
- **Grafana dashboards** — 3 JSON dashboards at `deploy/grafana/`
- **Load testing** — Locust test suite for performance benchmarking
- **Examples directory** — Sample scripts and integration patterns

### Test Coverage
- **2,032 tests** (+ 35 skipped PostgreSQL tests)

---

## [v1.2.0] — 2026-02-08

### Added
- **RBAC** — 4 roles (admin/editor/reader/subscriber) mapped to 10 scope subsets
- **Audit ledger** — Hash-chained SHA-256 tamper-evident log with verification endpoint
- **HTTP caching** — ETags, Cache-Control headers, 304 Not Modified responses
- **Webhook resilience** — Exponential backoff with jitter, circuit breaker, dead-letter queue
- **Server-Sent Events** — `/events` endpoint with Last-Event-ID replay from event buffer
- **OAuth 2.0 / OIDC** — Google and GitHub providers with PKCE
- **Field encryption** — PBKDF2 + XOR + HMAC at rest for sensitive fields
- **Rate limiting** — Sliding-window per-IP (default 60 req/60s)
- **CSRF / SSRF protection** — Stateless HMAC tokens; DNS + IP range blocking
- **SQLite storage backend** — Grants, webhooks, audit log, delivery log with WAL mode
- **PostgreSQL storage backend** — Production-grade backend with `--storage postgres --db-url`
- **TypeScript SDK** — `@cortex_ai/sdk` on npm, zero runtime dependencies, ESM + CJS dual build
- **Prometheus metrics** — 17 metrics on `/metrics` endpoint (stdlib-only)
- **Admin dashboard** — 5-page SPA at `/dashboard` (Overview, Graph, Grants, Versions, Settings)

### Test Coverage
- **1,710 tests** (+ 35 skipped PostgreSQL tests)

---

## [v1.1.0] — 2026-02-04

### Added
- **UPAI protocol** — W3C DID identity (`did:cortex:`) with Ed25519 signing
- **Grant tokens** — JWT-like, Ed25519-signed, 11 scopes, configurable expiration
- **Key rotation** — Multi-key management with revocation chain and grace periods
- **Disclosure policies** — 4 built-in policies + custom tag-based filtering
- **Verifiable credentials** — W3C VC 1.1 issuance and verification
- **Version control** — Git-like commits, diff, revert for identity graph
- **Encrypted backup** — PBKDF2 + XOR cipher + HMAC integrity, 6 recovery codes
- **Service discovery** — `.well-known/upai-configuration` endpoint
- **CaaS API** — 18 REST endpoints with OpenAPI 3.1 spec
- **JSON Schema validation** — Request/response validation on all endpoints

### Test Coverage
- **796 tests**

---

## [v1.0.0] — 2026-01-30

### Added
- **Knowledge graph engine** — Nodes with tags, confidence scores, temporal metadata, and properties
- **16+ extraction methods** — Identity, roles, companies, projects, skills, domains, relationships, values, priorities, metrics, negations, preferences, constraints, corrections, temporal context
- **Smart edges** — Pattern rules, co-occurrence (PMI), centrality (PageRank), graph-aware dedup
- **Temporal tracking** — First-seen/last-seen timestamps, timeline generation, drift scoring
- **Coding session extraction** — Technologies, tools, commands, projects from Claude Code `.jsonl` sessions
- **Cross-platform context writer** — Write identity to Claude Code, Cursor, Copilot, Windsurf, Gemini CLI simultaneously
- **Visualization** — Interactive force-directed HTML graph and chronological timeline

### Test Coverage
- **618 tests**
