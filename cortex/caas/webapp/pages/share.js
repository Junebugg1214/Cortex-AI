/* Cortex Web UI — Share Page */
(function () {
    'use strict';
    var C = window.CortexApp;

    var selectedPlatform = 'claude';
    var selectedPolicy = 'professional';
    var contextData = null;

    var PLATFORMS = [
        { id: 'claude', name: 'Claude', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15v-4H7l5-8v4h4l-5 8z"/></svg>' },
        { id: 'notion', name: 'Notion', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>' },
        { id: 'docs', name: 'Google Docs', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>' },
        { id: 'prompt', name: 'System Prompt', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>' },
        { id: 'jsonresume', name: 'ATS / JSON Resume', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>' },
    ];

    var POLICIES = [
        { id: 'full', name: 'Everything', desc: 'Share all your facts — the complete picture' },
        { id: 'professional', name: 'Work Only', desc: 'Just your job, skills, and priorities' },
        { id: 'technical', name: 'Tech Only', desc: 'Only your tech stack and preferences' },
        { id: 'minimal', name: 'Minimal', desc: 'Almost nothing — just basic preferences' },
    ];

    C.registerPage('share', function (container) {
        container.innerHTML =
            '<div class="page-header">' +
            '  <h1>Share</h1>' +
            '  <p>Export your memory for use with other platforms</p>' +
            '</div>' +
            '<div class="share-layout">' +
            '  <div class="share-config">' +
            '    <div>' +
            '      <div class="section-label">Platform</div>' +
            '      <div class="platform-cards" id="platform-cards"></div>' +
            '    </div>' +
            '    <div>' +
            '      <div class="section-label">Privacy Level</div>' +
            '      <div class="privacy-options" id="privacy-options"></div>' +
            '    </div>' +
            '  </div>' +
            '  <div class="share-preview card" id="share-preview">' +
            '    <div class="preview-header">' +
            '      <h3>Preview</h3>' +
            '      <span class="preview-count" id="preview-count"></span>' +
            '    </div>' +
            '    <div class="preview-content" id="preview-content">Loading preview...</div>' +
            '    <div class="share-actions">' +
            '      <button class="btn btn-primary" id="btn-copy">Copy to Clipboard</button>' +
            '      <button class="btn btn-outline" id="btn-download">Download File</button>' +
            '    </div>' +
            '  </div>' +
            '</div>';

        renderPlatforms();
        renderPolicies();
        loadPreview();

        document.getElementById('btn-copy').addEventListener('click', function () {
            var text = document.getElementById('preview-content').textContent;
            C.copyToClipboard(text);
        });

        document.getElementById('btn-download').addEventListener('click', function () {
            downloadExport();
        });
    });

    function renderPlatforms() {
        var container = document.getElementById('platform-cards');
        container.innerHTML = PLATFORMS.map(function (p) {
            return '<button class="platform-card' + (p.id === selectedPlatform ? ' selected' : '') +
                '" data-platform="' + p.id + '">' +
                p.icon + '<span>' + C.escapeHtml(p.name) + '</span></button>';
        }).join('');

        container.querySelectorAll('.platform-card').forEach(function (card) {
            card.addEventListener('click', function () {
                selectedPlatform = this.getAttribute('data-platform');
                renderPlatforms();
                updatePreview();
            });
        });
    }

    function renderPolicies() {
        var container = document.getElementById('privacy-options');
        container.innerHTML = POLICIES.map(function (p) {
            return '<button class="privacy-option' + (p.id === selectedPolicy ? ' selected' : '') +
                '" data-policy="' + p.id + '">' +
                '<div class="privacy-radio"></div>' +
                '<div><div class="privacy-name">' + C.escapeHtml(p.name) + '</div>' +
                '<div class="privacy-desc">' + C.escapeHtml(p.desc) + '</div></div></button>';
        }).join('');

        container.querySelectorAll('.privacy-option').forEach(function (opt) {
            opt.addEventListener('click', function () {
                selectedPolicy = this.getAttribute('data-policy');
                renderPolicies();
                loadPreview();
            });
        });
    }

    function normalizeGraphData(data) {
        if (data && data.graph) {
            var g = data.graph;
            var nodes = g.nodes || {};
            var edges = g.edges || {};
            return {
                nodes: Array.isArray(nodes) ? nodes : Object.values(nodes),
                edges: Array.isArray(edges) ? edges : Object.values(edges),
            };
        }
        return data;
    }

    function loadPreview() {
        C.apiRaw('/context/compact?policy=' + selectedPolicy, { method: 'GET' })
            .then(function (resp) {
                if (resp.status === 401) {
                    C.showLogin();
                    throw new Error('unauthorized');
                }
                if (!resp.ok) throw new Error('compact preview unavailable');
                return resp.text();
            })
            .then(function (text) {
                contextData = text;
                updatePreview();
            })
            .catch(function (err) {
                if (err.message === 'unauthorized') return;
                // Fallback: try full context
                C.api('/context?policy=' + selectedPolicy).then(function (data) {
                    contextData = normalizeGraphData(data);
                    updatePreview();
                }).catch(function (err2) {
                    if (err2.message === 'unauthorized') return;
                    document.getElementById('preview-content').textContent = 'Could not load preview: ' + err2.message;
                });
            });
    }

    function updatePreview() {
        var content = document.getElementById('preview-content');
        var count = document.getElementById('preview-count');

        if (!contextData) {
            content.textContent = 'Loading...';
            return;
        }

        var text = '';
        if (typeof contextData === 'string') {
            text = contextData;
        } else if (contextData.markdown) {
            text = contextData.markdown;
        } else if (contextData.context) {
            text = formatForPlatform(contextData.context);
        } else if (contextData.nodes) {
            text = formatForPlatform(contextData);
        } else {
            text = JSON.stringify(contextData, null, 2);
        }

        content.textContent = text;

        var lines = text.split('\n').length;
        count.textContent = lines + ' lines';
    }

    function formatForPlatform(data) {
        var nodes = data.nodes || [];
        var lines = [];

        if (selectedPlatform === 'prompt') {
            lines.push('# User Context');
            lines.push('');
            lines.push('The following is known about the user:');
            lines.push('');
            nodes.forEach(function (n) {
                var tags = (n.tags || []).join(', ');
                lines.push('- ' + (n.label || n.id) + (tags ? ' [' + tags + ']' : ''));
            });
        } else if (selectedPlatform === 'claude') {
            lines.push('<user-context>');
            nodes.forEach(function (n) {
                var brief = n.brief ? ': ' + n.brief : '';
                lines.push('  <fact tags="' + (n.tags || []).join(',') + '">' + (n.label || n.id) + brief + '</fact>');
            });
            lines.push('</user-context>');
        } else if (selectedPlatform === 'notion') {
            lines.push('# My Knowledge Graph');
            lines.push('');
            // Group by first tag
            var groups = {};
            nodes.forEach(function (n) {
                var tag = (n.tags && n.tags[0]) || 'Other';
                if (!groups[tag]) groups[tag] = [];
                groups[tag].push(n);
            });
            Object.keys(groups).forEach(function (tag) {
                lines.push('## ' + tag);
                groups[tag].forEach(function (n) {
                    lines.push('- **' + (n.label || n.id) + '**' + (n.brief ? ' — ' + n.brief : ''));
                });
                lines.push('');
            });
        } else if (selectedPlatform === 'jsonresume') {
            // Best effort: expose stable JSON structure for ATS/tools.
            return JSON.stringify({
                generated_at: new Date().toISOString(),
                policy: selectedPolicy,
                nodes: nodes.map(function (n) {
                    return {
                        id: n.id,
                        label: n.label || n.id,
                        tags: n.tags || [],
                        brief: n.brief || '',
                    };
                }),
            }, null, 2);
        } else {
            // Google Docs / generic
            lines.push('Personal Knowledge Graph Export');
            lines.push('Policy: ' + selectedPolicy);
            lines.push('Date: ' + new Date().toLocaleDateString());
            lines.push('');
            nodes.forEach(function (n) {
                lines.push('* ' + (n.label || n.id));
                if (n.brief) lines.push('  ' + n.brief);
            });
        }

        return lines.join('\n');
    }

    function downloadExport() {
        var text = document.getElementById('preview-content').textContent;
        var ext = '.md';
        var mimeType = 'text/markdown';
        if (selectedPlatform === 'claude') {
            ext = '.xml';
            mimeType = 'application/xml';
        } else if (selectedPlatform === 'jsonresume') {
            ext = '.json';
            mimeType = 'application/json';
        }

        var blob = new Blob([text], { type: mimeType });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'cortex-export-' + selectedPolicy + ext;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        C.showToast('File downloaded', 'success');
    }
})();
