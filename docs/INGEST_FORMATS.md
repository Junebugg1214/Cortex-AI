# Ingest formats

This page mirrors the formats handled by `cortex/extract_memory_loaders.py`.

## Supported file extensions

| Extension | Loader behavior |
| --- | --- |
| `.md` | Read as UTF-8 text and classify as `text` |
| `.txt` | Read as UTF-8 text and classify as `text` |
| `.json` | Parse as JSON and auto-detect the JSON shape |
| `.jsonl` | Parse one JSON object per line and auto-detect the JSONL shape |
| `.zip` | Scan safe entries and choose the best supported payload inside the archive |

Extension matching is currently lowercase suffix matching.

## ZIP archives

ZIP ingest scans entries ending in `.json`, `.jsonl`, `.txt`, or `.md`. It skips unsafe paths containing `..` or absolute paths and skips entries larger than 100 MB. If multiple supported files are present, Cortex chooses the highest-priority detected format.

Priority order inside ZIP files:

| Detected format | Priority |
| --- | ---: |
| `openai` | 70 |
| `gemini` | 60 |
| `perplexity` | 60 |
| `cursor` | 58 |
| `windsurf` | 58 |
| `copilot` | 58 |
| `grok` | 58 |
| `claude_code` | 55 |
| `api_logs` | 50 |
| `messages` | 40 |
| `jsonl` | 35 |
| `generic` | 20 |
| `text` | 10 |

## JSON and JSONL shape detection

| Detected format | Typical shape handled |
| --- | --- |
| `openai` | ChatGPT/OpenAI exports with `mapping` or `conversations` containing `mapping` |
| `gemini` | Gemini exports with `conversations` containing `turns`, or messages authored by `user` / `model` |
| `perplexity` | Objects with `threads` where each thread has `messages` |
| `cursor` | Cursor records with `composerId`, `bubbleId`, `bubbles`, or hinted Cursor chat/message fields |
| `windsurf` | Windsurf/Codeium records with `cascadeId`, `workspaceId`, `timelineId`, or timeline/workspace hints |
| `copilot` | Copilot records with `copilotSessionId`, `request`, `interactions`, or hinted history/session/message fields |
| `grok` | Grok/xAI records with `conversationId`, sender/content fields, or hinted conversation/chat/message containers |
| `claude_code` | Claude Code-style JSON/JSONL records with `type` in `user` / `assistant` / `system` plus `sessionId` and `cwd` |
| `api_logs` | Objects with `requests`, or lists of request-like objects with `messages` and `model` |
| `messages` | Objects with a top-level `messages` list, or lists of role/author/type message objects |
| `jsonl` | Generic JSONL fallback after platform checks |
| `generic` | Generic JSON fallback after platform checks |
| `text` | Plain text from `.txt`, `.md`, or text entries inside ZIP files |

## Unsupported directly

PDFs are not loaded directly. Convert PDFs to `.md` or `.txt` first, or export the source system to one of the JSON/JSONL/ZIP shapes above.

Other formats not handled by this loader include `.docx`, `.html`, `.csv`, images, audio, and video unless you pre-convert them to a supported text or JSON format.

## Practical examples

Plain markdown:

```bash
cortex extract policy_v3.md --output policy_v3.context.json
```

Plain text:

```bash
cortex extract notes.txt --output notes.context.json
```

ChatGPT/OpenAI ZIP export:

```bash
cortex extract chatgpt-export.zip --input-format openai --output chatgpt.context.json
```

Generic JSONL messages:

```bash
cortex extract session.jsonl --input-format jsonl --output session.context.json
```
