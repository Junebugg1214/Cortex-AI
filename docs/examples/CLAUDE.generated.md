# CLAUDE.md — Sample Cortex-Managed Output

This example shows the kind of project-level Claude Code file Cortex can manage.
It is an example artifact, not a contributor instruction file for this repository.

```md
# Project Notes

The text outside the Cortex block is still yours.

<!-- CORTEX:START -->
## Shared AI Context

- Active project: Cortex-AI
- Primary language: Python
- Prefers direct answers
- Uses FastAPI, SQLite, and MCP

## Constraints To Respect

- Keep storage user-owned
- Preserve existing project files outside managed markers
<!-- CORTEX:END -->

## Team Conventions

Any text outside the managed block stays untouched.
```

In a mixed file, Cortex only owns the content inside the `CORTEX:START` / `CORTEX:END` block.
That is why uninstall is non-destructive and why a repository can keep its own human-written guidance around the managed section.
