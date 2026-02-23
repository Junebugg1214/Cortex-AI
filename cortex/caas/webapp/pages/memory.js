/* Cortex Web UI — My Memory (Graph Explorer) Page */
(function () {
    'use strict';
    var C = window.CortexApp;

    // Tag color palette
    var TAG_COLORS = {
        skills: '#4f46e5', work: '#be185d', interests: '#059669',
        people: '#d97706', tech: '#7c3aed', education: '#ea580c',
        preferences: '#4338ca', health: '#dc2626', hobbies: '#0891b2',
        personality: '#7e22ce', goals: '#15803d', location: '#b45309',
    };
    var TAG_BG = {
        skills: '#eef2ff', work: '#fce7f3', interests: '#ecfdf5',
        people: '#fef3c7', tech: '#ede9fe', education: '#ffedd5',
        preferences: '#e0e7ff', health: '#fef2f2', hobbies: '#ecfeff',
        personality: '#faf5ff', goals: '#dcfce7', location: '#fef3c7',
    };

    var graphData = null;
    var layoutNodes = [];
    var layoutEdges = [];
    var selectedNode = null;
    var searchTerm = '';
    var activeFilters = new Set();
    var allTags = [];
    var cam = { x: 0, y: 0, zoom: 1 };
    var dragging = false;
    var dragStart = { x: 0, y: 0 };
    var canvas, ctx;

    C.registerPage('memory', function (container) {
        container.innerHTML =
            '<div class="page-header">' +
            '  <h1>My Memory</h1>' +
            '  <p>Explore your personal knowledge graph</p>' +
            '</div>' +
            '<div class="graph-wrapper">' +
            '  <div class="graph-toolbar">' +
            '    <input type="text" class="search-input" id="mem-search" placeholder="Search your memory...">' +
            '  </div>' +
            '  <div class="filter-chips" id="filter-chips"></div>' +
            '  <div class="graph-canvas-container">' +
            '    <canvas id="mem-canvas"></canvas>' +
            '    <div class="node-panel" id="node-panel">' +
            '      <button class="node-panel-close" id="panel-close">&times;</button>' +
            '      <div id="panel-content"></div>' +
            '    </div>' +
            '  </div>' +
            '  <div class="graph-stats" id="graph-stats"></div>' +
            '</div>';

        canvas = document.getElementById('mem-canvas');
        ctx = canvas.getContext('2d');
        cam = { x: 0, y: 0, zoom: 1 };
        selectedNode = null;
        searchTerm = '';
        activeFilters.clear();

        setupEvents();
        loadData();
    });

    function setupEvents() {
        document.getElementById('mem-search').addEventListener('input', C.debounce(function () {
            searchTerm = this.value.toLowerCase();
            draw();
        }, 200));

        document.getElementById('panel-close').addEventListener('click', function () {
            selectedNode = null;
            document.getElementById('node-panel').classList.remove('visible');
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
            if (!layoutNodes.length) return;
            var rect = canvas.getBoundingClientRect();
            var mx = (e.clientX - rect.left - cam.x) / cam.zoom;
            var my = (e.clientY - rect.top - cam.y) / cam.zoom;

            var hit = null;
            for (var i = 0; i < layoutNodes.length; i++) {
                var n = layoutNodes[i];
                var dx = mx - n.px, dy = my - n.py;
                if (dx * dx + dy * dy < (n.r + 4) * (n.r + 4)) {
                    hit = n;
                }
            }
            selectNode(hit);
            draw();
        });

        // Touch support
        canvas.addEventListener('touchstart', function (e) {
            if (e.touches.length === 1) {
                dragging = true;
                dragStart = { x: e.touches[0].clientX - cam.x, y: e.touches[0].clientY - cam.y };
            }
        }, { passive: true });

        canvas.addEventListener('touchmove', function (e) {
            if (dragging && e.touches.length === 1) {
                cam.x = e.touches[0].clientX - dragStart.x;
                cam.y = e.touches[0].clientY - dragStart.y;
                draw();
            }
        }, { passive: true });

        canvas.addEventListener('touchend', function () { dragging = false; }, { passive: true });
    }

    function normalizeGraphData(data) {
        // The API returns v6 format: {graph: {nodes: {id: {...}}, edges: {id: {...}}}}
        // The UI expects flat arrays: {nodes: [...], edges: [...]}
        if (data && data.graph) {
            var g = data.graph;
            var nodes = g.nodes || {};
            var edges = g.edges || {};
            return {
                nodes: Array.isArray(nodes) ? nodes : Object.values(nodes),
                edges: Array.isArray(edges) ? edges : Object.values(edges),
            };
        }
        // Already in flat format or unknown — normalize arrays
        return {
            nodes: Array.isArray(data.nodes) ? data.nodes : (data.nodes ? Object.values(data.nodes) : []),
            edges: Array.isArray(data.edges) ? data.edges : (data.edges ? Object.values(data.edges) : []),
        };
    }

    function loadData() {
        C.api('/context?policy=full').then(function (data) {
            graphData = normalizeGraphData(data);
            processGraph();
            renderFilters();
            renderStats();
            draw();
        }).catch(function (err) {
            if (err.message === 'unauthorized') return;
            C.showToast('Failed to load memory: ' + err.message, 'error');
        });
    }

    function processGraph() {
        if (!graphData) return;
        var nodes = graphData.nodes || [];
        var edges = graphData.edges || [];
        var tagSet = {};

        // Build node lookup
        var nodeMap = {};
        nodes.forEach(function (n, i) {
            nodeMap[n.id] = i;
            var tags = n.tags || [];
            tags.forEach(function (t) {
                var key = t.toLowerCase();
                tagSet[key] = (tagSet[key] || 0) + 1;
            });
        });

        allTags = Object.keys(tagSet).sort(function (a, b) { return tagSet[b] - tagSet[a]; });

        // Layout: Fruchterman-Reingold (simplified)
        var N = nodes.length;
        if (N === 0) { layoutNodes = []; layoutEdges = []; return; }

        // Initialize positions with a circular layout seeded by index
        var positions = [];
        for (var i = 0; i < N; i++) {
            var angle = (2 * Math.PI * i) / N;
            positions.push({ x: 0.5 + 0.35 * Math.cos(angle), y: 0.5 + 0.35 * Math.sin(angle) });
        }

        // Build adjacency for edge lookup
        var adjEdges = [];
        edges.forEach(function (e) {
            var si = typeof e.source === 'number' ? e.source : nodeMap[e.source];
            var ti = typeof e.target === 'number' ? e.target : nodeMap[e.target];
            if (si !== undefined && ti !== undefined) {
                adjEdges.push({ s: si, t: ti });
            }
        });

        // Fruchterman-Reingold iterations
        var area = 1.0;
        var k = Math.sqrt(area / N);
        var iterations = Math.min(50, 10 + N);
        var temp = 0.1;

        for (var iter = 0; iter < iterations; iter++) {
            var disp = [];
            for (var di = 0; di < N; di++) disp.push({ x: 0, y: 0 });

            // Repulsive forces
            for (var u = 0; u < N; u++) {
                for (var v = u + 1; v < N; v++) {
                    var dx = positions[u].x - positions[v].x;
                    var dy = positions[u].y - positions[v].y;
                    var dist = Math.sqrt(dx * dx + dy * dy) || 0.001;
                    var force = (k * k) / dist;
                    var fx = (dx / dist) * force;
                    var fy = (dy / dist) * force;
                    disp[u].x += fx; disp[u].y += fy;
                    disp[v].x -= fx; disp[v].y -= fy;
                }
            }

            // Attractive forces
            adjEdges.forEach(function (e) {
                var dx = positions[e.s].x - positions[e.t].x;
                var dy = positions[e.s].y - positions[e.t].y;
                var dist = Math.sqrt(dx * dx + dy * dy) || 0.001;
                var force = (dist * dist) / k;
                var fx = (dx / dist) * force;
                var fy = (dy / dist) * force;
                disp[e.s].x -= fx; disp[e.s].y -= fy;
                disp[e.t].x += fx; disp[e.t].y += fy;
            });

            // Apply displacements
            for (var ai = 0; ai < N; ai++) {
                var dlen = Math.sqrt(disp[ai].x * disp[ai].x + disp[ai].y * disp[ai].y) || 0.001;
                var scale = Math.min(dlen, temp) / dlen;
                positions[ai].x += disp[ai].x * scale;
                positions[ai].y += disp[ai].y * scale;
                positions[ai].x = Math.max(0.05, Math.min(0.95, positions[ai].x));
                positions[ai].y = Math.max(0.05, Math.min(0.95, positions[ai].y));
            }
            temp *= 0.95;
        }

        // Build layout nodes
        layoutNodes = nodes.map(function (n, idx) {
            var conf = n.confidence || 0.5;
            var r = 6 + conf * 14;
            var primaryTag = (n.tags && n.tags[0]) ? n.tags[0].toLowerCase() : 'default';
            return {
                id: n.id,
                label: n.label || n.id,
                tags: n.tags || [],
                confidence: conf,
                brief: n.brief || '',
                px: positions[idx].x * canvas.clientWidth,
                py: positions[idx].y * canvas.clientHeight,
                r: r,
                color: TAG_COLORS[primaryTag] || '#64748b',
                tagKey: primaryTag,
            };
        });

        layoutEdges = adjEdges;
    }

    function renderFilters() {
        var container = document.getElementById('filter-chips');
        var html = '';
        allTags.slice(0, 12).forEach(function (tag) {
            var label = tag.charAt(0).toUpperCase() + tag.slice(1);
            html += '<button class="chip" data-tag="' + C.escapeHtml(tag) + '">' + C.escapeHtml(label) + '</button>';
        });
        container.innerHTML = html;

        container.querySelectorAll('.chip').forEach(function (chip) {
            chip.addEventListener('click', function () {
                var tag = this.getAttribute('data-tag');
                if (activeFilters.has(tag)) {
                    activeFilters.delete(tag);
                    this.classList.remove('active');
                } else {
                    activeFilters.add(tag);
                    this.classList.add('active');
                }
                draw();
            });
        });
    }

    function renderStats() {
        if (!graphData) return;
        var el = document.getElementById('graph-stats');
        var nCount = (graphData.nodes || []).length;
        var eCount = (graphData.edges || []).length;
        el.innerHTML =
            '<span><strong>' + nCount + '</strong> facts</span>' +
            '<span><strong>' + eCount + '</strong> connections</span>' +
            '<span><strong>' + allTags.length + '</strong> categories</span>';
    }

    function selectNode(node) {
        selectedNode = node;
        var panel = document.getElementById('node-panel');
        var content = document.getElementById('panel-content');

        if (!node) {
            panel.classList.remove('visible');
            return;
        }
        panel.classList.add('visible');

        var tagsHtml = node.tags.map(function (t) {
            var key = t.toLowerCase();
            var bg = TAG_BG[key] || '#f1f5f9';
            var fg = TAG_COLORS[key] || '#475569';
            return '<span class="tag-badge" style="background:' + bg + ';color:' + fg + '">' + C.escapeHtml(t) + '</span>';
        }).join(' ');

        var connCount = 0;
        var nodeIdx = layoutNodes.indexOf(node);
        layoutEdges.forEach(function (e) { if (e.s === nodeIdx || e.t === nodeIdx) connCount++; });

        content.innerHTML =
            '<h3>' + C.escapeHtml(node.label) + '</h3>' +
            '<div class="node-detail-row">' +
            '  <div class="node-detail-label">Tags</div>' +
            '  <div class="node-detail-value">' + (tagsHtml || '<span style="color:#94a3b8">None</span>') + '</div>' +
            '</div>' +
            '<div class="node-detail-row">' +
            '  <div class="node-detail-label">Confidence</div>' +
            '  <div class="node-detail-value">' + Math.round(node.confidence * 100) + '%</div>' +
            '</div>' +
            (node.brief ? '<div class="node-detail-row"><div class="node-detail-label">Details</div><div class="node-detail-value">' + C.escapeHtml(node.brief) + '</div></div>' : '') +
            '<div class="node-detail-row">' +
            '  <div class="node-detail-label">Connections</div>' +
            '  <div class="node-detail-value">' + connCount + '</div>' +
            '</div>' +
            '<div class="node-detail-row">' +
            '  <div class="node-detail-label">ID</div>' +
            '  <div class="node-detail-value" style="font-family:var(--font-mono);font-size:11px;color:var(--color-text-muted);cursor:pointer" onclick="CortexApp.copyToClipboard(\'' + C.escapeHtml(node.id) + '\')">' + C.escapeHtml(node.id) + '</div>' +
            '</div>';
    }

    function isNodeVisible(node) {
        if (activeFilters.size > 0) {
            var hasTags = node.tags.some(function (t) { return activeFilters.has(t.toLowerCase()); });
            if (!hasTags) return false;
        }
        if (searchTerm) {
            return node.label.toLowerCase().indexOf(searchTerm) >= 0;
        }
        return true;
    }

    function draw() {
        if (!canvas || !ctx) return;
        var dpr = window.devicePixelRatio || 1;
        var cw = canvas.clientWidth;
        var ch = canvas.clientHeight;
        canvas.width = cw * dpr;
        canvas.height = ch * dpr;

        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Background
        ctx.fillStyle = '#fafbfc';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        if (!layoutNodes.length) {
            ctx.fillStyle = '#94a3b8';
            ctx.font = '15px ' + getComputedStyle(document.body).fontFamily;
            ctx.textAlign = 'center';
            ctx.fillText('No data yet. Upload a chat export to get started.', canvas.width / 2, canvas.height / 2);
            return;
        }

        ctx.save();
        ctx.scale(dpr, dpr);
        ctx.translate(cam.x, cam.y);
        ctx.scale(cam.zoom, cam.zoom);

        // Recalculate pixel positions based on current canvas size
        if (graphData) {
            for (var ri = 0; ri < layoutNodes.length; ri++) {
                // Positions are stored normalized; stored in px on processGraph.
                // Re-derive from first call only
            }
        }

        // Draw edges
        ctx.lineWidth = 1;
        layoutEdges.forEach(function (e) {
            var s = layoutNodes[e.s];
            var t = layoutNodes[e.t];
            if (!s || !t) return;
            var sVis = isNodeVisible(s);
            var tVis = isNodeVisible(t);
            ctx.globalAlpha = (sVis && tVis) ? 0.25 : 0.05;
            ctx.strokeStyle = '#94a3b8';
            ctx.beginPath();
            ctx.moveTo(s.px, s.py);
            ctx.lineTo(t.px, t.py);
            ctx.stroke();
        });

        ctx.globalAlpha = 1;

        // Draw nodes
        layoutNodes.forEach(function (n) {
            var vis = isNodeVisible(n);
            var isSelected = selectedNode && n.id === selectedNode.id;
            ctx.globalAlpha = vis ? 1 : 0.08;

            ctx.beginPath();
            ctx.arc(n.px, n.py, n.r, 0, Math.PI * 2);
            ctx.fillStyle = n.color;
            ctx.fill();

            if (isSelected) {
                ctx.strokeStyle = '#1e293b';
                ctx.lineWidth = 3;
                ctx.stroke();
            }

            // Label
            if (vis && (cam.zoom > 0.4 || isSelected)) {
                ctx.fillStyle = '#1e293b';
                ctx.font = (isSelected ? 'bold ' : '') + '11px -apple-system, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(n.label, n.px, n.py + n.r + 14);
            }
        });

        ctx.globalAlpha = 1;
        ctx.restore();
    }
})();
