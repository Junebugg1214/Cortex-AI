# Cortex Website

Static marketing and onboarding site for Cortex.

## Pages

- `index.html`: product story, problem framing, and high-level overview
- `how-it-works.html`: Mind model, subsystem explanation, and runtime flow
- `learn.html`: onboarding path and links into the repo docs

## Preview locally

```bash
python3 -m http.server 4173 --directory website
```

Then open:

- `http://127.0.0.1:4173/index.html`
- `http://127.0.0.1:4173/how-it-works.html`
- `http://127.0.0.1:4173/learn.html`

## Source of truth

The product messaging in this site is intentionally grounded in:

- `README.md`
- `docs/CORTEX_MIND_PRD.md`
- `docs/MINDS.md`
- `docs/BRAINPACKS.md`
- `docs/BETA_QUICKSTART.md`
- `docs/AGENT_QUICKSTARTS.md`
- `docs/SELF_HOSTING.md`
