/* Cortex Web UI — Core Application */
(function () {
    'use strict';

    // ── API helper ──────────────────────────────────────────────
    function api(path, opts) {
        opts = opts || {};
        opts.credentials = 'same-origin';
        opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
        return fetch(path, opts).then(function (resp) {
            if (resp.status === 401) {
                showLogin();
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
        });
    }

    function apiRaw(path, opts) {
        opts = opts || {};
        opts.credentials = 'same-origin';
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
        document.getElementById('login-password').value = '';
    }

    function hideLogin() {
        document.getElementById('login-overlay').style.display = 'none';
        document.getElementById('logout-btn').style.display = '';
    }

    function setupAuth() {
        var form = document.getElementById('login-form');
        if (form) {
            form.addEventListener('submit', function (e) {
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

        var logoutBtn = document.getElementById('logout-btn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', function () {
                fetch('/app/logout', {
                    method: 'POST',
                    credentials: 'same-origin',
                }).then(function () {
                    currentPage = null;
                    showLogin();
                });
            });
        }
    }

    function bootCheck() {
        fetch('/context/stats', { credentials: 'same-origin' }).then(function (resp) {
            if (resp.status === 401) {
                showLogin();
            } else {
                hideLogin();
                route();
            }
        }).catch(function () {
            hideLogin();
            route();
        });
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
    };

    // Boot
    setupAuth();
    bootCheck();
})();
