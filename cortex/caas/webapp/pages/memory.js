/* Cortex Web UI — My Memory (Summary + Graph Explorer) Page */
(function () {
    'use strict';
    var C = window.CortexApp;

    var TAG_COLORS = {
        identity: '#1d4ed8', professional_context: '#0f766e', business_context: '#7c2d12',
        active_priorities: '#be123c', work_history: '#0f766e', education_history: '#7c3aed',
        relationships: '#b45309', technical_expertise: '#4338ca', domain_knowledge: '#0e7490',
        market_context: '#9a3412', metrics: '#166534', constraints: '#b91c1c', values: '#a16207',
        negations: '#991b1b', user_preferences: '#6d28d9', communication_preferences: '#0369a1',
        correction_history: '#6b7280', history: '#4b5563', mentions: '#475569',
    };

    var TAG_BG = {
        identity: '#dbeafe', professional_context: '#ccfbf1', business_context: '#ffedd5',
        active_priorities: '#ffe4e6', work_history: '#ccfbf1', education_history: '#f3e8ff',
        relationships: '#fef3c7', technical_expertise: '#e0e7ff', domain_knowledge: '#cffafe',
        market_context: '#ffedd5', metrics: '#dcfce7', constraints: '#fee2e2', values: '#fef9c3',
        negations: '#fee2e2', user_preferences: '#ede9fe', communication_preferences: '#e0f2fe',
        correction_history: '#f3f4f6', history: '#e5e7eb', mentions: '#f1f5f9',
    };

    var graphData = null;
    var graphMeta = { totalNodes: 0, totalEdges: 0, nodesHasMore: false, edgesHasMore: false };
    var layoutNodes = [];
    var layoutEdges = [];
    var selectedNode = null;
    var searchTerm = '';
    var activeFilters = new Set();
    var allTags = [];
    var cam = { x: 0, y: 0, zoom: 1 };
    var dragging = false;
    var dragStart = { x: 0, y: 0 };
    var pointerDown = { x: 0, y: 0 };
    var pointerMoved = false;
    var pinnedNodeIds = new Set();
    var summaryFactWindow = 12;

    var canvas;
    var ctx;
    var activeView = 'summary';

    var MAX_FETCH_NODES = 1000;
    var MAX_FETCH_EDGES = 1000;
    var MAX_RENDER_NODES = 350;

    C.registerPage('memory', function (container) {
        container.innerHTML =
            '<div class="page-header">' +
            '  <h1>My Memory</h1>' +
            '  <p>Start with summary. Open advanced graph only when you need deeper inspection.</p>' +
            '</div>' +
            '<div class="card page-flow-cue">' +
            '  <span class="flow-step flow-step-active">1. Review Summary</span>' +
            '  <span class="flow-step">2. Advanced Graph</span>' +
            '  <span class="flow-step">3. Share</span>' +
            '</div>' +
            '<div class="memory-view-toggle">' +
            '  <button class="memory-view-btn active" data-view="summary">Summary</button>' +
            '  <button class="memory-view-btn" data-view="graph">Advanced Graph</button>' +
            '</div>' +
            '<section id="memory-summary" class="memory-summary"></section>' +
            '<section id="memory-graph" class="memory-graph is-hidden">' +
            '  <div class="graph-wrapper">' +
            '    <div class="graph-toolbar">' +
            '      <input type="text" class="search-input" id="mem-search" placeholder="Search your memory..." aria-label="Search memory graph">' +
            '      <button class="btn btn-outline btn-sm" id="graph-reset">Reset View</button>' +
            '      <button class="btn btn-outline btn-sm" id="graph-fit">Fit Graph</button>' +
            '    </div>' +
            '    <div class="filter-chips" id="filter-chips"></div>' +
            '    <div class="graph-canvas-container">' +
            '      <canvas id="mem-canvas"></canvas>' +
            '      <div class="node-panel" id="node-panel">' +
            '        <button class="node-panel-close" id="panel-close">&times;</button>' +
            '        <div id="panel-content"></div>' +
            '      </div>' +
            '    </div>' +
            '    <div class="graph-stats" id="graph-stats"></div>' +
            '  </div>' +
            '</section>';

        canvas = document.getElementById('mem-canvas');
        ctx = canvas.getContext('2d');

        cam = { x: 0, y: 0, zoom: 1 };
        selectedNode = null;
        searchTerm = '';
        activeFilters.clear();

        setupViewTabs();
        setupGraphEvents();
        loadData();
    });

    function setupViewTabs() {
        document.querySelectorAll('.memory-view-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                setActiveView(btn.getAttribute('data-view'));
            });
        });

        document.addEventListener('click', function (e) {
            if (!e.target || !e.target.matches) return;
            if (e.target.matches('[data-memory-view]')) {
                setActiveView(e.target.getAttribute('data-memory-view'));
            }
            if (e.target.matches('#summary-load-more')) {
                summaryFactWindow += 12;
                renderSummary();
            }
        });
    }

    function setActiveView(view) {
        activeView = view === 'graph' ? 'graph' : 'summary';
        var summaryEl = document.getElementById('memory-summary');
        var graphEl = document.getElementById('memory-graph');

        document.querySelectorAll('.memory-view-btn').forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-view') === activeView);
        });

        summaryEl.style.display = activeView === 'summary' ? '' : 'none';
        graphEl.classList.toggle('is-hidden', activeView !== 'graph');

        if (activeView === 'graph') {
            setTimeout(function () { draw(); }, 0);
            C.trackEvent('memory.graph_opened', { nodes: layoutNodes.length, edges: layoutEdges.length });
        }
    }

    function setupGraphEvents() {
        var searchInput = document.getElementById('mem-search');
        var panelClose = document.getElementById('panel-close');

        searchInput.addEventListener('input', C.debounce(function () {
            searchTerm = this.value.toLowerCase();
            draw();
        }, 200));

        panelClose.addEventListener('click', function () {
            selectedNode = null;
            document.getElementById('node-panel').classList.remove('visible');
            draw();
        });

        document.getElementById('graph-reset').addEventListener('click', function () {
            cam = { x: 0, y: 0, zoom: 1 };
            draw();
            C.trackEvent('memory.graph_reset', {});
        });

        document.getElementById('graph-fit').addEventListener('click', function () {
            fitToScreen();
            draw();
            C.trackEvent('memory.graph_fit', {});
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
            pointerDown = { x: e.clientX, y: e.clientY };
            pointerMoved = false;
        });

        canvas.addEventListener('mousemove', function (e) {
            if (!dragging) return;
            if (Math.abs(e.clientX - pointerDown.x) > 3 || Math.abs(e.clientY - pointerDown.y) > 3) pointerMoved = true;
            cam.x = e.clientX - dragStart.x;
            cam.y = e.clientY - dragStart.y;
            draw();
        });

        canvas.addEventListener('mouseup', function () { dragging = false; });
        canvas.addEventListener('mouseleave', function () { dragging = false; });

        canvas.addEventListener('click', function (e) {
            if (!layoutNodes.length) return;
            if (pointerMoved) {
                pointerMoved = false;
                return;
            }
            var rect = canvas.getBoundingClientRect();
            var mx = (e.clientX - rect.left - cam.x) / cam.zoom;
            var my = (e.clientY - rect.top - cam.y) / cam.zoom;

            var hit = null;
            for (var i = 0; i < layoutNodes.length; i++) {
                var n = layoutNodes[i];
                var dx = mx - n.px;
                var dy = my - n.py;
                if (dx * dx + dy * dy < (n.r + 4) * (n.r + 4)) hit = n;
            }
            selectNode(hit);
            draw();
        });
    }

    function loadData() {
        Promise.all([
            C.api('/context/stats', { cache: 'no-store' }),
            C.api('/context/nodes?limit=' + MAX_FETCH_NODES, { cache: 'no-store' }),
            C.api('/context/edges?limit=' + MAX_FETCH_EDGES, { cache: 'no-store' }),
        ]).then(function (results) {
            var stats = results[0] || {};
            var nodesPage = results[1] || {};
            var edgesPage = results[2] || {};

            graphData = {
                nodes: Array.isArray(nodesPage.items) ? nodesPage.items : [],
                edges: Array.isArray(edgesPage.items) ? edgesPage.items : [],
            };
            graphMeta = {
                totalNodes: stats.node_count || graphData.nodes.length,
                totalEdges: stats.edge_count || graphData.edges.length,
                nodesHasMore: !!nodesPage.has_more,
                edgesHasMore: !!edgesPage.has_more,
            };

            processGraph(function () {
                renderSummary();
                renderFilters();
                renderStats();
                draw();
            });

            if (graphMeta.nodesHasMore || graphMeta.edgesHasMore) {
                C.showToast('Large memory detected. Using optimized rendering mode.', 'info');
            }
        }).catch(function (err) {
            if (err.message === 'unauthorized') return;
            C.showToast('Failed to load memory: ' + err.message, 'error');
        });
    }

    function getTopTagCounts(limit) {
        var counts = {};
        (graphData.nodes || []).forEach(function (node) {
            (node.tags || []).forEach(function (tag) {
                var key = String(tag || '').toLowerCase();
                if (!key) return;
                counts[key] = (counts[key] || 0) + 1;
            });
        });
        return Object.keys(counts)
            .map(function (k) { return { tag: k, count: counts[k] }; })
            .sort(function (a, b) { return b.count - a.count; })
            .slice(0, limit || 8);
    }

    function getTopFacts(limit) {
        return (graphData.nodes || [])
            .slice()
            .sort(function (a, b) { return (b.confidence || 0) - (a.confidence || 0); })
            .slice(0, limit || summaryFactWindow);
    }

    function renderSummary() {
        var container = document.getElementById('memory-summary');
        if (!graphData || !(graphData.nodes || []).length) {
            container.innerHTML =
                '<div class="card empty-state">' +
                '  <h3>Your memory is empty</h3>' +
                '  <p>Try uploading a ChatGPT export zip or resume to generate your first graph.</p>' +
                '  <a class="btn btn-primary empty-state-action" href="#upload">Go to Upload</a>' +
                '</div>';
            return;
        }

        var topTags = getTopTagCounts(8);
        var topFacts = getTopFacts(summaryFactWindow);

        var statsHtml =
            '<div class="memory-summary-cards">' +
            '  <div class="card memory-summary-card"><div class="memory-summary-value">' + graphMeta.totalNodes + '</div><div class="memory-summary-label">Facts</div></div>' +
            '  <div class="card memory-summary-card"><div class="memory-summary-value">' + graphMeta.totalEdges + '</div><div class="memory-summary-label">Connections</div></div>' +
            '  <div class="card memory-summary-card"><div class="memory-summary-value">' + allTags.length + '</div><div class="memory-summary-label">Categories</div></div>' +
            '  <div class="card memory-summary-card"><div class="memory-summary-value">' + pinnedNodeIds.size + '</div><div class="memory-summary-label">Pinned Facts</div></div>' +
            '</div>';

        var tagsHtml = topTags.map(function (t) {
            var color = TAG_COLORS[t.tag] || '#475569';
            var bg = TAG_BG[t.tag] || '#f1f5f9';
            return '<span class="memory-tag-pill memory-tag-pill-toned">' + C.escapeHtml(t.tag) + ' (' + t.count + ')</span>';
        }).join('');

        var factsHtml = topFacts.map(function (n) {
            var label = n.label || n.id;
            var tags = (n.tags || []).slice(0, 2).join(', ');
            var confidence = Math.round((n.confidence || 0) * 100);
            return (
                '<li class="memory-fact-item">' +
                '  <div class="memory-fact-title">' + C.escapeHtml(label) + '</div>' +
                '  <div class="memory-fact-meta">' + C.escapeHtml(tags || 'untagged') + ' · ' + confidence + '% confidence</div>' +
                '</li>'
            );
        }).join('');

        var hasMoreFacts = (graphData.nodes || []).length > topFacts.length;

        container.innerHTML =
            statsHtml +
            '<div class="memory-summary-grid">' +
            '  <div class="card">' +
            '    <div class="memory-section-title">Top Categories</div>' +
            '    <div class="memory-tag-list">' + (tagsHtml || '<span class="memory-muted">No tags available yet.</span>') + '</div>' +
            '  </div>' +
            '  <div class="card">' +
            '    <div class="memory-section-title">High-Confidence Facts</div>' +
            '    <ul class="memory-fact-list">' + factsHtml + '</ul>' +
            (hasMoreFacts ? '<button class="btn btn-outline btn-sm" id="summary-load-more">Load More</button>' : '') +
            '  </div>' +
            '</div>' +
            '<div class="card memory-cta-row">' +
            '  <div>' +
            '    <div class="memory-section-title">Next step</div>' +
            '    <p class="memory-muted">Inspect relationships in Advanced Graph or generate a share-ready export.</p>' +
            '  </div>' +
            '  <div class="memory-cta-actions">' +
            '    <button class="btn btn-primary" data-memory-view="graph">Open Advanced Graph</button>' +
            '    <a class="btn btn-outline" href="#share">Go to Share</a>' +
            '  </div>' +
            '</div>';
    }

    function processGraph(done) {
        if (!graphData) { if (done) done(); return; }

        var nodes = (graphData.nodes || []).slice();
        var edges = (graphData.edges || []).slice();
        var tagSet = {};

        if (nodes.length > MAX_RENDER_NODES) {
            nodes.sort(function (a, b) { return (b.confidence || 0.5) - (a.confidence || 0.5); });
            nodes = nodes.slice(0, MAX_RENDER_NODES);
            var keep = {};
            nodes.forEach(function (n) { keep[n.id] = true; });
            edges = edges.filter(function (e) {
                var s = e.source_id || e.source;
                var t = e.target_id || e.target;
                return keep[s] && keep[t];
            });
        }

        var nodeMap = {};
        nodes.forEach(function (n, i) {
            nodeMap[n.id] = i;
            (n.tags || []).forEach(function (t) {
                var key = String(t || '').toLowerCase();
                if (key) tagSet[key] = (tagSet[key] || 0) + 1;
            });
        });

        allTags = Object.keys(tagSet).sort(function (a, b) { return tagSet[b] - tagSet[a]; });

        var payload = {
            nodes: nodes.map(function (n) { return { id: n.id, confidence: n.confidence || 0.5, label: n.label || n.id, tags: n.tags || [], brief: n.brief || '' }; }),
            edges: edges.map(function (e) { return { source: e.source_id || e.source, target: e.target_id || e.target }; }),
            width: canvas.clientWidth || 1000,
            height: canvas.clientHeight || 520,
        };

        computeLayoutAsync(payload, function (result) {
            layoutNodes = result.nodes.map(function (n) {
                var primaryTag = n.tags && n.tags[0] ? String(n.tags[0]).toLowerCase() : 'default';
                return {
                    id: n.id,
                    label: n.label,
                    tags: n.tags,
                    confidence: n.confidence,
                    brief: n.brief,
                    px: n.x,
                    py: n.y,
                    r: 6 + (n.confidence || 0.5) * 14,
                    color: TAG_COLORS[primaryTag] || '#64748b',
                };
            });
            layoutEdges = result.edges || [];
            fitToScreen();
            if (done) done();
        });
    }

    function computeLayoutAsync(payload, done) {
        if (window.Worker && payload.nodes.length > 120) {
            var workerCode = '' +
                'self.onmessage=function(ev){' +
                'var p=ev.data;var nodes=p.nodes||[];var edges=p.edges||[];var n=nodes.length;' +
                'var idx={};for(var i=0;i<n;i++){idx[nodes[i].id]=i;}' +
                'var pos=[];for(var j=0;j<n;j++){var a=(2*Math.PI*j)/Math.max(n,1);pos.push({x:0.5+0.35*Math.cos(a),y:0.5+0.35*Math.sin(a)});}' +
                'var adj=[];for(var k=0;k<edges.length;k++){var s=idx[edges[k].source],t=idx[edges[k].target];if(s!==undefined&&t!==undefined)adj.push({s:s,t:t});}' +
                'var area=1.0;var K=Math.sqrt(area/Math.max(n,1));var it=Math.min(40,10+n);var temp=0.1;' +
                'for(var r=0;r<it;r++){' +
                'var d=[];for(var di=0;di<n;di++)d.push({x:0,y:0});' +
                'for(var u=0;u<n;u++){for(var v=u+1;v<n;v++){var dx=pos[u].x-pos[v].x,dy=pos[u].y-pos[v].y,dist=Math.sqrt(dx*dx+dy*dy)||0.001,f=(K*K)/dist,fx=(dx/dist)*f,fy=(dy/dist)*f;d[u].x+=fx;d[u].y+=fy;d[v].x-=fx;d[v].y-=fy;}}' +
                'for(var e=0;e<adj.length;e++){var a1=adj[e].s,a2=adj[e].t,dx2=pos[a1].x-pos[a2].x,dy2=pos[a1].y-pos[a2].y,dist2=Math.sqrt(dx2*dx2+dy2*dy2)||0.001,f2=(dist2*dist2)/K,fx2=(dx2/dist2)*f2,fy2=(dy2/dist2)*f2;d[a1].x-=fx2;d[a1].y-=fy2;d[a2].x+=fx2;d[a2].y+=fy2;}' +
                'for(var z=0;z<n;z++){var dl=Math.sqrt(d[z].x*d[z].x+d[z].y*d[z].y)||0.001,sc=Math.min(dl,temp)/dl;pos[z].x=Math.max(0.05,Math.min(0.95,pos[z].x+d[z].x*sc));pos[z].y=Math.max(0.05,Math.min(0.95,pos[z].y+d[z].y*sc));}temp*=0.95;}' +
                'var outN=[];for(var q=0;q<n;q++){outN.push({id:nodes[q].id,label:nodes[q].label,tags:nodes[q].tags,brief:nodes[q].brief,confidence:nodes[q].confidence,x:pos[q].x*(p.width||1000),y:pos[q].y*(p.height||520)});}' +
                'self.postMessage({nodes:outN,edges:adj});};';

            var blob = new Blob([workerCode], { type: 'application/javascript' });
            var workerUrl = URL.createObjectURL(blob);
            var worker = new Worker(workerUrl);
            worker.onmessage = function (ev) {
                done(ev.data || { nodes: [], edges: [] });
                worker.terminate();
                URL.revokeObjectURL(workerUrl);
            };
            worker.onerror = function () {
                worker.terminate();
                URL.revokeObjectURL(workerUrl);
                done(computeLayoutSync(payload));
            };
            worker.postMessage(payload);
            return;
        }

        done(computeLayoutSync(payload));
    }

    function computeLayoutSync(payload) {
        var nodes = payload.nodes || [];
        var edges = payload.edges || [];
        var n = nodes.length;
        var index = {};
        for (var i = 0; i < n; i++) index[nodes[i].id] = i;

        var pos = [];
        for (var j = 0; j < n; j++) {
            var angle = (2 * Math.PI * j) / Math.max(n, 1);
            pos.push({ x: 0.5 + 0.35 * Math.cos(angle), y: 0.5 + 0.35 * Math.sin(angle) });
        }

        var adj = [];
        edges.forEach(function (e) {
            var s = index[e.source];
            var t = index[e.target];
            if (s !== undefined && t !== undefined) adj.push({ s: s, t: t });
        });

        var area = 1.0;
        var k = Math.sqrt(area / Math.max(n, 1));
        var it = Math.min(40, 10 + n);
        var temp = 0.1;

        for (var iter = 0; iter < it; iter++) {
            var disp = [];
            for (var d = 0; d < n; d++) disp.push({ x: 0, y: 0 });

            for (var u = 0; u < n; u++) {
                for (var v = u + 1; v < n; v++) {
                    var dx = pos[u].x - pos[v].x;
                    var dy = pos[u].y - pos[v].y;
                    var dist = Math.sqrt(dx * dx + dy * dy) || 0.001;
                    var force = (k * k) / dist;
                    var fx = (dx / dist) * force;
                    var fy = (dy / dist) * force;
                    disp[u].x += fx; disp[u].y += fy;
                    disp[v].x -= fx; disp[v].y -= fy;
                }
            }

            adj.forEach(function (e) {
                var adx = pos[e.s].x - pos[e.t].x;
                var ady = pos[e.s].y - pos[e.t].y;
                var adist = Math.sqrt(adx * adx + ady * ady) || 0.001;
                var aforce = (adist * adist) / k;
                var afx = (adx / adist) * aforce;
                var afy = (ady / adist) * aforce;
                disp[e.s].x -= afx; disp[e.s].y -= afy;
                disp[e.t].x += afx; disp[e.t].y += afy;
            });

            for (var a = 0; a < n; a++) {
                var len = Math.sqrt(disp[a].x * disp[a].x + disp[a].y * disp[a].y) || 0.001;
                var scale = Math.min(len, temp) / len;
                pos[a].x = Math.max(0.05, Math.min(0.95, pos[a].x + disp[a].x * scale));
                pos[a].y = Math.max(0.05, Math.min(0.95, pos[a].y + disp[a].y * scale));
            }
            temp *= 0.95;
        }

        var outNodes = nodes.map(function (node, idx) {
            return {
                id: node.id,
                label: node.label,
                tags: node.tags,
                brief: node.brief,
                confidence: node.confidence,
                x: pos[idx].x * (payload.width || 1000),
                y: pos[idx].y * (payload.height || 520),
            };
        });

        return { nodes: outNodes, edges: adj };
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
        var el = document.getElementById('graph-stats');
        el.innerHTML =
            '<span><strong>' + (graphMeta.totalNodes || 0) + '</strong> facts</span>' +
            '<span><strong>' + (graphMeta.totalEdges || 0) + '</strong> connections</span>' +
            '<span><strong>' + allTags.length + '</strong> categories</span>' +
            '<span><strong>' + layoutNodes.length + '</strong> shown</span>' +
            '<span><strong>' + pinnedNodeIds.size + '</strong> pinned</span>';
    }

    function togglePinSelected() {
        if (!selectedNode) return;
        if (pinnedNodeIds.has(selectedNode.id)) pinnedNodeIds.delete(selectedNode.id);
        else pinnedNodeIds.add(selectedNode.id);
        selectNode(selectedNode);
        draw();
        renderStats();
        renderSummary();
    }

    function focusSelectedNode() {
        if (!selectedNode) return;
        var cx = canvas.clientWidth / 2;
        var cy = canvas.clientHeight / 2;
        cam.x = cx - selectedNode.px * cam.zoom;
        cam.y = cy - selectedNode.py * cam.zoom;
        draw();
    }

    function fitToScreen() {
        if (!layoutNodes.length) return;
        var minX = Infinity; var minY = Infinity; var maxX = -Infinity; var maxY = -Infinity;
        layoutNodes.forEach(function (n) {
            minX = Math.min(minX, n.px - n.r);
            minY = Math.min(minY, n.py - n.r);
            maxX = Math.max(maxX, n.px + n.r);
            maxY = Math.max(maxY, n.py + n.r);
        });
        var width = Math.max(1, maxX - minX);
        var height = Math.max(1, maxY - minY);
        var padding = 40;
        var zx = (canvas.clientWidth - padding * 2) / width;
        var zy = (canvas.clientHeight - padding * 2) / height;
        cam.zoom = Math.max(0.2, Math.min(2.5, Math.min(zx, zy)));
        cam.x = (canvas.clientWidth / 2) - ((minX + maxX) / 2) * cam.zoom;
        cam.y = (canvas.clientHeight / 2) - ((minY + maxY) / 2) * cam.zoom;
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
            var key = String(t || '').toLowerCase();
            var bg = TAG_BG[key] || '#f1f5f9';
            var fg = TAG_COLORS[key] || '#475569';
            return '<span class="tag-badge">' + C.escapeHtml(t) + '</span>';
        }).join(' ');

        var connCount = 0;
        var idx = layoutNodes.indexOf(node);
        layoutEdges.forEach(function (e) { if (e.s === idx || e.t === idx) connCount++; });

        content.innerHTML =
            '<h3>' + C.escapeHtml(node.label) + '</h3>' +
            '<div class="node-detail-row"><div class="node-detail-label">Tags</div><div class="node-detail-value">' + (tagsHtml || '<span class="memory-muted">None</span>') + '</div></div>' +
            '<div class="node-detail-row"><div class="node-detail-label">Confidence</div><div class="node-detail-value">' + Math.round(node.confidence * 100) + '%</div></div>' +
            (node.brief ? '<div class="node-detail-row"><div class="node-detail-label">Details</div><div class="node-detail-value">' + C.escapeHtml(node.brief) + '</div></div>' : '') +
            '<div class="node-detail-row"><div class="node-detail-label">Connections</div><div class="node-detail-value">' + connCount + '</div></div>' +
            '<div class="node-actions"><button class="btn btn-outline btn-sm" id="focus-node-btn">Focus</button><button class="btn btn-outline btn-sm" id="pin-node-btn">' + (pinnedNodeIds.has(node.id) ? 'Unpin' : 'Pin') + '</button></div>';

        var focusBtn = document.getElementById('focus-node-btn');
        var pinBtn = document.getElementById('pin-node-btn');
        if (focusBtn) focusBtn.addEventListener('click', function () { focusSelectedNode(); C.trackEvent('memory.node_focus', { node: node.id }); });
        if (pinBtn) pinBtn.addEventListener('click', function () { togglePinSelected(); C.trackEvent('memory.node_pin_toggle', { node: node.id }); });
    }

    function isNodeVisible(node) {
        if (activeFilters.size > 0) {
            var hasTags = node.tags.some(function (t) { return activeFilters.has(String(t || '').toLowerCase()); });
            if (!hasTags) return false;
        }
        if (searchTerm) return node.label.toLowerCase().indexOf(searchTerm) >= 0;
        return true;
    }

    function draw() {
        if (!canvas || !ctx) return;
        var dpr = window.devicePixelRatio || 1;
        var cw = canvas.clientWidth || 1;
        var ch = canvas.clientHeight || 1;
        canvas.width = cw * dpr;
        canvas.height = ch * dpr;

        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#fafbfc';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        if (!layoutNodes.length) {
            ctx.fillStyle = '#94a3b8';
            ctx.font = '15px ' + getComputedStyle(document.body).fontFamily;
            ctx.textAlign = 'center';
            ctx.fillText('No data yet. Upload data to build your graph.', canvas.width / 2, canvas.height / 2);
            return;
        }

        ctx.save();
        ctx.scale(dpr, dpr);
        ctx.translate(cam.x, cam.y);
        ctx.scale(cam.zoom, cam.zoom);

        ctx.lineWidth = 1;
        layoutEdges.forEach(function (e) {
            var s = layoutNodes[e.s];
            var t = layoutNodes[e.t];
            if (!s || !t) return;
            ctx.globalAlpha = (isNodeVisible(s) && isNodeVisible(t)) ? 0.25 : 0.05;
            ctx.strokeStyle = '#94a3b8';
            ctx.beginPath();
            ctx.moveTo(s.px, s.py);
            ctx.lineTo(t.px, t.py);
            ctx.stroke();
        });

        ctx.globalAlpha = 1;

        layoutNodes.forEach(function (n) {
            var vis = isNodeVisible(n);
            var selected = selectedNode && n.id === selectedNode.id;
            var pinned = pinnedNodeIds.has(n.id);

            ctx.globalAlpha = vis ? 1 : 0.08;
            ctx.beginPath();
            ctx.arc(n.px, n.py, n.r, 0, Math.PI * 2);
            ctx.fillStyle = n.color;
            ctx.fill();

            if (selected || pinned) {
                ctx.strokeStyle = selected ? '#1e293b' : '#f59e0b';
                ctx.lineWidth = selected ? 3 : 2;
                ctx.stroke();
            }

            if (vis && (cam.zoom > 0.45 || selected)) {
                ctx.fillStyle = '#1e293b';
                ctx.font = (selected ? 'bold ' : '') + '11px -apple-system, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(n.label, n.px, n.py + n.r + 14);
            }
        });

        ctx.restore();
    }
})();
