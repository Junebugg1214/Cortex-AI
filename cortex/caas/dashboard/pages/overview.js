/* Cortex Dashboard — Overview Page */
(function () {
    'use strict';
    var D = window.CortexDashboard;

    D.registerPage('overview', async function (container) {
        D.renderPage(container, '<h2 class="page-title">Overview</h2>' +
            '<div class="stats-grid" id="ov-stats"></div>' +
            '<div class="two-col">' +
            '  <div class="card" id="ov-tags"><div class="card-header">Tag Distribution</div><div id="ov-tag-bars"></div></div>' +
            '  <div class="card" id="ov-activity"><div class="card-header">Recent Activity</div><div id="ov-audit"></div></div>' +
            '</div>'
        );

        try {
            var [identity, stats, audit, grants] = await Promise.all([
                D.api('/identity'),
                D.api('/stats'),
                D.api('/audit?limit=10'),
                D.api('/grants'),
            ]);

            // Identity + stats cards
            var activeGrants = grants.grants.filter(function (g) { return !g.revoked; }).length;
            document.getElementById('ov-stats').innerHTML =
                statCard('DID', '<span class="truncated" onclick="CortexDashboard.copyToClipboard(\'' + D.escapeHtml(identity.did) + '\')">' + D.truncateId(identity.did, 20) + '</span>', identity.key_type) +
                statCard('Nodes', stats.node_count, 'In graph') +
                statCard('Edges', stats.edge_count, 'Avg degree: ' + (stats.avg_degree || 0).toFixed(1)) +
                statCard('Active Grants', activeGrants, grants.grants.length + ' total');

            // Tag bars
            var tagDist = stats.tag_distribution || {};
            var maxCount = Math.max.apply(null, Object.values(tagDist).concat([1]));
            var tagHtml = '';
            var sorted = Object.entries(tagDist).sort(function (a, b) { return b[1] - a[1]; });
            sorted.slice(0, 12).forEach(function (entry) {
                var pct = Math.round((entry[1] / maxCount) * 100);
                tagHtml += '<div class="tag-bar">' +
                    '<span class="tag-bar-label">' + D.escapeHtml(entry[0]) + '</span>' +
                    '<div class="tag-bar-fill" style="width:' + pct + '%;background:' + tagColor(entry[0]) + '"></div>' +
                    '<span class="tag-bar-count">' + entry[1] + '</span></div>';
            });
            document.getElementById('ov-tag-bars').innerHTML = tagHtml || '<div class="loading">No tags</div>';

            // Audit log
            var entries = (audit.entries || []);
            if (entries.length === 0) {
                document.getElementById('ov-audit').innerHTML = '<div class="loading">No recent activity</div>';
            } else {
                var auditHtml = '<table class="data-table"><thead><tr><th>Event</th><th>Time</th></tr></thead><tbody>';
                entries.forEach(function (e) {
                    auditHtml += '<tr><td>' + D.escapeHtml(e.event_type || e.event || '') + '</td>' +
                        '<td>' + D.formatDate(e.timestamp) + '</td></tr>';
                });
                auditHtml += '</tbody></table>';
                document.getElementById('ov-audit').innerHTML = auditHtml;
            }
        } catch (e) {
            if (e.message !== 'unauthorized') D.showToast('Failed to load overview: ' + e.message, 'error');
        }
    });

    function statCard(label, value, detail) {
        return '<div class="card">' +
            '<div class="card-header">' + D.escapeHtml(label) + '</div>' +
            '<div class="card-value">' + value + '</div>' +
            (detail ? '<div style="font-size:0.8rem;color:var(--text-muted);margin-top:4px">' + detail + '</div>' : '') +
            '</div>';
    }

    // Simple tag color mapping (matches Python _tag_color palette)
    var TAG_COLORS = {
        identity: '#e74c3c', professional_context: '#3498db', skills_and_expertise: '#2ecc71',
        interests_and_values: '#9b59b6', personality_and_communication: '#f39c12',
        goals_and_aspirations: '#1abc9c', routine_and_preferences: '#e67e22',
        background_and_history: '#34495e', social_and_relationships: '#e91e63',
        health_and_wellness: '#00bcd4', financial: '#795548', creative_works: '#ff5722',
    };
    var EXTRA_COLORS = ['#16a085','#c0392b','#8e44ad','#d35400','#27ae60','#2980b9'];

    function tagColor(tag) {
        if (TAG_COLORS[tag]) return TAG_COLORS[tag];
        var h = 0;
        for (var i = 0; i < tag.length; i++) h = ((h << 5) - h + tag.charCodeAt(i)) | 0;
        return EXTRA_COLORS[Math.abs(h) % EXTRA_COLORS.length];
    }
})();
