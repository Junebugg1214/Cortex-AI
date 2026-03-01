/* Cortex Web UI — Upload Page */
(function () {
    'use strict';
    var C = window.CortexApp;
    var maxUploadBytes = 3 * 1024 * 1024 * 1024; // Fallback default: 3GB

    C.registerPage('upload', function (container) {
        container.innerHTML =
            '<div class="page-header">' +
            '  <h1>Upload</h1>' +
            '  <p>Import your data to build your personal knowledge graph</p>' +
            '</div>' +
            '<div id="upload-area"></div>' +
            '<div id="import-cards-area"></div>' +
            '<div id="api-keys-area"></div>';

        renderDropZone();
        renderImportCards();
        renderApiKeys();
        loadUploadConfig();
    });

    // ── Drop Zone ──────────────────────────────────────────────────

    function renderDropZone() {
        var area = document.getElementById('upload-area');
        area.innerHTML =
            '<div class="card">' +
            '  <div class="upload-zone" id="drop-zone">' +
            '    <div class="upload-zone-icon">' +
            '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
            '        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>' +
            '        <polyline points="17 8 12 3 7 8"/>' +
            '        <line x1="12" y1="3" x2="12" y2="15"/>' +
            '      </svg>' +
            '    </div>' +
            '    <h2>Drop your file here</h2>' +
            '    <p>Supports JSON, text, PDF, DOCX, and zip files. Drop chat exports, resumes, or LinkedIn data exports.</p>' +
            '    <input type="file" id="file-input" class="upload-hidden-input" accept=".json,.txt,.md,.csv,.zip,.pdf,.docx">' +
            '    <div class="platform-icons">' +
            '      <div class="platform-icon">' +
            '        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M22.28 10.42c-.2-.14-.42-.22-.65-.22H14.6l2.24-6.41c.16-.48-.05-1-.5-1.22a.99.99 0 00-1.17.25L5.32 13.58c-.18.2-.28.46-.28.73 0 .58.47 1.05 1.05 1.05h7.03l-2.24 6.41c-.16.48.05 1 .5 1.22.14.07.3.1.45.1.33 0 .64-.15.85-.42l9.85-10.76c.18-.2.28-.46.28-.73a1.03 1.03 0 00-.53-.76z"/></svg>' +
            '        <span>ChatGPT</span>' +
            '      </div>' +
            '      <div class="platform-icon">' +
            '        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15v-4H7l5-8v4h4l-5 8z"/></svg>' +
            '        <span>Claude</span>' +
            '      </div>' +
            '      <div class="platform-icon">' +
            '        <svg viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>' +
            '        <span>Resume</span>' +
            '      </div>' +
            '      <div class="platform-icon">' +
            '        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 3a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h14m-.5 15.5v-5.3a3.26 3.26 0 00-3.26-3.26c-.85 0-1.84.52-2.32 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 011.4 1.4v4.93h2.79M6.88 8.56a1.68 1.68 0 001.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 00-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>' +
            '        <span>LinkedIn</span>' +
            '      </div>' +
            '    </div>' +
            '  </div>' +
            '</div>';

        var dropZone = document.getElementById('drop-zone');
        var fileInput = document.getElementById('file-input');

        dropZone.addEventListener('click', function () { fileInput.click(); });

        dropZone.addEventListener('dragover', function (e) {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });

        dropZone.addEventListener('dragleave', function () {
            dropZone.classList.remove('dragover');
        });

        dropZone.addEventListener('drop', function (e) {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) {
                handleFile(e.dataTransfer.files[0]);
            }
        });

        fileInput.addEventListener('change', function () {
            if (fileInput.files.length > 0) {
                handleFile(fileInput.files[0]);
            }
        });
    }

    function handleFile(file) {
        if (file.size > maxUploadBytes) {
            C.showToast('File too large. Maximum size is ' + formatBytes(maxUploadBytes) + '.', 'error');
            return;
        }

        renderProgress(file.name);
        uploadFile(file);
    }

    function formatBytes(bytes) {
        if (bytes >= 1024 * 1024 * 1024) {
            return (bytes / (1024 * 1024 * 1024)).toFixed(0) + ' GB';
        }
        if (bytes >= 1024 * 1024) {
            return Math.round(bytes / (1024 * 1024)) + ' MB';
        }
        return bytes + ' bytes';
    }

    function loadUploadConfig() {
        C.apiRaw('/api/users/config', { method: 'GET' })
            .then(function (resp) {
                if (!resp.ok) return null;
                return resp.json();
            })
            .then(function (cfg) {
                if (!cfg) return;
                if (typeof cfg.max_upload_bytes === 'number' && cfg.max_upload_bytes > 0) {
                    maxUploadBytes = cfg.max_upload_bytes;
                }
            })
            .catch(function () {
                // Keep fallback.
            });
    }

    function renderProgress(filename) {
        var area = document.getElementById('upload-area');
        area.innerHTML =
            '<div class="card">' +
            '  <div class="upload-progress">' +
            '    <div class="progress-spinner"></div>' +
            '    <div class="progress-text">Processing ' + C.escapeHtml(filename) + '</div>' +
            '    <div class="progress-sub">Extracting facts and connections...</div>' +
            '  </div>' +
            '</div>';
    }

    function uploadFile(file) {
        var formData = new FormData();
        formData.append('file', file);

        C.apiRaw('/api/upload', {
            method: 'POST',
            body: formData,
        }).then(function (resp) {
            if (resp.status === 401) {
                C.showLogin();
                throw new Error('Your session expired. Please sign in and try again.');
            }
            return resp.json().then(function (data) {
                if (!resp.ok) {
                    var msg = (data.error && data.error.message) || data.error || 'Upload failed';
                    throw new Error(msg);
                }
                return data;
            });
        }).then(function (data) {
            renderResults(data);
        }).catch(function (err) {
            C.showToast('Upload failed: ' + err.message, 'error');
            renderDropZone();
        });
    }

    function renderResults(data) {
        var nodes = data.nodes_created || 0;
        var edges = data.edges_created || 0;
        var categories = data.categories || 0;
        var sourceLabel = 'Your data has been processed successfully';
        if (data.source_type === 'resume') {
            sourceLabel = 'Your resume has been processed successfully';
        } else if (data.source_type === 'linkedin_export') {
            sourceLabel = 'Your LinkedIn data has been imported successfully';
        } else if (data.source_type === 'github') {
            sourceLabel = 'GitHub repository data has been imported successfully';
        }

        var area = document.getElementById('upload-area');
        area.innerHTML =
            '<div class="card">' +
            '  <div class="upload-results">' +
            '    <div class="results-icon">' +
            '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '        <path d="M22 11.08V12a10 10 0 11-5.93-9.14"/>' +
            '        <polyline points="22 4 12 14.01 9 11.01"/>' +
            '      </svg>' +
            '    </div>' +
            '    <div class="results-title">Import Complete</div>' +
            '    <div class="results-summary">' + C.escapeHtml(sourceLabel) + '</div>' +
            '    <div class="results-stats">' +
            '      <div class="stat-item"><div class="stat-value">' + nodes + '</div><div class="stat-label">Facts</div></div>' +
            '      <div class="stat-item"><div class="stat-value">' + edges + '</div><div class="stat-label">Connections</div></div>' +
            '      <div class="stat-item"><div class="stat-value">' + categories + '</div><div class="stat-label">Categories</div></div>' +
            '    </div>' +
            '    <div>' +
            '      <a href="#memory" class="btn btn-primary btn-lg">View My Memory</a>' +
            '      <button class="btn btn-outline btn-lg" id="upload-another" style="margin-left:10px">Upload Another</button>' +
            '    </div>' +
            '  </div>' +
            '</div>';

        document.getElementById('upload-another').addEventListener('click', function () {
            renderDropZone();
        });
    }

    // ── Import Cards (GitHub + LinkedIn URL) ───────────────────────

    function renderImportCards() {
        var area = document.getElementById('import-cards-area');
        area.innerHTML =
            '<div class="import-cards">' +
            '  <div class="card import-card">' +
            '    <div class="import-card-header">' +
            '      <svg viewBox="0 0 24 24" fill="currentColor" width="24" height="24"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/></svg>' +
            '      <h3>GitHub Repository</h3>' +
            '    </div>' +
            '    <p class="import-card-desc">Import repo metadata, languages, topics, and README</p>' +
            '    <div class="import-card-body">' +
            '      <input type="text" id="github-url" class="import-input" placeholder="https://github.com/owner/repo">' +
            '      <input type="text" id="github-token" class="import-input" placeholder="Token (optional, for private repos)">' +
            '      <button class="btn btn-primary" id="github-import-btn">Import</button>' +
            '      <div id="github-status" class="import-status"></div>' +
            '    </div>' +
            '  </div>' +
            '  <div class="card import-card">' +
            '    <div class="import-card-header">' +
            '      <svg viewBox="0 0 24 24" fill="currentColor" width="24" height="24"><path d="M19 3a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h14m-.5 15.5v-5.3a3.26 3.26 0 00-3.26-3.26c-.85 0-1.84.52-2.32 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 011.4 1.4v4.93h2.79M6.88 8.56a1.68 1.68 0 001.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 00-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>' +
            '      <h3>LinkedIn Profile</h3>' +
            '    </div>' +
            '    <p class="import-card-desc">Import basic profile info from a public URL. For richer data, upload your LinkedIn data export above.</p>' +
            '    <div class="import-card-body">' +
            '      <input type="text" id="linkedin-url" class="import-input" placeholder="https://linkedin.com/in/yourname">' +
            '      <button class="btn btn-primary" id="linkedin-import-btn">Import</button>' +
            '      <div id="linkedin-status" class="import-status"></div>' +
            '    </div>' +
            '  </div>' +
            '</div>';

        document.getElementById('github-import-btn').addEventListener('click', function () {
            var url = document.getElementById('github-url').value.trim();
            var token = document.getElementById('github-token').value.trim();
            if (!url) { C.showToast('Please enter a GitHub URL', 'error'); return; }
            var statusEl = document.getElementById('github-status');
            statusEl.innerHTML = '<div class="progress-spinner" style="width:20px;height:20px;display:inline-block;vertical-align:middle"></div> Importing...';

            C.apiRaw('/api/import/github', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url, token: token || undefined }),
            }).then(function (resp) {
                return resp.json().then(function (data) {
                    if (!resp.ok) {
                        var msg = (data.error && data.error.message) || data.error || 'Import failed';
                        throw new Error(msg);
                    }
                    return data;
                });
            }).then(function (data) {
                statusEl.innerHTML =
                    '<span class="import-success">Imported ' + data.nodes_created + ' facts and ' +
                    data.edges_created + ' connections</span> &mdash; ' +
                    '<a href="#memory">View Memory</a>';
            }).catch(function (err) {
                statusEl.innerHTML = '<span class="import-error">' + C.escapeHtml(err.message) + '</span>';
            });
        });

        document.getElementById('linkedin-import-btn').addEventListener('click', function () {
            var url = document.getElementById('linkedin-url').value.trim();
            if (!url) { C.showToast('Please enter a LinkedIn URL', 'error'); return; }
            var statusEl = document.getElementById('linkedin-status');
            statusEl.innerHTML = '<div class="progress-spinner" style="width:20px;height:20px;display:inline-block;vertical-align:middle"></div> Importing...';

            C.apiRaw('/api/import/linkedin', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url }),
            }).then(function (resp) {
                return resp.json().then(function (data) {
                    if (!resp.ok) {
                        var msg = (data.error && data.error.message) || data.error || 'Import failed';
                        throw new Error(msg);
                    }
                    return data;
                });
            }).then(function (data) {
                var html = '<span class="import-success">Imported ' + data.nodes_created + ' facts</span>';
                if (data.limited) {
                    html += '<br><small class="import-warning">' + C.escapeHtml(data.hint || 'Limited data — use LinkedIn data export for richer results') + '</small>';
                }
                html += ' &mdash; <a href="#memory">View Memory</a>';
                statusEl.innerHTML = html;
            }).catch(function (err) {
                statusEl.innerHTML = '<span class="import-error">' + C.escapeHtml(err.message) + '</span>';
            });
        });
    }

    // ── API Keys Section ───────────────────────────────────────────

    function renderApiKeys() {
        var area = document.getElementById('api-keys-area');
        area.innerHTML =
            '<div class="card api-keys-section">' +
            '  <h2>Your Memory API</h2>' +
            '  <p class="api-keys-desc">Generate API keys so external chatbots, agents, and coding tools can access your memory.</p>' +
            '  <button class="btn btn-primary" id="show-create-key-btn">Generate API Key</button>' +
            '  <div id="create-key-form" style="display:none"></div>' +
            '  <div id="api-keys-list"></div>' +
            '</div>';

        document.getElementById('show-create-key-btn').addEventListener('click', function () {
            var formEl = document.getElementById('create-key-form');
            if (formEl.style.display === 'none') {
                formEl.style.display = 'block';
                this.textContent = 'Cancel';
                renderCreateKeyForm();
            } else {
                formEl.style.display = 'none';
                formEl.innerHTML = '';
                this.textContent = 'Generate API Key';
            }
        });

        loadApiKeys();
    }

    function renderCreateKeyForm() {
        var formEl = document.getElementById('create-key-form');
        formEl.innerHTML =
            '<div class="key-form">' +
            '  <label>Label</label>' +
            '  <input type="text" id="key-label" class="import-input" placeholder="e.g. My Claude context">' +
            '  <label>Policy</label>' +
            '  <div class="key-policy-options">' +
            '    <label class="radio-label"><input type="radio" name="key-policy" value="full" checked> Full</label>' +
            '    <label class="radio-label"><input type="radio" name="key-policy" value="professional"> Professional</label>' +
            '    <label class="radio-label"><input type="radio" name="key-policy" value="technical"> Technical</label>' +
            '    <label class="radio-label"><input type="radio" name="key-policy" value="minimal"> Minimal</label>' +
            '    <label class="radio-label"><input type="radio" name="key-policy" value="custom"> Custom</label>' +
            '  </div>' +
            '  <div id="custom-tags-area" style="display:none">' +
            '    <label>Include tags</label>' +
            '    <div class="key-tags-options">' +
            '      <label class="checkbox-label"><input type="checkbox" name="key-tag" value="identity"> identity</label>' +
            '      <label class="checkbox-label"><input type="checkbox" name="key-tag" value="technical_expertise"> technical_expertise</label>' +
            '      <label class="checkbox-label"><input type="checkbox" name="key-tag" value="professional_context"> professional_context</label>' +
            '      <label class="checkbox-label"><input type="checkbox" name="key-tag" value="domain_knowledge"> domain_knowledge</label>' +
            '      <label class="checkbox-label"><input type="checkbox" name="key-tag" value="active_priorities"> active_priorities</label>' +
            '      <label class="checkbox-label"><input type="checkbox" name="key-tag" value="communication_preferences"> communication_preferences</label>' +
            '      <label class="checkbox-label"><input type="checkbox" name="key-tag" value="business_context"> business_context</label>' +
            '      <label class="checkbox-label"><input type="checkbox" name="key-tag" value="education"> education</label>' +
            '    </div>' +
            '  </div>' +
            '  <label>Output format</label>' +
            '  <div class="key-policy-options">' +
            '    <label class="radio-label"><input type="radio" name="key-format" value="json" checked> JSON</label>' +
            '    <label class="radio-label"><input type="radio" name="key-format" value="claude_xml"> Claude XML</label>' +
            '    <label class="radio-label"><input type="radio" name="key-format" value="system_prompt"> System Prompt</label>' +
            '    <label class="radio-label"><input type="radio" name="key-format" value="markdown"> Markdown</label>' +
            '    <label class="radio-label"><input type="radio" name="key-format" value="jsonresume"> JSON Resume</label>' +
            '  </div>' +
            '  <button class="btn btn-success" id="create-key-submit">Create Key</button>' +
            '</div>';

        // Toggle custom tags visibility
        var radios = formEl.querySelectorAll('input[name="key-policy"]');
        for (var i = 0; i < radios.length; i++) {
            radios[i].addEventListener('change', function () {
                var customArea = document.getElementById('custom-tags-area');
                customArea.style.display = this.value === 'custom' ? 'block' : 'none';
            });
        }

        document.getElementById('create-key-submit').addEventListener('click', function () {
            var label = document.getElementById('key-label').value.trim() || 'Untitled Key';
            var policy = formEl.querySelector('input[name="key-policy"]:checked').value;
            var fmt = formEl.querySelector('input[name="key-format"]:checked').value;
            var tags = null;
            if (policy === 'custom') {
                tags = [];
                var checkboxes = formEl.querySelectorAll('input[name="key-tag"]:checked');
                for (var j = 0; j < checkboxes.length; j++) {
                    tags.push(checkboxes[j].value);
                }
                if (!tags.length) {
                    C.showToast('Select at least one tag for custom policy', 'error');
                    return;
                }
            }

            var body = { label: label, policy: policy, format: fmt };
            if (tags) { body.tags = tags; }

            C.apiRaw('/api/keys', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            }).then(function (resp) {
                if (resp.status === 401) {
                    C.showLogin();
                    throw new Error('Your session expired. Please sign in and try again.');
                }
                return resp.json().then(function (data) {
                    if (!resp.ok) {
                        var msg = (data.error && data.error.message) || data.error || 'Failed';
                        throw new Error(msg);
                    }
                    return data;
                });
            }).then(function (data) {
                // Show the secret once
                var formEl2 = document.getElementById('create-key-form');
                formEl2.innerHTML =
                    '<div class="key-created">' +
                    '  <div class="key-created-title">Key Created</div>' +
                    '  <p class="key-created-warning">Save this key — it won\'t be shown again.</p>' +
                    '  <div class="key-secret-display">' +
                    '    <code id="new-key-secret">' + C.escapeHtml(data.key_secret) + '</code>' +
                    '    <button class="btn btn-outline btn-sm" id="copy-key-btn">Copy</button>' +
                    '  </div>' +
                    '  <p class="key-url-label">Public URL:</p>' +
                    '  <div class="key-secret-display">' +
                    '    <code id="new-key-url">' + C.escapeHtml(window.location.origin + '/api/memory/' + data.key_secret) + '</code>' +
                    '    <button class="btn btn-outline btn-sm" id="copy-url-btn">Copy</button>' +
                    '  </div>' +
                    '</div>';

                document.getElementById('copy-key-btn').addEventListener('click', function () {
                    copyText(data.key_secret);
                    C.showToast('Key copied to clipboard', 'success');
                });
                document.getElementById('copy-url-btn').addEventListener('click', function () {
                    copyText(window.location.origin + '/api/memory/' + data.key_secret);
                    C.showToast('URL copied to clipboard', 'success');
                });

                document.getElementById('show-create-key-btn').textContent = 'Generate API Key';
                loadApiKeys();
            }).catch(function (err) {
                C.showToast('Failed to create key: ' + err.message, 'error');
            });
        });
    }

    function loadApiKeys() {
        C.apiRaw('/api/keys', { method: 'GET' }).then(function (resp) {
            if (resp.status === 401) {
                C.showLogin();
                throw new Error('unauthorized');
            }
            return resp.json();
        }).then(function (keys) {
            var listEl = document.getElementById('api-keys-list');
            if (!keys || keys.length === 0) {
                listEl.innerHTML = '<p class="api-keys-empty">No API keys yet.</p>';
                return;
            }
            var html = '<div class="key-list">';
            for (var i = 0; i < keys.length; i++) {
                var k = keys[i];
                var statusClass = k.active ? 'key-active' : 'key-revoked';
                var statusText = k.active ? 'Active' : 'Revoked';
                html += '<div class="key-item">' +
                    '<div class="key-item-header">' +
                    '  <span class="key-item-label">' + C.escapeHtml(k.label) + '</span>' +
                    '  <span class="key-item-status ' + statusClass + '">' + statusText + '</span>' +
                    '</div>' +
                    '<div class="key-item-meta">' +
                    '  <span class="chip">' + C.escapeHtml(k.policy) + '</span>' +
                    '  <span class="chip">' + C.escapeHtml(k.format) + '</span>' +
                    '  <span class="key-item-date">Created: ' + C.escapeHtml((k.created_at || '').substring(0, 10)) + '</span>' +
                    (k.last_used ? '  <span class="key-item-date">Last used: ' + C.escapeHtml(k.last_used.substring(0, 10)) + '</span>' : '') +
                    '</div>';
                if (k.active) {
                    html += '<button class="btn btn-outline btn-sm key-revoke-btn" data-key-id="' + C.escapeHtml(k.key_id) + '">Revoke</button>';
                }
                html += '</div>';
            }
            html += '</div>';
            listEl.innerHTML = html;

            // Bind revoke buttons
            var btns = listEl.querySelectorAll('.key-revoke-btn');
            for (var j = 0; j < btns.length; j++) {
                btns[j].addEventListener('click', function () {
                    var keyId = this.getAttribute('data-key-id');
                    revokeKey(keyId);
                });
            }
        }).catch(function () {
            // Silently fail — keys not loaded
        });
    }

    function revokeKey(keyId) {
        C.apiRaw('/api/keys/' + keyId, { method: 'DELETE' }).then(function (resp) {
            if (resp.status === 401) {
                C.showLogin();
                throw new Error('Your session expired. Please sign in and try again.');
            }
            return resp.json().then(function (data) {
                if (!resp.ok) throw new Error('Revoke failed');
                return data;
            });
        }).then(function () {
            C.showToast('Key revoked', 'success');
            loadApiKeys();
        }).catch(function (err) {
            C.showToast('Failed to revoke key: ' + err.message, 'error');
        });
    }

    function copyText(text) {
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text);
        } else {
            var ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
    }
})();
