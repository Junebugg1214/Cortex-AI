/* Cortex Dashboard — Core Application */
(function () {
    'use strict';

    // ── API helper ──────────────────────────────────────────────
    async function api(path, opts) {
        opts = opts || {};
        opts.credentials = 'same-origin';
        opts.cache = 'no-store';
        opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
        var resp = await fetch('/dashboard/api' + path, opts);
        if (resp.status === 401) {
            showLogin();
            throw new Error('unauthorized');
        }
        var data = null;
        var raw = '';
        try {
            raw = await resp.text();
            data = raw ? JSON.parse(raw) : {};
        } catch (_e) {
            data = {};
        }
        if (!resp.ok) {
            var msg = (data.error && data.error.message) || data.error || 'Request failed';
            throw new Error(msg);
        }
        return data;
    }

    // ── Auth ────────────────────────────────────────────────────
    var loginScreen = document.getElementById('login-screen');
    var appShell = document.getElementById('app-shell');
    var loginForm = document.getElementById('login-form');
    var loginError = document.getElementById('login-error');
    var loginBtn = document.getElementById('login-btn');

    function showLogin() {
        loginScreen.style.display = 'flex';
        appShell.style.display = 'none';
    }

    function showApp() {
        loginScreen.style.display = 'none';
        appShell.style.display = 'flex';
        route();
    }

    loginForm.addEventListener('submit', async function () {
        var pw = document.getElementById('login-password').value;
        loginBtn.disabled = true;
        loginBtn.textContent = 'Signing in...';
        loginError.style.display = 'none';
        try {
            await fetch('/dashboard/auth', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password: pw }),
            }).then(function (r) {
                if (!r.ok) throw new Error('Invalid password');
                return r.json();
            });
            showApp();
        } catch (e) {
            loginError.textContent = e.message;
            loginError.style.display = 'block';
        } finally {
            loginBtn.disabled = false;
            loginBtn.textContent = 'Sign In';
        }
    });

    // ── Router ──────────────────────────────────────────────────
    var routes = {};  // page name -> render function
    var currentPage = null;

    function registerPage(name, renderFn) {
        routes[name] = renderFn;
    }

    function route() {
        var hash = location.hash || '#/';
        var page = hash.replace('#/', '') || 'overview';
        if (page === currentPage) return;
        currentPage = page;

        // Update nav active state
        document.querySelectorAll('.nav-link').forEach(function (el) {
            el.classList.toggle('active', el.getAttribute('data-page') === page);
        });

        var container = document.getElementById('page-container');
        container.innerHTML = '<div class="loading">Loading...</div>';

        if (routes[page]) {
            try {
                routes[page](container);
            } catch (e) {
                container.innerHTML = '<div class="loading">Error: ' + escapeHtml(e.message) + '</div>';
            }
        } else {
            container.innerHTML = '<div class="loading">Page not found</div>';
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
    function formatDate(iso) {
        if (!iso) return '—';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return iso;
        return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    function truncateId(id, len) {
        len = len || 12;
        if (!id || id.length <= len) return id || '';
        return id.substring(0, len) + '...';
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

    function renderPage(container, html) {
        container.innerHTML = html;
    }

    // ── OAuth initialization ────────────────────────────────────
    (async function initOAuth() {
        try {
            var resp = await fetch('/dashboard/oauth/providers');
            var data = await resp.json();
            var providers = data.providers || [];
            if (providers.length === 0) return;

            var divider = document.getElementById('oauth-divider');
            var buttons = document.getElementById('oauth-buttons');
            divider.style.display = '';
            buttons.style.display = '';

            var providerLabels = { google: 'Google', github: 'GitHub' };
            providers.forEach(function (p) {
                var btn = document.createElement('button');
                btn.className = 'btn btn-oauth btn-oauth-' + p;
                btn.textContent = 'Sign in with ' + (providerLabels[p] || p);
                btn.addEventListener('click', function () {
                    window.location.href = '/dashboard/oauth/authorize?provider=' + encodeURIComponent(p);
                });
                buttons.appendChild(btn);
            });
        } catch (e) {
            // OAuth not available — silently ignore
        }

        // Check for OAuth error in URL params
        var params = new URLSearchParams(window.location.search);
        var oauthError = params.get('oauth_error');
        if (oauthError) {
            var errEl = document.getElementById('oauth-error');
            errEl.textContent = 'OAuth error: ' + oauthError;
            errEl.style.display = 'block';
            // Clean URL
            window.history.replaceState({}, '', window.location.pathname + window.location.hash);
        }
    })();

    // ── Check session on load ───────────────────────────────────
    (async function init() {
        try {
            await api('/identity');
            showApp();
        } catch (e) {
            showLogin();
        }
    })();

    // ── Exports for page modules ────────────────────────────────
    window.CortexDashboard = {
        api: api,
        registerPage: registerPage,
        showToast: showToast,
        formatDate: formatDate,
        truncateId: truncateId,
        copyToClipboard: copyToClipboard,
        escapeHtml: escapeHtml,
        debounce: debounce,
        renderPage: renderPage,
        route: route,
    };
})();
