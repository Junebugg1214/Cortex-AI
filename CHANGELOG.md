# Changelog

All notable changes to Cortex are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Breaking changes (gated by deprecation)

- Release sequencing: ship `1.5.0` with CLI-v2 compatibility shims live, keep one full minor release of deprecation warnings, and use `1.6.0` for the hard retirement of moved or retired top-level commands.
- Store integrity migration: PR [#232](https://github.com/Junebugg1214/Cortex-AI/pull/232) changes `version_id` derivation to include ancestry. Existing stores should run `cortex admin rehash --confirm`, review `.cortex/migrations/rehash-v2.log`, and then run `cortex verify` before depending on the new integrity guarantees.
- PR [#232](https://github.com/Junebugg1214/Cortex-AI/pull/232) Merkle-chained version IDs by folding parent lineage into commit identity and adding the rehash migration path.
- PR [#233](https://github.com/Junebugg1214/Cortex-AI/pull/233) made extracted provenance mandatory so source retraction can be total instead of best-effort.
- PR [#234](https://github.com/Junebugg1214/Cortex-AI/pull/234) replaced swallowed federation verification failures with structured signature errors.
- PR [#235](https://github.com/Junebugg1214/Cortex-AI/pull/235) changed deduplication to use transitive closure rather than a greedy single pass.
- PR [#236](https://github.com/Junebugg1214/Cortex-AI/pull/236) wired the polling mount watcher into the CLI and documented that it is polling-based.
- PR [#237](https://github.com/Junebugg1214/Cortex-AI/pull/237) reconciled README examples with implemented ingest formats, extractor behavior, remotes, and portability limits.
- PR [#238](https://github.com/Junebugg1214/Cortex-AI/pull/238) made the roadmap embedding stub fail at startup with an explicit configuration message.
- PR [#239](https://github.com/Junebugg1214/Cortex-AI/pull/239) introduced subpackages while preserving public imports through compatibility shims.
- PR [#240](https://github.com/Junebugg1214/Cortex-AI/pull/240) collapsed empty and tiny service mixins into their consumers.
- PR [#241](https://github.com/Junebugg1214/Cortex-AI/pull/241) broke up schema builders and added golden coverage for MCP/OpenAPI output stability.
- PR [#242](https://github.com/Junebugg1214/Cortex-AI/pull/242) documented the CLI-v2 taxonomy and migration table.
- PR [#243](https://github.com/Junebugg1214/Cortex-AI/pull/243) introduced CLI-v2 namespace shims for the deprecation window.
- PR [#244](https://github.com/Junebugg1214/Cortex-AI/pull/244) removed deprecated Tier-1 entries as the `1.6.0` hard-retirement step.
- PR [#245](https://github.com/Junebugg1214/Cortex-AI/pull/245) added the generated two-level help tree.
- PR [#246](https://github.com/Junebugg1214/Cortex-AI/pull/246) added the optional ASGI API server behind the `asgi` extra.
- PR [#247](https://github.com/Junebugg1214/Cortex-AI/pull/247) added a persistent SQLite-backed rate limiter.
- PR [#248](https://github.com/Junebugg1214/Cortex-AI/pull/248) added signed HTTP remotes.
- PR [#249](https://github.com/Junebugg1214/Cortex-AI/pull/249) hardened CI with coverage, security scanning, SBOM generation, and release provenance.
- PR [#250](https://github.com/Junebugg1214/Cortex-AI/pull/250) added typed extraction output for facts, claims, and relationships.
- PR [#251](https://github.com/Junebugg1214/Cortex-AI/pull/251) added a real optional SentenceTransformer embedding backend.

### Added

- public beta launch docs for quickstart, operations, and threat modeling
- prerelease-aware release automation for beta and release-candidate tags
- beta feedback issue template

### Changed

- release notes and manifests now describe stable vs prerelease behavior explicitly
- release workflow no longer treats prerelease tags like GA publishes
- the `full` optional extra now includes crypto, fast NumPy support, ASGI serving, and the optional embedding backend dependencies

### Removed

- Removed an optional hosted agent bridge, its console script, serve subcommand, and config table support. OpenClaw and Hermes remain first-class.

## [v1.4.1-beta] — 2026-03-26

This is the first self-hosted public beta positioned around **Git for AI Memory**.

### Added

- immutable versioned commits, branching, merge, rollback, review, blame, history, remotes, and governance
- local REST API, Python SDK, TypeScript SDK, and MCP server on top of user-owned storage
- SQLite-backed persistent indexing, conflict APIs, memory object APIs, and adoption-layer `MemorySession` helpers
- self-host config, scoped auth, backup/restore, Docker packaging, and release automation

### Notes

- Cortex is beta-ready for technical self-hosted teams
- user-owned storage remains the default and recommended operating model
- hosted Cortex is intentionally deferred

## Historical Notes

Earlier changelog entries from before the Git-for-AI-Memory repositioning are being normalized. The current beta
release notes above reflect the supported self-hosted runtime and operator surface in this repository.
