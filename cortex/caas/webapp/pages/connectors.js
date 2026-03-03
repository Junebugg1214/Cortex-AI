/* Cortex Web UI — Connectors Page */
(function () {
    'use strict';
    var C = window.CortexApp;

    var PROVIDERS = [
        'openai', 'anthropic', 'google', 'meta', 'mistral', 'perplexity', 'xai',
    ];

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

    function renderConnectors(items) {
        var el = document.getElementById('connectors-list');
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
            var scopes = (c.scopes || []).map(function (s) {
                return '<span class="connector-scope">' + C.escapeHtml(s) + '</span>';
            }).join('');
            return (
                '<article class="card connector-item" data-id="' + C.escapeHtml(c.connector_id) + '">' +
                '  <div class="connector-head">' +
                '    <div>' +
                '      <h3>' + C.escapeHtml(account) + '</h3>' +
                '      <p class="technical-only">' + C.escapeHtml(c.provider) + ' · ' + C.escapeHtml(c.connector_id) + '</p>' +
                '    </div>' +
                '    <div>' + connectorStatusBadge(c.status) + '</div>' +
                '  </div>' +
                '  <div class="connector-meta technical-only">' +
                '    <div><strong>Created:</strong> ' + C.escapeHtml(c.created_at || '-') + '</div>' +
                '    <div><strong>Updated:</strong> ' + C.escapeHtml(c.updated_at || '-') + '</div>' +
                '    <div><strong>Last Sync:</strong> ' + C.escapeHtml(c.last_sync_at || '-') + '</div>' +
                '  </div>' +
                '  <div class="connector-scopes technical-only">' + (scopes || '<span class="connector-scope">none</span>') + '</div>' +
                '  <div class="connector-actions">' +
                '    <button class="btn btn-outline btn-connector-toggle technical-only" data-id="' + C.escapeHtml(c.connector_id) + '" data-status="' + C.escapeHtml(c.status || 'active') + '">' + ((c.status || 'active') === 'active' ? 'Pause' : 'Activate') + '</button>' +
                '    <button class="btn btn-outline btn-danger btn-connector-delete" data-id="' + C.escapeHtml(c.connector_id) + '">Delete</button>' +
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
                : 'Connect AI providers so identity and memory persist across tools. Storage model: Local Vault or BYOS only.') + '</p>' +
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
            '      <label class="profile-label" for="connector-provider">Provider</label>' +
            '      <select id="connector-provider" class="login-input"></select>' +
            '      <label class="profile-label" for="connector-label">Account Label</label>' +
            '      <input id="connector-label" class="login-input" placeholder="Personal OpenAI">' +
            '      <button type="submit" class="btn btn-primary">Create Connector</button>' +
            '    </form>' +
            '  </section>' +
            '  <section id="connectors-list" class="connector-list"></section>' +
            '</div>';

        var providerSelect = document.getElementById('connector-provider');
        PROVIDERS.forEach(function (p) {
            var opt = document.createElement('option');
            opt.value = p;
            opt.textContent = p;
            providerSelect.appendChild(opt);
        });

        document.getElementById('connector-form').addEventListener('submit', function (ev) {
            ev.preventDefault();
            var payload = {
                provider: providerSelect.value,
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
                providerSelect.value = PROVIDERS[0];
                loadConnectors();
            }).catch(function (err) {
                C.showToast('Error: ' + err.message, 'error');
            });
        });

        loadConnectors();
    });
})();
