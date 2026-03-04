/* Cortex Web UI — Upload Page */
(function () {
    'use strict';
    var C = window.CortexApp;
    var maxUploadBytes = 3 * 1024 * 1024 * 1024; // Fallback default: 3GB
    var pendingRevokes = {};
    var storageModes = ['byos', 'self_host'];
    var defaultStorageMode = 'byos';
    var STORAGE_PREFS_KEY = 'cortex.storage.prefs.v1';
    var SELF_HOST_STARTER_COMMAND = 'bash <(curl -fsSL https://raw.githubusercontent.com/Junebugg1214/Cortex-AI/99bbcf0b877a7d558b9b5d360d14b6c7a20cef09/deploy/self-host-starter.sh)';

    C.registerPage('upload', function (container) {
        var isConsumer = C.isConsumerMode && C.isConsumerMode();
        container.innerHTML =
            '<div class="page-header">' +
            '  <h1>' + (isConsumer ? 'Add Data' : 'Import (Manual)') + '</h1>' +
            '  <p>' + (isConsumer
                ? 'Add your chats, files, or resume to build your AI ID.'
                : 'Best flow: connect assistants first, then use manual imports as a fallback.') + '</p>' +
            '</div>' +
            '<div class="card page-flow-cue">' +
            '  <span class="flow-step">1. Connectors</span>' +
            '  <span class="flow-step flow-step-active">' + (isConsumer ? '2. Add Data' : '2. Import') + '</span>' +
            '  <span class="flow-step">3. Share</span>' +
            '</div>' +
            '<div id="upload-area"></div>' +
            '<div id="import-cards-area" class="technical-only"></div>' +
            '<div id="api-keys-area" class="technical-only"></div>';

        renderDropZone();
        if (!(C.isConsumerMode && C.isConsumerMode())) {
            renderImportCards();
            renderApiKeys();
        }
        loadUploadConfig();
    });

    // ── Drop Zone ──────────────────────────────────────────────────

    function renderDropZone() {
        var area = document.getElementById('upload-area');
        var isConsumer = C.isConsumerMode && C.isConsumerMode();
        var githubOption = isConsumer ? '' : '      <option value="github">GitHub Repository URL</option>';
        var githubIcon = isConsumer ? '' :
            '      <div class="platform-icon technical-only">' +
            '        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M22.28 10.42c-.2-.14-.42-.22-.65-.22H14.6l2.24-6.41c.16-.48-.05-1-.5-1.22a.99.99 0 00-1.17.25L5.32 13.58c-.18.2-.28.46-.28.73 0 .58.47 1.05 1.05 1.05h7.03l-2.24 6.41c-.16.48.05 1 .5 1.22.14.07.3.1.45.1.33 0 .64-.15.85-.42l9.85-10.76c.18-.2.28-.46.28-.73a1.03 1.03 0 00-.53-.76z"/></svg>' +
            '        <span>GitHub</span>' +
            '      </div>';
        var storageCard = '<div class="card storage-mode-card">' +
            '  <div class="storage-mode-head">' +
            '    <h3>' + (isConsumer ? 'Choose Your Storage' : 'Storage Mode') + '</h3>' +
            '    <p>' + (isConsumer
                ? 'Use your own cloud storage or run your own Cortex server.'
                : 'Local vault is removed. Choose BYOS or Self-Host only.') + '</p>' +
            '  </div>' +
            '  <div class="storage-mode-options">' +
            '    <button class="btn btn-outline storage-mode-btn" data-storage-mode="byos">BYOS Cloud</button>' +
            '    <button class="btn btn-outline storage-mode-btn" data-storage-mode="self_host">Self-Host</button>' +
            '  </div>' +
            '  <div id="byos-config" class="storage-mode-pane is-hidden">' +
            '    <label class="profile-label" for="byos-provider">Storage Provider</label>' +
            '    <input id="byos-provider" class="login-input" placeholder="S3, R2, iCloud Drive, WebDAV">' +
            '    <label class="profile-label" for="byos-location">Storage Path or URL</label>' +
            '    <input id="byos-location" class="login-input" placeholder="s3://my-ai-id-vault/context.json or https://storage.example.com/vault/context.json">' +
            '    <label class="profile-label" for="e2e-passphrase">E2E Passphrase</label>' +
            '    <input id="e2e-passphrase" class="login-input" type="password" placeholder="Only you know this passphrase">' +
            '    <button class="btn btn-primary" id="save-byos-prefs">Save BYOS + E2E</button>' +
            '    <p class="storage-mode-hint">BYOS data is encrypted before write when passphrase is set. Keep this passphrase safe.</p>' +
            '  </div>' +
            '  <div id="self-host-config" class="storage-mode-pane is-hidden">' +
            '    <p class="storage-mode-hint">Run your own private server with one command:</p>' +
            '    <div class="self-host-command-row">' +
            '      <code id="self-host-command">' + C.escapeHtml(SELF_HOST_STARTER_COMMAND) + '</code>' +
            '      <button class="btn btn-outline btn-sm" id="copy-self-host-command">Copy</button>' +
            '    </div>' +
            '    <ol class="self-host-steps">' +
            '      <li>Run the command on your own machine or VPS.</li>' +
            '      <li>Create your account on your own Cortex URL.</li>' +
            '      <li>Import data there and keep full control of storage.</li>' +
            '    </ol>' +
            '  </div>' +
            '</div>';
        area.innerHTML =
            storageCard +
            '<div class="card upload-priority-cue">' +
            '  <strong>Recommended:</strong> Start in <a href="#connectors">Connectors</a> for ongoing memory continuity. ' +
            (isConsumer ? 'Use Add Data here whenever you want to include new files.' : 'Use manual imports here when needed.') +
            '</div>' +
            '<div class="card upload-guide">' +
            '  <h3>' + (isConsumer ? 'Source Guide' : 'Import Wizard') + '</h3>' +
            '  <p class="upload-guide-sub">Choose a source to see what file to upload.</p>' +
            '  <div class="upload-guide-row">' +
            '    <select id="source-guide-select" class="import-input" aria-label="Choose import source">' +
            '      <option value="chatgpt">ChatGPT Export</option>' +
            '      <option value="claude">Claude Export</option>' +
            '      <option value="linkedin">LinkedIn Export</option>' +
            '      <option value="resume">Resume PDF/DOCX</option>' +
            githubOption +
            '    </select>' +
            '    <div id="source-guide-copy" class="upload-guide-copy"></div>' +
            '  </div>' +
            '</div>' +
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
            '    <p>Supports JSON, text, PDF, DOCX, and zip files. You can upload multiple files at once.</p>' +
            '    <p class="upload-zone-subtle">Max file size: ' + C.escapeHtml(formatBytes(maxUploadBytes)) + '</p>' +
            '    <input type="file" id="file-input" class="upload-hidden-input" accept=".json,.txt,.md,.csv,.zip,.pdf,.docx" multiple>' +
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
            githubIcon +
            '    </div>' +
            '  </div>' +
            '</div>';

        var dropZone = document.getElementById('drop-zone');
        var fileInput = document.getElementById('file-input');
        var sourceGuide = document.getElementById('source-guide-select');
        var byosPane = document.getElementById('byos-config');
        var selfHostPane = document.getElementById('self-host-config');
        var byosProvider = document.getElementById('byos-provider');
        var byosLocation = document.getElementById('byos-location');
        var e2ePassphrase = document.getElementById('e2e-passphrase');
        var modeButtons = Array.prototype.slice.call(document.querySelectorAll('.storage-mode-btn'));

        function getStoredPrefs() {
            try {
                var raw = localStorage.getItem(STORAGE_PREFS_KEY);
                return raw ? JSON.parse(raw) : {};
            } catch (_e) {
                return {};
            }
        }

        function setStoredPrefs(next) {
            try {
                localStorage.setItem(STORAGE_PREFS_KEY, JSON.stringify(next));
            } catch (_e) {
                // Ignore local storage errors.
            }
        }

        function savePrefsRemote(next, opts) {
            opts = opts || {};
            return C.api('/api/storage/preferences', {
                method: 'PUT',
                body: JSON.stringify({
                    mode: next.mode || 'byos',
                    byos_provider: next.byos_provider || '',
                    byos_location: next.byos_location || '',
                }),
            }).then(function () {
                if (!opts.silent) C.showToast('Storage preference saved.', 'success');
            }).catch(function (err) {
                if (!opts.silent) C.showToast('Could not save storage preference: ' + err.message, 'error');
            });
        }

        function checkPrefsRemote(next) {
            return C.api('/api/storage/preferences/check', {
                method: 'POST',
                body: JSON.stringify({
                    mode: next.mode || 'byos',
                    byos_provider: next.byos_provider || '',
                    byos_location: next.byos_location || '',
                }),
            });
        }

        function setActiveStorageMode(mode, opts) {
            opts = opts || {};
            var safeMode = storageModes.indexOf(mode) >= 0 ? mode : defaultStorageMode;
            modeButtons.forEach(function (btn) {
                var isActive = btn.getAttribute('data-storage-mode') === safeMode;
                btn.classList.toggle('storage-mode-btn-active', isActive);
            });
            if (byosPane) {
                byosPane.classList.toggle('is-hidden', safeMode !== 'byos');
            }
            if (selfHostPane) {
                selfHostPane.classList.toggle('is-hidden', safeMode !== 'self_host');
            }
            if (fileInput) {
                fileInput.disabled = safeMode === 'self_host';
            }
            if (dropZone) {
                dropZone.classList.toggle('upload-zone-disabled', safeMode === 'self_host');
            }
            var prefs = getStoredPrefs();
            prefs.mode = safeMode;
            setStoredPrefs(prefs);
            if (!opts.silent) {
                savePrefsRemote(prefs, { silent: true });
            }
            C.trackEvent('storage.mode_changed', { mode: safeMode });
            if (!opts.silent && C.signalProgressChanged) {
                C.signalProgressChanged();
            }
        }

        var initialPrefs = getStoredPrefs();
        if (byosProvider) byosProvider.value = initialPrefs.byos_provider || '';
        if (byosLocation) byosLocation.value = initialPrefs.byos_location || '';
        if (e2ePassphrase && C.getE2EKey) e2ePassphrase.value = C.getE2EKey() || '';
        setActiveStorageMode(initialPrefs.mode || defaultStorageMode, { silent: true });
        C.api('/api/storage/preferences')
            .then(function (remotePrefs) {
                if (!remotePrefs || typeof remotePrefs !== 'object') return;
                var merged = getStoredPrefs();
                merged.mode = remotePrefs.mode || merged.mode || defaultStorageMode;
                merged.byos_provider = remotePrefs.byos_provider || merged.byos_provider || '';
                merged.byos_location = remotePrefs.byos_location || merged.byos_location || '';
                setStoredPrefs(merged);
                if (byosProvider) byosProvider.value = merged.byos_provider;
                if (byosLocation) byosLocation.value = merged.byos_location;
                setActiveStorageMode(merged.mode, { silent: true });
            })
            .catch(function () {
                // Keep local fallback in case API is unavailable.
            });

        modeButtons.forEach(function (btn) {
            var mode = btn.getAttribute('data-storage-mode');
            btn.classList.toggle('is-hidden', storageModes.indexOf(mode) < 0);
            btn.addEventListener('click', function () {
                setActiveStorageMode(mode);
            });
        });

        var copySelfHostBtn = document.getElementById('copy-self-host-command');
        if (copySelfHostBtn) {
            copySelfHostBtn.addEventListener('click', function () {
                C.copyToClipboard(SELF_HOST_STARTER_COMMAND);
            });
        }

        var saveByosBtn = document.getElementById('save-byos-prefs');
        if (saveByosBtn) {
            saveByosBtn.addEventListener('click', function () {
                var provider = byosProvider ? byosProvider.value.trim() : '';
                var location = byosLocation ? byosLocation.value.trim() : '';
                if (!provider || !location) {
                    C.showToast('Enter both provider and storage location.', 'error');
                    return;
                }
                var prefs = getStoredPrefs();
                prefs.byos_provider = provider;
                prefs.byos_location = location;
                prefs.mode = 'byos';
                if (C.setE2EKey) {
                    C.setE2EKey(e2ePassphrase ? e2ePassphrase.value.trim() : '');
                }
                setStoredPrefs(prefs);
                checkPrefsRemote(prefs).then(function (checkResult) {
                    if (!checkResult || checkResult.ok === false) {
                        C.showToast((checkResult && checkResult.message) || 'Storage check failed.', 'error');
                        return;
                    }
                    setActiveStorageMode('byos');
                    C.showToast((checkResult && checkResult.message) || (isConsumer ? 'Cloud storage saved.' : 'BYOS settings saved locally.'), 'success');
                }).catch(function (err) {
                    C.showToast('Storage check failed: ' + err.message, 'error');
                });
                C.trackEvent('storage.byos_saved', { provider: provider });
            });
        }
        if (e2ePassphrase) {
            e2ePassphrase.addEventListener('change', function () {
                if (C.setE2EKey) C.setE2EKey(e2ePassphrase.value.trim());
            });
        }

        function renderGuide(value) {
            var copy = {
                chatgpt: 'Export from ChatGPT settings, then upload the .zip file directly.',
                claude: 'Upload Claude export JSON; Cortex extracts facts, preferences, and project context.',
                linkedin: 'Upload LinkedIn “Get a copy of your data” ZIP (manual export only).',
                resume: 'Upload PDF or DOCX resume for role, company, skill, and education extraction.',
                github: 'Use GitHub import in Technical mode for repo-based memory extraction.',
            };
            document.getElementById('source-guide-copy').textContent = copy[value] || copy.chatgpt;
        }
        renderGuide('chatgpt');
        sourceGuide.addEventListener('change', function () {
            renderGuide(this.value);
            C.trackEvent('upload.guide_selected', { source: this.value });
        });

        dropZone.addEventListener('click', function () {
            if (fileInput.disabled) {
                C.showToast('Self-Host mode selected. Import data on your own hosted instance.', 'info');
                return;
            }
            fileInput.click();
        });

        dropZone.addEventListener('dragover', function (e) {
            e.preventDefault();
            if (fileInput.disabled) return;
            dropZone.classList.add('dragover');
        });

        dropZone.addEventListener('dragleave', function () {
            dropZone.classList.remove('dragover');
        });

        dropZone.addEventListener('drop', function (e) {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            if (fileInput.disabled) {
                C.showToast('Self-Host mode selected. Import data on your own hosted instance.', 'info');
                return;
            }
            if (e.dataTransfer.files.length > 0) {
                handleFiles(e.dataTransfer.files);
                C.trackEvent('upload.drop', { count: e.dataTransfer.files.length });
            }
        });

        fileInput.addEventListener('change', function () {
            if (fileInput.files.length > 0) {
                handleFiles(fileInput.files);
                fileInput.value = '';
                C.trackEvent('upload.pick', { count: fileInput.files.length });
            }
        });
    }

    function handleFiles(fileList) {
        var prefs = {};
        try {
            prefs = JSON.parse(localStorage.getItem(STORAGE_PREFS_KEY) || '{}') || {};
        } catch (_e) {
            prefs = {};
        }
        if (String(prefs.mode || '').toLowerCase() === 'self_host') {
            C.showToast('Self-Host mode selected. Run your own server and import data there.', 'info');
            return;
        }
        var files = Array.prototype.slice.call(fileList || []);
        if (!files.length) return;

        var allowed = [];
        var tooLarge = [];
        files.forEach(function (file) {
            if (file.size > maxUploadBytes) {
                tooLarge.push(file.name);
                return;
            }
            allowed.push(file);
        });

        if (tooLarge.length) {
            C.showToast(
                'Skipped ' + tooLarge.length + ' file(s) over ' + formatBytes(maxUploadBytes) + '.',
                'error'
            );
        }
        if (!allowed.length) return;
        processUploadQueue(allowed);
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
        var appStorage = (C.getStorageConfig && C.getStorageConfig()) || null;
        if (appStorage && Array.isArray(appStorage.modes) && appStorage.modes.length) {
            storageModes = appStorage.modes.slice();
        }
        if (appStorage && typeof appStorage.defaultMode === 'string' && appStorage.defaultMode) {
            defaultStorageMode = appStorage.defaultMode;
        }
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
                if (Array.isArray(cfg.storage_modes) && cfg.storage_modes.length) {
                    storageModes = cfg.storage_modes.slice();
                }
                if (typeof cfg.default_storage_mode === 'string' && cfg.default_storage_mode) {
                    defaultStorageMode = cfg.default_storage_mode;
                }
            })
            .catch(function () {
                // Keep fallback.
            });
    }

    function renderQueueProgress(files, results, currentIndex) {
        var area = document.getElementById('upload-area');
        var completed = results.length;
        var current = files[currentIndex];
        var listHtml = files.map(function (file, idx) {
            var status = 'Queued';
            var cls = 'upload-queue-item';
            if (idx < completed) {
                var r = results[idx];
                if (r && r.status === 'success') {
                    status = 'Imported';
                    cls += ' success';
                } else {
                    status = 'Failed';
                    cls += ' error';
                }
            } else if (idx === currentIndex) {
                status = 'Processing...';
                cls += ' active';
            }
            return (
                '<li class="' + cls + '">' +
                '  <span class="upload-queue-file">' + C.escapeHtml(file.name) + '</span>' +
                '  <span class="upload-queue-status">' + status + '</span>' +
                '</li>'
            );
        }).join('');

        area.innerHTML =
            '<div class="card">' +
            '  <div class="upload-progress">' +
            '    <div class="progress-spinner"></div>' +
            '    <div class="progress-text">Processing ' + C.escapeHtml(current.name) + '</div>' +
            '    <div class="progress-sub">' + (currentIndex + 1) + ' of ' + files.length + ' files</div>' +
            '    <ul class="upload-queue-list">' + listHtml + '</ul>' +
            '    <div class="progress-sub">Extracting facts and connections...</div>' +
            '  </div>' +
            '</div>';
    }

    function processUploadQueue(files) {
        var results = [];
        var sequence = Promise.resolve();

        files.forEach(function (file, index) {
            sequence = sequence.then(function () {
                renderQueueProgress(files, results, index);
                return uploadFile(file).then(function (data) {
                    results.push({ file: file, status: 'success', data: data });
                }).catch(function (err) {
                    results.push({ file: file, status: 'error', error: err.message || 'Upload failed' });
                });
            });
        });

        sequence.then(function () {
            renderBatchResults(results);
            if (results.some(function (r) { return r.status === 'success'; })) {
                C.signalProgressChanged();
            }
            C.trackEvent('upload.batch_completed', {
                total: results.length,
                success: results.filter(function (r) { return r.status === 'success'; }).length,
                failed: results.filter(function (r) { return r.status === 'error'; }).length,
            });
        });
    }

    function uploadFile(file) {
        var formData = new FormData();
        formData.append('file', file);

        return C.apiRaw('/api/upload', {
            method: 'POST',
            body: formData,
        }).then(function (resp) {
            if (resp.status === 401) {
                C.showLogin();
                throw new Error('Your session expired. Please sign in and try again.');
            }
            return parseJsonSafe(resp).then(function (data) {
                if (!resp.ok) {
                    var msg = (data.error && data.error.message) || data.error || 'Upload failed';
                    throw new Error(msg);
                }
                return data;
            });
        });
    }

    function describeSource(sourceType) {
        if (sourceType === 'resume') return 'Resume';
        if (sourceType === 'linkedin_export') return 'LinkedIn export';
        if (sourceType === 'github') return 'GitHub';
        if (sourceType === 'chatgpt') return 'ChatGPT';
        if (sourceType === 'claude') return 'Claude';
        return 'Import';
    }

    function renderBatchResults(results) {
        var successes = results.filter(function (r) { return r.status === 'success'; });
        var failures = results.filter(function (r) { return r.status === 'error'; });
        var nodes = 0;
        var edges = 0;
        var categories = 0;

        successes.forEach(function (r) {
            nodes += r.data.nodes_created || 0;
            edges += r.data.edges_created || 0;
            categories += r.data.categories || 0;
        });

        var summary;
        if (!successes.length) {
            summary = 'No files were imported successfully. Review errors below and try again.';
        } else if (successes.length === 1 && !failures.length) {
            summary = describeSource(successes[0].data.source_type) + ' imported successfully.';
        } else {
            summary = successes.length + ' file(s) imported, ' + failures.length + ' failed.';
        }

        var errorsHtml = '';
        if (failures.length) {
            var items = failures.map(function (r) {
                return '<li><strong>' + C.escapeHtml(r.file.name) + ':</strong> ' + C.escapeHtml(r.error) + '</li>';
            }).join('');
            errorsHtml = '<div class="upload-errors"><h3>Needs attention</h3><ul>' + items + '</ul></div>';
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
            '    <div class="results-title">' + ((C.isConsumerMode && C.isConsumerMode()) ? 'Data Added' : 'Import Complete') + '</div>' +
            '    <div class="results-summary">' + C.escapeHtml(summary) + '</div>' +
            '    <div class="results-stats">' +
            '      <div class="stat-item"><div class="stat-value">' + nodes + '</div><div class="stat-label">Facts</div></div>' +
            '      <div class="stat-item"><div class="stat-value">' + edges + '</div><div class="stat-label">Connections</div></div>' +
            '      <div class="stat-item"><div class="stat-value">' + categories + '</div><div class="stat-label">Categories</div></div>' +
            '    </div>' +
            errorsHtml +
            '    <div class="upload-results-actions">' +
            (successes.length
                ? '      <a href="#memory" class="btn btn-primary btn-lg">View My Memory</a>'
                : '') +
            '      <button class="btn btn-outline btn-lg" id="upload-another">' + ((C.isConsumerMode && C.isConsumerMode()) ? 'Add More Data' : 'Upload More') + '</button>' +
            '    </div>' +
            '  </div>' +
            '</div>';

        document.getElementById('upload-another').addEventListener('click', function () {
            renderDropZone();
        });
        if (!successes.length) {
            C.showToast('Uploads failed. Check file format and try again.', 'error');
        } else if (failures.length) {
            C.showToast('Imported with partial failures.', 'info');
        } else {
            C.showToast('Import complete.', 'success');
        }
    }

    // ── Import Cards (GitHub URL) ──────────────────────────────────

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
            '</div>';

        document.getElementById('github-import-btn').addEventListener('click', function () {
            var url = document.getElementById('github-url').value.trim();
            var token = document.getElementById('github-token').value.trim();
            if (!url) { C.showToast('Please enter a GitHub URL', 'error'); return; }
            C.trackEvent('import.github.started', { private_repo: !!token });
            var statusEl = document.getElementById('github-status');
            statusEl.innerHTML = '<div class="progress-spinner import-inline-spinner"></div> Importing...';

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
                C.signalProgressChanged();
                C.trackEvent('import.github.completed', { nodes: data.nodes_created || 0, edges: data.edges_created || 0 });
            }).catch(function (err) {
                statusEl.innerHTML = '<span class="import-error">' + C.escapeHtml(err.message) + '</span>';
                C.trackEvent('import.github.failed', { error: err.message });
            });
        });

    }

    // ── API Keys Section ───────────────────────────────────────────

    function renderApiKeys() {
        var area = document.getElementById('api-keys-area');
        area.innerHTML =
            '<div class="card api-keys-section">' +
            '  <div class="api-keys-header">' +
            '    <h2>Developer Access (Optional)</h2>' +
            '    <button class="btn btn-outline" id="toggle-api-keys">Show</button>' +
            '  </div>' +
            '  <p class="api-keys-desc">Only needed if you want custom tools to read memory via API.</p>' +
            '  <div id="api-keys-panel" class="is-hidden">' +
            '    <button class="btn btn-primary" id="show-create-key-btn">Generate API Key</button>' +
            '    <div id="create-key-form" class="is-hidden"></div>' +
            '    <div id="api-keys-list"></div>' +
            '  </div>' +
            '</div>';

        document.getElementById('toggle-api-keys').addEventListener('click', function () {
            var panel = document.getElementById('api-keys-panel');
            var open = !panel.classList.contains('is-hidden');
            panel.classList.toggle('is-hidden', open);
            this.textContent = open ? 'Show' : 'Hide';
            if (!open) loadApiKeys();
        });

        document.getElementById('show-create-key-btn').addEventListener('click', function () {
            var formEl = document.getElementById('create-key-form');
            if (formEl.classList.contains('is-hidden')) {
                formEl.classList.remove('is-hidden');
                this.textContent = 'Cancel';
                renderCreateKeyForm();
            } else {
                formEl.classList.add('is-hidden');
                formEl.innerHTML = '';
                this.textContent = 'Generate API Key';
            }
        });

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
            '  <div id="custom-tags-area" class="is-hidden">' +
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
                customArea.classList.toggle('is-hidden', this.value !== 'custom');
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
                return parseJsonSafe(resp).then(function (data) {
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
                C.signalProgressChanged();
                C.trackEvent('keys.created', { policy: policy, format: fmt });
            }).catch(function (err) {
                C.showToast('Failed to create key: ' + err.message, 'error');
                C.trackEvent('keys.create_failed', { error: err.message });
            });
        });
    }

    function loadApiKeys() {
        C.apiRaw('/api/keys', { method: 'GET' }).then(function (resp) {
            if (resp.status === 401) {
                C.showLogin();
                throw new Error('unauthorized');
            }
            return parseJsonSafe(resp);
        }).then(function (keys) {
            var listEl = document.getElementById('api-keys-list');
            if (!Array.isArray(keys) || keys.length === 0) {
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
        if (pendingRevokes[keyId]) return;
        var timer = setTimeout(function () {
            delete pendingRevokes[keyId];
            C.apiRaw('/api/keys/' + keyId, { method: 'DELETE' }).then(function (resp) {
                if (resp.status === 401) {
                    C.showLogin();
                    throw new Error('Your session expired. Please sign in and try again.');
                }
                return parseJsonSafe(resp).then(function (data) {
                    if (!resp.ok) throw new Error('Revoke failed');
                    return data;
                });
            }).then(function () {
                C.showToast('Key revoked', 'success');
                loadApiKeys();
                C.trackEvent('keys.revoked', { key_id: keyId });
                C.signalProgressChanged();
            }).catch(function (err) {
                C.showToast('Failed to revoke key: ' + err.message, 'error');
                C.trackEvent('keys.revoke_failed', { error: err.message });
            });
        }, 5000);

        pendingRevokes[keyId] = timer;
        C.showToast('Key scheduled for revoke.', {
            type: 'info',
            duration: 5200,
            actionLabel: 'Undo',
            onAction: function () {
                clearTimeout(pendingRevokes[keyId]);
                delete pendingRevokes[keyId];
                C.showToast('Revoke canceled.', 'success');
                C.trackEvent('keys.revoke_undo', { key_id: keyId });
            },
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

    function parseJsonSafe(resp) {
        return resp.text().then(function (text) {
            if (!text) return {};
            try {
                return JSON.parse(text);
            } catch (_e) {
                return { error: text };
            }
        });
    }
})();
