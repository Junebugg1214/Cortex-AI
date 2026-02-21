/* Cortex Web UI — Core Application */
(function () {
    'use strict';

    // ── API helper ──────────────────────────────────────────────
    function api(path, opts) {
        opts = opts || {};
        opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
        return fetch(path, opts).then(function (resp) {
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
        return fetch(path, opts || {});
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

    // ── Exports ─────────────────────────────────────────────────
    window.CortexApp = {
        api: api,
        apiRaw: apiRaw,
        registerPage: registerPage,
        showToast: showToast,
        escapeHtml: escapeHtml,
        debounce: debounce,
        copyToClipboard: copyToClipboard,
    };

    // Boot
    route();
})();
