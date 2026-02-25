/* Cortex Dashboard — Graph Health Page */
(function () {
    'use strict';
    var D = window.CortexDashboard;

    D.registerPage('health', async function (container) {
        D.renderPage(container,
            '<h2 class="page-title">Graph Health</h2>' +
            '<div class="stats-grid" id="health-stats"></div>' +
            '<div class="two-col">' +
            '  <div class="card" id="health-conf">' +
            '    <div class="card-header">Confidence Distribution</div>' +
            '    <div id="conf-bars"></div>' +
            '  </div>' +
            '  <div class="card" id="health-tags">' +
            '    <div class="card-header">Avg Confidence per Tag</div>' +
            '    <div id="tag-conf-bars"></div>' +
            '  </div>' +
            '</div>' +
            '<div class="card" style="margin-top:16px">' +
            '  <div class="card-header">Stale Nodes (>30 days)</div>' +
            '  <div id="stale-table"></div>' +
            '</div>' +
            '<div class="card" style="margin-top:16px">' +
            '  <div class="card-header">Orphan Nodes (no edges)</div>' +
            '  <div id="orphan-table"></div>' +
            '</div>' +
            '<div class="card" style="margin-top:16px">' +
            '  <div class="card-header">Recent Changes</div>' +
            '  <div id="changelog-feed"></div>' +
            '</div>'
        );

        try {
            var [health, changelog] = await Promise.all([
                D.api('/health'),
                D.api('/changelog?limit=5'),
            ]);

            // Stat cards
            document.getElementById('health-stats').innerHTML =
                statCard('Total Nodes', health.total_nodes, '') +
                statCard('Total Edges', health.total_edges, '') +
                statCard('Avg Confidence', health.avg_confidence.toFixed(2), '') +
                statCard('Stale Nodes', health.stale_count, '>30 days') +
                statCard('Orphan Nodes', health.orphan_count, 'No edges');

            // Confidence distribution bars
            var confDist = health.confidence_distribution || {};
            var maxConf = Math.max.apply(null, Object.values(confDist).concat([1]));
            var confHtml = '';
            Object.entries(confDist).forEach(function (entry) {
                var pct = Math.round((entry[1] / maxConf) * 100);
                confHtml += '<div class="tag-bar">' +
                    '<span class="tag-bar-label">' + entry[0] + '</span>' +
                    '<div class="tag-bar-fill" style="width:' + pct + '%;background:#4f46e5"></div>' +
                    '<span class="tag-bar-count">' + entry[1] + '</span></div>';
            });
            document.getElementById('conf-bars').innerHTML = confHtml || '<div class="loading">No data</div>';

            // Avg confidence per tag
            var tagConf = health.avg_confidence_per_tag || {};
            var tagHtml = '';
            var tagEntries = Object.entries(tagConf).sort(function (a, b) { return b[1] - a[1]; });
            tagEntries.slice(0, 12).forEach(function (entry) {
                var pct = Math.round(entry[1] * 100);
                tagHtml += '<div class="tag-bar">' +
                    '<span class="tag-bar-label">' + D.escapeHtml(entry[0]) + '</span>' +
                    '<div class="tag-bar-fill" style="width:' + pct + '%;background:#059669"></div>' +
                    '<span class="tag-bar-count">' + entry[1].toFixed(2) + '</span></div>';
            });
            document.getElementById('tag-conf-bars').innerHTML = tagHtml || '<div class="loading">No tags</div>';

            // Stale nodes table
            var stale = health.stale_nodes || [];
            if (stale.length === 0) {
                document.getElementById('stale-table').innerHTML = '<div class="loading">No stale nodes</div>';
            } else {
                var sh = '<table class="data-table"><thead><tr><th>Label</th><th>Last Seen</th><th>Days Stale</th></tr></thead><tbody>';
                stale.forEach(function (n) {
                    sh += '<tr><td>' + D.escapeHtml(n.label) + '</td><td>' + D.formatDate(n.last_seen) + '</td><td>' + n.days_stale + '</td></tr>';
                });
                sh += '</tbody></table>';
                document.getElementById('stale-table').innerHTML = sh;
            }

            // Orphan nodes table
            var orphans = health.orphan_nodes || [];
            if (orphans.length === 0) {
                document.getElementById('orphan-table').innerHTML = '<div class="loading">No orphan nodes</div>';
            } else {
                var oh = '<table class="data-table"><thead><tr><th>Label</th><th>Tags</th></tr></thead><tbody>';
                orphans.forEach(function (n) {
                    oh += '<tr><td>' + D.escapeHtml(n.label) + '</td><td>' + D.escapeHtml((n.tags || []).join(', ')) + '</td></tr>';
                });
                oh += '</tbody></table>';
                document.getElementById('orphan-table').innerHTML = oh;
            }

            // Changelog feed
            var entries = (changelog.entries || []);
            if (entries.length === 0) {
                document.getElementById('changelog-feed').innerHTML = '<div class="loading">No version history</div>';
            } else {
                var ch = '';
                entries.forEach(function (e) {
                    var s = e.diff && e.diff.summary ? e.diff.summary : {};
                    var parts = [];
                    if (s.added) parts.push('+' + s.added + ' added');
                    if (s.removed) parts.push('-' + s.removed + ' removed');
                    if (s.modified) parts.push(s.modified + ' modified');
                    if (s.edges_added) parts.push('+' + s.edges_added + ' edges');
                    if (s.edges_removed) parts.push('-' + s.edges_removed + ' edges');
                    var summary = parts.join(', ') || 'no changes';
                    ch += '<div style="padding:8px 0;border-bottom:1px solid var(--border)">' +
                        '<div style="font-weight:600;font-size:14px">' + D.escapeHtml(e.message || 'Version ' + e.version_id.substring(0, 8)) + '</div>' +
                        '<div style="font-size:12px;color:var(--text-muted)">' + D.formatDate(e.timestamp) + ' — ' + D.escapeHtml(summary) + '</div>' +
                        '</div>';
                });
                document.getElementById('changelog-feed').innerHTML = ch;
            }
        } catch (e) {
            if (e.message !== 'unauthorized') D.showToast('Failed to load health: ' + e.message, 'error');
        }
    });

    function statCard(label, value, detail) {
        return '<div class="card">' +
            '<div class="card-header">' + D.escapeHtml(String(label)) + '</div>' +
            '<div class="card-value">' + value + '</div>' +
            (detail ? '<div style="font-size:0.8rem;color:var(--text-muted);margin-top:4px">' + detail + '</div>' : '') +
            '</div>';
    }
})();
