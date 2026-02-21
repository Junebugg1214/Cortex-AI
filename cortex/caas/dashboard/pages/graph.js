/* Cortex Dashboard — Graph Explorer Page */
(function () {
    'use strict';
    var D = window.CortexDashboard;

    var graphData = null;
    var selectedNode = null;
    var searchTerm = '';
    var cam = { x: 0, y: 0, zoom: 1 };
    var dragging = false;
    var dragStart = { x: 0, y: 0 };
    var canvas, ctx;

    D.registerPage('graph', async function (container) {
        D.renderPage(container,
            '<h2 class="page-title">Graph Explorer</h2>' +
            '<div class="graph-container">' +
            '  <div class="graph-toolbar">' +
            '    <input type="text" id="graph-search" placeholder="Search nodes...">' +
            '    <select id="graph-policy">' +
            '      <option value="full">Full</option>' +
            '      <option value="professional">Professional</option>' +
            '      <option value="technical">Technical</option>' +
            '      <option value="minimal">Minimal</option>' +
            '    </select>' +
            '    <button class="btn btn-sm btn-outline" id="graph-reset">Reset View</button>' +
            '  </div>' +
            '  <canvas id="graph-canvas" width="960" height="600"></canvas>' +
            '  <div class="node-detail-panel" id="node-detail"></div>' +
            '</div>'
        );

        canvas = document.getElementById('graph-canvas');
        ctx = canvas.getContext('2d');
        cam = { x: 0, y: 0, zoom: 1 };
        selectedNode = null;

        // Event listeners
        document.getElementById('graph-policy').addEventListener('change', function () {
            loadGraph(this.value);
        });
        document.getElementById('graph-search').addEventListener('input', D.debounce(function () {
            searchTerm = this.value.toLowerCase();
            draw();
        }, 200));
        document.getElementById('graph-reset').addEventListener('click', function () {
            cam = { x: 0, y: 0, zoom: 1 };
            selectedNode = null;
            document.getElementById('node-detail').classList.remove('visible');
            draw();
        });

        canvas.addEventListener('wheel', function (e) {
            e.preventDefault();
            var factor = e.deltaY < 0 ? 1.1 : 0.9;
            cam.zoom = Math.max(0.2, Math.min(5, cam.zoom * factor));
            draw();
        });

        canvas.addEventListener('mousedown', function (e) {
            dragging = true;
            dragStart = { x: e.clientX - cam.x, y: e.clientY - cam.y };
        });

        canvas.addEventListener('mousemove', function (e) {
            if (dragging) {
                cam.x = e.clientX - dragStart.x;
                cam.y = e.clientY - dragStart.y;
                draw();
            }
        });

        canvas.addEventListener('mouseup', function () { dragging = false; });
        canvas.addEventListener('mouseleave', function () { dragging = false; });

        canvas.addEventListener('click', function (e) {
            if (!graphData) return;
            var rect = canvas.getBoundingClientRect();
            var mx = (e.clientX - rect.left - cam.x) / cam.zoom;
            var my = (e.clientY - rect.top - cam.y) / cam.zoom;
            var hit = null;
            var W = canvas.width, H = canvas.height;
            graphData.nodes.forEach(function (n) {
                var nx = n.x * W, ny = n.y * H;
                var dx = mx - nx, dy = my - ny;
                if (dx * dx + dy * dy < (n.r + 4) * (n.r + 4)) hit = n;
            });
            selectNode(hit);
            draw();
        });

        await loadGraph('full');
    });

    async function loadGraph(policy) {
        try {
            graphData = await D.api('/graph?policy=' + policy);
            cam = { x: 0, y: 0, zoom: 1 };
            draw();
        } catch (e) {
            if (e.message !== 'unauthorized') D.showToast('Failed to load graph: ' + e.message, 'error');
        }
    }

    function selectNode(node) {
        selectedNode = node;
        var panel = document.getElementById('node-detail');
        if (!node) {
            panel.classList.remove('visible');
            return;
        }
        panel.classList.add('visible');
        panel.innerHTML =
            '<h4>' + D.escapeHtml(node.label) + '</h4>' +
            '<div class="detail-row"><div class="detail-label">ID</div>' +
            '<span class="truncated" onclick="CortexDashboard.copyToClipboard(\'' + node.id + '\')">' + D.truncateId(node.id) + '</span></div>' +
            '<div class="detail-row"><div class="detail-label">Tags</div>' + (node.tags || []).map(function (t) { return '<span class="badge badge-info">' + D.escapeHtml(t) + '</span> '; }).join('') + '</div>' +
            '<div class="detail-row"><div class="detail-label">Confidence</div>' + (node.confidence * 100).toFixed(0) + '%</div>' +
            (node.brief ? '<div class="detail-row"><div class="detail-label">Brief</div>' + D.escapeHtml(node.brief) + '</div>' : '') +
            '<div class="detail-row"><div class="detail-label">Connections</div>' + countEdges(node) + '</div>';
    }

    function countEdges(node) {
        if (!graphData) return 0;
        var idx = graphData.nodes.indexOf(node);
        var c = 0;
        graphData.edges.forEach(function (e) { if (e.s === idx || e.t === idx) c++; });
        return c;
    }

    function draw() {
        if (!canvas || !ctx || !graphData) return;
        var W = canvas.width, H = canvas.height;
        var dpr = window.devicePixelRatio || 1;
        canvas.width = canvas.clientWidth * dpr;
        canvas.height = canvas.clientHeight * dpr;
        W = canvas.width;
        H = canvas.height;
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, W, H);

        // Background
        ctx.fillStyle = '#fafafa';
        ctx.fillRect(0, 0, W, H);

        ctx.save();
        ctx.translate(cam.x * dpr, cam.y * dpr);
        ctx.scale(cam.zoom * dpr, cam.zoom * dpr);

        var cw = canvas.clientWidth, ch = canvas.clientHeight;

        // Draw edges
        ctx.lineWidth = 1;
        graphData.edges.forEach(function (e) {
            var s = graphData.nodes[e.s], t = graphData.nodes[e.t];
            if (!s || !t) return;
            ctx.strokeStyle = 'rgba(149,165,166,0.4)';
            ctx.beginPath();
            ctx.moveTo(s.x * cw, s.y * ch);
            ctx.lineTo(t.x * cw, t.y * ch);
            ctx.stroke();
        });

        // Draw nodes
        graphData.nodes.forEach(function (n) {
            var nx = n.x * cw, ny = n.y * ch;
            var isMatch = searchTerm && n.label.toLowerCase().indexOf(searchTerm) >= 0;
            var isSelected = selectedNode && n.id === selectedNode.id;
            var alpha = searchTerm ? (isMatch ? 1 : 0.15) : 1;

            ctx.globalAlpha = alpha;
            ctx.beginPath();
            ctx.arc(nx, ny, n.r, 0, Math.PI * 2);
            ctx.fillStyle = n.color || '#95a5a6';
            ctx.fill();

            if (isSelected) {
                ctx.strokeStyle = '#2c3e50';
                ctx.lineWidth = 3;
                ctx.stroke();
            }

            // Label
            if (cam.zoom > 0.5 || isMatch || isSelected) {
                ctx.fillStyle = '#2c3e50';
                ctx.font = (isSelected ? 'bold ' : '') + '11px -apple-system, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(n.label, nx, ny + n.r + 14);
            }
            ctx.globalAlpha = 1;
        });

        ctx.restore();
    }
})();
