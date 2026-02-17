/* Cortex Dashboard — Settings Page */
(function () {
    'use strict';
    var D = window.CortexDashboard;

    D.registerPage('settings', async function (container) {
        D.renderPage(container,
            '<h2 class="page-title">Settings</h2>' +
            '<div class="two-col">' +
            '  <div>' +
            '    <div class="card">' +
            '      <div class="card-header">Server Configuration</div>' +
            '      <div id="settings-config"></div>' +
            '    </div>' +
            '    <div class="card" style="margin-top:16px">' +
            '      <div class="card-header">Export</div>' +
            '      <button class="btn btn-primary" id="export-btn">Download Graph JSON</button>' +
            '    </div>' +
            '  </div>' +
            '  <div>' +
            '    <div class="card">' +
            '      <div class="card-header">Webhooks</div>' +
            '      <form id="wh-form" onsubmit="return false" style="margin-bottom:16px">' +
            '        <div class="form-group"><label>URL</label><input type="url" id="wh-url" placeholder="https://example.com/webhook" required></div>' +
            '        <div class="form-group"><label>Events</label><div class="scope-list" id="wh-events">' +
            '          <label><input type="checkbox" value="grant.created" checked> grant.created</label>' +
            '          <label><input type="checkbox" value="grant.revoked" checked> grant.revoked</label>' +
            '          <label><input type="checkbox" value="context.updated"> context.updated</label>' +
            '          <label><input type="checkbox" value="version.created"> version.created</label>' +
            '        </div></div>' +
            '        <button type="submit" class="btn btn-primary btn-sm">Register Webhook</button>' +
            '      </form>' +
            '      <div id="wh-list"></div>' +
            '    </div>' +
            '  </div>' +
            '</div>'
        );

        // Export
        document.getElementById('export-btn').addEventListener('click', async function () {
            try {
                var data = await D.api('/graph?policy=full');
                var blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url;
                a.download = 'cortex-graph-export.json';
                a.click();
                URL.revokeObjectURL(url);
                D.showToast('Graph exported', 'success');
            } catch (e) {
                D.showToast('Export failed: ' + e.message, 'error');
            }
        });

        // Webhook form
        document.getElementById('wh-form').addEventListener('submit', async function () {
            var url = document.getElementById('wh-url').value.trim();
            if (!url) return;
            var events = [];
            document.querySelectorAll('#wh-events input:checked').forEach(function (cb) {
                events.push(cb.value);
            });
            try {
                var result = await D.api('/webhooks', {
                    method: 'POST',
                    body: JSON.stringify({ url: url, events: events }),
                });
                D.showToast('Webhook registered', 'success');
                document.getElementById('wh-url').value = '';
                // Show secret once
                if (result.secret) {
                    alert('Webhook secret (save this):\n\n' + result.secret);
                }
                await loadWebhooks();
            } catch (e) {
                D.showToast('Failed: ' + e.message, 'error');
            }
        });

        await Promise.all([loadConfig(), loadWebhooks()]);
    });

    async function loadConfig() {
        try {
            var config = await D.api('/config');
            var html = '<table class="data-table"><tbody>';
            html += configRow('Port', config.port);
            html += configRow('DID', '<span class="truncated" onclick="CortexDashboard.copyToClipboard(\'' + D.escapeHtml(config.did || '') + '\')">' + D.truncateId(config.did, 24) + '</span>');
            html += configRow('Storage', config.storage_backend);
            html += configRow('Nodes', config.node_count);
            html += configRow('Edges', config.edge_count);
            html += configRow('Grants', config.grant_count);
            html += configRow('Webhooks', config.webhook_count);
            html += configRow('Policies', (config.policies || []).join(', '));
            html += '</tbody></table>';
            document.getElementById('settings-config').innerHTML = html;
        } catch (e) {
            if (e.message !== 'unauthorized') document.getElementById('settings-config').innerHTML = '<div class="loading">Failed to load config</div>';
        }
    }

    function configRow(label, value) {
        return '<tr><td style="font-weight:600;color:var(--text-muted);width:120px">' + label + '</td><td>' + (value == null ? '—' : value) + '</td></tr>';
    }

    async function loadWebhooks() {
        try {
            var data = await D.api('/webhooks');
            var webhooks = data.webhooks || [];
            if (webhooks.length === 0) {
                document.getElementById('wh-list').innerHTML = '<div class="loading">No webhooks registered</div>';
                return;
            }
            var html = '<table class="data-table"><thead><tr><th>URL</th><th>Events</th><th>Status</th><th></th></tr></thead><tbody>';
            webhooks.forEach(function (wh) {
                html += '<tr>' +
                    '<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + D.escapeHtml(wh.url) + '">' + D.escapeHtml(wh.url) + '</td>' +
                    '<td style="font-size:0.75rem">' + (wh.events || []).join(', ') + '</td>' +
                    '<td>' + (wh.active ? '<span class="badge badge-active">Active</span>' : '<span class="badge badge-revoked">Inactive</span>') + '</td>' +
                    '<td><button class="btn btn-danger btn-sm" onclick="CortexDashboard._deleteWebhook(\'' + D.escapeHtml(wh.webhook_id) + '\')">Delete</button></td>' +
                    '</tr>';
            });
            html += '</tbody></table>';
            document.getElementById('wh-list').innerHTML = html;
        } catch (e) {
            if (e.message !== 'unauthorized') document.getElementById('wh-list').innerHTML = '<div class="loading">Failed to load webhooks</div>';
        }
    }

    D._deleteWebhook = async function (webhookId) {
        if (!confirm('Delete this webhook?')) return;
        try {
            await D.api('/webhooks/' + webhookId, { method: 'DELETE' });
            D.showToast('Webhook deleted', 'success');
            await loadWebhooks();
        } catch (e) {
            D.showToast('Failed: ' + e.message, 'error');
        }
    };
})();
