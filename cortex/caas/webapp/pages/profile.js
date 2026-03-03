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
        var isConsumer = C.isConsumerMode && C.isConsumerMode();
        container.innerHTML =
            '<div class="page-header">' +
            '  <h1>AI ID Card</h1>' +
            '  <p>' + (isConsumer
                ? 'Your AI ID belongs to you. Keep one clear profile and share it with simple controls.'
                : 'Your AI ID belongs to you. Keep one clear profile and share it with policy controls.') + '</p>' +
            '</div>' +
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
            '    <div class="profile-field profile-wide technical-only">' +
            '      <label class="profile-label" for="profile-github-url">GitHub URL (Optional)</label>' +
            '      <input type="url" id="profile-github-url" class="login-input" placeholder="https://github.com/yourname">' +
            '      <div class="profile-help">Optional link for coder-facing technical memory cards.</div>' +
            '    </div>' +
            '    <div class="profile-field">' +
            '      <label class="profile-label" for="profile-policy">' + (isConsumer ? 'Sharing Level' : 'Privacy Level') + '</label>' +
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
            document.getElementById('profile-github-url').value = data.github_url || '';
            policySelect.value = data.policy || 'professional';
            if (data.sections) {
                togglesDiv.querySelectorAll('input[type=checkbox]').forEach(function (cb) {
                    cb.checked = data.sections.indexOf(cb.dataset.section) >= 0;
                });
            }
        }

        function loadSingleProfile() {
            C.api('/api/profile').then(function (data) {
                if (data && data.handle) fillForm(data);
            }).catch(function () {});
        }

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
                    github_url: document.getElementById('profile-github-url').value.trim(),
                    policy: policySelect.value,
                    sections: sections,
                }),
            }).then(function () {
                C.showToast('Profile saved!', 'success');
                loadSingleProfile();
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

        loadSingleProfile();
    });
})();
