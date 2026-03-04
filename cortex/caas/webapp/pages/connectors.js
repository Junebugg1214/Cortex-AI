/* Cortex Web UI — Connectors Page */
(function () {
    'use strict';
    var C = window.CortexApp;

    var PROVIDERS = [
        'openai', 'anthropic', 'google', 'meta', 'mistral', 'perplexity', 'xai', 'github',
    ];
    var PROVIDER_LABELS = {
        openai: 'ChatGPT (OpenAI)',
        anthropic: 'Claude (Anthropic)',
        google: 'Gemini (Google)',
        meta: 'Meta AI',
        mistral: 'Mistral',
        perplexity: 'Perplexity',
        xai: 'Grok (xAI)',
        github: 'GitHub',
    };
    var JOBS = [
        { id: 'memory_pull_prompt', name: 'Memory Pull Prompt' },
        { id: 'github_repo_sync', name: 'GitHub Repo Sync' },
        { id: 'custom_json_sync', name: 'Custom JSON Sync' },
    ];
    var CAPABILITIES = {
        providers: {},
        valid_jobs: JOBS.map(function (j) { return j.id; }),
    };

    function inferDefaultJob(provider) {
        var key = String(provider || '').toLowerCase();
        var caps = CAPABILITIES.providers[key] || {};
        if (caps.default_job) return caps.default_job;
        return key === 'github' ? 'github_repo_sync' : 'memory_pull_prompt';
    }

    function providerLabel(provider) {
        var key = String(provider || '').toLowerCase();
        return PROVIDER_LABELS[key] || key || 'Unknown';
    }

    function connectorStatusBadge(status) {
        var safe = C.escapeHtml(String(status || 'active'));
        return '<span class="connector-status connector-status-' + safe + '">' + safe + '</span>';
    }

    function loadConnectors() {
        C.api('/api/connectors')
            .then(function (resp) {
                renderConnectors(resp.connectors || []);
            })
            .catch(function (err) {
                document.getElementById('connectors-list').innerHTML =
                    '<div class="card"><p>Could not load connectors: ' + C.escapeHtml(err.message) + '</p></div>';
            });
    }

    function loadCapabilities() {
        return C.api('/api/connectors/capabilities')
            .then(function (resp) {
                if (resp && resp.providers && typeof resp.providers === 'object') {
                    CAPABILITIES = resp;
                }
                return CAPABILITIES;
            })
            .catch(function () {
                return CAPABILITIES;
            });
    }

    function getAllowedJobs(provider) {
        var key = String(provider || '').toLowerCase();
        var caps = CAPABILITIES.providers[key] || {};
        var jobs = Array.isArray(caps.jobs) && caps.jobs.length ? caps.jobs.slice() : [inferDefaultJob(key)];
        return jobs.filter(function (jobId) {
            return CAPABILITIES.valid_jobs.indexOf(jobId) >= 0;
        });
    }

    function renderConnectors(items) {
        var el = document.getElementById('connectors-list');
        var isConsumer = C.isConsumerMode && C.isConsumerMode();
        if (!items.length) {
            el.innerHTML =
                '<div class="card connector-empty">' +
                '<h3>No connectors yet</h3>' +
                '<p>Add your first provider connection to enable seamless memory continuity.</p>' +
                '</div>';
            return;
        }

        el.innerHTML = items.map(function (c) {
            var account = c.account_label || c.external_user_id || 'Unlabeled account';
            var metadata = c.metadata && typeof c.metadata === 'object' ? c.metadata : {};
            var job = metadata._job || inferDefaultJob((c.provider || '').toLowerCase());
            var syncNote = metadata._last_sync_message || '';
            var autoEnabled = metadata._auto_sync_enabled !== false;
            var autoEvery = parseInt(metadata._auto_sync_interval_seconds || 86400, 10);
            if (!autoEvery || autoEvery < 1) autoEvery = 86400;
            var autoHours = Math.round(autoEvery / 3600);
            var scopes = (c.scopes || []).map(function (s) {
                return '<span class="connector-scope">' + C.escapeHtml(s) + '</span>';
            }).join('');
            return (
                '<article class="card connector-item" data-id="' + C.escapeHtml(c.connector_id) + '">' +
                '  <div class="connector-head">' +
                '    <div>' +
                '      <h3>' + C.escapeHtml(account) + '</h3>' +
                '      <p>' + C.escapeHtml(providerLabel(c.provider)) + '</p>' +
                '      <p class="technical-only">' + C.escapeHtml(c.provider) + ' · ' + C.escapeHtml(c.connector_id) + '</p>' +
                '    </div>' +
                '    <div>' + connectorStatusBadge(c.status) + '</div>' +
                '  </div>' +
                (isConsumer ? '' : ('  <div><strong>Job:</strong> ' + C.escapeHtml(job) + '</div>')) +
                '  <div><strong>Auto-run:</strong> ' + (autoEnabled ? ('Every ' + autoHours + 'h') : 'Off') + '</div>' +
                ((job === 'memory_pull_prompt' && metadata._job_config && metadata._job_config.bridge_url)
                    ? '  <div><strong>Mode:</strong> Auto bridge configured</div>'
                    : '') +
                (syncNote ? '  <div><strong>Sync:</strong> ' + C.escapeHtml(syncNote) + '</div>' : '') +
                '  <div class="connector-meta technical-only">' +
                '    <div><strong>Created:</strong> ' + C.escapeHtml(c.created_at || '-') + '</div>' +
                '    <div><strong>Updated:</strong> ' + C.escapeHtml(c.updated_at || '-') + '</div>' +
                '    <div><strong>Last Sync:</strong> ' + C.escapeHtml(c.last_sync_at || '-') + '</div>' +
                '  </div>' +
                '  <div class="connector-scopes technical-only">' + (scopes || '<span class="connector-scope">none</span>') + '</div>' +
                '  <div class="connector-actions">' +
                '    <button class="btn btn-primary btn-connector-sync" data-id="' + C.escapeHtml(c.connector_id) + '">' + (isConsumer ? 'Sync now' : 'Run now') + '</button>' +
                '    <button class="btn btn-outline btn-connector-auto-toggle" data-id="' + C.escapeHtml(c.connector_id) + '" data-auto-enabled="' + (autoEnabled ? 'true' : 'false') + '" data-meta="' + C.escapeHtml(encodeURIComponent(JSON.stringify(metadata))) + '">' + (autoEnabled ? 'Pause auto-sync' : 'Resume auto-sync') + '</button>' +
                '    <button class="btn btn-outline btn-connector-toggle technical-only" data-id="' + C.escapeHtml(c.connector_id) + '" data-status="' + C.escapeHtml(c.status || 'active') + '">' + ((c.status || 'active') === 'active' ? 'Pause' : 'Activate') + '</button>' +
                '    <button class="btn btn-outline btn-danger btn-connector-delete" data-id="' + C.escapeHtml(c.connector_id) + '">' + (isConsumer ? 'Disconnect' : 'Delete') + '</button>' +
                '  </div>' +
                '</article>'
            );
        }).join('');

        bindConnectorActions();
    }

    function updateConnector(connectorId, payload, successMsg) {
        C.api('/api/connectors/' + encodeURIComponent(connectorId), {
            method: 'PUT',
            body: JSON.stringify(payload),
        }).then(function () {
            C.showToast(successMsg, 'success');
            loadConnectors();
        }).catch(function (err) {
            C.showToast('Error: ' + err.message, 'error');
        });
    }

    function bindConnectorActions() {
        document.querySelectorAll('.btn-connector-sync').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var connectorId = this.getAttribute('data-id');
                C.api('/api/connectors/' + encodeURIComponent(connectorId) + '/sync', {
                    method: 'POST',
                    body: JSON.stringify({}),
                }).then(function (resp) {
                    if (resp && resp.action_required && resp.prompt) {
                        C.copyToClipboard(resp.prompt);
                        C.showToast('Sync prompt copied. Run it in your assistant, then paste the response.', 'info');
                        var pasted = window.prompt('Paste exported memory response to import now (optional):');
                        if (!pasted || !pasted.trim()) {
                            loadConnectors();
                            return;
                        }
                        return C.api('/api/connectors/' + encodeURIComponent(connectorId) + '/sync', {
                            method: 'POST',
                            body: JSON.stringify({ memory_dump: pasted.trim() }),
                        }).then(function (finalResp) {
                            C.showToast(finalResp.message || 'Connector sync complete', 'success');
                            loadConnectors();
                        });
                    }
                    C.showToast((resp && resp.message) || 'Connector sync complete', 'success');
                    loadConnectors();
                }).catch(function (err) {
                    C.showToast('Sync failed: ' + err.message, 'error');
                    loadConnectors();
                });
            });
        });

        document.querySelectorAll('.btn-connector-auto-toggle').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var connectorId = this.getAttribute('data-id');
                var enabled = this.getAttribute('data-auto-enabled') !== 'false';
                var metaRaw = this.getAttribute('data-meta') || '';
                var metadata = {};
                try {
                    metadata = JSON.parse(decodeURIComponent(metaRaw));
                } catch (_e) {
                    metadata = {};
                }
                metadata._auto_sync_enabled = !enabled;
                if (!metadata._auto_sync_interval_seconds) {
                    metadata._auto_sync_interval_seconds = 24 * 60 * 60;
                }
                updateConnector(
                    connectorId,
                    { metadata: metadata },
                    enabled ? 'Auto-run paused' : 'Auto-run resumed'
                );
            });
        });

        document.querySelectorAll('.btn-connector-toggle').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var connectorId = this.getAttribute('data-id');
                var status = this.getAttribute('data-status') || 'active';
                var next = status === 'active' ? 'paused' : 'active';
                updateConnector(connectorId, { status: next }, 'Connector updated');
            });
        });

        document.querySelectorAll('.btn-connector-delete').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var connectorId = this.getAttribute('data-id');
                if (!window.confirm('Delete this connector?')) return;
                C.api('/api/connectors/' + encodeURIComponent(connectorId), {
                    method: 'DELETE',
                }).then(function () {
                    C.showToast('Connector deleted', 'success');
                    loadConnectors();
                }).catch(function (err) {
                    C.showToast('Error: ' + err.message, 'error');
                });
            });
        });
    }

    C.registerPage('connectors', function (container) {
        var isConsumer = C.isConsumerMode && C.isConsumerMode();
        container.innerHTML =
            '<div class="page-header">' +
            '  <h1>Connectors</h1>' +
            '  <p>' + (isConsumer
                ? 'Connect your AI apps so your AI ID stays consistent across tools.'
                : 'Connect AI providers so identity and memory persist across tools on your own infrastructure.') + '</p>' +
            '</div>' +
            '<div class="card page-flow-cue">' +
            '  <span class="flow-step flow-step-active">1. Connect</span>' +
            '  <span class="flow-step">2. ' + (isConsumer ? 'Add Data (Optional)' : 'Import Fallback') + '</span>' +
            '  <span class="flow-step">3. Share</span>' +
            '</div>' +
            '<div class="connector-layout">' +
            '  <section class="card connector-create">' +
            '    <h3>Add Connector</h3>' +
            '    <form id="connector-form" class="connector-form">' +
            '      <label class="profile-label" for="connector-provider">' + (isConsumer ? 'AI App' : 'Provider') + '</label>' +
            '      <select id="connector-provider" class="login-input"></select>' +
            '      <label class="profile-label technical-only" for="connector-job">Job</label>' +
            '      <select id="connector-job" class="login-input technical-only"></select>' +
            '      <label class="profile-label" for="connector-label">Account Label</label>' +
            '      <input id="connector-label" class="login-input" placeholder="' + (isConsumer ? 'Personal ChatGPT' : 'Personal OpenAI') + '">' +
            '      <label class="profile-label technical-only" for="connector-target">Job Target (optional)</label>' +
            '      <input id="connector-target" class="login-input technical-only" placeholder="GitHub URL or JSON endpoint URL">' +
            '      <label class="profile-label technical-only" for="connector-bridge-url">Auto Bridge URL (optional)</label>' +
            '      <input id="connector-bridge-url" class="login-input technical-only" placeholder="https://bridge.example.com/memory/export">' +
            '      <label class="profile-label technical-only" for="connector-bridge-token">Bridge Token (optional)</label>' +
            '      <input id="connector-bridge-token" type="password" class="login-input technical-only" placeholder="Bearer token for bridge endpoint">' +
            '      <button type="submit" class="btn btn-primary">Create Connector</button>' +
            '    </form>' +
            '  </section>' +
            '  <section id="connectors-list" class="connector-list"></section>' +
            '</div>';

        var providerSelect = document.getElementById('connector-provider');
        var jobSelect = document.getElementById('connector-job');
        function renderProviderOptions() {
            providerSelect.innerHTML = '';
            var providers = Object.keys(CAPABILITIES.providers || {});
            if (!providers.length) providers = PROVIDERS.slice();
            providers.forEach(function (p) {
                var opt = document.createElement('option');
                opt.value = p;
                opt.textContent = providerLabel(p);
                providerSelect.appendChild(opt);
            });
        }
        function renderJobOptions(provider) {
            var allowed = getAllowedJobs(provider);
            jobSelect.innerHTML = '';
            allowed.forEach(function (jobId) {
                var jobDef = JOBS.find(function (j) { return j.id === jobId; });
                var opt = document.createElement('option');
                opt.value = jobId;
                opt.textContent = jobDef ? jobDef.name : jobId;
                jobSelect.appendChild(opt);
            });
            jobSelect.value = inferDefaultJob(provider);
        }
        providerSelect.addEventListener('change', function () {
            renderJobOptions(providerSelect.value);
        });

        document.getElementById('connector-form').addEventListener('submit', function (ev) {
            ev.preventDefault();
            var isConsumerMode = C.isConsumerMode && C.isConsumerMode();
            var target = document.getElementById('connector-target').value.trim();
            var bridgeUrl = document.getElementById('connector-bridge-url').value.trim();
            var bridgeToken = document.getElementById('connector-bridge-token').value.trim();
            var selectedJob = isConsumerMode ? inferDefaultJob(providerSelect.value) : jobSelect.value;
            var jobConfig = {};
            if (target) {
                if (selectedJob === 'github_repo_sync') jobConfig.repo_url = target;
                else if (selectedJob === 'custom_json_sync') jobConfig.url = target;
            }
            if (bridgeUrl && selectedJob === 'memory_pull_prompt') {
                jobConfig.bridge_url = bridgeUrl;
            }
            if (bridgeToken && selectedJob === 'memory_pull_prompt') {
                jobConfig.bridge_token = bridgeToken;
            }
            var payload = {
                provider: providerSelect.value,
                job: selectedJob,
                job_config: jobConfig,
                account_label: document.getElementById('connector-label').value.trim(),
                scopes: ['memory:read'],
                metadata: {
                    source: 'webapp',
                },
            };
            C.api('/api/connectors', {
                method: 'POST',
                body: JSON.stringify(payload),
            }).then(function () {
                C.showToast('Connector created', 'success');
                document.getElementById('connector-form').reset();
                providerSelect.selectedIndex = 0;
                renderJobOptions(providerSelect.value);
                loadConnectors();
            }).catch(function (err) {
                C.showToast('Error: ' + err.message, 'error');
            });
        });

        loadCapabilities().then(function () {
            renderProviderOptions();
            renderJobOptions(providerSelect.value);
            loadConnectors();
        });
    });
})();
