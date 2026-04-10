"""
Small local web UI for Git-for-AI-Memory workflows.

Zero-dependency HTTP server with a single-page interface for review, blame,
history, governance, remote sync, indexing, and maintenance operations.
"""

from __future__ import annotations

import json
import secrets
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from cortex.auth import authorize_api_key
from cortex.config import APIKeyConfig, is_loopback_host, validate_runtime_security
from cortex.http_hardening import (
    HTTPRequestPolicy,
    HTTPRequestValidationError,
    InMemoryRateLimiter,
    apply_read_timeout,
    enforce_rate_limit,
    read_json_request,
    request_policy_for_mode,
)
from cortex.webapp_backend import MemoryUIBackend


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


UI_SESSION_HEADER = "X-Cortex-UI-Session"
UI_SESSION_PLACEHOLDER = "__CORTEX_UI_SESSION_TOKEN__"


UI_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cortex UI</title>
  <style>
    :root {
      --bg: #edf2ea;
      --bg-soft: #f7fbf5;
      --panel: rgba(255, 252, 247, 0.9);
      --panel-strong: #fffdf9;
      --ink: #15211b;
      --muted: #607165;
      --line: #d7dfd5;
      --accent: #11695b;
      --accent-strong: #0c4f45;
      --accent-soft: #d9ece7;
      --info: #244d72;
      --warning: #9a5e14;
      --danger: #a73d31;
      --shadow: 0 18px 42px rgba(28, 46, 39, 0.1);
      --radius: 22px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Avenir Next", "Gill Sans", "Trebuchet MS", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(17, 105, 91, 0.15), transparent 28%),
        radial-gradient(circle at bottom right, rgba(154, 94, 20, 0.10), transparent 24%),
        linear-gradient(180deg, var(--bg-soft), var(--bg));
    }
    h1, h2, h3, h4, summary {
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
    }
    .shell {
      display: grid;
      grid-template-columns: 290px 1fr;
      min-height: 100vh;
    }
    aside {
      padding: 28px 22px;
      border-right: 1px solid var(--line);
      background: rgba(248, 252, 248, 0.8);
      backdrop-filter: blur(16px);
    }
    .brand {
      margin-bottom: 24px;
    }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 10px;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(17, 105, 91, 0.1);
      color: var(--accent-strong);
      font-size: 0.78rem;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .brand h1 {
      margin: 0;
      font-size: 2rem;
      letter-spacing: 0.01em;
    }
    .brand p {
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.55;
      font-size: 0.97rem;
    }
    .meta-card, .nav button, .panel, .result, .tool-card, .subpanel {
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      border-radius: var(--radius);
      background: var(--panel);
    }
    .meta-card {
      padding: 16px;
      margin-bottom: 18px;
      font-size: 0.92rem;
      line-height: 1.45;
    }
    .meta-card strong {
      display: block;
      margin-bottom: 4px;
      font-size: 0.84rem;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .meta-block + .meta-block {
      margin-top: 12px;
    }
    .nav {
      display: grid;
      gap: 10px;
    }
    .nav button {
      padding: 14px 16px;
      cursor: pointer;
      text-align: left;
      font: inherit;
      transition: transform 120ms ease, background 120ms ease, border-color 120ms ease;
    }
    .nav button.active,
    .nav button[aria-selected="true"] {
      background: linear-gradient(135deg, var(--accent-soft), #eefaf7);
      border-color: rgba(17, 105, 91, 0.32);
      transform: translateX(4px);
    }
    main {
      padding: 28px;
      display: grid;
      gap: 18px;
      align-content: start;
    }
    .hero {
      padding: 26px;
      border: 1px solid rgba(17, 105, 91, 0.18);
      border-radius: calc(var(--radius) + 8px);
      background:
        linear-gradient(135deg, rgba(17, 105, 91, 0.12), rgba(255, 255, 255, 0.9)),
        var(--panel);
      box-shadow: var(--shadow);
    }
    .hero h2 {
      margin: 0 0 8px;
      font-size: 2.1rem;
      line-height: 1.05;
    }
    .hero p {
      margin: 0;
      max-width: 74ch;
      color: var(--muted);
      line-height: 1.6;
    }
    .panel {
      display: none;
      padding: 22px;
    }
    .panel.active {
      display: block;
    }
    .panel h3 {
      margin: 0 0 10px;
      font-size: 1.2rem;
    }
    .panel-copy {
      margin: 0 0 12px;
      color: var(--muted);
      line-height: 1.45;
      max-width: 68ch;
    }
    .panel-grid {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      margin-bottom: 16px;
    }
    .split-results {
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      margin-top: 16px;
    }
    .stack {
      display: grid;
      gap: 16px;
    }
    label {
      display: grid;
      gap: 6px;
      font-size: 0.92rem;
      color: var(--muted);
    }
    input, textarea, select {
      width: 100%;
      padding: 11px 12px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: white;
      color: var(--ink);
      font: inherit;
    }
    textarea {
      min-height: 90px;
      resize: vertical;
    }
    .checkbox {
      display: flex;
      gap: 10px;
      align-items: center;
      padding: 12px 14px;
      border-radius: 14px;
      background: white;
      border: 1px solid var(--line);
      color: var(--ink);
    }
    .checkbox input {
      width: auto;
      margin: 0;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 14px 0 6px;
    }
    button.action {
      border: 0;
      border-radius: 999px;
      padding: 11px 16px;
      background: var(--accent);
      color: white;
      cursor: pointer;
      font: inherit;
    }
    button.subtle {
      background: #eef2ec;
      color: var(--ink);
    }
    button.action[disabled] {
      opacity: 0.62;
      cursor: progress;
    }
    .result {
      min-height: 140px;
      padding: 16px;
      overflow: auto;
      background: var(--panel-strong);
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 12px 14px;
      background: white;
    }
    .card strong {
      display: block;
      margin-top: 4px;
      font-size: 1.5rem;
      line-height: 1.1;
    }
    .card small {
      display: block;
      margin-top: 6px;
      color: var(--muted);
      line-height: 1.35;
    }
    .quick-actions {
      padding: 18px;
      background: linear-gradient(135deg, rgba(17, 105, 91, 0.08), rgba(255, 255, 255, 0.96));
    }
    .quick-actions h4 {
      margin: 0 0 8px;
      font-size: 1.05rem;
    }
    .quick-grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      margin-top: 12px;
    }
    .tiny {
      font-size: 0.85rem;
      color: var(--muted);
      line-height: 1.45;
    }
    .status-pass { color: var(--accent); }
    .status-fail { color: var(--danger); }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin: 0 6px 6px 0;
      padding: 5px 10px;
      border-radius: 999px;
      background: #eef2ec;
      color: var(--ink);
      font-size: 0.8rem;
    }
    .pill.good {
      background: rgba(17, 105, 91, 0.12);
      color: var(--accent-strong);
    }
    .pill.warn {
      background: rgba(154, 94, 20, 0.13);
      color: var(--warning);
    }
    .pill.info {
      background: rgba(36, 77, 114, 0.12);
      color: var(--info);
    }
    .list {
      display: grid;
      gap: 10px;
    }
    .item {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      background: white;
    }
    .item h4 {
      margin: 0 0 6px;
      font-size: 1.02rem;
    }
    .item p {
      margin: 0;
      color: var(--muted);
      line-height: 1.52;
    }
    .item p + p {
      margin-top: 8px;
    }
    .tool-grid {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
      margin-top: 14px;
    }
    .tool-card {
      padding: 14px 16px;
      background: var(--panel-strong);
    }
    .tool-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
      margin-bottom: 10px;
    }
    .tool-head h4 {
      margin: 0;
      font-size: 1.08rem;
    }
    .tool-note {
      margin: 0 0 8px;
      color: var(--muted);
      line-height: 1.4;
      font-size: 0.9rem;
    }
    .meter {
      width: 100%;
      height: 8px;
      border-radius: 999px;
      background: #e6ece8;
      overflow: hidden;
      margin-bottom: 10px;
    }
    .meter > span {
      display: block;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), #3b8c7b);
    }
    .meta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 10px;
    }
    .tool-stats {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      margin-bottom: 10px;
    }
    .tool-stat {
      padding: 10px;
      border-radius: 12px;
      background: #f4f7f3;
      border: 1px solid var(--line);
    }
    .tool-stat strong {
      display: block;
      font-size: 1.05rem;
      line-height: 1.1;
    }
    .tool-stat span {
      display: block;
      margin-top: 4px;
      color: var(--muted);
      font-size: 0.78rem;
    }
    .path-list {
      display: grid;
      gap: 6px;
      margin-top: 8px;
    }
    .path-list div {
      padding: 8px 10px;
      border-radius: 12px;
      background: #f3f6f2;
      border: 1px solid var(--line);
      word-break: break-word;
    }
    .subpanel {
      padding: 0;
      overflow: hidden;
      background: var(--panel-strong);
    }
    .subpanel > summary,
    .subpanel-header {
      list-style: none;
      cursor: pointer;
      padding: 16px 18px;
      font-size: 1.06rem;
      border-bottom: 1px solid transparent;
      background: linear-gradient(135deg, rgba(17, 105, 91, 0.07), rgba(255, 255, 255, 0.92));
    }
    .subpanel > summary::-webkit-details-marker { display: none; }
    .subpanel[open] > summary {
      border-bottom-color: var(--line);
    }
    .subpanel-body {
      padding: 18px;
    }
    .mono,
    pre {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.88rem;
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
    }
    .command-block {
      margin: 10px 0 0;
      padding: 12px 14px;
      border-radius: 16px;
      background: #13211b;
      color: #f5f7f4;
    }
    .helper {
      margin: -8px 0 8px;
      color: var(--muted);
      font-size: 0.88rem;
    }
    .segmented {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
    }
    .segmented button {
      border: 1px solid var(--line);
      background: var(--panel-strong);
      color: var(--ink);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 0.88rem;
      cursor: pointer;
    }
    .segmented button.active {
      background: #13211b;
      color: #f5f7f4;
      border-color: #13211b;
    }
    .danger { color: var(--danger); }
    .warning { color: var(--warning); }
    .info { color: var(--info); }
    .empty {
      color: var(--muted);
      font-style: italic;
    }
    details.raw {
      margin-top: 14px;
    }
    details.raw summary {
      cursor: pointer;
      color: var(--muted);
    }
    @media (max-width: 980px) {
      .shell { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      main { padding: 20px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand">
        <div class="eyebrow">Cortex 1.4</div>
        <h1>Cortex</h1>
        <p>Portable AI Minds across your tools. Start from one durable brain-state, then inspect targets, packs, mounts, and operator details only when you need them.</p>
      </div>
      <div class="meta-card" id="meta-card">Loading workspace…</div>
      <div class="nav" role="tablist" aria-label="Cortex UI panels">
        <button data-panel="overview" class="active" role="tab" aria-selected="true">Overview</button>
        <button data-panel="tools" role="tab" aria-selected="false">Tools</button>
        <button data-panel="minds" role="tab" aria-selected="false">Minds</button>
        <button data-panel="brainpacks" role="tab" aria-selected="false">Brainpacks</button>
        <button data-panel="audit" role="tab" aria-selected="false">Freshness</button>
        <button data-panel="review" role="tab" aria-selected="false">Review & Trace</button>
        <button data-panel="advanced" role="tab" aria-selected="false">Advanced</button>
      </div>
    </aside>
    <main>
      <section class="hero">
        <div class="eyebrow">Local-first Mind control plane</div>
        <h2>One portable Mind, wired across your tools</h2>
        <p>Start from your default Mind, keep it mounted where it matters, and only drill into tool scans or operator plumbing when the overview says you should.</p>
      </section>

      <section id="panel-overview" class="panel active" role="tabpanel">
        <h3>Mind Overview</h3>
        <p class="panel-copy">Lead from the default Mind: its branch, attached Brainpacks, mounted targets, pending proposals, and the runtime follow-up that matters next.</p>
        <div id="overview-cards" class="cards"></div>
        <div class="split-results">
          <div class="quick-actions subpanel">
            <div class="subpanel-body">
              <h4>Quick actions</h4>
              <p class="tiny">These refresh the default Mind loop and the runtime state around it.</p>
              <div class="actions">
                <button class="action" onclick="runScanAction(this)">Refresh overview</button>
                <button class="action subtle" onclick="runSyncAction(this)">Sync mounted targets</button>
                <button class="action subtle" onclick="loadMetrics(this)">Refresh metrics</button>
              </div>
              <div class="quick-grid">
                <label>Remember one thing
                  <textarea id="remember-statement" placeholder="We prefer concise, implementation-first responses."></textarea>
                </label>
                <div>
                  <p class="tiny">Use this for one-off context that should land in the active Mind and refresh the runtimes mounted from it.</p>
                  <div class="actions">
                    <button class="action" onclick="runRememberAction(this)">Remember & sync</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div id="overview-action-result" class="result empty">Refresh the overview, sync mounted targets, or remember one thing from here.</div>
        </div>
        <div class="split-results">
          <div id="overview-journey" class="result empty">Default Mind workflow and next steps will appear here.</div>
          <div id="overview-adoptable" class="result empty">Mind queue, attached packs, and detected sources will appear here.</div>
        </div>
        <div class="split-results">
          <div id="overview-health" class="result empty">Mind and workspace health will appear here.</div>
          <div id="overview-metrics" class="result empty">Observability and maintenance signals will appear here.</div>
        </div>
      </section>

      <section id="panel-tools" class="panel" role="tabpanel">
        <h3>Connected Tools</h3>
        <p class="panel-copy">Each tool gets a different routed slice. This view shows what is configured, how much context each target has, and what it will receive.</p>
        <div class="panel-grid">
          <label>Preview target
            <select id="tools-context-target"></select>
          </label>
          <label>Preview max chars
            <input id="tools-context-max-chars" type="number" value="700" min="150">
          </label>
        </div>
        <div class="actions">
          <button class="action" onclick="loadWorkspace(this)">Refresh tool scan</button>
          <button class="action subtle" onclick="previewTargetContext(this)">Preview routed context</button>
        </div>
        <div id="tools-summary" class="result empty">Tool coverage and routing details will appear here.</div>
        <div id="tools-list" class="tool-grid"></div>
        <div id="tools-context-result" class="result empty">Select a target to preview the context Cortex would hand it right now.</div>
      </section>

      <section id="panel-minds" class="panel" role="tabpanel">
        <h3>Minds</h3>
        <p class="panel-copy">A Mind is the top-level portable brain-state object in Cortex: core state, attached Brainpacks, mounted targets, and runtime composition in one place.</p>
        <div class="panel-grid">
          <label>Selected Mind
            <select id="mind-select" onchange="loadMindView()"></select>
          </label>
          <label>Compose target
            <select id="mind-compose-target"></select>
          </label>
          <label>Compose task
            <input id="mind-compose-task" placeholder="support, investor update, memory routing">
          </label>
          <label>Compose max chars
            <input id="mind-compose-max-chars" type="number" value="900" min="150">
          </label>
        </div>
        <div class="actions">
          <button class="action" onclick="loadMinds(this)">Refresh Minds</button>
          <button class="action subtle" onclick="previewMindCompose(this)">Refresh compose preview</button>
        </div>
        <div id="mind-summary" class="result empty">Mind summary cards will appear here.</div>
        <div class="split-results">
          <div id="mind-core" class="result empty">Core state will appear here.</div>
          <div id="mind-attachments" class="result empty">Attached Brainpacks will appear here.</div>
        </div>
        <div class="split-results">
          <div id="mind-branch-policy" class="result empty">Branch and policy status will appear here.</div>
          <div id="mind-mounts" class="result empty">Mounted targets will appear here.</div>
        </div>
        <div id="mind-compose" class="result empty">Compose preview will appear here.</div>
      </section>

      <section id="panel-brainpacks" class="panel" role="tabpanel">
        <h3>Brainpacks</h3>
        <p class="panel-copy">Browse your compiled domain minds by source material, concepts, claims, open questions, and generated artifacts.</p>
        <div class="panel-grid">
          <label>Selected pack
            <select id="brainpack-select" onchange="loadBrainpackView()"></select>
          </label>
          <div>
            <div class="tiny">Section</div>
            <div id="brainpack-tabs" class="segmented" role="tablist" aria-label="Brainpack sections">
              <button data-brainpack-view="sources" class="active" onclick="activateBrainpackView('sources', this)">Sources</button>
              <button data-brainpack-view="concepts" onclick="activateBrainpackView('concepts', this)">Concepts</button>
              <button data-brainpack-view="claims" onclick="activateBrainpackView('claims', this)">Claims</button>
              <button data-brainpack-view="unknowns" onclick="activateBrainpackView('unknowns', this)">Unknowns</button>
              <button data-brainpack-view="artifacts" onclick="activateBrainpackView('artifacts', this)">Artifacts</button>
            </div>
          </div>
        </div>
        <div class="actions">
          <button class="action" onclick="loadBrainpacks(this)">Refresh packs</button>
          <button class="action subtle" onclick="loadBrainpackView(this)">Refresh section</button>
        </div>
        <div id="brainpack-summary" class="result empty">Brainpack summary cards will appear here.</div>
        <div id="brainpack-content" class="result empty">Select a pack to inspect its sources, concepts, claims, unknowns, and artifacts.</div>
      </section>

      <section id="panel-audit" class="panel" role="tabpanel">
        <h3>Freshness & Gaps</h3>
        <p class="panel-copy">Spot drift fast. Cortex compares the canonical graph against the local files it manages and flags anything that needs a sync.</p>
        <div class="actions">
          <button class="action" onclick="loadWorkspace(this)">Refresh freshness audit</button>
        </div>
        <div class="split-results">
          <div id="audit-status" class="result empty">Target freshness and missing-label details will appear here.</div>
          <div id="audit-issues" class="result empty">Audit issues and next actions will appear here.</div>
        </div>
      </section>

      <section id="panel-review" class="panel" role="tabpanel">
        <h3>Review & Trace</h3>
        <p class="panel-copy">These tools are still here when you need them. They just are not the front door anymore.</p>
        <div class="stack">
          <div class="subpanel">
            <div class="subpanel-header">Semantic review</div>
            <div class="subpanel-body">
              <p class="panel-copy">Run semantic review against a stored ref or point at a graph file if you want to compare an uncommitted payload.</p>
              <div class="panel-grid">
                <label>Context file (optional)<input id="review-input-file" placeholder="/abs/path/context.json"></label>
                <label>Against ref<input id="review-against" value="HEAD"></label>
                <label>Current ref<input id="review-ref" value="HEAD"></label>
                <label>Fail on<input id="review-fail-on" value="blocking"></label>
              </div>
              <p class="helper">Leave the context file blank to review the stored ref directly.</p>
              <div class="actions">
                <button class="action" onclick="runReview(this)">Run review</button>
                <button class="action subtle" onclick="fillDefaultContext('review-input-file')">Use default context</button>
              </div>
              <div id="review-result" class="result empty">Run a review to see structural and semantic drift.</div>
            </div>
          </div>

          <div class="subpanel">
            <div class="subpanel-header">Trace one node</div>
            <div class="subpanel-body">
              <p class="panel-copy">Trace one memory node back through versions and claim lineage. This is useful when a fact looks wrong and you want to know where it came from.</p>
              <div class="panel-grid">
                <label>Context file (optional)<input id="blame-input-file" placeholder="/abs/path/context.json"></label>
                <label>Label<input id="blame-label" placeholder="Project Atlas"></label>
                <label>Node id<input id="blame-node-id" placeholder="optional"></label>
                <label>Ref<input id="blame-ref" value="HEAD"></label>
                <label>Source filter<input id="blame-source" placeholder="optional"></label>
                <label>Limit<input id="blame-limit" type="number" value="20" min="1"></label>
              </div>
              <p class="helper">Leave the context file blank to blame against the stored ref.</p>
              <div class="actions">
                <button class="action" onclick="runBlame(this)">Trace claim</button>
                <button class="action subtle" onclick="fillDefaultContext('blame-input-file')">Use default context</button>
              </div>
              <div id="blame-result" class="result empty">Trace a claim back to versions, sources, and claim-ledger receipts.</div>
            </div>
          </div>

          <div class="subpanel">
            <div class="subpanel-header">History timeline</div>
            <div class="subpanel-body">
              <p class="panel-copy">Inspect the timeline for one memory node without leaving the browser. It works against stored refs and uncommitted payloads.</p>
              <div class="panel-grid">
                <label>Context file (optional)<input id="history-input-file" placeholder="/abs/path/context.json"></label>
                <label>Label<input id="history-label" placeholder="Project Atlas"></label>
                <label>Node id<input id="history-node-id" placeholder="optional"></label>
                <label>Ref<input id="history-ref" value="HEAD"></label>
                <label>Source filter<input id="history-source" placeholder="optional"></label>
                <label>Limit<input id="history-limit" type="number" value="20" min="1"></label>
              </div>
              <p class="helper">Leave the context file blank to read history directly from the active store.</p>
              <div class="actions">
                <button class="action" onclick="runHistory(this)">Show history</button>
                <button class="action subtle" onclick="fillDefaultContext('history-input-file')">Use default context</button>
              </div>
              <div id="history-result" class="result empty">See the timeline of one memory claim across versions and claim events.</div>
            </div>
          </div>
        </div>
      </section>

      <section id="panel-advanced" class="panel" role="tabpanel">
        <h3>Advanced Controls</h3>
        <p class="panel-copy">Operator controls stay available here without crowding the main portability workflow.</p>
        <div class="stack">
          <details class="subpanel" open>
            <summary>Governance</summary>
            <div class="subpanel-body">
              <p class="panel-copy">Create or delete namespace rules, then preview whether a write would be allowed or require approval.</p>
              <div class="panel-grid">
                <label>Rule name<input id="gov-name" placeholder="protect-main"></label>
                <label>Actor pattern<input id="gov-actor-pattern" value="agent/*"></label>
                <label>Actions (comma-separated)<input id="gov-actions" value="write"></label>
                <label>Namespaces (comma-separated)<input id="gov-namespaces" value="main"></label>
                <label>Approval below confidence<input id="gov-confidence" type="number" step="0.01" placeholder="0.75"></label>
                <label>Approval tags (comma-separated)<input id="gov-tags" placeholder="active_priorities"></label>
                <label>Approval semantic changes (comma-separated)<input id="gov-change-types" placeholder="lifecycle_shift"></label>
                <label>Description<textarea id="gov-description" placeholder="Require review before low-confidence writes to main."></textarea></label>
                <label class="checkbox"><input id="gov-require-approval" type="checkbox"> Require approval when this rule matches</label>
              </div>
              <div class="actions">
                <button class="action" onclick="saveGovernance('allow', this)">Save allow rule</button>
                <button class="action subtle" onclick="saveGovernance('deny', this)">Save deny rule</button>
                <button class="action subtle" onclick="loadGovernance(this)">Refresh rules</button>
              </div>
              <div class="panel-grid">
                <label>Check actor<input id="gov-check-actor" value="agent/coder"></label>
                <label>Check action<input id="gov-check-action" value="write"></label>
                <label>Check namespace<input id="gov-check-namespace" value="main"></label>
                <label>Check input file (optional)<input id="gov-check-input-file" placeholder="/abs/path/context.json"></label>
                <label>Against ref<input id="gov-check-against" value="HEAD"></label>
              </div>
              <div class="actions">
                <button class="action" onclick="checkGovernance(this)">Check access</button>
              </div>
              <div class="split-results">
                <div id="governance-rules-result" class="result empty">Configured governance rules will appear here.</div>
                <div id="governance-check-result" class="result empty">Access-check results will appear here.</div>
              </div>
            </div>
          </details>

          <details class="subpanel">
            <summary>Remotes</summary>
            <div class="subpanel-body">
              <p class="panel-copy">Manage explicit remotes and run push, pull, or fork flows from the browser. Clicking “Use remote” will preload the form.</p>
              <div class="panel-grid">
                <label>Remote name<input id="remote-name" value="origin"></label>
                <label>Remote path<input id="remote-path" placeholder="/abs/path/to/other/store"></label>
                <label>Default branch<input id="remote-default-branch" value="main"></label>
              </div>
              <div class="actions">
                <button class="action" onclick="addRemote(this)">Add remote</button>
                <button class="action subtle" onclick="loadRemotes(this)">Refresh remotes</button>
              </div>
              <div class="panel-grid">
                <label>Push branch<input id="remote-push-branch" value="main"></label>
                <label>Push to branch<input id="remote-push-target" placeholder="optional"></label>
                <label>Pull branch<input id="remote-pull-branch" value="main"></label>
                <label>Into branch<input id="remote-pull-into" placeholder="remotes/origin/main"></label>
                <label>Fork local branch<input id="remote-fork-branch" value="agent/experiment"></label>
              </div>
              <div class="actions">
                <button class="action" onclick="pushRemote(this)">Push</button>
                <button class="action subtle" onclick="pullRemote(this)">Pull</button>
                <button class="action subtle" onclick="forkRemote(this)">Fork</button>
              </div>
              <div class="split-results">
                <div id="remote-list-result" class="result empty">Configured remotes will appear here.</div>
                <div id="remote-activity-result" class="result empty">Push, pull, and fork activity will appear here.</div>
              </div>
            </div>
          </details>

          <details class="subpanel">
            <summary>Maintenance & index</summary>
            <div class="subpanel-body">
              <p class="panel-copy">Operate persistent indexing, inspect maintenance state, and run safe prune workflows with dry-run support.</p>
              <div class="stack">
                <div>
                  <div class="panel-grid">
                    <label>Index ref<input id="ops-index-ref" value="HEAD"></label>
                    <label class="checkbox"><input id="ops-index-all-refs" type="checkbox"> Rebuild all refs</label>
                  </div>
                  <div class="actions">
                    <button class="action" onclick="loadIndexStatus(this)">Refresh index status</button>
                    <button class="action subtle" onclick="rebuildIndex(this)">Rebuild index</button>
                  </div>
                  <div id="ops-index-result" class="result empty">Index status, lag, and rebuild responses will appear here.</div>
                </div>
                <div>
                  <div class="panel-grid">
                    <label>Retention days<input id="ops-retention-days" type="number" value="7" min="0"></label>
                    <label class="checkbox"><input id="ops-prune-dry-run" type="checkbox" checked> Dry run prune first</label>
                    <label>Audit entries<input id="ops-audit-limit" type="number" value="20" min="1"></label>
                  </div>
                  <div class="actions">
                    <button class="action" onclick="loadPruneStatus(this)">Refresh maintenance status</button>
                    <button class="action subtle" onclick="runPrune(this)">Run prune</button>
                    <button class="action subtle" onclick="loadPruneAudit(this)">Refresh audit</button>
                  </div>
                  <div class="split-results">
                    <div id="ops-prune-result" class="result empty">Maintenance status and prune responses will appear here.</div>
                    <div id="ops-audit-result" class="result empty">Prune audit entries will appear here.</div>
                  </div>
                </div>
              </div>
            </div>
          </details>
        </div>
      </section>
    </main>
  </div>

  <script>
    const uiSessionToken = __CORTEX_UI_SESSION_TOKEN__;
    let defaultContext = "";
    let workspaceState = {
      meta: null,
      health: null,
      metrics: null,
      pruneStatus: null,
      scan: null,
      status: null,
      audit: null,
      minds: {
        list: null,
        status: null,
        mounts: null,
        compose: null,
        selected: "",
      },
      brainpacks: {
        list: null,
        status: null,
        selected: "",
        view: "sources",
      },
    };

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
    }

    async function api(path, options = {}) {
      const headers = { ...(options.headers || {}) };
      if (uiSessionToken) {
        headers["X-Cortex-UI-Session"] = uiSessionToken;
      }
      if (options.body !== undefined) {
        headers["Content-Type"] = "application/json";
      }
      const res = await fetch(path, { ...options, headers });
      const text = await res.text();
      let data = {};
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (err) {
          data = { status: res.ok ? "ok" : "error", error: text };
        }
      }
      if (!res.ok) {
        throw new Error(data.error || data.message || `Request failed (${res.status})`);
      }
      return data;
    }

    function fillDefaultContext(id) {
      if (defaultContext) {
        document.getElementById(id).value = defaultContext;
      }
    }

    function requireValue(id, label) {
      const value = document.getElementById(id).value.trim();
      if (!value) {
        throw new Error(`${label} is required.`);
      }
      return value;
    }

    function commaList(id) {
      return document.getElementById(id).value.split(",").map((value) => value.trim()).filter(Boolean);
    }

    function numericValue(id, fallback) {
      const raw = document.getElementById(id).value;
      const parsed = Number(raw);
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function checked(id) {
      return Boolean(document.getElementById(id).checked);
    }

    function shortRef(value) {
      if (!value) return "(empty)";
      return value.length > 14 ? `${value.slice(0, 14)}…` : value;
    }

    function percent(value) {
      const numeric = Number(value || 0);
      return `${Math.round(numeric * 100)}%`;
    }

    function renderKeyValue(obj) {
      return `<pre class="mono">${escapeHtml(JSON.stringify(obj, null, 2))}</pre>`;
    }

    function renderRawDetails(title, data) {
      return `<details class="raw"><summary>${escapeHtml(title)}</summary>${renderKeyValue(data)}</details>`;
    }

    function setResult(id, html) {
      const el = document.getElementById(id);
      el.classList.remove("empty");
      el.innerHTML = html;
    }

    function setEmpty(id, text) {
      const el = document.getElementById(id);
      el.classList.add("empty");
      el.textContent = text;
    }

    function setError(id, err) {
      setResult(id, `<div class="danger"><strong>Error</strong><p>${escapeHtml(err.message || err)}</p></div>`);
    }

    async function withBusy(trigger, label, work) {
      const button = trigger || null;
      const original = button ? button.textContent : "";
      if (button) {
        button.disabled = true;
        button.textContent = label;
      }
      try {
        return await work();
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = original;
        }
      }
    }

    function applyDefaultContext() {
      if (!defaultContext) return;
      ["review-input-file", "blame-input-file", "history-input-file", "gov-check-input-file"].forEach((id) => {
        const el = document.getElementById(id);
        if (el && !el.value) {
          el.value = defaultContext;
        }
      });
    }

    function collectStatusAlerts(status) {
      return (status?.issues || []).filter((issue) =>
        Boolean(issue.stale) ||
        (issue.missing_labels || []).length > 0 ||
        (issue.unexpected_labels || []).length > 0 ||
        (issue.missing_paths || []).length > 0
      );
    }

    function renderBlameNodes(nodes) {
      if (!nodes.length) return '<div class="empty">No matching nodes found.</div>';
      return nodes.map((item) => {
        const node = item.node || {};
        const history = item.history || {};
        const claims = item.claim_lineage || {};
        return `
          <div class="item">
            <h4>${escapeHtml(node.label || "(unnamed)")} <span class="mono">${escapeHtml(node.id || "")}</span></h4>
            <div>${(node.tags || []).map((tag) => `<span class="pill">${escapeHtml(tag)}</span>`).join("")}</div>
            <p>${escapeHtml((item.why_present || []).join(" | ") || "No immediate explanation recorded.")}</p>
            <p><strong>Versions seen:</strong> ${history.versions_seen || 0} &nbsp; <strong>Claim events:</strong> ${claims.event_count || 0}</p>
            ${history.introduced_in ? `<p><strong>Introduced:</strong> <span class="mono">${escapeHtml(history.introduced_in.version_id)}</span> ${escapeHtml(history.introduced_in.message || "")}</p>` : ""}
          </div>
        `;
      }).join("");
    }

    function currentOverviewMindState() {
      const minds = workspaceState.minds?.list?.minds || [];
      const selectedName = (workspaceState.minds?.selected || "").trim();
      const summary = minds.find((mind) => mind.mind === selectedName)
        || minds.find((mind) => mind.is_default)
        || minds[0]
        || null;
      return {
        summary,
        status: workspaceState.minds?.status || null,
        mounts: workspaceState.minds?.mounts || null,
      };
    }

    function refreshOverviewPanels() {
      if (!workspaceState.meta) {
        return;
      }
      const mindState = currentOverviewMindState();
      updateMetaCard(workspaceState.meta, workspaceState.scan, workspaceState.status, mindState.summary, mindState.status, mindState.mounts);
      document.getElementById("overview-cards").innerHTML = renderOverviewCards(
        workspaceState.meta,
        workspaceState.scan,
        workspaceState.status,
        workspaceState.audit,
        mindState.summary,
        mindState.status,
        mindState.mounts,
      );
      setResult(
        "overview-journey",
        renderJourney(workspaceState.scan, workspaceState.status, workspaceState.audit, mindState.summary, mindState.status, mindState.mounts),
      );
      setResult(
        "overview-adoptable",
        renderAdoptableSources(workspaceState.scan, mindState.summary, mindState.status, mindState.mounts),
      );
      setResult(
        "overview-health",
        renderHealthSummary(workspaceState.meta, workspaceState.health, workspaceState.scan, workspaceState.status, mindState.summary, mindState.status),
      );
      setResult("overview-metrics", renderMetricsSummary(workspaceState.metrics, workspaceState.pruneStatus));
    }

    function renderOverviewCards(meta, scan, status, audit, mindSummary, mindStatus, mindMounts) {
      const alerts = collectStatusAlerts(status).length;
      const tools = scan?.tools || [];
      const mcpReady = tools.filter((tool) => tool.cortex_mcp_configured).length;
      const mindLabel = mindStatus?.manifest?.label || mindSummary?.label || mindStatus?.mind || mindSummary?.mind || "No Mind yet";
      const mindKind = mindStatus?.manifest?.kind || mindSummary?.kind || "mind";
      const mindState = mindStatus?.is_default ?? mindSummary?.is_default ? "default" : "named";
      const mountedTargets = mindMounts?.mounted_targets || mindStatus?.mounted_targets || [];
      const proposalCount = Number(mindStatus?.proposals?.pending_proposal_count ?? mindSummary?.pending_proposal_count ?? 0);
      const packCount = Number(mindStatus?.attachment_count ?? mindSummary?.attachment_count ?? 0);
      const mountCount = Number(mindMounts?.mount_count ?? mindStatus?.mount_count ?? mindSummary?.mount_count ?? 0);
      const factCount = Number(mindStatus?.core_state?.fact_count || 0);
      return `
        <div class="card"><div>Mind</div><strong>${escapeHtml(mindLabel)}</strong><small>${escapeHtml(mindKind)} · ${escapeHtml(mindState)}</small></div>
        <div class="card"><div>Core facts</div><strong>${escapeHtml(String(factCount))}</strong><small>${escapeHtml(shortRef(mindStatus?.core_state?.graph_ref || mindSummary?.graph_ref || "(none)"))}</small></div>
        <div class="card"><div>Brainpacks</div><strong>${escapeHtml(String(packCount))}</strong><small>Attached specialist modules active in this Mind.</small></div>
        <div class="card"><div>Mounted targets</div><strong>${escapeHtml(String(mountCount))}</strong><small>${escapeHtml(mountedTargets.join(", ") || "No persisted mounts yet.")}</small></div>
        <div class="card"><div>Pending proposals</div><strong>${escapeHtml(String(proposalCount))}</strong><small>Unreviewed context waiting before it touches canonical memory.</small></div>
        <div class="card"><div>MCP ready</div><strong>${escapeHtml(String(mcpReady))}</strong><small>${escapeHtml(String(tools.length))} detected tool(s) · ${escapeHtml(String(alerts + ((audit?.issues || []).length || 0)))} attention item(s).</small></div>
      `;
    }

    function renderJourney(scan, status, audit, mindSummary, mindStatus, mindMounts) {
      const mindName = mindStatus?.mind || mindSummary?.mind || "self";
      const mountedTargets = mindMounts?.mounted_targets || mindStatus?.mounted_targets || [];
      const detectedTargets = (scan?.adoptable_targets || []).join(" ");
      const ingestCommand = detectedTargets
        ? `cortex mind ingest ${mindName} --from-detected ${detectedTargets}`
        : `cortex mind ingest ${mindName} --from-detected chatgpt claude cursor codex`;
      const alerts = collectStatusAlerts(status);
      const attentionCopy = alerts.length || (audit?.issues || []).length
        ? "At least one runtime or freshness surface still needs follow-up."
        : "The main operational question now is whether the default Mind itself needs better content or better mounts.";
      return `
        <div class="list">
          <div class="item">
            <h4>Default Mind workflow</h4>
            <p>${escapeHtml(attentionCopy)}</p>
            <div class="command-block">cortex mind status ${escapeHtml(mindName)}</div>
            <div class="command-block">cortex mind remember ${escapeHtml(mindName)} "New fact"</div>
            <div class="command-block">${escapeHtml(ingestCommand)}</div>
            <div class="command-block">cortex mind mount ${escapeHtml(mindName)} --to ${escapeHtml(mountedTargets[0] || "codex")}</div>
            <div class="command-block">cortex doctor</div>
          </div>
          <div class="item">
            <h4>Permission boundary</h4>
            <p>Detected local context stays read-only until you ingest it into a Mind. Untrusted source ingestion lands as reviewable proposals instead of mutating canonical memory directly.</p>
          </div>
        </div>
      `;
    }

    function renderAdoptableSources(scan, mindSummary, mindStatus, mindMounts) {
      const proposals = mindStatus?.proposals?.items || [];
      const attachments = mindStatus?.attached_brainpacks || [];
      const grouped = new Map();
      for (const source of (scan?.adoptable_sources || [])) {
        const bucket = grouped.get(source.target) || { importable: 0, metadataOnly: 0, paths: [] };
        if (source.importable) bucket.importable += 1;
        if (source.metadata_only) bucket.metadataOnly += 1;
        bucket.paths.push(source.path);
        grouped.set(source.target, bucket);
      }
      if (!proposals.length && !attachments.length && !grouped.size) {
        return '<div class="empty">No pending proposals, attached Brainpacks, or detected sources yet.</div>';
      }
      const items = [];
      if (mindStatus || mindSummary) {
        const mountedTargets = mindMounts?.mounted_targets || mindStatus?.mounted_targets || [];
        items.push(`
          <div class="item">
            <h4>${escapeHtml(mindStatus?.manifest?.label || mindSummary?.label || mindStatus?.mind || mindSummary?.mind || "Mind queue")}</h4>
            <div class="meta-row">
              <span class="pill good">${escapeHtml(String(proposals.length))} pending proposal(s)</span>
              <span class="pill info">${escapeHtml(String(attachments.length))} attached Brainpack(s)</span>
              <span class="pill">${escapeHtml(String(mountedTargets.length))} mounted target(s)</span>
            </div>
            <p class="tiny">${escapeHtml(mountedTargets.join(", ") || "No persisted mounts yet.")}</p>
          </div>
        `);
      }
      for (const proposal of proposals.slice(0, 3)) {
        items.push(`
          <div class="item">
            <h4>${escapeHtml(proposal.proposal_id || "proposal")}</h4>
            <div class="meta-row">
              <span class="pill warn">${escapeHtml(proposal.status || "pending_review")}</span>
              <span class="pill">${escapeHtml(String(proposal.proposed_source_count || 0))} source(s)</span>
              <span class="pill">${escapeHtml(String(proposal.graph_node_count || 0))} node(s)</span>
            </div>
            <p class="tiny">${escapeHtml(proposal.created_at || proposal.path || "Queued for review.")}</p>
          </div>
        `);
      }
      for (const [target, info] of Array.from(grouped.entries())) {
        items.push(`
          <div class="item">
            <h4>${escapeHtml(target)}</h4>
            <div class="meta-row">
              <span class="pill good">${escapeHtml(String(info.importable))} importable</span>
              <span class="pill info">${escapeHtml(String(info.metadataOnly))} metadata only</span>
            </div>
            <p class="tiny">${escapeHtml(info.paths.slice(0, 2).join(" · "))}</p>
          </div>
        `);
      }
      return `<div class="list">${items.join("")}</div>`;
    }

    function renderHealthSummary(meta, health, scan, status, mindSummary, mindStatus) {
      const alerts = collectStatusAlerts(status);
      const index = meta?.index || {};
      return `
        <div class="list">
          <div class="item">
            <h4>Mind & workspace state</h4>
            <p><strong>Mind:</strong> ${escapeHtml(mindStatus?.manifest?.label || mindSummary?.label || mindStatus?.mind || mindSummary?.mind || "No Mind selected")}</p>
            <p><strong>Branch:</strong> <span class="mono">${escapeHtml(mindStatus?.branches?.current_branch || mindSummary?.current_branch || meta?.current_branch || "main")}</span></p>
            <p><strong>Graph ref:</strong> <span class="mono">${escapeHtml(mindStatus?.core_state?.graph_ref || mindSummary?.graph_ref || "(none)")}</span></p>
            <p><strong>Default policy:</strong> ${escapeHtml(mindStatus?.policies?.default_disclosure || mindSummary?.default_policy || "professional")}</p>
            <p><strong>Workspace:</strong> <span class="mono">${escapeHtml(meta?.workspace_dir || "(unknown)")}</span></p>
            <p><strong>Store:</strong> <span class="mono">${escapeHtml(meta?.store_dir || "(unknown)")}</span></p>
            <p><strong>HEAD:</strong> <span class="mono">${escapeHtml(shortRef(meta?.head || "(empty)"))}</span></p>
          </div>
          <div class="item">
            <h4>Release & index</h4>
            <p><strong>Release:</strong> ${escapeHtml(meta?.release?.project_version || "dev")} (${escapeHtml(meta?.release?.maturity || "local")})</p>
            <p><strong>Backend:</strong> ${escapeHtml(meta?.backend || "filesystem")}</p>
            <p><strong>Index mode:</strong> ${escapeHtml(index.persistent ? "persistent" : "graph checkout")}</p>
            <p>${escapeHtml(index.message || "Index is ready.")}</p>
            <p><strong>Open alerts:</strong> ${escapeHtml(String(alerts.length))}</p>
          </div>
        </div>
        ${renderRawDetails("Raw health payload", health)}
      `;
    }

    function renderMetricsSummary(metrics, pruneStatus) {
      return `
        <div class="list">
          <div class="item">
            <h4>Observability</h4>
            <p><strong>Requests:</strong> ${escapeHtml(String(metrics?.requests_total ?? 0))}</p>
            <p><strong>Errors:</strong> ${escapeHtml(String(metrics?.errors_total ?? 0))}</p>
            <p><strong>Backend:</strong> ${escapeHtml(metrics?.backend || "filesystem")}</p>
            <p><strong>Current branch:</strong> ${escapeHtml(metrics?.current_branch || "main")}</p>
          </div>
          <div class="item">
            <h4>Maintenance</h4>
            <p><strong>Stale merge artifacts:</strong> ${escapeHtml(String((pruneStatus?.stale_merge_artifacts || []).length))}</p>
            <p><strong>Pending prune audit entries:</strong> ${escapeHtml(String((pruneStatus?.audit_entries || []).length || 0))}</p>
          </div>
        </div>
        ${renderRawDetails("Raw metrics payload", metrics)}
      `;
    }

    function updateMetaCard(meta, scan, status, mindSummary, mindStatus, mindMounts) {
      const alerts = collectStatusAlerts(status).length;
      const mindLabel = mindStatus?.manifest?.label || mindSummary?.label || mindStatus?.mind || mindSummary?.mind || "No Mind";
      const mountedTargets = mindMounts?.mounted_targets || mindStatus?.mounted_targets || [];
      const pending = mindStatus?.proposals?.pending_proposal_count ?? mindSummary?.pending_proposal_count ?? 0;
      document.getElementById("meta-card").innerHTML = `
        <div class="meta-block"><strong>Workspace</strong><div class="mono">${escapeHtml(meta?.workspace_dir || "(unknown)")}</div></div>
        <div class="meta-block"><strong>Store</strong><div class="mono">${escapeHtml(meta?.store_dir || "(unknown)")}</div></div>
        <div class="meta-block"><strong>Mind</strong><div class="mono">${escapeHtml(mindLabel)}</div></div>
        <div class="meta-block"><strong>Mounted</strong><div class="mono">${escapeHtml(String(mountedTargets.length))}</div></div>
        <div class="meta-block"><strong>Pending</strong><div class="mono">${escapeHtml(String(pending))}</div></div>
        <div class="meta-block"><strong>Needs attention</strong><div class="mono">${escapeHtml(String(alerts))}</div></div>
      `;
    }

    function renderToolsSummary(scan) {
      const tools = scan?.tools || [];
      const mcpReady = tools.filter((tool) => tool.cortex_mcp_configured).length;
      const metadataOnly = (scan?.adoptable_sources || []).filter((source) => source.metadata_only).length;
      return `
        <div class="cards">
          <div class="card"><div>Targets</div><strong>${escapeHtml(String(tools.length))}</strong><small>Local tools or artifacts Cortex can inspect right now.</small></div>
          <div class="card"><div>MCP ready</div><strong>${escapeHtml(String(mcpReady))}</strong><small>Targets already configured to consume Cortex over MCP.</small></div>
          <div class="card"><div>Metadata-only</div><strong>${escapeHtml(String(metadataOnly))}</strong><small>Configs detected for visibility only.</small></div>
        </div>
      `;
    }

    function renderTools(scan, status) {
      const tools = [...(scan?.tools || [])].sort((left, right) => (right.fact_count || 0) - (left.fact_count || 0));
      const statusMap = new Map((status?.issues || []).map((issue) => [issue.target, issue]));
      if (!tools.length) {
        document.getElementById("tools-list").innerHTML = '<div class="empty">No local tools detected yet.</div>';
        return;
      }
      document.getElementById("tools-list").innerHTML = tools.map((tool) => {
        const issue = statusMap.get(tool.target);
        const hasAlert = issue && (
          Boolean(issue.stale) ||
          (issue.missing_labels || []).length > 0 ||
          (issue.unexpected_labels || []).length > 0 ||
          (issue.missing_paths || []).length > 0
        );
        const statusPill = tool.cortex_mcp_configured
          ? '<span class="pill good">Cortex MCP configured</span>'
          : hasAlert
            ? '<span class="pill warn">Needs attention</span>'
            : '<span class="pill info">File-based sync</span>';
        const warningLine = hasAlert
          ? `<p class="warning">${escapeHtml([
              issue.stale ? "stale target" : "",
              (issue.missing_labels || []).length ? `${issue.missing_labels.length} missing label(s)` : "",
              (issue.unexpected_labels || []).length ? `${issue.unexpected_labels.length} unexpected label(s)` : "",
              (issue.missing_paths || []).length ? `${issue.missing_paths.length} missing path(s)` : "",
            ].filter(Boolean).join(" · "))}</p>`
          : "";
        return `
          <article class="tool-card">
            <div class="tool-head">
              <div>
                <h4>${escapeHtml(tool.name || tool.target)}</h4>
                <p class="tool-note">${escapeHtml(tool.note || "No note available.")}</p>
              </div>
              <div>${statusPill}</div>
            </div>
            <div class="meter"><span style="width:${escapeHtml(String(Math.max(4, Math.round((tool.coverage || 0) * 100))))}%"></span></div>
            <div class="tool-stats">
              <div class="tool-stat"><strong>${escapeHtml(String(tool.fact_count || 0))}</strong><span>facts</span></div>
              <div class="tool-stat"><strong>${escapeHtml(percent(tool.coverage || 0))}</strong><span>coverage</span></div>
              <div class="tool-stat"><strong>${escapeHtml(String(tool.mcp_server_count || 0))}</strong><span>MCP servers</span></div>
            </div>
            ${warningLine}
            <details class="raw">
              <summary>Files</summary>
              <div class="path-list">
                ${(tool.paths || []).map((path) => `<div class="mono">${escapeHtml(path)}</div>`).join("") || '<div class="mono">(no local path recorded)</div>'}
              </div>
            </details>
          </article>
        `;
      }).join("");
    }

    function populateMindSelector(data) {
      const select = document.getElementById("mind-select");
      const minds = data?.minds || [];
      const previous = workspaceState.minds?.selected || "";
      if (!minds.length) {
        select.innerHTML = "";
        workspaceState.minds.selected = "";
        return;
      }
      const selected = minds.some((mind) => mind.mind === previous)
        ? previous
        : (minds.find((mind) => mind.is_default)?.mind || minds[0].mind);
      workspaceState.minds.selected = selected;
      select.innerHTML = minds.map((mind) => {
        const isSelected = mind.mind === selected ? ' selected' : '';
        const label = mind.is_default ? `${mind.mind} (default)` : mind.mind;
        return `<option value="${escapeHtml(mind.mind)}"${isSelected}>${escapeHtml(label)}</option>`;
      }).join("");
    }

    function preferredMindTargets(status, mounts) {
      const ordered = [];
      const seen = new Set();
      function add(target) {
        const value = String(target || "").trim();
        if (!value || seen.has(value)) return;
        seen.add(value);
        ordered.push(value);
      }
      ["chatgpt", "claude-code", "codex", "cursor", "hermes", "openclaw"].forEach(add);
      (status?.mounted_targets || []).forEach(add);
      (status?.attached_mounted_targets || []).forEach(add);
      (mounts?.mounted_targets || []).forEach(add);
      (status?.attached_brainpacks || []).forEach((pack) => {
        (pack?.activation?.targets || []).forEach(add);
      });
      return ordered;
    }

    function populateMindTargetSelector(status, mounts) {
      const select = document.getElementById("mind-compose-target");
      const options = preferredMindTargets(status, mounts);
      const current = (select.value || workspaceState.minds.compose?.target || "").trim();
      const selected = options.includes(current) ? current : (options[0] || "chatgpt");
      select.innerHTML = options.map((target) => {
        const isSelected = target === selected ? ' selected' : '';
        return `<option value="${escapeHtml(target)}"${isSelected}>${escapeHtml(target)}</option>`;
      }).join("");
      workspaceState.minds.compose = { ...(workspaceState.minds.compose || {}), target: selected };
    }

    function renderMindSummary(status, mounts) {
      const policies = status?.policies || {};
      const branches = status?.branches || {};
      return `
        <div class="cards">
          <div class="card"><div>Mind</div><strong>${escapeHtml(status?.manifest?.label || status?.mind || "(unknown)")}</strong><small>${escapeHtml(status?.manifest?.kind || "mind")} · ${escapeHtml(status?.is_default ? "default" : "named")}</small></div>
          <div class="card"><div>Core facts</div><strong>${escapeHtml(String(status?.core_state?.fact_count || 0))}</strong><small>${escapeHtml(String(status?.core_state?.edge_count || 0))} graph edges in the active core state.</small></div>
          <div class="card"><div>Brainpacks</div><strong>${escapeHtml(String(status?.attachment_count || 0))}</strong><small>${escapeHtml(String(status?.attached_mount_count || 0))} attached pack mounts across specialist modules.</small></div>
          <div class="card"><div>Mounted targets</div><strong>${escapeHtml(String(mounts?.mount_count || status?.mount_count || 0))}</strong><small>${escapeHtml(((mounts?.mounted_targets || status?.mounted_targets || []).join(", ")) || "No persisted mounts yet.")}</small></div>
          <div class="card"><div>Branch</div><strong>${escapeHtml(branches?.current_branch || status?.manifest?.current_branch || "main")}</strong><small>default: ${escapeHtml(branches?.default_branch || status?.manifest?.default_branch || "main")}</small></div>
          <div class="card"><div>Policy</div><strong>${escapeHtml(policies?.default_disclosure || status?.default_disclosure || "professional")}</strong><small>${escapeHtml(String(Object.keys(policies?.target_overrides || {}).length))} target override(s).</small></div>
        </div>
      `;
    }

    function renderMindCoreState(status) {
      const core = status?.core_state || {};
      const previewNodes = core.preview_nodes || [];
      return `
        <div class="list">
          <div class="item">
            <h4>Core state</h4>
            <p><strong>Graph ref:</strong> <span class="mono">${escapeHtml(core.graph_ref || status?.graph_ref || "(none)")}</span></p>
            <p><strong>Source:</strong> ${escapeHtml(core.graph_source || "unknown")}</p>
            <p><strong>Categories:</strong> ${escapeHtml((core.categories || []).join(", ") || "No categories recorded.")}</p>
          </div>
          <div class="item">
            <h4>Preview facts</h4>
            ${
              previewNodes.length
                ? `<div class="list">${previewNodes.map((node) => `
                    <div class="item">
                      <h4>${escapeHtml(node.label || "(unnamed)")} <span class="mono">${escapeHtml(node.id || "")}</span></h4>
                      <div>${(node.tags || []).map((tag) => `<span class="pill">${escapeHtml(tag)}</span>`).join("")}</div>
                      <p>${escapeHtml(node.brief || "No summary available.")}</p>
                      <p><strong>Confidence:</strong> ${escapeHtml(String(node.confidence ?? 0))}</p>
                    </div>
                  `).join("")}</div>`
                : '<div class="empty">No core-state facts yet. Ingest or remember something into this Mind first.</div>'
            }
          </div>
        </div>
      `;
    }

    function renderMindAttachments(status) {
      const attachments = status?.attached_brainpacks || [];
      if (!attachments.length) {
        return '<div class="empty">No Brainpacks are attached to this Mind yet.</div>';
      }
      return `<div class="list">${attachments.map((pack) => `
        <div class="item">
          <h4>${escapeHtml(pack.pack || pack.id || "(pack)")} <span class="mono">${escapeHtml(pack.pack_ref || "")}</span></h4>
          <div class="meta-row">
            <span class="pill">${escapeHtml(pack.compile_status || "idle")}</span>
            <span class="pill">${escapeHtml(String(pack.priority ?? 0))} priority</span>
            <span class="pill ${pack.activation?.always_on ? "good" : "info"}">${escapeHtml(pack.activation?.always_on ? "always on" : "selective")}</span>
          </div>
          <p>${escapeHtml(pack.pack_description || "No description recorded.")}</p>
          <p><strong>Activation targets:</strong> ${escapeHtml((pack.activation?.targets || []).join(", ") || "all compatible targets")}</p>
          <p><strong>Task terms:</strong> ${escapeHtml((pack.activation?.task_terms || []).join(", ") || "none")}</p>
          <p><strong>Mounted targets:</strong> ${escapeHtml((pack.mounted_targets || []).join(", ") || "none")}</p>
        </div>
      `).join("")}</div>`;
    }

    function renderMindBranchPolicy(status) {
      const branches = status?.branches || {};
      const branchRecords = branches.branch_records || {};
      const policies = status?.policies || {};
      const branchItems = Object.entries(branchRecords);
      const policyOverrides = Object.entries(policies.target_overrides || {});
      const approvalRules = Object.entries(policies.approval_rules || {});
      return `
        <div class="list">
          <div class="item">
            <h4>Branch status</h4>
            <p><strong>Current:</strong> <span class="mono">${escapeHtml(branches.current_branch || status?.manifest?.current_branch || "main")}</span></p>
            <p><strong>Default:</strong> <span class="mono">${escapeHtml(branches.default_branch || status?.manifest?.default_branch || "main")}</span></p>
            <p><strong>Current head:</strong> <span class="mono">${escapeHtml(shortRef(branches.current_branch_head || ""))}</span></p>
            ${
              branchItems.length
                ? `<div class="path-list">${branchItems.map(([name, record]) => `
                    <div><strong>${escapeHtml(name)}</strong><br><span class="mono">${escapeHtml(shortRef(record.head || ""))}</span><br><span class="tiny">${escapeHtml(record.created_at || "")}</span></div>
                  `).join("")}</div>`
                : '<div class="empty">No branch records yet.</div>'
            }
          </div>
          <div class="item">
            <h4>Policy status</h4>
            <p><strong>Default disclosure:</strong> ${escapeHtml(policies.default_disclosure || status?.default_disclosure || "professional")}</p>
            <p><strong>Target overrides:</strong> ${escapeHtml(String(policyOverrides.length))}</p>
            ${policyOverrides.length ? `<div class="path-list">${policyOverrides.map(([name, value]) => `<div><strong>${escapeHtml(name)}</strong><br>${escapeHtml(value)}</div>`).join("")}</div>` : '<p class="tiny">No target-specific disclosure overrides.</p>'}
            <p><strong>Approval rules:</strong> ${escapeHtml(String(approvalRules.length))}</p>
            ${approvalRules.length ? `<div class="path-list">${approvalRules.map(([name, value]) => `<div><strong>${escapeHtml(name)}</strong><br>${escapeHtml(String(value))}</div>`).join("")}</div>` : '<p class="tiny">No explicit approval rules recorded.</p>'}
          </div>
        </div>
      `;
    }

    function renderMindMounts(mounts) {
      if (!(mounts?.mounts || []).length) {
        return '<div class="empty">This Mind has not been mounted into any targets yet.</div>';
      }
      return `<div class="list">${(mounts.mounts || []).map((item) => `
        <div class="item">
          <h4>${escapeHtml(item.target || "(target)")}</h4>
          <div class="meta-row">
            <span class="pill">${escapeHtml(item.mode || (item.smart ? "smart" : "full"))}</span>
            <span class="pill">${escapeHtml(item.policy || "default policy")}</span>
            <span class="pill">${escapeHtml(item.consume_as || "context")}</span>
          </div>
          <p><strong>Task:</strong> ${escapeHtml(item.task || "none")}</p>
          <p><strong>Mounted:</strong> ${escapeHtml(item.mounted_at || "unknown")}</p>
          <p><strong>Project dir:</strong> <span class="mono">${escapeHtml(item.project_dir || "")}</span></p>
          ${
            (item.paths || []).length
              ? `<details class="raw"><summary>Paths</summary><div class="path-list">${item.paths.map((path) => `<div class="mono">${escapeHtml(path)}</div>`).join("")}</div></details>`
              : ""
          }
        </div>
      `).join("")}</div>`;
    }

    function renderMindComposePreview(data) {
      const included = data?.included_brainpacks || [];
      const skipped = data?.skipped_brainpacks || [];
      const markdown = data?.context_markdown || JSON.stringify(data?.target_payload || {}, null, 2);
      return `
        <div class="list">
          <div class="item">
            <h4>Compose summary</h4>
            <p><strong>Target:</strong> ${escapeHtml(data?.target || "(unknown)")}</p>
            <p><strong>Task:</strong> ${escapeHtml(data?.task || "none")}</p>
            <p><strong>Base graph:</strong> <span class="mono">${escapeHtml(data?.base_graph_ref || "(none)")}</span> · ${escapeHtml(data?.base_graph_source || "unknown")}</p>
            <p><strong>Included Brainpacks:</strong> ${escapeHtml(included.map((item) => item.pack).join(", ") || "none")}</p>
            <p><strong>Skipped Brainpacks:</strong> ${escapeHtml(skipped.map((item) => `${item.pack}:${item.selection_reason}`).join(", ") || "none")}</p>
            <div class="meta-row">
              <span class="pill">${escapeHtml(String(data?.fact_count || 0))} routed facts</span>
              ${(data?.route_tags || []).map((tag) => `<span class="pill">${escapeHtml(tag)}</span>`).join("")}
            </div>
          </div>
          <div class="item">
            <h4>Rendered preview</h4>
            <pre>${escapeHtml(markdown)}</pre>
          </div>
        </div>
      `;
    }

    async function loadMinds(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        try {
          const data = await api("/api/minds");
          workspaceState.minds.list = data;
          populateMindSelector(data);
          if (!(data.minds || []).length) {
            workspaceState.minds.status = null;
            workspaceState.minds.mounts = null;
            setEmpty("mind-summary", "No Minds yet. Create one with `cortex mind init`.");
            setEmpty("mind-core", "Once a Mind exists, Cortex will show its base brain-state here.");
            setEmpty("mind-attachments", "Attached Brainpacks will appear here.");
            setEmpty("mind-branch-policy", "Branch and policy status will appear here.");
            setEmpty("mind-mounts", "Mounted targets will appear here.");
            setEmpty("mind-compose", "Compose preview will appear here.");
            refreshOverviewPanels();
            return;
          }
          await loadMindView();
        } catch (err) {
          setError("mind-summary", err);
          setError("mind-core", err);
          setError("mind-attachments", err);
          setError("mind-branch-policy", err);
          setError("mind-mounts", err);
          setError("mind-compose", err);
        }
      });
    }

    async function loadMindView(trigger) {
      return withBusy(trigger, "Loading...", async () => {
        try {
          const select = document.getElementById("mind-select");
          const mindName = (select?.value || workspaceState.minds.selected || "").trim();
          if (!mindName) {
            setEmpty("mind-summary", "No Mind selected yet.");
            setEmpty("mind-core", "Select a Mind first.");
            setEmpty("mind-attachments", "Select a Mind first.");
            setEmpty("mind-branch-policy", "Select a Mind first.");
            setEmpty("mind-mounts", "Select a Mind first.");
            setEmpty("mind-compose", "Select a Mind first.");
            return;
          }
          workspaceState.minds.selected = mindName;
          const [status, mounts] = await Promise.all([
            api(`/api/minds/status?name=${encodeURIComponent(mindName)}`),
            api(`/api/minds/mounts?name=${encodeURIComponent(mindName)}`),
          ]);
          workspaceState.minds.status = status;
          workspaceState.minds.mounts = mounts;
          populateMindTargetSelector(status, mounts);
          refreshOverviewPanels();
          setResult("mind-summary", renderMindSummary(status, mounts));
          setResult("mind-core", `${renderMindCoreState(status)}${renderRawDetails("Raw core-state payload", status.core_state || {})}`);
          setResult("mind-attachments", `${renderMindAttachments(status)}${renderRawDetails("Raw attachment payload", { attached_brainpacks: status.attached_brainpacks || [] })}`);
          setResult("mind-branch-policy", `${renderMindBranchPolicy(status)}${renderRawDetails("Raw branch/policy payload", { branches: status.branches || {}, policies: status.policies || {} })}`);
          setResult("mind-mounts", `${renderMindMounts(mounts)}${renderRawDetails("Raw mounts payload", mounts)}`);
          await previewMindCompose();
        } catch (err) {
          setError("mind-summary", err);
          setError("mind-core", err);
          setError("mind-attachments", err);
          setError("mind-branch-policy", err);
          setError("mind-mounts", err);
          setError("mind-compose", err);
        }
      });
    }

    async function previewMindCompose(trigger) {
      return withBusy(trigger, "Composing...", async () => {
        try {
          const mindName = (document.getElementById("mind-select")?.value || workspaceState.minds.selected || "").trim();
          if (!mindName) {
            setEmpty("mind-compose", "Select a Mind first.");
            return;
          }
          const target = document.getElementById("mind-compose-target")?.value?.trim() || "chatgpt";
          const task = document.getElementById("mind-compose-task")?.value?.trim() || "";
          const maxChars = numericValue("mind-compose-max-chars", 900);
          const data = await api("/api/minds/compose", {
            method: "POST",
            body: JSON.stringify({
              name: mindName,
              target,
              task,
              max_chars: maxChars,
              smart: true,
            }),
          });
          workspaceState.minds.compose = data;
          setResult("mind-compose", `${renderMindComposePreview(data)}${renderRawDetails("Raw compose payload", data)}`);
        } catch (err) {
          setError("mind-compose", err);
        }
      });
    }

    function populateBrainpackSelector(data) {
      const select = document.getElementById("brainpack-select");
      const packs = data?.packs || [];
      const previous = workspaceState.brainpacks?.selected || "";
      if (!packs.length) {
        select.innerHTML = "";
        workspaceState.brainpacks.selected = "";
        return;
      }
      const selected = packs.some((pack) => pack.pack === previous) ? previous : packs[0].pack;
      workspaceState.brainpacks.selected = selected;
      select.innerHTML = packs.map((pack) => {
        const isSelected = pack.pack === selected ? ' selected' : '';
        return `<option value="${escapeHtml(pack.pack)}"${isSelected}>${escapeHtml(pack.pack)}</option>`;
      }).join("");
    }

    function brainpackViewEndpoint(view, packName) {
      const encodedName = encodeURIComponent(packName);
      if (view === "concepts") return `/api/packs/concepts?name=${encodedName}`;
      if (view === "claims") return `/api/packs/claims?name=${encodedName}`;
      if (view === "unknowns") return `/api/packs/unknowns?name=${encodedName}`;
      if (view === "artifacts") return `/api/packs/artifacts?name=${encodedName}`;
      return `/api/packs/sources?name=${encodedName}`;
    }

    function renderBrainpackSummary(status) {
      const lintSummary = status?.lint_summary || {};
      return `
        <div class="cards">
          <div class="card"><div>Sources</div><strong>${escapeHtml(String(status?.source_count || 0))}</strong><small>${escapeHtml(String(status?.text_source_count || 0))} readable and compiled.</small></div>
          <div class="card"><div>Concepts</div><strong>${escapeHtml(String(status?.graph_nodes || 0))}</strong><small>${escapeHtml(String(status?.graph_edges || 0))} relationships in the concept graph.</small></div>
          <div class="card"><div>Claims</div><strong>${escapeHtml(String(status?.claim_count || 0))}</strong><small>Provisional claims extracted from the pack.</small></div>
          <div class="card"><div>Unknowns</div><strong>${escapeHtml(String(status?.unknown_count || 0))}</strong><small>Open questions or gaps still worth exploring.</small></div>
          <div class="card"><div>Artifacts</div><strong>${escapeHtml(String(status?.artifact_count || 0))}</strong><small>Generated outputs filed back into the pack.</small></div>
          <div class="card"><div>Lint</div><strong>${escapeHtml(String(status?.lint_status || "not_run"))}</strong><small>${escapeHtml(String(lintSummary.total_findings || 0))} findings · ${escapeHtml(String(lintSummary.high || 0))} high.</small></div>
        </div>
      `;
    }

    function renderBrainpackSources(data) {
      if (!(data?.sources || []).length) {
        return '<div class="empty">No sources ingested into this Brainpack yet.</div>';
      }
      return `<div class="list">${(data.sources || []).map((item) => `
        <div class="item">
          <h4>${escapeHtml(item.title || item.source_path || "Source")}</h4>
          <div class="meta-row">
            <span class="pill">${escapeHtml(item.type || "source")}</span>
            <span class="pill">${escapeHtml(item.mode || "copy")}</span>
            <span class="pill ${item.readable ? "good" : "warn"}">${escapeHtml(item.readable ? "readable" : "not compiled")}</span>
          </div>
          <p>${escapeHtml(item.summary || item.preview || "No summary available yet.")}</p>
          <p class="mono">${escapeHtml(item.source_path || "")}</p>
          ${item.wiki_path ? `<p><strong>Wiki page:</strong> <span class="mono">${escapeHtml(item.wiki_path)}</span></p>` : ""}
        </div>
      `).join("")}</div>`;
    }

    function renderBrainpackConcepts(data) {
      if (!(data?.concepts || []).length) {
        return '<div class="empty">No compiled concepts yet. Run `cortex pack compile` first.</div>';
      }
      return `<div class="list">${(data.concepts || []).map((item) => `
        <div class="item">
          <h4>${escapeHtml(item.label || "(unnamed)")} <span class="mono">${escapeHtml(item.id || "")}</span></h4>
          <div>${(item.tags || []).map((tag) => `<span class="pill">${escapeHtml(tag)}</span>`).join("")}</div>
          <p>${escapeHtml(item.brief || "No description available.")}</p>
          <p><strong>Confidence:</strong> ${escapeHtml(String(item.confidence ?? 0))} · <strong>Degree:</strong> ${escapeHtml(String(item.degree ?? 0))} · <strong>Quotes:</strong> ${escapeHtml(String(item.source_quote_count ?? 0))}</p>
        </div>
      `).join("")}</div>`;
    }

    function renderBrainpackClaims(data) {
      if (!(data?.claims || []).length) {
        return '<div class="empty">No claim candidates recorded for this Brainpack yet.</div>';
      }
      return `<div class="list">${(data.claims || []).map((item) => `
        <div class="item">
          <h4>${escapeHtml(item.label || "(claim)")}</h4>
          <div>${(item.tags || []).map((tag) => `<span class="pill">${escapeHtml(tag)}</span>`).join("")}</div>
          <p>${escapeHtml(item.brief || "No summary available.")}</p>
          <p><strong>Confidence:</strong> ${escapeHtml(String(item.confidence ?? 0))} · <strong>Source quotes:</strong> ${escapeHtml(String((item.source_quotes || []).length))}</p>
        </div>
      `).join("")}</div>`;
    }

    function renderBrainpackUnknowns(data) {
      if (!(data?.unknowns || []).length) {
        return '<div class="empty">No open questions are recorded for this Brainpack right now.</div>';
      }
      return `<div class="list">${(data.unknowns || []).map((item) => `
        <div class="item">
          <h4>${escapeHtml(item.question || item.title || "(unknown)")}</h4>
          <div class="meta-row">
            ${item.type ? `<span class="pill">${escapeHtml(item.type)}</span>` : ""}
            ${item.source_path ? `<span class="pill">${escapeHtml(item.source_path.split("/").slice(-1)[0])}</span>` : ""}
          </div>
          <p>${escapeHtml(item.reason || "No reason recorded.")}</p>
        </div>
      `).join("")}</div>`;
    }

    function renderBrainpackArtifacts(data) {
      if (!(data?.artifacts || []).length) {
        return '<div class="empty">No artifacts have been filed back into this Brainpack yet.</div>';
      }
      return `<div class="list">${(data.artifacts || []).map((item) => `
        <div class="item">
          <h4>${escapeHtml(item.title || "(artifact)")}</h4>
          <p class="mono">${escapeHtml(item.path || "")}</p>
          <p>${escapeHtml(item.preview || "No preview available.")}</p>
          <p><strong>Updated:</strong> ${escapeHtml(item.updated_at || "unknown")} · <strong>Size:</strong> ${escapeHtml(String(item.size_bytes || 0))} bytes</p>
        </div>
      `).join("")}</div>`;
    }

    function renderBrainpackSection(view, data) {
      if (view === "concepts") return renderBrainpackConcepts(data);
      if (view === "claims") return renderBrainpackClaims(data);
      if (view === "unknowns") return renderBrainpackUnknowns(data);
      if (view === "artifacts") return renderBrainpackArtifacts(data);
      return renderBrainpackSources(data);
    }

    function activateBrainpackView(view, trigger) {
      workspaceState.brainpacks.view = view;
      document.querySelectorAll("#brainpack-tabs button").forEach((button) => {
        button.classList.toggle("active", button.dataset.brainpackView === view);
      });
      if (trigger) {
        loadBrainpackView(trigger);
      }
    }

    function populateContextTargets(scan) {
      const select = document.getElementById("tools-context-target");
      const current = select.value;
      const tools = scan?.tools || [];
      select.innerHTML = tools.map((tool) => {
        const value = tool.target || "";
        const selected = value === current || (!current && tools[0]?.target === value) ? ' selected' : '';
        return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(tool.name || value)}</option>`;
      }).join("");
    }

    function renderTargetPreview(data) {
      const markdown = data.context_markdown || JSON.stringify(data.target_payload || {}, null, 2);
      return `
        <div class="list">
          <div class="item">
            <h4>${escapeHtml(data.name || data.target)}</h4>
            <p><strong>Mode:</strong> ${escapeHtml(data.mode || "smart")} · <strong>Policy:</strong> ${escapeHtml(data.policy || "full")} · <strong>Consumes as:</strong> ${escapeHtml(data.consume_as || "context")}</p>
            <div class="meta-row">
              <span class="pill">${escapeHtml(String(data.fact_count || 0))} routed facts</span>
              ${(data.route_tags || []).map((tag) => `<span class="pill">${escapeHtml(tag)}</span>`).join("")}
            </div>
            <details class="raw">
              <summary>Files</summary>
              <div class="path-list">
                ${(data.paths || []).map((path) => `<div class="mono">${escapeHtml(path)}</div>`).join("") || '<div class="mono">(no path for this target)</div>'}
              </div>
            </details>
          </div>
          <div class="item">
            <h4>Rendered context</h4>
            <pre>${escapeHtml(markdown)}</pre>
          </div>
        </div>
      `;
    }

    function renderAuditStatus(status) {
      const alerts = collectStatusAlerts(status);
      if (!alerts.length) {
        return '<div class="item"><h4>All synced</h4><p>Every detected target currently matches the routed context Cortex expects to see.</p></div>';
      }
      return `<div class="list">${alerts.map((issue) => `
        <div class="item">
          <h4>${escapeHtml(issue.name || issue.target)}</h4>
          <p>${escapeHtml(issue.stale ? "Target is stale." : "Target differs from the expected routed context.")}</p>
          ${(issue.missing_labels || []).length ? `<p><strong>Missing labels:</strong> ${escapeHtml(issue.missing_labels.join(", "))}</p>` : ""}
          ${(issue.unexpected_labels || []).length ? `<p><strong>Unexpected labels:</strong> ${escapeHtml(issue.unexpected_labels.join(", "))}</p>` : ""}
          ${(issue.missing_paths || []).length ? `<p><strong>Missing paths:</strong> ${escapeHtml(issue.missing_paths.join(", "))}</p>` : ""}
        </div>
      `).join("")}</div>`;
    }

    function renderAuditIssues(audit) {
      if (!(audit?.issues || []).length) {
        return '<div class="item"><h4>No audit issues</h4><p>Cortex did not find any missing-context or portability issues that require immediate intervention.</p></div>';
      }
      return `<div class="list">${(audit.issues || []).map((issue) => `
        <div class="item">
          <h4>${escapeHtml(issue.target || issue.type || "Issue")}</h4>
          <p>${escapeHtml(issue.message || "No message provided.")}</p>
          ${(issue.missing_labels || []).length ? `<p><strong>Missing labels:</strong> ${escapeHtml(issue.missing_labels.join(", "))}</p>` : ""}
        </div>
      `).join("")}</div>`;
    }

    async function loadBrainpacks(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        try {
          const data = await api("/api/packs");
          workspaceState.brainpacks.list = data;
          populateBrainpackSelector(data);
          if (!(data.packs || []).length) {
            setEmpty("brainpack-summary", "No Brainpacks yet. Create one with `cortex pack init`, ingest sources, then compile it.");
            setEmpty("brainpack-content", "Once a Brainpack exists, Cortex will show its sources, concepts, claims, unknowns, and artifacts here.");
            return;
          }
          await loadBrainpackView();
        } catch (err) {
          setError("brainpack-summary", err);
          setError("brainpack-content", err);
        }
      });
    }

    async function loadBrainpackView(trigger) {
      return withBusy(trigger, "Loading...", async () => {
        try {
          const select = document.getElementById("brainpack-select");
          const packName = (select?.value || workspaceState.brainpacks.selected || "").trim();
          if (!packName) {
            setEmpty("brainpack-summary", "No Brainpack selected yet.");
            setEmpty("brainpack-content", "Select a Brainpack first.");
            return;
          }
          workspaceState.brainpacks.selected = packName;
          const view = workspaceState.brainpacks.view || "sources";
          const [status, detail] = await Promise.all([
            api(`/api/packs/status?name=${encodeURIComponent(packName)}`),
            api(brainpackViewEndpoint(view, packName)),
          ]);
          workspaceState.brainpacks.status = status;
          setResult("brainpack-summary", renderBrainpackSummary(status));
          setResult("brainpack-content", `${renderBrainpackSection(view, detail)}${renderRawDetails(`Raw ${view} payload`, detail)}`);
        } catch (err) {
          setError("brainpack-summary", err);
          setError("brainpack-content", err);
        }
      });
    }

    async function loadWorkspace(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        const [meta, health, metrics, pruneStatus, scan, status, audit] = await Promise.all([
          api("/api/meta"),
          api("/api/health"),
          api("/api/metrics"),
          api("/api/prune/status"),
          api("/api/portability/scan"),
          api("/api/portability/status"),
          api("/api/portability/audit"),
        ]);
        workspaceState = {
          ...workspaceState,
          meta,
          health,
          metrics,
          pruneStatus,
          scan,
          status,
          audit,
        };
        defaultContext = meta.context_file || "";
        applyDefaultContext();
        refreshOverviewPanels();
        setResult("tools-summary", renderToolsSummary(scan));
        renderTools(scan, status);
        setResult("audit-status", renderAuditStatus(status));
        setResult("audit-issues", renderAuditIssues(audit));
        populateContextTargets(scan);
      });
    }

    async function loadMetrics(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        const metrics = await api("/api/metrics");
        workspaceState.metrics = metrics;
        setResult("overview-metrics", renderMetricsSummary(metrics, workspaceState.pruneStatus || {}));
      });
    }

    async function runScanAction(trigger) {
      return withBusy(trigger, "Scanning...", async () => {
        try {
          await loadWorkspace();
          const scan = workspaceState.scan || {};
          setResult(
            "overview-action-result",
            `<div class="item"><h4>Overview refreshed</h4><p>Found ${escapeHtml(String((scan.tools || []).length))} tool(s), ${escapeHtml(String(scan.total_facts || 0))} graph fact(s), and ${escapeHtml(String((scan.adoptable_sources || []).length))} detected source(s).</p></div>`
          );
        } catch (err) {
          setError("overview-action-result", err);
        }
      });
    }

    async function runSyncAction(trigger) {
      return withBusy(trigger, "Syncing...", async () => {
        try {
          const data = await api("/api/portability/sync", {
            method: "POST",
            body: JSON.stringify({
              smart: true,
              max_chars: 1500,
            }),
          });
          if (data.status === "empty") {
            setResult("overview-action-result", `<div class="item"><h4>Nothing to sync yet</h4><p>${escapeHtml(data.message || "No canonical context exists yet.")}</p></div>`);
            return;
          }
          setResult(
            "overview-action-result",
            `<div class="item"><h4>Sync complete</h4><p>Refreshed ${escapeHtml(String((data.targets || []).length))} mounted target(s) from the active Mind context.</p></div>`
          );
          await loadWorkspace();
        } catch (err) {
          setError("overview-action-result", err);
        }
      });
    }

    async function runRememberAction(trigger) {
      return withBusy(trigger, "Remembering...", async () => {
        try {
          const statement = document.getElementById("remember-statement").value.trim();
          if (!statement) {
            throw new Error("Add a statement first.");
          }
          const data = await api("/api/portability/remember", {
            method: "POST",
            body: JSON.stringify({
              statement,
              smart: true,
              max_chars: 1500,
            }),
          });
          document.getElementById("remember-statement").value = "";
          setResult(
            "overview-action-result",
            `<div class="item"><h4>Remembered and synced</h4><p>Added the statement to the active Mind workflow and updated ${escapeHtml(String((data.targets || []).length))} mounted target(s).</p></div>`
          );
          await loadWorkspace();
        } catch (err) {
          setError("overview-action-result", err);
        }
      });
    }

    async function previewTargetContext(trigger) {
      return withBusy(trigger, "Previewing...", async () => {
        try {
          const target = document.getElementById("tools-context-target").value.trim();
          if (!target) {
            setEmpty("tools-context-result", "Pick a target first to preview its routed context.");
            return;
          }
          const maxChars = numericValue("tools-context-max-chars", 700);
          const data = await api(`/api/portability/context?target=${encodeURIComponent(target)}&smart=true&max_chars=${encodeURIComponent(maxChars)}`);
          setResult("tools-context-result", renderTargetPreview(data));
        } catch (err) {
          setError("tools-context-result", err);
        }
      });
    }

    async function runReview(trigger) {
      return withBusy(trigger, "Reviewing...", async () => {
        try {
          const data = await api("/api/review", {
            method: "POST",
            body: JSON.stringify({
              input_file: document.getElementById("review-input-file").value.trim(),
              against: requireValue("review-against", "Against ref"),
              ref: document.getElementById("review-ref").value.trim() || "HEAD",
              fail_on: document.getElementById("review-fail-on").value.trim() || "blocking",
            }),
          });
          const summary = data.summary || {};
          const semantic = (data.semantic_changes || []).slice(0, 12).map((item) => `
            <div class="item">
              <h4>${escapeHtml(item.type)}</h4>
              <p>${escapeHtml(item.description)}</p>
            </div>
          `).join("");
          setResult("review-result", `
            <div class="cards">
              <div class="card"><div>Status</div><strong class="status-${data.status}">${escapeHtml(data.status)}</strong></div>
              <div class="card"><div>Added</div><strong>${summary.added_nodes ?? 0}</strong></div>
              <div class="card"><div>Modified</div><strong>${summary.modified_nodes ?? 0}</strong></div>
              <div class="card"><div>Contradictions</div><strong>${summary.new_contradictions ?? 0}</strong></div>
              <div class="card"><div>Temporal gaps</div><strong>${summary.new_temporal_gaps ?? 0}</strong></div>
              <div class="card"><div>Semantic</div><strong>${summary.semantic_changes ?? 0}</strong></div>
            </div>
            <div class="list">${semantic || '<div class="empty">No semantic changes detected.</div>'}</div>
            ${renderRawDetails("Raw review payload", data)}
          `);
        } catch (err) {
          setError("review-result", err);
        }
      });
    }

    async function runBlame(trigger) {
      return withBusy(trigger, "Tracing...", async () => {
        try {
          const data = await api("/api/blame", {
            method: "POST",
            body: JSON.stringify({
              input_file: document.getElementById("blame-input-file").value.trim(),
              label: document.getElementById("blame-label").value.trim(),
              node_id: document.getElementById("blame-node-id").value.trim(),
              ref: document.getElementById("blame-ref").value.trim() || "HEAD",
              source: document.getElementById("blame-source").value.trim(),
              limit: numericValue("blame-limit", 20),
            }),
          });
          setResult("blame-result", `${renderBlameNodes(data.nodes || [])}${renderRawDetails("Raw blame payload", data)}`);
        } catch (err) {
          setError("blame-result", err);
        }
      });
    }

    async function runHistory(trigger) {
      return withBusy(trigger, "Loading...", async () => {
        try {
          const data = await api("/api/history", {
            method: "POST",
            body: JSON.stringify({
              input_file: document.getElementById("history-input-file").value.trim(),
              label: document.getElementById("history-label").value.trim(),
              node_id: document.getElementById("history-node-id").value.trim(),
              ref: document.getElementById("history-ref").value.trim() || "HEAD",
              source: document.getElementById("history-source").value.trim(),
              limit: numericValue("history-limit", 20),
            }),
          });
          setResult("history-result", `${renderBlameNodes(data.nodes || [])}${renderRawDetails("Raw history payload", data)}`);
        } catch (err) {
          setError("history-result", err);
        }
      });
    }

    async function loadGovernance(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        try {
          const data = await api("/api/governance/rules");
          const rules = (data.rules || []).map((rule) => `
            <div class="item">
              <h4>${escapeHtml(rule.name)} <span class="pill">${escapeHtml(rule.effect)}</span></h4>
              <p>${escapeHtml(rule.description || "No description.")}</p>
              <p class="mono">actor=${escapeHtml(rule.actor_pattern)} actions=${escapeHtml((rule.actions || []).join(","))} namespaces=${escapeHtml((rule.namespaces || []).join(","))}</p>
              <div class="actions">
                <button class="action subtle" onclick="deleteGovernance('${encodeURIComponent(rule.name)}', this)">Delete</button>
              </div>
            </div>
          `).join("") || '<div class="empty">No governance rules configured.</div>';
          setResult("governance-rules-result", `<div class="list">${rules}</div>`);
        } catch (err) {
          setError("governance-rules-result", err);
        }
      });
    }

    async function saveGovernance(effect, trigger) {
      return withBusy(trigger, "Saving...", async () => {
        try {
          await api(`/api/governance/${effect}`, {
            method: "POST",
            body: JSON.stringify({
              name: requireValue("gov-name", "Rule name"),
              actor_pattern: document.getElementById("gov-actor-pattern").value.trim() || "*",
              actions: commaList("gov-actions"),
              namespaces: commaList("gov-namespaces"),
              require_approval: checked("gov-require-approval"),
              approval_below_confidence: document.getElementById("gov-confidence").value ? Number(document.getElementById("gov-confidence").value) : null,
              approval_tags: commaList("gov-tags"),
              approval_change_types: commaList("gov-change-types"),
              description: document.getElementById("gov-description").value.trim(),
            }),
          });
          setResult("governance-check-result", `<div class="item"><h4>Saved</h4><p>The ${escapeHtml(effect)} rule was saved successfully.</p></div>`);
          await loadGovernance();
        } catch (err) {
          setError("governance-check-result", err);
        }
      });
    }

    async function deleteGovernance(name, trigger) {
      return withBusy(trigger, "Deleting...", async () => {
        try {
          await api("/api/governance/delete", {
            method: "POST",
            body: JSON.stringify({ name: decodeURIComponent(name) }),
          });
          setResult("governance-check-result", `<div class="item"><h4>Deleted</h4><p>Rule ${escapeHtml(decodeURIComponent(name))} was removed.</p></div>`);
          await loadGovernance();
        } catch (err) {
          setError("governance-check-result", err);
        }
      });
    }

    async function checkGovernance(trigger) {
      return withBusy(trigger, "Checking...", async () => {
        try {
          const data = await api("/api/governance/check", {
            method: "POST",
            body: JSON.stringify({
              actor: requireValue("gov-check-actor", "Actor"),
              action: requireValue("gov-check-action", "Action"),
              namespace: requireValue("gov-check-namespace", "Namespace"),
              input_file: document.getElementById("gov-check-input-file").value.trim(),
              against: document.getElementById("gov-check-against").value.trim(),
            }),
          });
          setResult("governance-check-result", `
            <div class="item">
              <h4>${escapeHtml(data.allowed ? "ALLOW" : "DENY")}</h4>
              <p>${escapeHtml((data.reasons || []).join(" | ") || "No additional reasons.")}</p>
            </div>
            ${renderRawDetails("Raw governance payload", data)}
          `);
        } catch (err) {
          setError("governance-check-result", err);
        }
      });
    }

    function selectRemote(name, defaultBranch) {
      const resolvedName = decodeURIComponent(name || "");
      const resolvedBranch = decodeURIComponent(defaultBranch || "");
      document.getElementById("remote-name").value = resolvedName;
      if (resolvedBranch) {
        document.getElementById("remote-default-branch").value = resolvedBranch;
        document.getElementById("remote-pull-branch").value = resolvedBranch;
      }
    }

    async function loadRemotes(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        try {
          const data = await api("/api/remotes");
          const remotes = (data.remotes || []).map((remote) => `
            <div class="item">
              <h4>${escapeHtml(remote.name)}</h4>
              <p class="mono">${escapeHtml(remote.store_path)}</p>
              <p>default branch: ${escapeHtml(remote.default_branch)}</p>
              <div class="actions">
                <button class="action subtle" onclick="selectRemote('${encodeURIComponent(remote.name)}', '${encodeURIComponent(remote.default_branch)}')">Use remote</button>
                <button class="action subtle" onclick="removeRemote('${encodeURIComponent(remote.name)}', this)">Remove</button>
              </div>
            </div>
          `).join("") || '<div class="empty">No remotes configured.</div>';
          setResult("remote-list-result", `<div class="list">${remotes}</div>`);
        } catch (err) {
          setError("remote-list-result", err);
        }
      });
    }

    async function addRemote(trigger) {
      return withBusy(trigger, "Adding...", async () => {
        try {
          await api("/api/remote/add", {
            method: "POST",
            body: JSON.stringify({
              name: requireValue("remote-name", "Remote name"),
              path: requireValue("remote-path", "Remote path"),
              default_branch: document.getElementById("remote-default-branch").value.trim() || "main",
            }),
          });
          setResult("remote-activity-result", `<div class="item"><h4>Remote added</h4><p>The remote is ready for sync operations.</p></div>`);
          await loadRemotes();
          await loadWorkspace();
        } catch (err) {
          setError("remote-activity-result", err);
        }
      });
    }

    async function removeRemote(name, trigger) {
      return withBusy(trigger, "Removing...", async () => {
        try {
          await api("/api/remote/remove", {
            method: "POST",
            body: JSON.stringify({ name: decodeURIComponent(name) }),
          });
          setResult("remote-activity-result", `<div class="item"><h4>Remote removed</h4><p>${escapeHtml(decodeURIComponent(name))} is no longer configured.</p></div>`);
          await loadRemotes();
        } catch (err) {
          setError("remote-activity-result", err);
        }
      });
    }

    async function pushRemote(trigger) {
      return withBusy(trigger, "Pushing...", async () => {
        try {
          const data = await api("/api/remote/push", {
            method: "POST",
            body: JSON.stringify({
              name: requireValue("remote-name", "Remote name"),
              branch: document.getElementById("remote-push-branch").value.trim() || "HEAD",
              to_branch: document.getElementById("remote-push-target").value.trim(),
            }),
          });
          setResult("remote-activity-result", `<div class="item"><h4>Pushed</h4><p>${escapeHtml(data.branch)} -> ${escapeHtml(data.remote)}:${escapeHtml(data.remote_branch)}</p></div>${renderRawDetails("Raw push payload", data)}`);
          await loadWorkspace();
        } catch (err) {
          setError("remote-activity-result", err);
        }
      });
    }

    async function pullRemote(trigger) {
      return withBusy(trigger, "Pulling...", async () => {
        try {
          const data = await api("/api/remote/pull", {
            method: "POST",
            body: JSON.stringify({
              name: requireValue("remote-name", "Remote name"),
              branch: document.getElementById("remote-pull-branch").value.trim(),
              into_branch: document.getElementById("remote-pull-into").value.trim(),
            }),
          });
          setResult("remote-activity-result", `<div class="item"><h4>Pulled</h4><p>${escapeHtml(data.remote)}:${escapeHtml(data.remote_branch)} -> ${escapeHtml(data.branch)}</p></div>${renderRawDetails("Raw pull payload", data)}`);
          await loadWorkspace();
        } catch (err) {
          setError("remote-activity-result", err);
        }
      });
    }

    async function forkRemote(trigger) {
      return withBusy(trigger, "Forking...", async () => {
        try {
          const data = await api("/api/remote/fork", {
            method: "POST",
            body: JSON.stringify({
              name: requireValue("remote-name", "Remote name"),
              branch_name: requireValue("remote-fork-branch", "Fork branch name"),
              remote_branch: document.getElementById("remote-pull-branch").value.trim(),
            }),
          });
          setResult("remote-activity-result", `<div class="item"><h4>Forked</h4><p>${escapeHtml(data.remote)}:${escapeHtml(data.remote_branch)} -> ${escapeHtml(data.branch)}</p></div>${renderRawDetails("Raw fork payload", data)}`);
          await loadWorkspace();
        } catch (err) {
          setError("remote-activity-result", err);
        }
      });
    }

    async function loadIndexStatus(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        try {
          const ref = document.getElementById("ops-index-ref").value.trim() || "HEAD";
          const data = await api(`/api/index/status?ref=${encodeURIComponent(ref)}`);
          setResult("ops-index-result", renderKeyValue(data));
        } catch (err) {
          setError("ops-index-result", err);
        }
      });
    }

    async function rebuildIndex(trigger) {
      return withBusy(trigger, "Rebuilding...", async () => {
        try {
          const data = await api("/api/index/rebuild", {
            method: "POST",
            body: JSON.stringify({
              ref: document.getElementById("ops-index-ref").value.trim() || "HEAD",
              all_refs: checked("ops-index-all-refs"),
            }),
          });
          setResult("ops-index-result", renderKeyValue(data));
          await loadWorkspace();
        } catch (err) {
          setError("ops-index-result", err);
        }
      });
    }

    async function loadPruneStatus(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        try {
          const retention = numericValue("ops-retention-days", 7);
          const data = await api(`/api/prune/status?retention_days=${encodeURIComponent(retention)}`);
          workspaceState.pruneStatus = data;
          setResult("ops-prune-result", renderKeyValue(data));
        } catch (err) {
          setError("ops-prune-result", err);
        }
      });
    }

    async function runPrune(trigger) {
      return withBusy(trigger, checked("ops-prune-dry-run") ? "Dry running..." : "Pruning...", async () => {
        try {
          const data = await api("/api/prune", {
            method: "POST",
            body: JSON.stringify({
              dry_run: checked("ops-prune-dry-run"),
              retention_days: numericValue("ops-retention-days", 7),
            }),
          });
          setResult("ops-prune-result", renderKeyValue(data));
          await loadPruneAudit();
          await loadWorkspace();
        } catch (err) {
          setError("ops-prune-result", err);
        }
      });
    }

    async function loadPruneAudit(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        try {
          const limit = numericValue("ops-audit-limit", 20);
          const data = await api(`/api/prune/audit?limit=${encodeURIComponent(limit)}`);
          if (!(data.entries || []).length) {
            setEmpty("ops-audit-result", "No prune audit entries yet.");
            return;
          }
          setResult("ops-audit-result", renderKeyValue(data));
        } catch (err) {
          setError("ops-audit-result", err);
        }
      });
    }

    function activatePanel(panelName, updateHash = true) {
      const name = panelName || "overview";
      document.querySelectorAll(".nav button").forEach((item) => {
        const selected = item.dataset.panel === name;
        item.classList.toggle("active", selected);
        item.setAttribute("aria-selected", selected ? "true" : "false");
      });
      document.querySelectorAll(".panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === `panel-${name}`);
      });
      if (updateHash) {
        history.replaceState(null, "", `#${name}`);
      }
    }

    document.querySelectorAll(".nav button").forEach((button) => {
      button.addEventListener("click", () => activatePanel(button.dataset.panel));
    });
    window.addEventListener("hashchange", () => {
      activatePanel(window.location.hash.replace(/^#/, "") || "overview", false);
    });

    async function bootstrap() {
      try {
        activatePanel(window.location.hash.replace(/^#/, "") || "overview", false);
        await loadWorkspace();
        await Promise.all([
          loadMinds(),
          loadBrainpacks(),
          loadGovernance(),
          loadRemotes(),
          loadIndexStatus(),
          loadPruneStatus(),
          loadPruneAudit(),
        ]);
        await previewTargetContext();
      } catch (err) {
        document.getElementById("meta-card").innerHTML = `<span class="danger">${escapeHtml(err.message || err)}</span>`;
      }
    }

    bootstrap();
  </script>
</body>
</html>
"""


def make_handler(
    backend: MemoryUIBackend,
    *,
    api_keys: tuple[APIKeyConfig, ...] = (),
    allow_local_session: bool = True,
    session_token: str | None = None,
    request_policy: HTTPRequestPolicy | None = None,
):
    def query_value(parsed, key: str, default: str = "") -> str:
        return parse_qs(parsed.query).get(key, [default])[0]

    def query_int(parsed, key: str, default: int) -> int:
        raw = query_value(parsed, key, "")
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"Invalid integer for {key}: {raw}") from exc

    def query_bool(parsed, key: str, default: bool = False) -> bool:
        raw = query_value(parsed, key, "")
        if not raw:
            return default
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean for {key}: {raw}")

    session_secret = session_token or secrets.token_urlsafe(24)
    rendered_html = UI_HTML.replace(UI_SESSION_PLACEHOLDER, json.dumps(session_secret))
    policy = request_policy or HTTPRequestPolicy()
    rate_limiter = InMemoryRateLimiter(policy.rate_limit_per_minute) if policy.rate_limit_per_minute else None

    class MemoryUIHandler(BaseHTTPRequestHandler):
        server_version = "CortexUI/1.0"
        _cortex_ui_session_token = session_secret
        _cortex_ui_local_session_enabled = allow_local_session
        _cortex_ui_api_key_count = len(api_keys)
        _cortex_ui_request_policy = policy
        _cortex_ui_rate_limiter = rate_limiter

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send_json(self, payload: dict[str, Any], status: int = 200, *, request_id: str = "") -> None:
            data = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            if request_id:
                self.send_header("X-Request-ID", request_id)
            self.end_headers()
            self.wfile.write(data)

        def _send_html(self, text: str, status: int = 200, *, request_id: str = "") -> None:
            data = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            )
            if request_id:
                self.send_header("X-Request-ID", request_id)
            self.end_headers()
            self.wfile.write(data)

        def _normalized_headers(self) -> dict[str, str]:
            return {str(key).lower(): str(value).strip() for key, value in self.headers.items()}

        def _origin_matches_host(self, headers: dict[str, str]) -> bool:
            origin = headers.get("origin", "").strip()
            if not origin:
                return False
            host = headers.get("x-forwarded-host", "").strip() or headers.get("host", "").strip()
            if not host:
                return False
            proto = headers.get("x-forwarded-proto", "").strip() or "http"
            parsed_origin = urlparse(origin)
            return f"{parsed_origin.scheme}://{parsed_origin.netloc}" == f"{proto}://{host}"

        def _authorize_api_request(self, *, method: str) -> tuple[int, str] | None:
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                return None

            headers = self._normalized_headers()
            required_scope = "read" if method == "GET" else "write"
            decision = None
            if api_keys:
                decision = authorize_api_key(
                    keys=api_keys,
                    headers=headers,
                    required_scope=required_scope,
                    namespace=None,
                    namespace_required=False,
                )
                if decision.allowed:
                    return None

            session_header = headers.get(UI_SESSION_HEADER.lower(), "")
            if allow_local_session and session_header and secrets.compare_digest(session_header, session_secret):
                if method == "POST" and not self._origin_matches_host(headers):
                    return (
                        403,
                        "Forbidden: browser session POST requests must include an Origin matching the current host.",
                    )
                return None

            if decision is not None and decision.error and "missing API key" not in decision.error:
                return decision.status_code, decision.error
            if allow_local_session:
                return (
                    401,
                    "Unauthorized: missing API key or local UI session token. Browser requests should send X-Cortex-UI-Session.",
                )
            return 401, "Unauthorized: missing API key."

        def _log_request(
            self,
            *,
            request_id: str,
            method: str,
            path: str,
            started_at: float,
            status: int,
            error: str = "",
        ) -> None:
            backend.service.observability.record_request(
                request_id=request_id,
                method=method,
                path=path,
                status=status,
                duration_ms=(perf_counter() - started_at) * 1000,
                namespace=backend.backend.versions.current_branch(),
                backend=backend._backend_name(),
                index_lag_commits=backend._safe_index_status(ref="HEAD").get("lag_commits"),
                error=error,
            )

        def _write_request_error(self, status: int, message: str, *, request_id: str) -> None:
            self._send_json({"status": "error", "error": message}, status=status, request_id=request_id)

        def _log_unhandled_exception(self, *, request_id: str, exc: Exception) -> None:
            print(f"[cortex-ui] request_id={request_id} unhandled error: {exc}", file=sys.stderr)
            traceback.print_exc()

        def _check_rate_limit(self) -> str | None:
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                return None
            return enforce_rate_limit(
                self,
                limiter=self._cortex_ui_rate_limiter,
                policy=self._cortex_ui_request_policy,
            )

        def do_GET(self) -> None:  # noqa: N802
            request_id = uuid4().hex[:16]
            started_at = perf_counter()
            status = 200
            error = ""
            try:
                apply_read_timeout(self, policy=self._cortex_ui_request_policy)
                if rate_error := self._check_rate_limit():
                    status = 429
                    error = rate_error
                    self._write_request_error(status, error, request_id=request_id)
                    return
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send_html(rendered_html, request_id=request_id)
                    return
                auth_error = self._authorize_api_request(method="GET")
                if auth_error is not None:
                    status, error = auth_error
                    self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
                    return
                if parsed.path == "/api/meta":
                    self._send_json(backend.meta(), request_id=request_id)
                    return
                if parsed.path == "/api/health":
                    self._send_json(backend.health(), request_id=request_id)
                    return
                if parsed.path == "/api/metrics":
                    self._send_json(backend.metrics(), request_id=request_id)
                    return
                if parsed.path == "/api/portability/scan":
                    self._send_json(
                        backend.portability_scan(
                            project_dir=query_value(parsed, "project_dir", ""),
                            metadata_only=query_bool(parsed, "metadata_only", False),
                        ),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/portability/status":
                    self._send_json(
                        backend.portability_status(project_dir=query_value(parsed, "project_dir", "")),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/portability/audit":
                    self._send_json(
                        backend.portability_audit(project_dir=query_value(parsed, "project_dir", "")),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/portability/context":
                    target = query_value(parsed, "target", "").strip()
                    if not target:
                        raise ValueError("target is required")
                    self._send_json(
                        backend.portability_context(
                            target=target,
                            project_dir=query_value(parsed, "project_dir", ""),
                            smart=query_bool(parsed, "smart", True),
                            max_chars=query_int(parsed, "max_chars", 900),
                        ),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/minds":
                    self._send_json(backend.mind_list(), request_id=request_id)
                    return
                if parsed.path == "/api/minds/status":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.mind_status(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/minds/mounts":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.mind_mounts(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/packs":
                    self._send_json(backend.pack_list(), request_id=request_id)
                    return
                if parsed.path == "/api/packs/status":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.pack_status(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/packs/sources":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.pack_sources(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/packs/concepts":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.pack_concepts(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/packs/claims":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.pack_claims(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/packs/unknowns":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.pack_unknowns(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/packs/artifacts":
                    name = query_value(parsed, "name", "").strip()
                    if not name:
                        raise ValueError("name is required")
                    self._send_json(backend.pack_artifacts(name=name), request_id=request_id)
                    return
                if parsed.path == "/api/governance/rules":
                    self._send_json(backend.list_governance_rules(), request_id=request_id)
                    return
                if parsed.path == "/api/remotes":
                    self._send_json(backend.list_remotes(), request_id=request_id)
                    return
                if parsed.path == "/api/index/status":
                    self._send_json(
                        backend.index_status(ref=query_value(parsed, "ref", "HEAD")),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/prune/status":
                    self._send_json(
                        backend.prune_status(retention_days=query_int(parsed, "retention_days", 7)),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/prune/audit":
                    self._send_json(
                        backend.prune_audit(limit=query_int(parsed, "limit", 20)),
                        request_id=request_id,
                    )
                    return
                status = 404
                error = "Not found"
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            except ValueError as exc:
                status = 400
                error = str(exc)
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            except FileNotFoundError as exc:
                status = 404
                error = str(exc)
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            except Exception as exc:  # pragma: no cover - defensive
                status = 500
                self._log_unhandled_exception(request_id=request_id, exc=exc)
                error = "Internal server error."
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            finally:
                self._log_request(
                    request_id=request_id,
                    method="GET",
                    path=self.path,
                    started_at=started_at,
                    status=status,
                    error=error,
                )

        def do_POST(self) -> None:  # noqa: N802
            request_id = uuid4().hex[:16]
            started_at = perf_counter()
            status = 200
            error = ""
            try:
                apply_read_timeout(self, policy=self._cortex_ui_request_policy)
                if rate_error := self._check_rate_limit():
                    status = 429
                    error = rate_error
                    self._write_request_error(status, error, request_id=request_id)
                    return
                auth_error = self._authorize_api_request(method="POST")
                if auth_error is not None:
                    status, error = auth_error
                    self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
                    return
                payload = read_json_request(self, policy=self._cortex_ui_request_policy, require_object=True)
                path = self.path
                if path == "/api/review":
                    self._send_json(backend.review(**payload), request_id=request_id)
                    return
                if path == "/api/portability/sync":
                    self._send_json(backend.portability_sync(**payload), request_id=request_id)
                    return
                if path == "/api/portability/remember":
                    self._send_json(backend.portability_remember(**payload), request_id=request_id)
                    return
                if path == "/api/minds/compose":
                    self._send_json(backend.mind_compose(**payload), request_id=request_id)
                    return
                if path == "/api/blame":
                    self._send_json(backend.blame(**payload), request_id=request_id)
                    return
                if path == "/api/history":
                    self._send_json(backend.history(**payload), request_id=request_id)
                    return
                if path == "/api/governance/allow":
                    self._send_json(
                        backend.save_governance_rule(effect="allow", payload=payload), request_id=request_id
                    )
                    return
                if path == "/api/governance/deny":
                    self._send_json(backend.save_governance_rule(effect="deny", payload=payload), request_id=request_id)
                    return
                if path == "/api/governance/delete":
                    self._send_json(backend.delete_governance_rule(payload["name"]), request_id=request_id)
                    return
                if path == "/api/governance/check":
                    self._send_json(backend.check_governance(**payload), request_id=request_id)
                    return
                if path == "/api/remote/add":
                    self._send_json(backend.add_remote(**payload), request_id=request_id)
                    return
                if path == "/api/remote/remove":
                    self._send_json(backend.remove_remote(payload["name"]), request_id=request_id)
                    return
                if path == "/api/remote/push":
                    self._send_json(backend.remote_push(**payload), request_id=request_id)
                    return
                if path == "/api/remote/pull":
                    self._send_json(backend.remote_pull(**payload), request_id=request_id)
                    return
                if path == "/api/remote/fork":
                    self._send_json(backend.remote_fork(**payload), request_id=request_id)
                    return
                if path == "/api/index/rebuild":
                    self._send_json(backend.index_rebuild(**payload), request_id=request_id)
                    return
                if path == "/api/prune":
                    self._send_json(backend.prune(**payload), request_id=request_id)
                    return
            except HTTPRequestValidationError as exc:
                status = exc.status
                error = exc.message
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            except ValueError as exc:
                status = 400
                error = str(exc)
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            except FileNotFoundError as exc:
                status = 404
                error = str(exc)
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            except Exception as exc:  # pragma: no cover - defensive
                status = 500
                self._log_unhandled_exception(request_id=request_id, exc=exc)
                error = "Internal server error."
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            else:
                status = 404
                error = "Not found"
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            finally:
                self._log_request(
                    request_id=request_id,
                    method="POST",
                    path=self.path,
                    started_at=started_at,
                    status=status,
                    error=error,
                )

    return MemoryUIHandler


def start_ui_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    store_dir: str | Path = ".cortex",
    context_file: str | Path | None = None,
    open_browser: bool = False,
    runtime_mode: str = "local-single-user",
    allow_unsafe_bind: bool = False,
    api_keys: tuple[APIKeyConfig, ...] = (),
    request_policy: HTTPRequestPolicy | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    validate_runtime_security(
        surface="ui",
        host=host,
        runtime_mode=runtime_mode,
        api_keys=api_keys,
        allow_unsafe_bind=allow_unsafe_bind,
    )
    backend = MemoryUIBackend(store_dir=store_dir, context_file=context_file)
    policy = request_policy or request_policy_for_mode(runtime_mode)
    server = ThreadingHTTPServer(
        (host, port),
        make_handler(
            backend,
            api_keys=api_keys,
            allow_local_session=is_loopback_host(host),
            request_policy=policy,
        ),
    )
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}/"
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    return server, url
