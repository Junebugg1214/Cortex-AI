/* Cortex Web UI — Profile Page */
(function () {
    'use strict';
    var C = window.CortexApp;
    var pendingDelete = null;

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
            '  <p>Configure and publish your profile in a few steps</p>' +
            '</div>' +
            '<div class="profile-toolbar">' +
            '  <div class="profile-field">' +
            '    <label class="profile-label" for="profile-selector">Profile</label>' +
            '    <select id="profile-selector" class="login-input profile-select"></select>' +
            '  </div>' +
            '  <div class="profile-toolbar-actions">' +
            '    <button class="btn btn-outline" id="btn-new-profile">+ New Profile</button>' +
            '    <button class="btn btn-outline btn-danger is-hidden" id="btn-delete-profile">Delete</button>' +
            '  </div>' +
            '</div>' +
            '<div id="profile-empty-hint" class="profile-empty-hint is-hidden">No profiles yet. Click <strong>+ New Profile</strong> to create your first one.</div>' +
            '<div class="profile-config card">' +
            '  <div class="profile-grid">' +
            '    <div class="profile-field">' +
            '      <label class="profile-label" for="profile-handle">Handle</label>' +
            '      <input type="text" id="profile-handle" class="login-input" placeholder="your-name">' +
            '      <div class="profile-help">URL: /p/<span id="handle-preview">your-name</span></div>' +
            '    </div>' +
            '    <div class="profile-field">' +
            '      <label class="profile-label" for="profile-name">Display Name</label>' +
            '      <input type="text" id="profile-name" class="login-input" placeholder="Your Full Name">' +
            '    </div>' +
            '    <div class="profile-field profile-wide">' +
            '      <label class="profile-label" for="profile-headline">Headline</label>' +
            '      <input type="text" id="profile-headline" class="login-input" placeholder="Software Engineer">' +
            '    </div>' +
            '    <div class="profile-field profile-wide">' +
            '      <label class="profile-label" for="profile-bio">Bio</label>' +
            '      <textarea id="profile-bio" class="login-input profile-textarea" rows="3" placeholder="A short bio..."></textarea>' +
            '    </div>' +
            '    <div class="profile-field">' +
            '      <label class="profile-label" for="profile-policy">Privacy Level</label>' +
            '      <select id="profile-policy" class="login-input profile-policy-select"></select>' +
            '    </div>' +
            '  </div>' +
            '  <div class="profile-field">' +
            '    <label class="profile-label">Sections</label>' +
            '    <div id="section-toggles" class="profile-sections"></div>' +
            '  </div>' +
            '  <div class="profile-actions">' +
            '    <button class="btn btn-primary" id="btn-save-profile">Save Profile</button>' +
            '    <button class="btn btn-outline" id="btn-preview-profile">Preview</button>' +
            '    <button class="btn btn-outline" id="btn-auto-profile">Auto-fill from Memory</button>' +
            '    <button class="btn btn-outline" id="btn-qr-profile">QR Code</button>' +
            '  </div>' +
            '</div>' +
            '<div id="qr-modal" class="profile-modal is-hidden">' +
            '  <div class="profile-modal-card">' +
            '    <div id="qr-content"></div>' +
            '    <button class="btn btn-outline profile-modal-close" id="btn-close-qr">Close</button>' +
            '  </div>' +
            '</div>';

        var policySelect = document.getElementById('profile-policy');
        POLICIES.forEach(function (p) {
            var opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name;
            policySelect.appendChild(opt);
        });

        var togglesDiv = document.getElementById('section-toggles');
        SECTIONS.forEach(function (s) {
            var label = document.createElement('label');
            label.className = 'profile-section-pill';
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
                var hint = document.getElementById('profile-empty-hint');
                profileSelector.innerHTML = '';
                profiles.forEach(function (p) {
                    var opt = document.createElement('option');
                    opt.value = p.handle;
                    opt.textContent = p.display_name || p.handle;
                    profileSelector.appendChild(opt);
                });
                deleteBtn.classList.toggle('is-hidden', profiles.length === 0);
                if (profiles.length > 0) {
                    fillForm(profiles[0]);
                    hint.classList.add('is-hidden');
                } else {
                    profileSelector.innerHTML = '<option value="">No profiles yet</option>';
                    hint.classList.remove('is-hidden');
                }
            }).catch(function () {
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
            C.trackEvent('profile.new_clicked', {});
        });

        deleteBtn.addEventListener('click', function () {
            var handle = profileSelector.value;
            if (!handle) return;
            if (pendingDelete) return;

            pendingDelete = setTimeout(function () {
                pendingDelete = null;
                C.api('/api/profile?handle=' + encodeURIComponent(handle), { method: 'DELETE' })
                    .then(function () {
                        C.showToast('Profile deleted', 'success');
                        loadProfiles();
                        C.trackEvent('profile.deleted', { handle: handle });
                    })
                    .catch(function (err) { C.showToast('Error: ' + err.message, 'error'); });
            }, 5000);

            C.showToast('Profile scheduled for deletion.', {
                type: 'info',
                duration: 5200,
                actionLabel: 'Undo',
                onAction: function () {
                    clearTimeout(pendingDelete);
                    pendingDelete = null;
                    C.showToast('Delete canceled.', 'success');
                    C.trackEvent('profile.delete_undo', { handle: handle });
                },
            });
        });

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
                C.trackEvent('profile.saved', { handle: handleInput.value.toLowerCase().trim(), policy: policySelect.value });
            }).catch(function (err) {
                C.showToast('Error: ' + err.message, 'error');
            });
        });

        document.getElementById('btn-preview-profile').addEventListener('click', function () {
            var handle = handleInput.value.trim();
            var url = '/api/profile/preview' + (handle ? '?handle=' + encodeURIComponent(handle) : '');
            window.open(url, '_blank');
            C.trackEvent('profile.preview_opened', { handle: handle });
        });

        document.getElementById('btn-auto-profile').addEventListener('click', function () {
            C.api('/api/profile/auto').then(function (data) {
                if (!data || !data.handle) {
                    C.showToast('No graph data available to auto-fill', 'error');
                    return;
                }
                fillForm(data);
                C.showToast('Profile auto-filled from memory!', 'success');
                C.trackEvent('profile.autofill', {});
            }).catch(function (err) {
                C.showToast('Error: ' + err.message, 'error');
            });
        });

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
                    qrModal.classList.remove('is-hidden');
                    C.trackEvent('profile.qr_opened', { handle: handle });
                })
                .catch(function (err) { C.showToast('Error: ' + err.message, 'error'); });
        });

        document.getElementById('btn-close-qr').addEventListener('click', function () {
            qrModal.classList.add('is-hidden');
        });

        qrModal.addEventListener('click', function (e) {
            if (e.target === qrModal) qrModal.classList.add('is-hidden');
        });

        loadProfiles();
    });
})();
