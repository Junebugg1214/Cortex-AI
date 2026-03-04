# Beta Tester Guide (Web App)

Thanks for testing Cortex.

## Beta URL

- [https://gollumgo.com/app](https://gollumgo.com/app)

## What Cortex is

Cortex is a portable AI ID layer.
It helps you keep your memory/context consistent across tools and share only the slices you choose.

## What to test

1. Onboarding clarity
2. Connector setup flow
3. Sync flow (`Run now`, auto-run status)
4. Add Data/import fallback
5. Memory review experience
6. Share flow (professional/technical/minimal/full)
7. General speed, errors, confusing copy, broken buttons

## What to flag during beta

When reporting an issue, include:

- page (`Connectors`, `Add Data`, `Share`, etc.)
- exact action taken
- expected vs actual behavior
- screenshot/screen recording if possible

High priority issues:

- broken onboarding steps
- failed syncs without clear error
- data shown under wrong share scope
- auth/session issues
- anything that feels unsafe/confusing with data controls

## Data ownership note

The philosophy is: your AI ID should belong to you.

For strong ownership/privacy guarantees, run Cortex on your own infrastructure.

## Self-host setup (recommended)

### One command

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git && cd Cortex-AI && CORTEX_REF=ae5b9d0b57e00aa27ac8d46bd635e9325934ca97 bash deploy/self-host-starter.sh
```

### Then

1. Open your own `/app` URL shown by the installer.
2. Create your account there.
3. Add connectors and run sync from your own server.

### Private repo auth fallback

```bash
CORTEX_REPO_URL=git@github.com:Junebugg1214/Cortex-AI.git CORTEX_REF=<tag-or-commit> bash deploy/self-host-starter.sh
```

## Why self-host matters

Self-hosting aligns product behavior with the ownership promise:

- your server
- your infra
- your operational control

That is the best way to ensure your AI ID is truly under your control.
