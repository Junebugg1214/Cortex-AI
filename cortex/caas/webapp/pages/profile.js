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

        // Handle preview
        var handleInput = document.getElementById('profile-handle');
        handleInput.addEventListener('input', function () {
            document.getElementById('handle-preview').textContent = handleInput.value || 'your-name';
        });

        // Load existing profile
        C.api('/api/profile').then(function (data) {
            if (data && data.handle) {
                handleInput.value = data.handle;
                document.getElementById('handle-preview').textContent = data.handle;
                document.getElementById('profile-name').value = data.display_name || '';
                document.getElementById('profile-headline').value = data.headline || '';
                document.getElementById('profile-bio').value = data.bio || '';
                policySelect.value = data.policy || 'professional';
                if (data.sections) {
                    var boxes = togglesDiv.querySelectorAll('input[type=checkbox]');
                    boxes.forEach(function (cb) {
                        cb.checked = data.sections.indexOf(cb.dataset.section) >= 0;
                    });
                }
            }
        }).catch(function () { /* no profile yet */ });

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
                handleInput.value = data.handle;
                document.getElementById('handle-preview').textContent = data.handle;
                document.getElementById('profile-name').value = data.display_name || '';
                document.getElementById('profile-headline').value = data.headline || '';
                document.getElementById('profile-bio').value = data.bio || '';
                policySelect.value = data.policy || 'professional';
                if (data.sections) {
                    var boxes = togglesDiv.querySelectorAll('input[type=checkbox]');
                    boxes.forEach(function (cb) {
                        cb.checked = data.sections.indexOf(cb.dataset.section) >= 0;
                    });
                }
                C.showToast('Profile auto-filled from memory!', 'success');
            }).catch(function (err) {
                C.showToast('Error: ' + err.message, 'error');
            });
        });
    });
})();
