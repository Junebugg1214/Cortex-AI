/* Cortex Web UI — Profile Page */
(function () {
    'use strict';
    var C = window.CortexApp;

    var SECTIONS = [
        { id: 'about', name: 'About' },
        { id: 'experience', name: 'Experience' },
        { id: 'skills', name: 'Skills' },
        { id: 'education', name: 'Education' },
        { id: 'projects', name: 'Projects' },
        { id: 'endorsements', name: 'Endorsements' },
    ];

    var POLICIES = [
        { id: 'professional', name: 'Professional' },
        { id: 'full', name: 'Full' },
        { id: 'technical', name: 'Technical' },
        { id: 'minimal', name: 'Minimal' },
    ];

    C.registerPage('profile', function (container) {
        container.innerHTML =
            '<div class="page-header">' +
            '  <h1>Public Profile</h1>' +
            '  <p>Configure your public profile page</p>' +
            '</div>' +
            '<div style="margin-bottom:16px;">' +
            '  <label style="font-weight:600;display:block;margin-bottom:4px;">Profile</label>' +
            '  <select id="profile-selector" class="login-input" style="width:300px;"></select>' +
            '  <button class="btn btn-outline" id="btn-new-profile" style="margin-left:8px;">+ New Profile</button>' +
            '  <button class="btn btn-danger" id="btn-delete-profile" style="margin-left:8px;display:none;">Delete</button>' +
            '</div>' +
            '<div class="profile-config card" style="padding:20px;">' +
            '  <div style="margin-bottom:16px;">' +
            '    <label style="font-weight:600;display:block;margin-bottom:4px;">Handle</label>' +
            '    <input type="text" id="profile-handle" class="login-input" placeholder="your-name" style="width:300px;">' +
            '    <span style="color:#6b7280;font-size:13px;margin-left:8px;">URL: /p/<span id="handle-preview">your-name</span></span>' +
            '  </div>' +
            '  <div style="margin-bottom:16px;">' +
            '    <label style="font-weight:600;display:block;margin-bottom:4px;">Display Name</label>' +
            '    <input type="text" id="profile-name" class="login-input" placeholder="Your Full Name" style="width:300px;">' +
            '  </div>' +
            '  <div style="margin-bottom:16px;">' +
            '    <label style="font-weight:600;display:block;margin-bottom:4px;">Headline</label>' +
            '    <input type="text" id="profile-headline" class="login-input" placeholder="Software Engineer" style="width:400px;">' +
            '  </div>' +
            '  <div style="margin-bottom:16px;">' +
            '    <label style="font-weight:600;display:block;margin-bottom:4px;">Bio</label>' +
            '    <textarea id="profile-bio" class="login-input" rows="3" style="width:100%;resize:vertical;" placeholder="A short bio..."></textarea>' +
            '  </div>' +
            '  <div style="margin-bottom:16px;">' +
            '    <label style="font-weight:600;display:block;margin-bottom:4px;">Privacy Level</label>' +
            '    <select id="profile-policy" class="login-input" style="width:200px;"></select>' +
            '  </div>' +
            '  <div style="margin-bottom:16px;">' +
            '    <label style="font-weight:600;display:block;margin-bottom:4px;">Sections</label>' +
            '    <div id="section-toggles" style="display:flex;gap:12px;flex-wrap:wrap;"></div>' +
            '  </div>' +
            '  <div style="display:flex;gap:12px;">' +
            '    <button class="btn btn-primary" id="btn-save-profile">Save Profile</button>' +
            '    <button class="btn btn-outline" id="btn-preview-profile">Preview</button>' +
            '    <button class="btn btn-outline" id="btn-auto-profile">Auto-fill from Memory</button>' +
            '    <button class="btn btn-outline" id="btn-qr-profile">QR Code</button>' +
            '  </div>' +
            '</div>' +
            '<div id="qr-modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:1000;align-items:center;justify-content:center;">' +
            '  <div style="background:#fff;border-radius:12px;padding:24px;text-align:center;max-width:320px;">' +
            '    <div id="qr-content"></div>' +
            '    <button class="btn btn-outline" id="btn-close-qr" style="margin-top:12px;">Close</button>' +
            '  </div>' +
            '</div>';

        // Populate policy select
        var policySelect = document.getElementById('profile-policy');
        POLICIES.forEach(function (p) {
            var opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name;
            policySelect.appendChild(opt);
        });

        // Populate section toggles
        var togglesDiv = document.getElementById('section-toggles');
        SECTIONS.forEach(function (s) {
            var label = document.createElement('label');
            label.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:14px;';
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = true;
            cb.dataset.section = s.id;
            label.appendChild(cb);
            label.appendChild(document.createTextNode(s.name));
            togglesDiv.appendChild(label);
        });

        var handleInput = document.getElementById('profile-handle');
        var profileSelector = document.getElementById('profile-selector');
        var deleteBtn = document.getElementById('btn-delete-profile');

        handleInput.addEventListener('input', function () {
            document.getElementById('handle-preview').textContent = handleInput.value || 'your-name';
        });

        function fillForm(data) {
            if (!data) return;
            handleInput.value = data.handle || '';
            document.getElementById('handle-preview').textContent = data.handle || 'your-name';
            document.getElementById('profile-name').value = data.display_name || '';
            document.getElementById('profile-headline').value = data.headline || '';
            document.getElementById('profile-bio').value = data.bio || '';
            policySelect.value = data.policy || 'professional';
            if (data.sections) {
                togglesDiv.querySelectorAll('input[type=checkbox]').forEach(function (cb) {
                    cb.checked = data.sections.indexOf(cb.dataset.section) >= 0;
                });
            }
        }

        function loadProfiles() {
            C.api('/api/profiles').then(function (resp) {
                var profiles = resp.profiles || [];
                profileSelector.innerHTML = '';
                profiles.forEach(function (p) {
                    var opt = document.createElement('option');
                    opt.value = p.handle;
                    opt.textContent = p.display_name || p.handle;
                    profileSelector.appendChild(opt);
                });
                deleteBtn.style.display = profiles.length > 0 ? '' : 'none';
                if (profiles.length > 0) {
                    fillForm(profiles[0]);
                }
            }).catch(function () {
                // Load single profile fallback
                C.api('/api/profile').then(function (data) {
                    if (data && data.handle) fillForm(data);
                }).catch(function () {});
            });
        }

        profileSelector.addEventListener('change', function () {
            var handle = profileSelector.value;
            if (!handle) return;
            C.api('/api/profile?handle=' + encodeURIComponent(handle)).then(function (data) {
                fillForm(data);
            }).catch(function () {});
        });

        document.getElementById('btn-new-profile').addEventListener('click', function () {
            handleInput.value = '';
            document.getElementById('handle-preview').textContent = 'your-name';
            document.getElementById('profile-name').value = '';
            document.getElementById('profile-headline').value = '';
            document.getElementById('profile-bio').value = '';
            policySelect.value = 'professional';
            togglesDiv.querySelectorAll('input[type=checkbox]').forEach(function (cb) { cb.checked = true; });
            handleInput.focus();
        });

        deleteBtn.addEventListener('click', function () {
            var handle = profileSelector.value;
            if (!handle || !confirm('Delete profile "' + handle + '"?')) return;
            C.api('/api/profile?handle=' + encodeURIComponent(handle), { method: 'DELETE' })
                .then(function () {
                    C.showToast('Profile deleted', 'success');
                    loadProfiles();
                })
                .catch(function (err) { C.showToast('Error: ' + err.message, 'error'); });
        });

        // Save
        document.getElementById('btn-save-profile').addEventListener('click', function () {
            var sections = [];
            togglesDiv.querySelectorAll('input[type=checkbox]:checked').forEach(function (cb) {
                sections.push(cb.dataset.section);
            });

            C.api('/api/profile', {
                method: 'POST',
                body: JSON.stringify({
                    handle: handleInput.value.toLowerCase().trim(),
                    display_name: document.getElementById('profile-name').value,
                    headline: document.getElementById('profile-headline').value,
                    bio: document.getElementById('profile-bio').value,
                    policy: policySelect.value,
                    sections: sections,
                }),
            }).then(function () {
                C.showToast('Profile saved!', 'success');
                loadProfiles();
            }).catch(function (err) {
                C.showToast('Error: ' + err.message, 'error');
            });
        });

        // Preview
        document.getElementById('btn-preview-profile').addEventListener('click', function () {
            window.open('/api/profile/preview', '_blank');
        });

        // Auto-fill from Memory
        document.getElementById('btn-auto-profile').addEventListener('click', function () {
            C.api('/api/profile/auto').then(function (data) {
                if (!data || !data.handle) {
                    C.showToast('No graph data available to auto-fill', 'error');
                    return;
                }
                fillForm(data);
                C.showToast('Profile auto-filled from memory!', 'success');
            }).catch(function (err) {
                C.showToast('Error: ' + err.message, 'error');
            });
        });

        // QR Code
        var qrModal = document.getElementById('qr-modal');
        document.getElementById('btn-qr-profile').addEventListener('click', function () {
            var handle = handleInput.value.trim();
            var url = '/api/profile/qr' + (handle ? '?handle=' + encodeURIComponent(handle) : '');
            fetch(url, { credentials: 'same-origin' })
                .then(function (r) {
                    if (!r.ok) throw new Error('QR generation failed');
                    return r.text();
                })
                .then(function (svg) {
                    document.getElementById('qr-content').innerHTML = svg;
                    qrModal.style.display = 'flex';
                })
                .catch(function (err) { C.showToast('Error: ' + err.message, 'error'); });
        });

        document.getElementById('btn-close-qr').addEventListener('click', function () {
            qrModal.style.display = 'none';
        });
        qrModal.addEventListener('click', function (e) {
            if (e.target === qrModal) qrModal.style.display = 'none';
        });

        // Initial load
        loadProfiles();
    });
})();
