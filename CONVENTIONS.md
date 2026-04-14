# Cortex Conventions

This repository uses one canonical naming style for user-facing surfaces.

## CLI

- Use `cortex <noun> <verb>` for first-class workflows.
- Use `cortex <noun> --help` to discover the available verbs and examples.
- Prefer plain-English error messages with a recovery step.

## IDs

- Mind IDs use lowercase snake case or kebab case depending on the source system, but must remain stable once created.
- Audience IDs use lowercase kebab case, such as `executive` or `team-brief`.
- Stable source IDs are content-addressed and treated as canonical lineage keys.
- Human labels are display names only and may change over time.

## UI Copy

- Use direct, active voice.
- Put the primary action first.
- Use the same label for the same action everywhere.

## Onboarding

- Step names should be short, imperative, and user-facing.
- Completion state should be persistent and skippable.
- If the user can recover from a failure, say how to do it in one sentence.
