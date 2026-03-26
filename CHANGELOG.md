# Changelog

All notable changes to Cortex are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- public beta launch docs for quickstart, operations, and threat modeling
- prerelease-aware release automation for beta and release-candidate tags
- beta feedback issue template

### Changed

- release notes and manifests now describe stable vs prerelease behavior explicitly
- release workflow no longer treats prerelease tags like GA publishes

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
