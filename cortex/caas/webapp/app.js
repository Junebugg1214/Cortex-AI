/* Cortex Web UI — Core Application */
(function () {
    'use strict';

    // State
    var multiUserEnabled = false;
    var registrationOpen = false;
    var currentUser = null;

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
    }

    window.addEventListener('hashchange', route);

    // ── Toast notifications ─────────────────────────────────────
    function showToast(msg, type) {
        type = type || 'info';
        var el = document.createElement('div');
        el.className = 'toast toast-' + type;
        el.textContent = msg;
        document.getElementById('toast-container').appendChild(el);
        setTimeout(function () { el.remove(); }, 4000);
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
            });
        } else {
            var ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            ta.remove();
            showToast('Copied to clipboard', 'success');
        }
    }

    // ── Login / Logout ──────────────────────────────────────────
    function showLogin() {
        document.getElementById('login-overlay').style.display = 'flex';
        document.getElementById('logout-btn').style.display = 'none';
        document.getElementById('login-error').textContent = '';

        // Show appropriate form based on mode
        var adminForm = document.getElementById('login-form');
        var userForm = document.getElementById('user-login-form');
        var signupLink = document.getElementById('signup-link');

        if (multiUserEnabled) {
            adminForm.style.display = 'none';
            userForm.style.display = 'block';
            signupLink.style.display = registrationOpen ? 'block' : 'none';
            document.getElementById('login-email').value = '';
            document.getElementById('login-user-password').value = '';
        } else {
            adminForm.style.display = 'block';
            userForm.style.display = 'none';
            signupLink.style.display = 'none';
            document.getElementById('login-password').value = '';
        }
    }

    function hideLogin() {
        document.getElementById('login-overlay').style.display = 'none';
        document.getElementById('logout-btn').style.display = '';
    }

    function setupAuth() {
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
            })
            .catch(function () {
                multiUserEnabled = false;
                registrationOpen = false;
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
    };

    // Boot
    setupAuth();
    bootCheck();
})();
