/* Cortex Web UI — Upload Page */
(function () {
    'use strict';
    var C = window.CortexApp;

    C.registerPage('upload', function (container) {
        container.innerHTML =
            '<div class="page-header">' +
            '  <h1>Upload</h1>' +
            '  <p>Import your chat exports to build your personal knowledge graph</p>' +
            '</div>' +
            '<div id="upload-area"></div>';

        renderDropZone();
    });

    function renderDropZone() {
        var area = document.getElementById('upload-area');
        area.innerHTML =
            '<div class="card">' +
            '  <div class="upload-zone" id="drop-zone">' +
            '    <div class="upload-zone-icon">' +
            '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
            '        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>' +
            '        <polyline points="17 8 12 3 7 8"/>' +
            '        <line x1="12" y1="3" x2="12" y2="15"/>' +
            '      </svg>' +
            '    </div>' +
            '    <h2>Drop your chat export here</h2>' +
            '    <p>Or click to browse. Supports JSON and text files.</p>' +
            '    <input type="file" id="file-input" class="upload-hidden-input" accept=".json,.txt,.md,.csv">' +
            '    <div class="platform-icons">' +
            '      <div class="platform-icon">' +
            '        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M22.28 10.42c-.2-.14-.42-.22-.65-.22H14.6l2.24-6.41c.16-.48-.05-1-.5-1.22a.99.99 0 00-1.17.25L5.32 13.58c-.18.2-.28.46-.28.73 0 .58.47 1.05 1.05 1.05h7.03l-2.24 6.41c-.16.48.05 1 .5 1.22.14.07.3.1.45.1.33 0 .64-.15.85-.42l9.85-10.76c.18-.2.28-.46.28-.73a1.03 1.03 0 00-.53-.76z"/></svg>' +
            '        <span>ChatGPT</span>' +
            '      </div>' +
            '      <div class="platform-icon">' +
            '        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15v-4H7l5-8v4h4l-5 8z"/></svg>' +
            '        <span>Claude</span>' +
            '      </div>' +
            '      <div class="platform-icon">' +
            '        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>' +
            '        <span>Gemini</span>' +
            '      </div>' +
            '      <div class="platform-icon">' +
            '        <svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="10"/></svg>' +
            '        <span>Perplexity</span>' +
            '      </div>' +
            '    </div>' +
            '  </div>' +
            '</div>';

        var dropZone = document.getElementById('drop-zone');
        var fileInput = document.getElementById('file-input');

        dropZone.addEventListener('click', function () { fileInput.click(); });

        dropZone.addEventListener('dragover', function (e) {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });

        dropZone.addEventListener('dragleave', function () {
            dropZone.classList.remove('dragover');
        });

        dropZone.addEventListener('drop', function (e) {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) {
                handleFile(e.dataTransfer.files[0]);
            }
        });

        fileInput.addEventListener('change', function () {
            if (fileInput.files.length > 0) {
                handleFile(fileInput.files[0]);
            }
        });
    }

    function handleFile(file) {
        // Size check: 10 MB max
        if (file.size > 10 * 1024 * 1024) {
            C.showToast('File too large. Maximum size is 10 MB.', 'error');
            return;
        }

        renderProgress(file.name);
        uploadFile(file);
    }

    function renderProgress(filename) {
        var area = document.getElementById('upload-area');
        area.innerHTML =
            '<div class="card">' +
            '  <div class="upload-progress">' +
            '    <div class="progress-spinner"></div>' +
            '    <div class="progress-text">Processing ' + C.escapeHtml(filename) + '</div>' +
            '    <div class="progress-sub">Extracting facts and connections...</div>' +
            '  </div>' +
            '</div>';
    }

    function uploadFile(file) {
        var formData = new FormData();
        formData.append('file', file);

        C.apiRaw('/api/upload', {
            method: 'POST',
            body: formData,
        }).then(function (resp) {
            return resp.json().then(function (data) {
                if (!resp.ok) {
                    var msg = (data.error && data.error.message) || data.error || 'Upload failed';
                    throw new Error(msg);
                }
                return data;
            });
        }).then(function (data) {
            renderResults(data);
        }).catch(function (err) {
            C.showToast('Upload failed: ' + err.message, 'error');
            renderDropZone();
        });
    }

    function renderResults(data) {
        var nodes = data.nodes_created || 0;
        var edges = data.edges_created || 0;
        var categories = data.categories || 0;

        var area = document.getElementById('upload-area');
        area.innerHTML =
            '<div class="card">' +
            '  <div class="upload-results">' +
            '    <div class="results-icon">' +
            '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '        <path d="M22 11.08V12a10 10 0 11-5.93-9.14"/>' +
            '        <polyline points="22 4 12 14.01 9 11.01"/>' +
            '      </svg>' +
            '    </div>' +
            '    <div class="results-title">Upload Complete</div>' +
            '    <div class="results-summary">Your chat export has been processed successfully</div>' +
            '    <div class="results-stats">' +
            '      <div class="stat-item"><div class="stat-value">' + nodes + '</div><div class="stat-label">Facts</div></div>' +
            '      <div class="stat-item"><div class="stat-value">' + edges + '</div><div class="stat-label">Connections</div></div>' +
            '      <div class="stat-item"><div class="stat-value">' + categories + '</div><div class="stat-label">Categories</div></div>' +
            '    </div>' +
            '    <div>' +
            '      <a href="#memory" class="btn btn-primary btn-lg">View My Memory</a>' +
            '      <button class="btn btn-outline btn-lg" id="upload-another" style="margin-left:10px">Upload Another</button>' +
            '    </div>' +
            '  </div>' +
            '</div>';

        document.getElementById('upload-another').addEventListener('click', function () {
            renderDropZone();
        });
    }
})();
