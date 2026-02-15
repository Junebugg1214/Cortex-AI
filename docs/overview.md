# Cortex — What It Is

Cortex is a tool that takes everything AI platforms know about you — your ChatGPT conversations, Claude chats, coding sessions — and builds a **portable knowledge graph** that **you own**.

Instead of each AI having its own incomplete picture of you, Cortex creates one unified identity you can take anywhere.

---

## How to Use It

### 1. Extract your data

Export your chat history from ChatGPT (as a `.zip`), Claude, Gemini, or any supported platform. Then run:

```bash
pip install cortex-identity
cortex chatgpt-export.zip -o context.json
```

This reads your conversations and builds a knowledge graph — nodes like "Python", "healthcare", "prefers concise answers" connected by relationships.

### 2. Push it to another platform

```bash
cortex sync context.json --to claude --policy professional -o ./output
```

This takes your graph, filters it through a disclosure policy (so you control what's shared), and exports it in a format the target platform understands.

### 3. Sign and version it

```bash
cortex identity --init --name "Your Name"
cortex commit context.json -m "Initial context"
```

This creates a cryptographic identity (`did:key`) and version-controls your graph like git. You can prove the data is yours and hasn't been tampered with.

### 4. Serve it as an API

```bash
cortex serve context.json --port 8421
cortex grant --create --audience "Claude" --policy professional
```

This starts an HTTP server. AI platforms can request a scoped access token, then pull your context directly over the network — filtered by the disclosure policy you chose.

---

## Keeping Your Graph Up to Date

For chat platforms (ChatGPT, Claude, Gemini), the extraction process is **manual**. When you have new conversations, export your data again and merge it with your existing graph:

```bash
cortex chatgpt-export-new.zip --merge context.json -o context.json
```

Repeat this periodically (weekly, monthly) to keep your knowledge graph current. These platforms don't offer live APIs for conversations, so export-and-merge is the workflow for now.

For **Claude Code**, Cortex can extract in real-time. It watches your coding sessions as they happen and automatically merges new signals into your graph:

```bash
cortex extract-coding --watch -o context.json
```

---

## The Key Ideas

- **You own your data** — it's a local file, not locked in someone's cloud
- **Portable** — works across ChatGPT, Claude, Gemini, Cursor, Copilot, and more
- **Privacy controls** — disclosure policies let you share "professional" info with one platform and "technical" info with another
- **Cryptographically signed** — proves the data is yours and unchanged
- **API-ready** — platforms can pull your context over HTTP instead of you copy-pasting
- **Zero dependencies** — runs with just Python's standard library
