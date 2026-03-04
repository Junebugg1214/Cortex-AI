/* Cortex Web UI — Core Application */
(function () {
    'use strict';

    // State
    var multiUserEnabled = false;
    var registrationOpen = false;
    var storageModes = ['self_host'];
    var defaultStorageMode = 'self_host';
    var consumerMode = true;
    var currentUser = null;
    var onboardingState = {
        hasStorageChoice: false,
        hasData: false,
        hasShareKey: false,
        explored: false,
        nextAction: null,
    };
    var onboardingRefreshPromise = null;
    var lastOnboardingRefreshAt = 0;
    var VISITED_PAGES_KEY = 'cortex.webapp.visited.v1';
    var CONSUMER_MODE_KEY = 'cortex.webapp.consumer_mode.v1';
    var STORAGE_PREFS_KEY = 'cortex.storage.prefs.v1';

    // ── API helper ──────────────────────────────────────────────
    function shouldBypassLoginOverlay() {
        var hash = location.hash.replace('#', '') || 'upload';
        return multiUserEnabled && registrationOpen && hash === 'signup';
    }

    function api(path, opts) {
        function consume(resp, allowRetry) {
            if (resp.status === 304 && allowRetry) {
                // Browser/proxy cache revalidation can return empty 304 bodies.
                // Retry once with explicit cache bypass so callers still get JSON.
                var retryOpts = Object.assign({}, opts, {
                    credentials: 'same-origin',
                    cache: 'reload',
                    headers: Object.assign({}, opts.headers || {}, {
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache',
                    }),
                });
                return fetch(path, retryOpts).then(function (retryResp) {
                    return consume(retryResp, false);
                });
            }
            if (resp.status === 401) {
                if (!shouldBypassLoginOverlay()) {
                    showLogin();
                }
                throw new Error('unauthorized');
            }
            if (!resp.ok) {
                return resp.json().then(function (d) {
                    var msg = (d.error && d.error.message) || d.error || 'Request failed';
                    throw new Error(msg);
                }).catch(function (e) {
                    if (e.message && e.message !== 'Request failed') throw e;
                    throw new Error('Request failed (' + resp.status + ')');
                });
            }
            return resp.json();
        }

        opts = opts || {};
        opts.credentials = 'same-origin';
        if (opts.cache === undefined) opts.cache = 'no-store';
        opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
        return fetch(path, opts).then(function (resp) { return consume(resp, true); });
    }

    function apiRaw(path, opts) {
        opts = opts || {};
        opts.credentials = 'same-origin';
        if (opts.cache === undefined) opts.cache = 'no-store';
        opts.headers = Object.assign({}, opts.headers || {});
        return fetch(path, opts);
    }

    // ── Router ──────────────────────────────────────────────────
    var pages = {};
    var currentPage = null;

    function registerPage(name, renderFn) {
        pages[name] = renderFn;
    }

    function route() {
        var hash = location.hash.replace('#', '') || 'upload';
        if (hash === currentPage) return;
        currentPage = hash;
        markPageVisited(hash);

        // Update tab active state
        document.querySelectorAll('.tab-link').forEach(function (el) {
            el.classList.toggle('active', el.getAttribute('data-page') === hash);
        });

        var container = document.getElementById('page-container');
        container.innerHTML = '<div class="page-loading">Loading...</div>';

        if (pages[hash]) {
            try {
                pages[hash](container);
            } catch (e) {
                container.innerHTML = '<div class="page-loading">Error: ' + escapeHtml(e.message) + '</div>';
            }
        } else {
            container.innerHTML = '<div class="page-loading">Page not found</div>';
        }
        refreshOnboardingState(false);
        trackEvent('nav.page_view', { page: hash });
    }

    window.addEventListener('hashchange', route);

    // ── Toast notifications ─────────────────────────────────────
    function showToast(msg, typeOrOpts) {
        var opts = {};
        if (typeof typeOrOpts === 'string') {
            opts.type = typeOrOpts;
        } else if (typeOrOpts && typeof typeOrOpts === 'object') {
            opts = typeOrOpts;
        }
        var type = opts.type || 'info';
        var duration = typeof opts.duration === 'number' ? opts.duration : 4000;
        var el = document.createElement('div');
        el.className = 'toast toast-' + type;
        el.innerHTML = '<span class="toast-message">' + escapeHtml(msg) + '</span>';
        if (opts.actionLabel && typeof opts.onAction === 'function') {
            var btn = document.createElement('button');
            btn.className = 'toast-action';
            btn.type = 'button';
            btn.textContent = opts.actionLabel;
            btn.addEventListener('click', function () {
                try { opts.onAction(); } catch (_e) {}
                el.remove();
            });
            el.appendChild(btn);
        }
        document.getElementById('toast-container').appendChild(el);
        setTimeout(function () { el.remove(); }, duration);
    }

    // ── Utilities ───────────────────────────────────────────────
    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function debounce(fn, ms) {
        var timer;
        return function () {
            var args = arguments;
            var ctx = this;
            clearTimeout(timer);
            timer = setTimeout(function () { fn.apply(ctx, args); }, ms);
        };
    }

    function copyToClipboard(text) {
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(function () {
                showToast('Copied to clipboard', 'success');
                trackEvent('clipboard.copied', { length: (text || '').length });
            });
        } else {
            var ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            ta.remove();
            showToast('Copied to clipboard', 'success');
            trackEvent('clipboard.copied', { length: (text || '').length, legacy: true });
        }
    }

    function trackEvent(name, payload) {
        void name;
        void payload;
    }

    function openIssueReporter() {
        var page = currentPage || (location.hash.replace('#', '') || 'upload');
        var action = window.prompt('What were you trying to do?', '');
        if (action === null) return;
        action = String(action || '').trim();
        if (!action) {
            showToast('Please add what you were trying to do.', 'error');
            return;
        }
        var notes = window.prompt('What happened? (optional)', '') || '';
        var severity = window.prompt('Severity: low, medium, or high (default: medium)', 'medium');
        severity = String(severity || 'medium').trim().toLowerCase();
        if (['low', 'medium', 'high'].indexOf(severity) < 0) severity = 'medium';

        api('/api/beta/report', {
            method: 'POST',
            body: JSON.stringify({
                page: page,
                action: action,
                notes: notes,
                severity: severity,
            }),
        }).then(function () {
            showToast('Issue reported. Thank you.', 'success');
            trackEvent('beta.issue_reported', { page: page, severity: severity });
        }).catch(function (err) {
            showToast('Could not report issue: ' + err.message, 'error');
        });
    }

    function loadConsumerMode() {
        try {
            var raw = localStorage.getItem(CONSUMER_MODE_KEY);
            if (raw === null) return true;
            return raw !== 'false';
        } catch (_e) {
            return true;
        }
    }

    function applyConsumerModeClass() {
        document.body.classList.toggle('consumer-mode', !!consumerMode);
    }

    function renderConsumerModeToggle() {
        var btn = document.getElementById('consumer-mode-btn');
        if (!btn) return;
        btn.textContent = 'Consumer Mode: ' + (consumerMode ? 'On' : 'Off');
        btn.classList.toggle('btn-consumer-on', !!consumerMode);
        renderConsumerNavLabels();
    }

    function renderConsumerNavLabels() {
        var labelMap = consumerMode
            ? { upload: 'Add Data', memory: 'Memory', share: 'Share', connectors: 'Connect', profile: 'AI ID' }
            : { upload: 'Upload', memory: 'My Memory', share: 'Share', connectors: 'Connectors', profile: 'Profile' };
        document.querySelectorAll('.tab-link').forEach(function (link) {
            var page = link.getAttribute('data-page');
            var span = link.querySelector('span');
            if (!span || !labelMap[page]) return;
            span.textContent = labelMap[page];
        });
    }

    function setConsumerMode(value) {
        consumerMode = !!value;
        try {
            localStorage.setItem(CONSUMER_MODE_KEY, consumerMode ? 'true' : 'false');
        } catch (_e) {
            // Ignore localStorage failures.
        }
        applyConsumerModeClass();
        renderConsumerModeToggle();
        currentPage = null;
        route();
    }

    // ── Login / Logout ──────────────────────────────────────────
    function showLogin() {
        document.getElementById('login-overlay').classList.remove('is-hidden');
        document.getElementById('logout-btn').classList.add('is-hidden');
        document.getElementById('login-error').textContent = '';
        setHudVisible(false);

        // Show appropriate form based on mode
        var adminForm = document.getElementById('login-form');
        var userForm = document.getElementById('user-login-form');
        var signupLink = document.getElementById('signup-link');

        if (multiUserEnabled) {
            adminForm.classList.add('is-hidden');
            userForm.classList.remove('is-hidden');
            signupLink.classList.toggle('is-hidden', !registrationOpen);
            document.getElementById('login-email').value = '';
            document.getElementById('login-user-password').value = '';
        } else {
            adminForm.classList.remove('is-hidden');
            userForm.classList.add('is-hidden');
            signupLink.classList.add('is-hidden');
            document.getElementById('login-password').value = '';
        }
    }

    function hideLogin() {
        document.getElementById('login-overlay').classList.add('is-hidden');
        document.getElementById('logout-btn').classList.remove('is-hidden');
        setHudVisible(true);
        refreshOnboardingState(true);
    }

    function setHudVisible(visible) {
        var hud = document.getElementById('app-hud');
        if (!hud) return;
        hud.classList.toggle('is-hidden', !visible);
    }

    function getVisitedPages() {
        try {
            var raw = localStorage.getItem(VISITED_PAGES_KEY);
            if (!raw) return {};
            var parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (_e) {
            return {};
        }
    }

    function markPageVisited(page) {
        var allowed = { upload: true, memory: true, share: true, connectors: true, profile: true };
        if (!allowed[page]) return;
        var visited = getVisitedPages();
        if (visited[page]) return;
        visited[page] = true;
        try {
            localStorage.setItem(VISITED_PAGES_KEY, JSON.stringify(visited));
        } catch (_e) {
            // Ignore storage failures (private mode / storage quotas).
        }
    }

    function getStoragePrefs() {
        try {
            var raw = localStorage.getItem(STORAGE_PREFS_KEY);
            if (!raw) return {};
            var parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (_e) {
            return {};
        }
    }

    function hasStorageChoiceCompleted() {
        var prefs = getStoragePrefs();
        var mode = String((prefs && prefs.mode) || '').toLowerCase();
        if (mode === 'self_host') return true;
        return false;
    }

    function computeNextAction(state, visited) {
        if (consumerMode && !state.hasStorageChoice) {
            return {
                title: 'Choose where your AI ID data lives',
                detail: 'Run your own Cortex instance to keep your AI ID on your infrastructure.',
                ctaLabel: 'Choose Storage',
                ctaHref: '#upload',
            };
        }
        if (!visited.connectors) {
            return {
                title: consumerMode ? 'Connect your AI apps first' : 'Connect your AI tools first',
                detail: consumerMode
                    ? 'Set up connectors so your context follows you across assistants.'
                    : 'Set up connectors for seamless memory continuity across assistants.',
                ctaLabel: consumerMode ? 'Open Connect' : 'Open Connectors',
                ctaHref: '#connectors',
            };
        }
        if (!state.hasData) {
            return {
                title: consumerMode ? 'Add your first data' : 'Add your first memory data',
                detail: consumerMode
                    ? 'Add chat exports, files, or a resume to build your AI ID.'
                    : 'Use manual import for chat exports and resumes when connector sync is not available.',
                ctaLabel: consumerMode ? 'Go to Add Data' : 'Go to Upload',
                ctaHref: '#upload',
            };
        }
        if (!visited.memory) {
            return {
                title: consumerMode ? 'Review your memory' : 'Explore what Cortex extracted',
                detail: consumerMode
                    ? 'Check your summary to confirm your AI ID looks right.'
                    : 'Review your graph so you can validate facts and see how your context connects.',
                ctaLabel: consumerMode ? 'Open Memory' : 'Open My Memory',
                ctaHref: '#memory',
            };
        }
        if ((!consumerMode && !state.hasShareKey) || (consumerMode && !visited.share)) {
            return {
                title: consumerMode ? 'Create your first share card' : 'Create your first shareable API key',
                detail: consumerMode
                    ? 'Pick a sharing intent and copy the version of your AI ID you want to share.'
                    : 'Use policy-based keys to share only the context each tool should access.',
                ctaLabel: 'Open Share',
                ctaHref: '#share',
            };
        }
        if (!visited.profile) {
            return {
                title: consumerMode ? 'Optional: customize your AI ID card' : 'Optional: configure your AI ID card',
                detail: consumerMode
                    ? 'Set sharing level and generate a QR card for quick sharing.'
                    : 'Set share policy, generate QR, and add optional GitHub URL for technical work.',
                ctaLabel: consumerMode ? 'Open AI ID' : 'Open Profile',
                ctaHref: '#profile',
            };
        }
        return {
            title: 'Setup complete',
            detail: consumerMode
                ? 'Your AI ID is ready. You can now share context anywhere.'
                : 'Your memory is imported, explored, and ready to share.',
            ctaLabel: consumerMode ? 'View Memory' : 'View My Memory',
            ctaHref: '#memory',
        };
    }

    function renderHud() {
        var hud = document.getElementById('app-hud');
        if (!hud) return;
        if (!document.getElementById('login-overlay').classList.contains('is-hidden')) {
            hud.classList.add('is-hidden');
            return;
        }

        var visited = getVisitedPages();
        var steps = [];
        if (consumerMode) {
            steps.push({ id: 'storage', label: 'Storage', done: onboardingState.hasStorageChoice });
        }
        steps.push(
            { id: 'connect', label: 'Connect', done: !!visited.connectors },
            { id: 'import', label: consumerMode ? 'Add Data' : 'Import', done: onboardingState.hasData },
            { id: 'explore', label: consumerMode ? 'Review' : 'Explore', done: onboardingState.hasData && !!visited.memory },
            { id: 'share', label: 'Share', done: consumerMode ? !!visited.share : onboardingState.hasShareKey }
        );
        var firstIncomplete = null;
        for (var i = 0; i < steps.length; i++) {
            if (!steps[i].done) {
                firstIncomplete = steps[i].id;
                break;
            }
        }

        var next = onboardingState.nextAction || computeNextAction(onboardingState, visited);
        var tipsHtml =
            '<div class="hud-tip">' +
            '  <strong>Tip</strong>: ' + (consumerMode
                ? 'Choose a Share intent to generate the right version of your AI ID in one click.'
                : 'Use Share intents to generate safer, policy-scoped exports in one click.') +
            '</div>';
        var stepHtml = steps.map(function (step) {
            var cls = 'journey-step';
            if (step.done) cls += ' done';
            else if (step.id === firstIncomplete) cls += ' current';
            return (
                '<div class="' + cls + '">' +
                '  <div class="journey-dot"></div>' +
                '  <span>' + escapeHtml(step.label) + '</span>' +
                '</div>'
            );
        }).join('');

        hud.innerHTML =
            '<div class="app-hud-inner">' +
            '  <div class="journey-track">' +
            '    <div class="journey-title">' + (consumerMode ? 'Quick Setup' : 'Setup Journey') + '</div>' +
            '    <div class="journey-steps">' + stepHtml + '</div>' +
            '    ' + tipsHtml +
            '  </div>' +
            '  <div class="next-action-card">' +
            '    <div class="next-action-title">' + escapeHtml(next.title) + '</div>' +
            '    <div class="next-action-detail">' + escapeHtml(next.detail) + '</div>' +
            '    <a class="btn btn-primary btn-sm" href="' + escapeHtml(next.ctaHref) + '">' + escapeHtml(next.ctaLabel) + '</a>' +
            '  </div>' +
            '</div>';
        hud.classList.remove('is-hidden');
    }

    function refreshOnboardingState(force) {
        var now = Date.now();
        if (!force && onboardingRefreshPromise) return onboardingRefreshPromise;
        if (!force && now - lastOnboardingRefreshAt < 5000) {
            renderHud();
            return Promise.resolve(onboardingState);
        }

        var statsReq = apiRaw('/context/stats', { method: 'GET', cache: 'no-store' })
            .then(function (resp) {
                if (!resp.ok) return { node_count: 0 };
                return resp.json();
            })
            .catch(function () { return { node_count: 0 }; });

        var keysReq = apiRaw('/api/keys', { method: 'GET', cache: 'no-store' })
            .then(function (resp) {
                if (!resp.ok) return [];
                return resp.text().then(function (text) {
                    if (!text) return [];
                    try { return JSON.parse(text); } catch (_e) { return []; }
                });
            })
            .catch(function () { return []; });

        onboardingRefreshPromise = Promise.all([statsReq, keysReq]).then(function (results) {
            var stats = results[0] || {};
            var keys = Array.isArray(results[1]) ? results[1] : [];
            var visited = getVisitedPages();
            onboardingState.hasStorageChoice = hasStorageChoiceCompleted();
            onboardingState.hasData = (stats.node_count || 0) > 0;
            onboardingState.hasShareKey = keys.some(function (k) { return !!k.active; });
            onboardingState.explored = !!visited.memory;
            onboardingState.nextAction = computeNextAction(onboardingState, visited);
            lastOnboardingRefreshAt = Date.now();
            renderHud();
            return onboardingState;
        }).finally(function () {
            onboardingRefreshPromise = null;
        });

        return onboardingRefreshPromise;
    }

    function setupAuth() {
        // Consumer mode toggle
        var consumerBtn = document.getElementById('consumer-mode-btn');
        if (consumerBtn) {
            consumerBtn.addEventListener('click', function () {
                setConsumerMode(!consumerMode);
            });
        }

        // Admin login form (single-user mode)
        var adminForm = document.getElementById('login-form');
        if (adminForm) {
            adminForm.addEventListener('submit', function (e) {
                e.preventDefault();
                var pw = document.getElementById('login-password').value;
                fetch('/app/auth', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password: pw }),
                }).then(function (resp) {
                    if (!resp.ok) {
                        document.getElementById('login-error').textContent = 'Invalid password';
                        return;
                    }
                    hideLogin();
                    currentPage = null;
                    route();
                }).catch(function () {
                    document.getElementById('login-error').textContent = 'Connection error';
                });
            });
        }

        // Multi-user login form
        var userForm = document.getElementById('user-login-form');
        if (userForm) {
            userForm.addEventListener('submit', function (e) {
                e.preventDefault();
                var email = document.getElementById('login-email').value.trim();
                var pw = document.getElementById('login-user-password').value;

                fetch('/api/login', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: email, password: pw }),
                }).then(function (resp) {
                    if (!resp.ok) {
                        return resp.json().then(function (data) {
                            var msg = 'Invalid credentials';
                            if (data.error && data.error.messages) {
                                msg = data.error.messages.join(', ');
                            }
                            document.getElementById('login-error').textContent = msg;
                        });
                    }
                    return resp.json().then(function (data) {
                        currentUser = data;
                        hideLogin();
                        currentPage = null;
                        route();
                    });
                }).catch(function () {
                    document.getElementById('login-error').textContent = 'Connection error';
                });
            });
        }

        // Signup link click handler
        var signupLink = document.getElementById('goto-signup');
        if (signupLink) {
            signupLink.addEventListener('click', function (e) {
                hideLogin();
            });
        }

        // Logout button
        var logoutBtn = document.getElementById('logout-btn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', function () {
                var logoutUrl = multiUserEnabled ? '/api/logout' : '/app/logout';
                fetch(logoutUrl, {
                    method: 'POST',
                    credentials: 'same-origin',
                }).then(function () {
                    currentUser = null;
                    currentPage = null;
                    showLogin();
                });
            });
        }

        var reportIssueBtn = document.getElementById('report-issue-btn');
        if (reportIssueBtn) {
            reportIssueBtn.addEventListener('click', function () {
                openIssueReporter();
            });
        }
    }

    function checkMultiUserConfig() {
        return fetch('/api/users/config', { credentials: 'same-origin' })
            .then(function (resp) {
                if (!resp.ok) return { multi_user_enabled: false, registration_open: false };
                return resp.json();
            })
            .then(function (data) {
                multiUserEnabled = data.multi_user_enabled || false;
                registrationOpen = data.registration_open || false;
                if (Array.isArray(data.storage_modes) && data.storage_modes.length) {
                    storageModes = data.storage_modes;
                }
                if (typeof data.default_storage_mode === 'string' && data.default_storage_mode) {
                    defaultStorageMode = data.default_storage_mode;
                }
            })
            .catch(function () {
                multiUserEnabled = false;
                registrationOpen = false;
                storageModes = ['self_host'];
                defaultStorageMode = 'self_host';
            });
    }

    function bootCheck() {
        // First check multi-user config
        checkMultiUserConfig().then(function () {
            // Then check auth status
            var checkUrl = multiUserEnabled ? '/api/me' : '/context/stats';
            fetch(checkUrl, { credentials: 'same-origin' }).then(function (resp) {
                if (resp.status === 401) {
                    if (!shouldBypassLoginOverlay()) {
                        showLogin();
                    } else {
                        hideLogin();
                        route();
                    }
                } else {
                    if (multiUserEnabled) {
                        resp.json().then(function (data) {
                            currentUser = data;
                            hideLogin();
                            route();
                        });
                    } else {
                        hideLogin();
                        route();
                    }
                }
            }).catch(function () {
                hideLogin();
                route();
            });
        });
    }

    function getCurrentUser() {
        return currentUser;
    }

    function isMultiUserMode() {
        return multiUserEnabled;
    }

    function getStorageConfig() {
        return {
            modes: storageModes.slice(),
            defaultMode: defaultStorageMode,
        };
    }

    function signalProgressChanged() {
        return refreshOnboardingState(true);
    }

    function isConsumerMode() {
        return !!consumerMode;
    }

    // ── Exports ─────────────────────────────────────────────────
    window.CortexApp = {
        api: api,
        apiRaw: apiRaw,
        registerPage: registerPage,
        showToast: showToast,
        escapeHtml: escapeHtml,
        debounce: debounce,
        copyToClipboard: copyToClipboard,
        showLogin: showLogin,
        getCurrentUser: getCurrentUser,
        isMultiUserMode: isMultiUserMode,
        isConsumerMode: isConsumerMode,
        setConsumerMode: setConsumerMode,
        getStorageConfig: getStorageConfig,
        signalProgressChanged: signalProgressChanged,
        refreshOnboardingState: refreshOnboardingState,
        trackEvent: trackEvent,
    };

    // Boot
    consumerMode = loadConsumerMode();
    applyConsumerModeClass();
    renderConsumerModeToggle();
    setupAuth();
    bootCheck();
})();
