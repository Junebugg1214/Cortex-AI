"""
Cortex Local Dashboard — Phase 6 (v6.0)

stdlib http.server dashboard with AJAX polling.
Serves a single-page app for graph exploration.
Pure Python stdlib — no external dependencies.
"""

from __future__ import annotations

import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cortex.graph import CortexGraph


# ---------------------------------------------------------------------------
# Dashboard HTML (embedded SPA)
# ---------------------------------------------------------------------------

def _build_dashboard_html() -> str:
    """Build the self-contained dashboard HTML string."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cortex Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #f0f2f5; color: #2c3e50; }
.header { background: #2c3e50; color: #fff; padding: 12px 24px; font-size: 18px; font-weight: 600; }
.container { display: flex; height: calc(100vh - 48px); }
.graph-panel { flex: 7; position: relative; background: #fff; margin: 12px; border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow: hidden; }
.graph-panel canvas { width: 100%; height: 100%; }
.side-panel { flex: 3; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 12px; }
.card { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.card h3 { font-size: 13px; text-transform: uppercase; color: #7f8c8d; margin-bottom: 8px; letter-spacing: 0.5px; }
.card .value { font-size: 24px; font-weight: 700; color: #2c3e50; }
.card .detail { font-size: 12px; color: #95a5a6; margin-top: 4px; }
.card ul { list-style: none; font-size: 12px; }
.card ul li { padding: 3px 0; border-bottom: 1px solid #f0f2f5; }
.badge { display: inline-block; background: #ecf0f1; border-radius: 3px; padding: 1px 6px;
  font-size: 10px; color: #7f8c8d; margin-left: 4px; }
.status { font-size: 11px; color: #95a5a6; text-align: center; padding: 8px; }
</style>
</head>
<body>
<div class="header">Cortex Dashboard</div>
<div class="container">
  <div class="graph-panel"><canvas id="gc"></canvas></div>
  <div class="side-panel">
    <div class="card" id="stats-card"><h3>Statistics</h3><div class="value">-</div></div>
    <div class="card" id="gaps-card"><h3>Gap Analysis</h3><ul></ul></div>
    <div class="card" id="components-card"><h3>Components</h3><ul></ul></div>
  </div>
</div>
<div class="status" id="status">Connecting...</div>
<script>
const gc=document.getElementById("gc"), gx=gc.getContext("2d");
let gNodes=[], gEdges=[], scale=1, ox=0, oy=0;

function resizeCanvas() {
  const p=gc.parentElement; gc.width=p.clientWidth; gc.height=p.clientHeight; drawGraph();
}
window.addEventListener("resize", resizeCanvas);

function drawGraph() {
  const w=gc.width, h=gc.height;
  gx.clearRect(0,0,w,h);
  gx.save(); gx.scale(scale,scale); gx.translate(ox,oy);
  for(const e of gEdges) {
    const a=gNodes[e.s], b=gNodes[e.t]; if(!a||!b) continue;
    gx.beginPath(); gx.moveTo(a.x,a.y); gx.lineTo(b.x,b.y);
    gx.strokeStyle="rgba(150,150,150,0.3)"; gx.lineWidth=1; gx.stroke();
  }
  for(const n of gNodes) {
    gx.beginPath(); gx.arc(n.x,n.y,n.r,0,Math.PI*2);
    gx.fillStyle=n.color; gx.globalAlpha=0.85; gx.fill();
    gx.globalAlpha=1; gx.strokeStyle="#fff"; gx.lineWidth=1; gx.stroke();
    gx.fillStyle="#2c3e50"; gx.font="10px sans-serif"; gx.textAlign="center";
    gx.fillText(n.label, n.x, n.y+n.r+12);
  }
  gx.restore();
}

async function poll() {
  try {
    const [gr, st, gp, cp] = await Promise.all([
      fetch("/api/graph").then(r=>r.json()),
      fetch("/api/stats").then(r=>r.json()),
      fetch("/api/gaps").then(r=>r.json()),
      fetch("/api/components").then(r=>r.json()),
    ]);
    // Graph
    gNodes=gr.nodes||[]; gEdges=gr.edges||[];
    resizeCanvas();
    // Stats
    const sc=document.querySelector("#stats-card .value");
    sc.textContent=st.node_count+" nodes, "+st.edge_count+" edges";
    const det=document.querySelector("#stats-card .detail")||document.createElement("div");
    det.className="detail"; det.textContent="Avg degree: "+(st.avg_degree||0).toFixed(1);
    if(!document.querySelector("#stats-card .detail")) document.getElementById("stats-card").appendChild(det);
    // Gaps
    const gu=document.querySelector("#gaps-card ul"); gu.innerHTML="";
    const gapTypes=["category_gaps","confidence_gaps","relationship_gaps","isolated_nodes","stale_nodes"];
    for(const t of gapTypes) {
      const items=gp[t]||[];
      if(items.length>0) {
        const li=document.createElement("li");
        li.innerHTML=t.replace(/_/g," ")+'<span class="badge">'+items.length+"</span>";
        gu.appendChild(li);
      }
    }
    if(!gu.children.length) { const li=document.createElement("li"); li.textContent="No gaps"; gu.appendChild(li); }
    // Components
    const cu=document.querySelector("#components-card ul"); cu.innerHTML="";
    for(const c of cp.slice(0,8)) {
      const li=document.createElement("li");
      li.textContent=c.labels.slice(0,5).join(", ")+(c.labels.length>5?"...":"")+'  ('+c.size+')';
      cu.appendChild(li);
    }
    if(!cu.children.length) { const li=document.createElement("li"); li.textContent="Empty graph"; cu.appendChild(li); }
    document.getElementById("status").textContent="Last update: "+new Date().toLocaleTimeString();
  } catch(e) {
    document.getElementById("status").textContent="Error: "+e.message;
  }
}

// Zoom/pan on graph canvas
gc.addEventListener("wheel", function(e) { e.preventDefault(); scale*=e.deltaY<0?1.1:0.9; drawGraph(); });
let drag=false, lx=0, ly=0;
gc.addEventListener("mousedown", function(e) { drag=true; lx=e.clientX; ly=e.clientY; });
gc.addEventListener("mousemove", function(e) {
  if(!drag) return; ox+=(e.clientX-lx)/scale; oy+=(e.clientY-ly)/scale; lx=e.clientX; ly=e.clientY; drawGraph();
});
gc.addEventListener("mouseup", function() { drag=false; });

poll();
setInterval(poll, 5000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Request Handler
# ---------------------------------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Cortex dashboard."""

    graph: CortexGraph  # Set before server starts

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._serve_html(_build_dashboard_html())
        elif path == "/api/graph":
            self._serve_graph_json()
        elif path == "/api/stats":
            self._serve_stats()
        elif path == "/api/gaps":
            self._serve_gaps()
        elif path == "/api/components":
            self._serve_components()
        else:
            self.send_error(404)

    def _serve_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self._respond(200, "text/html; charset=utf-8", body)

    def _serve_graph_json(self) -> None:
        from cortex.viz.layout import fruchterman_reingold
        from cortex.viz.renderer import _tag_color, _node_radius

        graph = self.__class__.graph
        layout = fruchterman_reingold(graph)

        nodes: list[dict[str, Any]] = []
        node_id_to_idx: dict[str, int] = {}
        for nid, pos in layout.items():
            node = graph.get_node(nid)
            if not node:
                continue
            node_id_to_idx[nid] = len(nodes)
            primary_tag = node.tags[0] if node.tags else "mentions"
            nodes.append({
                "id": nid,
                "label": node.label,
                "x": round(pos[0] * 800, 2),
                "y": round(pos[1] * 600, 2),
                "r": round(_node_radius(node.confidence), 1),
                "color": _tag_color(primary_tag),
                "tags": list(node.tags),
                "confidence": round(node.confidence, 2),
            })

        edges: list[dict[str, Any]] = []
        for edge in graph.edges.values():
            si = node_id_to_idx.get(edge.source_id)
            ti = node_id_to_idx.get(edge.target_id)
            if si is not None and ti is not None:
                edges.append({
                    "s": si, "t": ti,
                    "relation": edge.relation,
                    "confidence": round(edge.confidence, 2),
                })

        self._json_response({"nodes": nodes, "edges": edges})

    def _serve_stats(self) -> None:
        graph = self.__class__.graph
        self._json_response(graph.stats())

    def _serve_gaps(self) -> None:
        from cortex.intelligence import GapAnalyzer
        graph = self.__class__.graph
        analyzer = GapAnalyzer()
        self._json_response(analyzer.all_gaps(graph))

    def _serve_components(self) -> None:
        from cortex.query import connected_components
        graph = self.__class__.graph
        comps = connected_components(graph)
        result = []
        for comp in comps:
            labels = sorted(
                graph.get_node(nid).label
                for nid in comp
                if graph.get_node(nid)
            )
            result.append({"size": len(comp), "labels": labels})
        self._json_response(result)

    def _json_response(self, data: Any) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self._respond(200, "application/json", body)

    def _respond(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress noisy default request logging."""
        pass


# ---------------------------------------------------------------------------
# Server launcher
# ---------------------------------------------------------------------------

def start_dashboard(
    graph: CortexGraph,
    port: int = 8420,
    open_browser: bool = True,
) -> HTTPServer:
    """Start the dashboard server (blocking). Returns server on shutdown."""
    DashboardHandler.graph = graph
    server = HTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"Cortex Dashboard: http://127.0.0.1:{port}")
    if open_browser:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{port}")
    server.serve_forever()
    return server
