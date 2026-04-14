"""Static Cortex UI shell markup."""

UI_BODY = r"""
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
      <div class="shortcuts-card" id="shortcuts-card">
        <div class="tiny">Keyboard shortcuts</div>
        <ul>
          <li><kbd>Alt</kbd> + <kbd>1</kbd> Overview</li>
          <li><kbd>Alt</kbd> + <kbd>2</kbd> Minds</li>
          <li><kbd>Alt</kbd> + <kbd>3</kbd> Brainpacks</li>
          <li><kbd>Alt</kbd> + <kbd>4</kbd> Review</li>
          <li><kbd>Alt</kbd> + <kbd>5</kbd> Refresh workspace</li>
        </ul>
      </div>
    </aside>
    <main>
      <div id="loading-banner" class="loading-banner hidden" role="status" aria-live="polite">
        <span id="loading-label">Working…</span>
        <button id="loading-cancel" class="action subtle" type="button">Cancel</button>
      </div>
      <section class="hero">
        <div class="eyebrow">Local-first Mind control plane</div>
        <h2>One portable Mind, wired across your tools</h2>
        <p>Start from your default Mind, keep it mounted where it matters, and only drill into tool scans or operator plumbing when the overview says you should.</p>
      </section>

      <section id="onboarding-wizard" class="wizard hidden" aria-labelledby="onboarding-title">
        <div class="wizard-head">
          <div>
            <div class="eyebrow">First run</div>
            <h3 id="onboarding-title">Get to your first useful output</h3>
            <p>One Mind, one source, one compiled output, then you are ready to work from Cortex instead of reading about it.</p>
          </div>
          <div class="actions">
            <button class="action subtle" type="button" onclick="skipOnboarding()">Skip for now</button>
            <button class="action subtle" type="button" onclick="resetOnboarding()">Reset wizard</button>
          </div>
        </div>
        <div class="wizard-steps">
          <article class="wizard-step" data-step="mind">
            <h4>1. Name your first Mind</h4>
            <label>Mind name
              <input id="wizard-mind-name" placeholder="self">
            </label>
            <label>Display label
              <input id="wizard-mind-label" placeholder="Your name or team">
            </label>
            <div class="actions">
              <button class="action" type="button" onclick="createWizardMind(this)">Create your first Mind</button>
            </div>
          </article>
          <article class="wizard-step" data-step="source">
            <h4>2. Ingest one source</h4>
            <label>Source type
              <select id="wizard-source-kind">
                <option value="paste">Paste</option>
                <option value="file">File</option>
                <option value="url">URL</option>
              </select>
            </label>
            <label>Source value
              <textarea id="wizard-source-value" placeholder="Paste a note, file path, or URL"></textarea>
            </label>
            <div class="actions">
              <button class="action" type="button" onclick="ingestWizardSource(this)">Import from existing source</button>
            </div>
          </article>
          <article class="wizard-step" data-step="compile">
            <h4>3. Compile your first output</h4>
            <label>Audience template
              <select id="wizard-template">
                <option value="executive">Executive</option>
                <option value="attorney">Attorney</option>
                <option value="onboarding">Onboarding</option>
                <option value="audit">Audit</option>
              </select>
            </label>
            <div class="actions">
              <button class="action" type="button" onclick="compileWizardOutput(this)">Compile first output</button>
            </div>
          </article>
          <article class="wizard-step" data-step="result">
            <h4>4. What just happened</h4>
            <div id="wizard-result" class="result empty">Once you compile, Cortex will explain what was kept, what was redacted, and why the output now fits the audience you chose.</div>
          </article>
        </div>
      </section>

      <section id="panel-overview" class="panel active" role="tabpanel">
        <h3>Mind Overview</h3>
        <p class="panel-copy">Lead from the default Mind: its branch, attached Brainpacks, mounted targets, pending proposals, and the runtime follow-up that matters next.</p>
        <div id="overview-empty-state" class="empty-state hidden">
          <p>Cortex keeps one source-aware Mind in sync across tools so you can remember, compile, and mount the same context without rebuilding it by hand.</p>
          <div class="actions">
            <button class="action" type="button" onclick="scrollToWizard('mind')">Create your first Mind</button>
            <a href="#panel-tools" class="inline-link" onclick="scrollToWizard('source'); return false;">Import from existing source</a>
          </div>
        </div>
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
"""[1:-1]
