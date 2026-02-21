/* Cortex Dashboard — Version Timeline Page */
(function () {
    'use strict';
    var D = window.CortexDashboard;

    var versions = [];

    D.registerPage('versions', async function (container) {
        D.renderPage(container,
            '<h2 class="page-title">Version Timeline</h2>' +
            '<div class="two-col">' +
            '  <div>' +
            '    <div class="card">' +
            '      <div class="card-header">History</div>' +
            '      <div id="version-timeline" class="timeline"></div>' +
            '    </div>' +
            '  </div>' +
            '  <div>' +
            '    <div class="card">' +
            '      <div class="card-header">Compare Versions</div>' +
            '      <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px">' +
            '        <select id="diff-a" style="flex:1;padding:6px;border:1px solid var(--border);border-radius:var(--radius)"></select>' +
            '        <span style="color:var(--text-muted)">vs</span>' +
            '        <select id="diff-b" style="flex:1;padding:6px;border:1px solid var(--border);border-radius:var(--radius)"></select>' +
            '        <button class="btn btn-primary btn-sm" id="diff-btn">Compare</button>' +
            '      </div>' +
            '      <div id="diff-result"></div>' +
            '    </div>' +
            '  </div>' +
            '</div>'
        );

        document.getElementById('diff-btn').addEventListener('click', async function () {
            var a = document.getElementById('diff-a').value;
            var b = document.getElementById('diff-b').value;
            if (!a || !b) { D.showToast('Select two versions', 'error'); return; }
            if (a === b) { D.showToast('Select different versions', 'error'); return; }
            await loadDiff(a, b);
        });

        await loadVersions();
    });

    async function loadVersions() {
        try {
            var data = await D.api('/versions?limit=50');
            versions = data.items || [];
            var timelineEl = document.getElementById('version-timeline');
            var selectA = document.getElementById('diff-a');
            var selectB = document.getElementById('diff-b');

            if (versions.length === 0) {
                timelineEl.innerHTML = '<div class="loading">No versions yet. Use <code>cortex commit</code> to create one.</div>';
                return;
            }

            var timelineHtml = '';
            var optionsHtml = '';
            versions.forEach(function (v, i) {
                timelineHtml +=
                    '<div class="timeline-item">' +
                    '  <div class="timeline-card">' +
                    '    <div class="timeline-meta">' + D.formatDate(v.timestamp) + ' &middot; ' + D.escapeHtml(v.source || 'manual') + '</div>' +
                    '    <div style="font-weight:600">' + D.escapeHtml(v.message || 'No message') + '</div>' +
                    '    <div style="font-size:0.8rem;color:var(--text-muted);margin-top:4px">' +
                    '      <span class="truncated" onclick="CortexDashboard.copyToClipboard(\'' + D.escapeHtml(v.version_id) + '\')">' + D.truncateId(v.version_id) + '</span>' +
                    '      &middot; ' + (v.node_count || 0) + ' nodes, ' + (v.edge_count || 0) + ' edges' +
                    (v.signature ? ' &middot; signed' : '') +
                    '    </div>' +
                    '  </div>' +
                    '</div>';

                var label = D.truncateId(v.version_id) + ' — ' + (v.message || '').substring(0, 30);
                optionsHtml += '<option value="' + D.escapeHtml(v.version_id) + '">' + D.escapeHtml(label) + '</option>';
            });
            timelineEl.innerHTML = timelineHtml;
            selectA.innerHTML = optionsHtml;
            selectB.innerHTML = optionsHtml;
            // Default: compare last two
            if (versions.length >= 2) {
                selectB.selectedIndex = 1;
            }
        } catch (e) {
            if (e.message !== 'unauthorized') D.showToast('Failed to load versions', 'error');
        }
    }

    async function loadDiff(a, b) {
        var el = document.getElementById('diff-result');
        el.innerHTML = '<div class="loading">Computing diff...</div>';
        try {
            var diff = await D.api('/versions/diff?a=' + encodeURIComponent(a) + '&b=' + encodeURIComponent(b));
            var html = '<div class="diff-container">';

            if (diff.added_nodes && diff.added_nodes.length) {
                html += '<div style="margin-bottom:12px"><strong>Added Nodes (' + diff.added_nodes.length + ')</strong></div>';
                diff.added_nodes.forEach(function (n) {
                    html += '<div class="diff-added">+ ' + D.escapeHtml(n.label || n.id || n) + '</div>';
                });
            }

            if (diff.removed_nodes && diff.removed_nodes.length) {
                html += '<div style="margin:12px 0"><strong>Removed Nodes (' + diff.removed_nodes.length + ')</strong></div>';
                diff.removed_nodes.forEach(function (n) {
                    html += '<div class="diff-removed">- ' + D.escapeHtml(n.label || n.id || n) + '</div>';
                });
            }

            if (diff.modified_nodes && diff.modified_nodes.length) {
                html += '<div style="margin:12px 0"><strong>Modified Nodes (' + diff.modified_nodes.length + ')</strong></div>';
                diff.modified_nodes.forEach(function (n) {
                    html += '<div class="diff-modified">~ ' + D.escapeHtml(n.label || n.id || n) + '</div>';
                });
            }

            if (diff.added_edges && diff.added_edges.length) {
                html += '<div style="margin:12px 0"><strong>Added Edges (' + diff.added_edges.length + ')</strong></div>';
                diff.added_edges.forEach(function (e) {
                    html += '<div class="diff-added">+ ' + D.escapeHtml((e.source || '') + ' --[' + (e.relation || '') + ']--> ' + (e.target || '')) + '</div>';
                });
            }

            if (diff.removed_edges && diff.removed_edges.length) {
                html += '<div style="margin:12px 0"><strong>Removed Edges (' + diff.removed_edges.length + ')</strong></div>';
                diff.removed_edges.forEach(function (e) {
                    html += '<div class="diff-removed">- ' + D.escapeHtml((e.source || '') + ' --[' + (e.relation || '') + ']--> ' + (e.target || '')) + '</div>';
                });
            }

            var hasContent = (diff.added_nodes && diff.added_nodes.length) ||
                (diff.removed_nodes && diff.removed_nodes.length) ||
                (diff.modified_nodes && diff.modified_nodes.length) ||
                (diff.added_edges && diff.added_edges.length) ||
                (diff.removed_edges && diff.removed_edges.length);

            if (!hasContent) {
                html += '<div style="color:var(--text-muted)">No differences found.</div>';
            }

            html += '</div>';
            el.innerHTML = html;
        } catch (e) {
            el.innerHTML = '<div class="loading" style="color:var(--danger)">Failed: ' + D.escapeHtml(e.message) + '</div>';
        }
    }
})();
