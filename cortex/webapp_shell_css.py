"""Static Cortex UI shell styles."""

UI_CSS = r"""
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
    .hidden {
      display: none !important;
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
    .loading-banner {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 14px;
      padding: 12px 16px;
      border: 1px solid rgba(17, 105, 91, 0.16);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.88);
      box-shadow: var(--shadow);
      position: sticky;
      top: 16px;
      z-index: 4;
    }
    .loading-banner.hidden {
      display: none;
    }
    .shortcuts-card {
      margin-top: 18px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: rgba(255, 255, 255, 0.72);
      box-shadow: var(--shadow);
    }
    .shortcuts-card ul {
      margin: 10px 0 0;
      padding: 0 0 0 18px;
      color: var(--muted);
      line-height: 1.6;
    }
    kbd {
      display: inline-block;
      padding: 1px 6px;
      border: 1px solid var(--line);
      border-bottom-width: 2px;
      border-radius: 8px;
      background: white;
      font: inherit;
      font-size: 0.8rem;
    }
    .wizard {
      padding: 22px;
      border: 1px solid rgba(17, 105, 91, 0.22);
      border-radius: calc(var(--radius) + 6px);
      background: linear-gradient(135deg, rgba(17, 105, 91, 0.08), rgba(255, 255, 255, 0.94));
      box-shadow: var(--shadow);
    }
    .wizard-head {
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: start;
      margin-bottom: 16px;
    }
    .wizard-head h3 {
      margin: 0 0 8px;
      font-size: 1.45rem;
    }
    .wizard-head p {
      margin: 0;
      color: var(--muted);
      max-width: 70ch;
      line-height: 1.5;
    }
    .wizard-steps {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }
    .wizard-step {
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: var(--shadow);
    }
    .wizard-step.active {
      border-color: rgba(17, 105, 91, 0.34);
      transform: translateY(-2px);
    }
    .wizard-step h4 {
      margin: 0 0 10px;
      font-size: 1.02rem;
    }
    .empty-state {
      margin: 10px 0 16px;
      padding: 18px;
      border-radius: 20px;
      border: 1px dashed rgba(17, 105, 91, 0.28);
      background: rgba(255, 255, 255, 0.85);
    }
    .empty-state p {
      margin: 0 0 12px;
      max-width: 72ch;
      color: var(--muted);
      line-height: 1.55;
    }
    .inline-link {
      display: inline-flex;
      align-items: center;
      padding: 11px 16px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: white;
      color: var(--accent-strong);
      text-decoration: none;
      font: inherit;
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
"""[1:-1]
