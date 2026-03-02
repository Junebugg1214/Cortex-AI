/* Cortex Web UI — Signup Page */
(function () {
    'use strict';
    var C = window.CortexApp;

    // Check if multi-user is enabled
    function checkMultiUserConfig() {
        return fetch('/api/users/config', { credentials: 'same-origin' })
            .then(function (resp) { return resp.json(); })
            .then(function (data) { return data; })
            .catch(function () { return { multi_user_enabled: false, registration_open: false }; });
    }

    C.registerPage('signup', function (container) {
        container.innerHTML =
            '<div class="signup-page">' +
            '  <div class="login-brand signup-brand">' +
            '    <svg width="48" height="48" viewBox="0 0 40 40" fill="none">' +
            '      <circle cx="20" cy="20" r="18" stroke="#4f46e5" stroke-width="2" fill="none"/>' +
            '      <circle cx="20" cy="12" r="3" fill="#4f46e5"/>' +
            '      <circle cx="12" cy="26" r="3" fill="#4f46e5"/>' +
            '      <circle cx="28" cy="26" r="3" fill="#4f46e5"/>' +
            '      <line x1="20" y1="15" x2="12" y2="23" stroke="#4f46e5" stroke-width="1.5" opacity="0.5"/>' +
            '      <line x1="20" y1="15" x2="28" y2="23" stroke="#4f46e5" stroke-width="1.5" opacity="0.5"/>' +
            '      <line x1="12" y1="26" x2="28" y2="26" stroke="#4f46e5" stroke-width="1.5" opacity="0.5"/>' +
            '    </svg>' +
            '    <h1 class="signup-title">Create Account</h1>' +
            '    <p class="signup-subtitle">Join Cortex to start building your knowledge graph</p>' +
            '  </div>' +
            '  <div id="signup-loading" class="signup-loading">Loading...</div>' +
            '  <form id="signup-form" class="is-hidden">' +
            '    <div class="signup-field">' +
            '      <label class="signup-label">Email</label>' +
            '      <input type="email" id="signup-email" class="login-input" placeholder="you@example.com" required autocomplete="email">' +
            '    </div>' +
            '    <div class="signup-field">' +
            '      <label class="signup-label">Display Name</label>' +
            '      <input type="text" id="signup-name" class="login-input" placeholder="Your Name" autocomplete="name">' +
            '    </div>' +
            '    <div class="signup-field">' +
            '      <label class="signup-label">Password</label>' +
            '      <input type="password" id="signup-password" class="login-input" placeholder="At least 8 characters" required autocomplete="new-password">' +
            '      <p class="signup-hint">Minimum 8 characters</p>' +
            '    </div>' +
            '    <div class="signup-field">' +
            '      <label class="signup-label">Confirm Password</label>' +
            '      <input type="password" id="signup-confirm" class="login-input" placeholder="Confirm password" required autocomplete="new-password">' +
            '    </div>' +
            '    <div id="signup-error" class="login-error signup-error is-hidden"></div>' +
            '    <button type="submit" class="btn btn-primary signup-submit">Create Account</button>' +
            '  </form>' +
            '  <div id="signup-disabled" class="signup-disabled is-hidden">' +
            '    <p class="signup-disabled-title">Registration is currently closed.</p>' +
            '    <p class="signup-disabled-desc">Please contact the administrator for access.</p>' +
            '  </div>' +
            '  <div class="signup-footer">' +
            '    <span class="signup-footer-text">Already have an account? </span>' +
            '    <a href="#upload" class="signup-footer-link">Sign in</a>' +
            '  </div>' +
            '</div>';

        var form = document.getElementById('signup-form');
        var loading = document.getElementById('signup-loading');
        var disabled = document.getElementById('signup-disabled');
        var errorEl = document.getElementById('signup-error');

        // Check if registration is open
        checkMultiUserConfig().then(function (config) {
            loading.classList.add('is-hidden');
            if (!config.multi_user_enabled || !config.registration_open) {
                disabled.classList.remove('is-hidden');
            } else {
                form.classList.remove('is-hidden');
            }
        });

        function showError(msg) {
            errorEl.textContent = msg;
            errorEl.classList.remove('is-hidden');
        }

        function hideError() {
            errorEl.classList.add('is-hidden');
        }

        form.addEventListener('submit', function (e) {
            e.preventDefault();
            hideError();

            var email = document.getElementById('signup-email').value.trim();
            var name = document.getElementById('signup-name').value.trim();
            var password = document.getElementById('signup-password').value;
            var confirm = document.getElementById('signup-confirm').value;

            // Validation
            if (!email) {
                showError('Email is required');
                return;
            }
            if (password.length < 8) {
                showError('Password must be at least 8 characters');
                return;
            }
            if (password !== confirm) {
                showError('Passwords do not match');
                return;
            }

            // Submit signup
            fetch('/api/signup', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    email: email,
                    password: password,
                    display_name: name
                })
            })
            .then(function (resp) {
                if (!resp.ok) {
                    return resp.json().then(function (data) {
                        var msg = 'Signup failed';
                        if (data.error && data.error.messages) {
                            msg = data.error.messages.join(', ');
                        } else if (data.error && data.error.message) {
                            msg = data.error.message;
                        }
                        throw new Error(msg);
                    });
                }
                return resp.json();
            })
            .then(function (data) {
                C.showToast('Account created! Please sign in.', 'success');
                // Redirect to login (which will show the login modal)
                window.location.hash = '#upload';
                if (window.CortexApp.showLogin) {
                    window.CortexApp.showLogin();
                }
            })
            .catch(function (err) {
                showError(err.message);
            });
        });
    });
})();
