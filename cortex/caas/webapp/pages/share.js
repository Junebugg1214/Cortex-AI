/* Cortex Web UI — Share Page */
(function () {
    'use strict';
    var C = window.CortexApp;

    var selectedPlatform = 'claude';
    var selectedPolicy = 'professional';
    var selectedIntent = 'assistant';
    var contextData = null;
    var exposureStats = { facts: 0, categories: 0 };

    var PLATFORMS = [
        { id: 'claude', name: 'Claude', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15v-4H7l5-8v4h4l-5 8z"/></svg>' },
        { id: 'notion', name: 'Notion', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>' },
        { id: 'docs', name: 'Google Docs', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>' },
        { id: 'prompt', name: 'System Prompt', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>' },
        { id: 'jsonresume', name: 'ATS / JSON Resume', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>' },
    ];

    var POLICIES = [
        { id: 'full', name: 'Everything', desc: 'Share all your facts' },
        { id: 'professional', name: 'Work Only', desc: 'Job, skills, and priorities' },
        { id: 'technical', name: 'Tech Only', desc: 'Tools, projects, and coding style' },
        { id: 'minimal', name: 'Minimal', desc: 'Lowest disclosure' },
    ];

    var INTENTS = [
        { id: 'assistant', name: 'Coding Assistant', desc: 'Use for coding copilots', platform: 'claude', policy: 'technical' },
        { id: 'recruiter', name: 'Recruiter / ATS', desc: 'Use for hiring workflows', platform: 'jsonresume', policy: 'professional' },
        { id: 'agent', name: 'Agent Handoff', desc: 'Use for personal agent setup', platform: 'prompt', policy: 'full' },
        { id: 'public', name: 'Public Bio', desc: 'Use for broad public sharing', platform: 'docs', policy: 'minimal' },
    ];

    C.registerPage('share', function (container) {
        var isConsumer = C.isConsumerMode && C.isConsumerMode();
        container.innerHTML =
            '<div class="page-header">' +
            '  <h1>Share</h1>' +
            '  <p>Simple flow: choose intent, check preview, then copy or download.</p>' +
            '</div>' +
            '<div class="card page-flow-cue">' +
            '  <span class="flow-step flow-step-active">1. Intent</span>' +
            '  <span class="flow-step">2. Preview</span>' +
            '  <span class="flow-step">3. Share</span>' +
            '</div>' +
            '<div class="share-layout">' +
            '  <div class="share-config">' +
            '    <div class="card">' +
            '      <div class="section-label">Intent</div>' +
            '      <div class="intent-cards" id="intent-cards"></div>' +
            '    </div>' +
            '    <div class="card technical-only">' +
            '      <div class="section-label">Platform</div>' +
            '      <div class="platform-cards" id="platform-cards"></div>' +
            '    </div>' +
            '    <div class="card technical-only">' +
            '      <div class="section-label">Privacy Level</div>' +
            '      <div class="privacy-options" id="privacy-options"></div>' +
            '    </div>' +
            '  </div>' +
            '  <div class="share-preview card" id="share-preview">' +
            '    <div class="preview-header">' +
            '      <h3>Preview</h3>' +
            '      <span class="preview-count" id="preview-count"></span>' +
            '    </div>' +
            '    <div id="intent-summary" class="intent-summary"></div>' +
            '    <div class="trust-indicator" id="trust-indicator"></div>' +
            '    <div class="preview-content" id="preview-content">Loading preview...</div>' +
            '    <div class="share-actions">' +
            '      <button class="btn btn-primary" id="btn-copy">Copy to Clipboard</button>' +
            '      <button class="btn btn-outline" id="btn-download">Download File</button>' +
            '    </div>' +
            '  </div>' +
            '</div>';

        renderIntents();
        if (!isConsumer) {
            renderPlatforms();
            renderPolicies();
        }
        applyIntent('assistant');

        document.getElementById('btn-copy').addEventListener('click', function () {
            var text = document.getElementById('preview-content').textContent;
            C.copyToClipboard(text);
            C.trackEvent('share.copied', { platform: selectedPlatform, policy: selectedPolicy });
        });

        document.getElementById('btn-download').addEventListener('click', function () {
            downloadExport();
        });
    });

    function renderIntents() {
        var container = document.getElementById('intent-cards');
        container.innerHTML = INTENTS.map(function (intent) {
            var cls = 'intent-card' + (intent.id === selectedIntent ? ' selected' : '');
            return (
                '<button class="' + cls + '" data-intent="' + intent.id + '">' +
                '  <div class="intent-title">' + C.escapeHtml(intent.name) + '</div>' +
                '  <div class="intent-desc">' + C.escapeHtml(intent.desc) + '</div>' +
                '</button>'
            );
        }).join('');

        container.querySelectorAll('.intent-card').forEach(function (card) {
            card.addEventListener('click', function () {
                applyIntent(this.getAttribute('data-intent'));
            });
        });
    }

    function applyIntent(intentId) {
        var intent = INTENTS.find(function (x) { return x.id === intentId; });
        if (!intent) return;
        selectedIntent = intent.id;
        selectedPlatform = intent.platform;
        selectedPolicy = intent.policy;
        renderIntents();
        if (!(C.isConsumerMode && C.isConsumerMode())) {
            renderPlatforms();
            renderPolicies();
        }
        loadPreview();
        renderIntentSummary();
        C.trackEvent('share.intent_selected', { intent: selectedIntent, platform: selectedPlatform, policy: selectedPolicy });
    }

    function renderIntentSummary() {
        var intent = INTENTS.find(function (x) { return x.id === selectedIntent; });
        var platformName = getPlatformName(selectedPlatform);
        var policyName = getPolicyName(selectedPolicy);
        var summary = document.getElementById('intent-summary');
        var title = intent ? intent.name : 'Custom';
        var desc = intent ? intent.desc : 'Manually selected settings';

        summary.innerHTML =
            '<strong>' + C.escapeHtml(title) + '</strong>' +
            ' · ' + C.escapeHtml(platformName) +
            ' · ' + C.escapeHtml(policyName) +
            '<br><span>' + C.escapeHtml(desc) + '</span>';
    }

    function renderPlatforms() {
        var container = document.getElementById('platform-cards');
        container.innerHTML = PLATFORMS.map(function (p) {
            return '<button class="platform-card' + (p.id === selectedPlatform ? ' selected' : '') + '" data-platform="' + p.id + '">' +
                p.icon + '<span>' + C.escapeHtml(p.name) + '</span></button>';
        }).join('');

        container.querySelectorAll('.platform-card').forEach(function (card) {
            card.addEventListener('click', function () {
                selectedPlatform = this.getAttribute('data-platform');
                selectedIntent = 'custom';
                renderIntents();
                renderPlatforms();
                renderIntentSummary();
                updatePreview();
                C.trackEvent('share.platform_changed', { platform: selectedPlatform });
            });
        });
    }

    function renderPolicies() {
        var container = document.getElementById('privacy-options');
        container.innerHTML = POLICIES.map(function (p) {
            return '<button class="privacy-option' + (p.id === selectedPolicy ? ' selected' : '') + '" data-policy="' + p.id + '">' +
                '<div class="privacy-radio"></div>' +
                '<div><div class="privacy-name">' + C.escapeHtml(p.name) + '</div>' +
                '<div class="privacy-desc">' + C.escapeHtml(p.desc) + '</div></div></button>';
        }).join('');

        container.querySelectorAll('.privacy-option').forEach(function (opt) {
            opt.addEventListener('click', function () {
                selectedPolicy = this.getAttribute('data-policy');
                selectedIntent = 'custom';
                renderIntents();
                renderPolicies();
                renderIntentSummary();
                loadPreview();
                C.trackEvent('share.policy_changed', { policy: selectedPolicy });
            });
        });
    }

    function extractNodesFromContext(data) {
        if (!data) return [];
        if (data.context && data.context.nodes) return data.context.nodes;
        if (data.nodes) return data.nodes;
        if (data.graph && data.graph.nodes) {
            var nodes = data.graph.nodes;
            return Array.isArray(nodes) ? nodes : Object.values(nodes);
        }
        return [];
    }

    function updateTrustIndicator() {
        var el = document.getElementById('trust-indicator');
        if (!el) return;
        el.textContent = 'Current policy exposes about ' + exposureStats.facts + ' facts across ' + exposureStats.categories + ' categories.';
    }

    function loadExposureStats() {
        C.api('/context?policy=' + selectedPolicy).then(function (data) {
            var nodes = extractNodesFromContext(data);
            var tagSet = {};
            nodes.forEach(function (n) {
                (n.tags || []).forEach(function (tag) { tagSet[String(tag || '').toLowerCase()] = true; });
            });
            exposureStats = { facts: nodes.length, categories: Object.keys(tagSet).length };
            updateTrustIndicator();
        }).catch(function () {
            exposureStats = { facts: 0, categories: 0 };
            updateTrustIndicator();
        });
    }

    function loadPreview() {
        loadExposureStats();

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
                renderIntentSummary();
            })
            .catch(function (err) {
                if (err.message === 'unauthorized') return;
                C.api('/context?policy=' + selectedPolicy).then(function (data) {
                    contextData = data;
                    updatePreview();
                    renderIntentSummary();
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
        var nodeCount = 0;
        if (typeof contextData === 'string') {
            text = contextData;
        } else {
            var nodes = extractNodesFromContext(contextData);
            nodeCount = nodes.length;
            if (!nodeCount) {
                content.innerHTML =
                    '<div class="empty-state">' +
                    '  <h3>No shareable data yet</h3>' +
                    '  <p>Import data first, then return here to generate exports.</p>' +
                    '  <a class="btn btn-primary empty-state-action" href="#upload">Go to Import</a>' +
                    '</div>';
                count.textContent = '0 lines';
                return;
            }
            text = formatForPlatform({ nodes: nodes });
        }

        content.textContent = text;
        count.textContent = text.split('\n').length + ' lines';
        C.trackEvent('share.preview_loaded', { platform: selectedPlatform, policy: selectedPolicy, facts: nodeCount || exposureStats.facts });
    }

    function formatForPlatform(data) {
        var nodes = data.nodes || [];
        var lines = [];

        if (selectedPlatform === 'prompt') {
            lines.push('# User Context');
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

    function getPlatformName(id) {
        var item = PLATFORMS.find(function (p) { return p.id === id; });
        return item ? item.name : id;
    }

    function getPolicyName(id) {
        var item = POLICIES.find(function (p) { return p.id === id; });
        return item ? item.name : id;
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
        C.trackEvent('share.downloaded', { platform: selectedPlatform, policy: selectedPolicy, ext: ext });
    }
})();
