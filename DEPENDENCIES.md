# Dependency Notes

This repository did not add any new third-party runtime dependencies as part of the current hardening work.

## Runtime

- `tomli`
  Kept only for Python versions below 3.11, matching the existing project metadata.

## Development

- `pytest`
  Test runner.
- `ruff`
  Linting and formatting.
- `PyNaCl`
  Optional crypto/dev workflows already supported by the project.

## Policy

- New dependencies must be justified in the file that introduces them.
- New dependencies must also be documented here with:
  - why they are needed
  - whether they are runtime or development only
  - what built-in alternative was insufficient
