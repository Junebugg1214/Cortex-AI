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
            '<div class="signup-page" style="max-width:400px;margin:60px auto;padding:0 20px;">' +
            '  <div class="login-brand" style="text-align:center;margin-bottom:32px;">' +
            '    <svg width="48" height="48" viewBox="0 0 40 40" fill="none">' +
            '      <circle cx="20" cy="20" r="18" stroke="#4f46e5" stroke-width="2" fill="none"/>' +
            '      <circle cx="20" cy="12" r="3" fill="#4f46e5"/>' +
            '      <circle cx="12" cy="26" r="3" fill="#4f46e5"/>' +
            '      <circle cx="28" cy="26" r="3" fill="#4f46e5"/>' +
            '      <line x1="20" y1="15" x2="12" y2="23" stroke="#4f46e5" stroke-width="1.5" opacity="0.5"/>' +
            '      <line x1="20" y1="15" x2="28" y2="23" stroke="#4f46e5" stroke-width="1.5" opacity="0.5"/>' +
            '      <line x1="12" y1="26" x2="28" y2="26" stroke="#4f46e5" stroke-width="1.5" opacity="0.5"/>' +
            '    </svg>' +
            '    <h1 style="margin:16px 0 8px;font-size:24px;font-weight:600;">Create Account</h1>' +
            '    <p style="color:#6b7280;font-size:14px;">Join Cortex to start building your knowledge graph</p>' +
            '  </div>' +
            '  <div id="signup-loading" style="text-align:center;padding:20px;">Loading...</div>' +
            '  <form id="signup-form" style="display:none;">' +
            '    <div style="margin-bottom:16px;">' +
            '      <label style="font-weight:500;display:block;margin-bottom:6px;font-size:14px;">Email</label>' +
            '      <input type="email" id="signup-email" class="login-input" placeholder="you@example.com" required autocomplete="email">' +
            '    </div>' +
            '    <div style="margin-bottom:16px;">' +
            '      <label style="font-weight:500;display:block;margin-bottom:6px;font-size:14px;">Display Name</label>' +
            '      <input type="text" id="signup-name" class="login-input" placeholder="Your Name" autocomplete="name">' +
            '    </div>' +
            '    <div style="margin-bottom:16px;">' +
            '      <label style="font-weight:500;display:block;margin-bottom:6px;font-size:14px;">Password</label>' +
            '      <input type="password" id="signup-password" class="login-input" placeholder="At least 8 characters" required autocomplete="new-password">' +
            '      <p style="color:#6b7280;font-size:12px;margin-top:4px;">Minimum 8 characters</p>' +
            '    </div>' +
            '    <div style="margin-bottom:16px;">' +
            '      <label style="font-weight:500;display:block;margin-bottom:6px;font-size:14px;">Confirm Password</label>' +
            '      <input type="password" id="signup-confirm" class="login-input" placeholder="Confirm password" required autocomplete="new-password">' +
            '    </div>' +
            '    <div id="signup-error" class="login-error" style="margin-bottom:16px;display:none;"></div>' +
            '    <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:12px;">Create Account</button>' +
            '  </form>' +
            '  <div id="signup-disabled" style="display:none;text-align:center;padding:20px;">' +
            '    <p style="color:#dc2626;margin-bottom:16px;">Registration is currently closed.</p>' +
            '    <p style="color:#6b7280;font-size:14px;">Please contact the administrator for access.</p>' +
            '  </div>' +
            '  <div style="text-align:center;margin-top:24px;">' +
            '    <span style="color:#6b7280;font-size:14px;">Already have an account? </span>' +
            '    <a href="#upload" style="color:#4f46e5;font-size:14px;text-decoration:none;">Sign in</a>' +
            '  </div>' +
            '</div>';

        var form = document.getElementById('signup-form');
        var loading = document.getElementById('signup-loading');
        var disabled = document.getElementById('signup-disabled');
        var errorEl = document.getElementById('signup-error');

        // Check if registration is open
        checkMultiUserConfig().then(function (config) {
            loading.style.display = 'none';
            if (!config.multi_user_enabled || !config.registration_open) {
                disabled.style.display = 'block';
            } else {
                form.style.display = 'block';
            }
        });

        function showError(msg) {
            errorEl.textContent = msg;
            errorEl.style.display = 'block';
        }

        function hideError() {
            errorEl.style.display = 'none';
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
