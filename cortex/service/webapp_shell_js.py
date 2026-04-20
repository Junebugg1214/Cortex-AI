"""Static Cortex UI shell script payload."""

UI_JS = r"""
    const uiSessionToken = __CORTEX_UI_SESSION_TOKEN__;
    let defaultContext = "";
    let activeRequestController = null;
    let workspaceState = {
      meta: null,
      health: null,
      metrics: null,
      pruneStatus: null,
      scan: null,
      status: null,
      audit: null,
      onboarding: null,
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
      if (activeRequestController && !options.signal) {
        options.signal = activeRequestController.signal;
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
        const error = new Error(data.error || data.message || `Request failed (${res.status})`);
        error.code = data.code || `http_${res.status}`;
        error.suggestion = data.suggestion || "Try again after correcting the highlighted fields.";
        error.why = data.why || "";
        throw error;
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

    function renderErrorCard(err) {
      const message = escapeHtml(err?.message || "Something went wrong.");
      const code = escapeHtml(err?.code || "unknown_error");
      const suggestion = escapeHtml(err?.suggestion || "Try the action again.");
      const why = escapeHtml(err?.why || err?.details || "Cortex could not complete the request with the current inputs.");
      return `
        <div class="danger">
          <strong>What went wrong</strong>
          <p>${message}</p>
          <strong>Why it happened</strong>
          <p>${why}</p>
          <strong>What to do next</strong>
          <p>${suggestion}</p>
          <p class="tiny">Code: ${code}</p>
        </div>
      `;
    }

    function setError(id, err) {
      setResult(id, renderErrorCard(err));
    }

    async function withBusy(trigger, label, work) {
      const button = trigger || null;
      const original = button ? button.textContent : "";
      const controller = new AbortController();
      if (button) {
        button.disabled = true;
        button.textContent = label;
      }
      activeRequestController = controller;
      const loadingBanner = document.getElementById("loading-banner");
      const loadingLabel = document.getElementById("loading-label");
      const loadingCancel = document.getElementById("loading-cancel");
      if (loadingLabel) {
        loadingLabel.textContent = label;
      }
      if (loadingBanner) {
        loadingBanner.classList.remove("hidden");
      }
      if (loadingCancel) {
        loadingCancel.onclick = () => {
          if (!controller.signal.aborted) {
            controller.abort();
          }
        };
      }
      try {
        return await work(controller);
      } catch (err) {
        if (err?.name === "AbortError") {
          const cancelled = new Error("Request cancelled.");
          cancelled.code = "cancelled";
          cancelled.suggestion = "Run the action again when you are ready.";
          throw cancelled;
        }
        throw err;
      } finally {
        activeRequestController = null;
        if (loadingBanner) {
          loadingBanner.classList.add("hidden");
        }
        if (button) {
          button.disabled = false;
          button.textContent = original;
        }
      }
    }

    function showWizardStep(step) {
      document.querySelectorAll(".wizard-step").forEach((el) => {
        el.classList.toggle("active", el.dataset.step === step);
      });
    }

    function showOnboardingWizard(visible) {
      const wizard = document.getElementById("onboarding-wizard");
      if (!wizard) return;
      wizard.classList.toggle("hidden", !visible);
    }

    function scrollToWizard(step) {
      showOnboardingWizard(true);
      showWizardStep(step || "mind");
      document.getElementById("onboarding-wizard")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function updateOnboardingState(state) {
      workspaceState.onboarding = state || workspaceState.onboarding;
      const onboarding = workspaceState.onboarding || {};
      const shouldShow = onboarding.status !== "complete";
      showOnboardingWizard(shouldShow);
      if (shouldShow) {
        showWizardStep(onboarding.next_step || onboarding.step || "mind");
      }
      renderEmptyWorkspace();
    }

    function renderEmptyWorkspace() {
      const meta = workspaceState.meta || {};
      const onboarding = workspaceState.onboarding || {};
      const empty = document.getElementById("overview-empty-state");
      if (!empty) return;
      if ((workspaceState.minds?.list?.minds || []).length) {
        empty.classList.add("hidden");
        return;
      }
      empty.classList.remove("hidden");
      empty.innerHTML = `
        <p>Cortex keeps one source-aware Mind in sync across tools so you can remember, compile, and mount the same context without rebuilding it by hand.</p>
        <div class="actions">
          <button class="action" type="button" onclick="scrollToWizard('mind')">Create your first Mind</button>
          <a href="#" class="inline-link" onclick="scrollToWizard('source'); return false;">Import from existing source</a>
        </div>
        <p class="tiny">Store: ${escapeHtml(meta.store_dir || "(unknown)")} · Step: ${escapeHtml(onboarding.step || "welcome")}</p>
      `;
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
      renderEmptyWorkspace();
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
            <div class="command-block">cortex admin doctor</div>
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
            renderEmptyWorkspace();
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
        const [meta, health, metrics, pruneStatus, scan, status, audit, onboarding] = await Promise.all([
          api("/api/meta"),
          api("/api/health"),
          api("/api/metrics"),
          api("/api/prune/status"),
          api("/api/portability/scan"),
          api("/api/portability/status"),
          api("/api/portability/audit"),
          api("/api/onboarding/state"),
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
          onboarding: onboarding.onboarding || onboarding,
        };
        defaultContext = meta.context_file || "";
        applyDefaultContext();
        updateOnboardingState(workspaceState.onboarding);
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

    function renderWizardResult(data) {
      return `
        <div class="item">
          <h4>${escapeHtml(data?.title || "Onboarding complete")}</h4>
          <p>${escapeHtml(data?.result_summary || data?.summary || "Cortex created a Mind, ingested one source, and compiled a first audience-specific output.")}</p>
          <p class="tiny">Mind: ${escapeHtml(data?.mind_id || data?.mind || "(unknown)")} · Template: ${escapeHtml(data?.audience_template || "executive")}</p>
        </div>
      `;
    }

    async function createWizardMind(trigger) {
      return withBusy(trigger, "Creating Mind...", async () => {
        try {
          const mindId = document.getElementById("wizard-mind-name").value.trim() || "self";
          const label = document.getElementById("wizard-mind-label").value.trim() || mindId;
          const data = await api("/api/onboarding/create", {
            method: "POST",
            body: JSON.stringify({
              mind_id: mindId,
              mind_label: label,
              label,
              owner: label,
              kind: "person",
            }),
          });
          await api("/api/onboarding/start", {
            method: "POST",
            body: JSON.stringify({
              mind_id: mindId,
              mind_label: label,
            }),
          });
          workspaceState.onboarding = data.onboarding || workspaceState.onboarding;
          updateOnboardingState(workspaceState.onboarding);
          await loadWorkspace();
          setResult("wizard-result", `<div class="item"><h4>Mind created</h4><p>${escapeHtml(label)} is ready. Import one source next.</p></div>`);
        } catch (err) {
          setError("wizard-result", err);
        }
      });
    }

    async function ingestWizardSource(trigger) {
      return withBusy(trigger, "Importing source...", async () => {
        try {
          const mindId = document.getElementById("wizard-mind-name").value.trim() || "self";
          const sourceKind = document.getElementById("wizard-source-kind").value.trim() || "paste";
          const sourceValue = document.getElementById("wizard-source-value").value.trim();
          if (!sourceValue) {
            throw new Error("Add a source value first.");
          }
          const data = await api("/api/onboarding/ingest", {
            method: "POST",
            body: JSON.stringify({
              mind_id: mindId,
              source_kind: sourceKind,
              source_value: sourceValue,
            }),
          });
          workspaceState.onboarding = data.onboarding || workspaceState.onboarding;
          updateOnboardingState(workspaceState.onboarding);
          await loadWorkspace();
          setResult("wizard-result", `<div class="item"><h4>Source imported</h4><p>${escapeHtml(sourceKind)} source imported into ${escapeHtml(mindId)}.</p></div>`);
        } catch (err) {
          setError("wizard-result", err);
        }
      });
    }

    async function compileWizardOutput(trigger) {
      return withBusy(trigger, "Compiling...", async () => {
        try {
          const mindId = document.getElementById("wizard-mind-name").value.trim() || "self";
          const template = document.getElementById("wizard-template").value.trim() || "executive";
          const data = await api("/api/onboarding/compile", {
            method: "POST",
            body: JSON.stringify({
              mind_id: mindId,
              audience_template: template,
            }),
          });
          workspaceState.onboarding = data.onboarding || workspaceState.onboarding;
          updateOnboardingState(workspaceState.onboarding);
          await loadWorkspace();
          setResult("wizard-result", `${renderWizardResult(data)}${renderRawDetails("Raw onboarding payload", data)}`);
        } catch (err) {
          setError("wizard-result", err);
        }
      });
    }

    async function skipOnboarding() {
      try {
        const data = await api("/api/onboarding/skip", { method: "POST", body: JSON.stringify({}) });
        workspaceState.onboarding = data.onboarding || workspaceState.onboarding;
        updateOnboardingState(workspaceState.onboarding);
        renderEmptyWorkspace();
      } catch (err) {
        setError("wizard-result", err);
      }
    }

    async function resetOnboarding() {
      try {
        const data = await api("/api/onboarding/reset", { method: "POST", body: JSON.stringify({}) });
        workspaceState.onboarding = data.onboarding || workspaceState.onboarding;
        updateOnboardingState(workspaceState.onboarding);
        renderEmptyWorkspace();
        scrollToWizard(workspaceState.onboarding?.next_step || "mind");
      } catch (err) {
        setError("wizard-result", err);
      }
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
    window.addEventListener("keydown", (event) => {
      const target = event.target;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable)) {
        return;
      }
      if (!event.altKey || event.ctrlKey || event.metaKey) return;
      const shortcut = event.key.toLowerCase();
      if (shortcut === "1") {
        activatePanel("overview");
      } else if (shortcut === "2") {
        activatePanel("minds");
      } else if (shortcut === "3") {
        activatePanel("brainpacks");
      } else if (shortcut === "4") {
        activatePanel("review");
      } else if (shortcut === "5") {
        loadWorkspace();
      } else {
        return;
      }
      event.preventDefault();
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
        document.getElementById("meta-card").innerHTML = renderErrorCard(err);
      }
    }

    bootstrap();
"""[1:-1]
