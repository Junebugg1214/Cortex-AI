/* Cortex Dashboard — Grant Manager Page */
(function () {
    'use strict';
    var D = window.CortexDashboard;

    D.registerPage('grants', async function (container) {
        D.renderPage(container,
            '<h2 class="page-title">Grant Manager</h2>' +
            '<div class="two-col">' +
            '  <div class="card" id="grant-form-card">' +
            '    <div class="card-header">Create Grant</div>' +
            '    <form id="grant-form" onsubmit="return false">' +
            '      <div class="form-group"><label>Audience</label><input type="text" id="gf-audience" placeholder="e.g. claude.ai" required></div>' +
            '      <div class="form-group"><label>Policy</label>' +
            '        <select id="gf-policy"><option value="full">Full</option><option value="professional" selected>Professional</option><option value="technical">Technical</option><option value="minimal">Minimal</option></select>' +
            '      </div>' +
            '      <div class="form-group"><label>Scopes</label><div class="scope-list">' +
            '        <label><input type="checkbox" value="context:read" checked> context:read</label>' +
            '        <label><input type="checkbox" value="context:subscribe"> context:subscribe</label>' +
            '        <label><input type="checkbox" value="versions:read" checked> versions:read</label>' +
            '        <label><input type="checkbox" value="identity:read" checked> identity:read</label>' +
            '      </div></div>' +
            '      <div class="form-group"><label>TTL (hours): <span id="gf-ttl-val">24</span></label>' +
            '        <input type="range" id="gf-ttl" min="1" max="8760" value="24" style="width:100%">' +
            '      </div>' +
            '      <button type="submit" class="btn btn-primary" id="gf-submit">Create Grant</button>' +
            '    </form>' +
            '  </div>' +
            '  <div class="card">' +
            '    <div class="card-header">Active Grants</div>' +
            '    <div id="grant-list"></div>' +
            '  </div>' +
            '</div>' +
            '<div id="token-modal"></div>'
        );

        // TTL slider display
        document.getElementById('gf-ttl').addEventListener('input', function () {
            var v = parseInt(this.value);
            var display = v < 24 ? v + 'h' : (v / 24).toFixed(0) + 'd';
            document.getElementById('gf-ttl-val').textContent = display;
        });

        // Create grant
        document.getElementById('grant-form').addEventListener('submit', async function () {
            var audience = document.getElementById('gf-audience').value.trim();
            if (!audience) return;
            var policy = document.getElementById('gf-policy').value;
            var scopes = [];
            document.querySelectorAll('.scope-list input:checked').forEach(function (cb) {
                scopes.push(cb.value);
            });
            var ttl = parseInt(document.getElementById('gf-ttl').value);
            var btn = document.getElementById('gf-submit');
            btn.disabled = true;
            try {
                var result = await D.api('/grants', {
                    method: 'POST',
                    body: JSON.stringify({ audience: audience, policy: policy, scopes: scopes, ttl_hours: ttl }),
                });
                D.showToast('Grant created for ' + audience, 'success');
                showTokenModal(result);
                document.getElementById('gf-audience').value = '';
                await loadGrants();
            } catch (e) {
                D.showToast('Failed: ' + e.message, 'error');
            } finally {
                btn.disabled = false;
            }
        });

        await loadGrants();
    });

    async function loadGrants() {
        try {
            var data = await D.api('/grants');
            var grants = data.grants || [];
            if (grants.length === 0) {
                document.getElementById('grant-list').innerHTML = '<div class="loading">No grants yet</div>';
                return;
            }
            var html = '<table class="data-table"><thead><tr><th>ID</th><th>Audience</th><th>Policy</th><th>Status</th><th>Created</th><th></th></tr></thead><tbody>';
            grants.forEach(function (g) {
                var status = g.revoked
                    ? '<span class="badge badge-revoked">Revoked</span>'
                    : '<span class="badge badge-active">Active</span>';
                html += '<tr>' +
                    '<td><span class="truncated" onclick="CortexDashboard.copyToClipboard(\'' + D.escapeHtml(g.grant_id) + '\')">' + D.truncateId(g.grant_id) + '</span></td>' +
                    '<td>' + D.escapeHtml(g.audience || '') + '</td>' +
                    '<td>' + D.escapeHtml(g.policy || '') + '</td>' +
                    '<td>' + status + '</td>' +
                    '<td>' + D.formatDate(g.created_at) + '</td>' +
                    '<td>' + (g.revoked ? '' : '<button class="btn btn-danger btn-sm" onclick="CortexDashboard._revokeGrant(\'' + g.grant_id + '\')">Revoke</button>') + '</td>' +
                    '</tr>';
            });
            html += '</tbody></table>';
            document.getElementById('grant-list').innerHTML = html;
        } catch (e) {
            if (e.message !== 'unauthorized') D.showToast('Failed to load grants', 'error');
        }
    }

    function showTokenModal(result) {
        document.getElementById('token-modal').innerHTML =
            '<div class="modal-overlay" onclick="this.remove()">' +
            '  <div class="modal" onclick="event.stopPropagation()">' +
            '    <h3>Grant Created</h3>' +
            '    <p style="margin-bottom:12px">Copy this token now — it won\'t be shown again.</p>' +
            '    <div class="form-group"><label>Grant ID</label><input type="text" value="' + D.escapeHtml(result.grant_id) + '" readonly onclick="this.select()"></div>' +
            '    <div class="form-group"><label>Token</label><textarea readonly style="width:100%;height:80px;font-family:monospace;font-size:0.75rem;padding:8px;border:1px solid var(--border);border-radius:var(--radius)" onclick="this.select()">' + D.escapeHtml(result.token) + '</textarea></div>' +
            '    <p style="font-size:0.8rem;color:var(--text-muted)">Expires: ' + D.formatDate(result.expires_at) + ' | Policy: ' + D.escapeHtml(result.policy) + '</p>' +
            '    <div class="modal-actions">' +
            '      <button class="btn btn-primary" onclick="CortexDashboard.copyToClipboard(\'' + D.escapeHtml(result.token).replace(/'/g, "\\'") + '\');this.textContent=\'Copied!\'">Copy Token</button>' +
            '      <button class="btn btn-outline" onclick="this.closest(\'.modal-overlay\').remove()">Close</button>' +
            '    </div>' +
            '  </div>' +
            '</div>';
    }

    // Expose revoke to inline onclick
    D._revokeGrant = async function (grantId) {
        if (!confirm('Revoke grant ' + grantId.substring(0, 12) + '...?')) return;
        try {
            await D.api('/grants/' + grantId, { method: 'DELETE' });
            D.showToast('Grant revoked', 'success');
            await loadGrants();
        } catch (e) {
            D.showToast('Failed: ' + e.message, 'error');
        }
    };
})();
