"""
Cortex Graph Renderer — Phase 6 (v6.0)

HTML and SVG graph visualization with interactive features.
Self-contained output files (inline CSS + JS, no external dependencies).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from cortex.graph import CATEGORY_ORDER
from cortex.viz.layout import LayoutResult

if TYPE_CHECKING:
    from cortex.graph import CortexGraph


# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

TAG_COLORS: dict[str, str] = {
    "identity":                   "#e74c3c",
    "professional_context":       "#3498db",
    "business_context":           "#2ecc71",
    "active_priorities":          "#f39c12",
    "relationships":              "#9b59b6",
    "technical_expertise":        "#1abc9c",
    "domain_knowledge":           "#e67e22",
    "market_context":             "#34495e",
    "metrics":                    "#16a085",
    "constraints":                "#c0392b",
    "values":                     "#8e44ad",
    "negations":                  "#7f8c8d",
    "user_preferences":           "#2980b9",
    "communication_preferences":  "#27ae60",
    "correction_history":         "#d35400",
    "history":                    "#95a5a6",
    "mentions":                   "#bdc3c7",
}

# Extra colors for custom tags (hash-indexed)
_EXTRA_COLORS = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
    "#469990", "#dcbeff", "#9a6324", "#800000", "#aaffc3",
]


def _tag_color(tag: str) -> str:
    """Return color for a tag. Known tags use fixed palette, custom get hash-based."""
    if tag in TAG_COLORS:
        return TAG_COLORS[tag]
    idx = hash(tag) % len(_EXTRA_COLORS)
    return _EXTRA_COLORS[idx]


def _html_escape(s: str) -> str:
    """Basic HTML escaping."""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&#39;"))


def _node_radius(confidence: float, min_r: float = 8.0, max_r: float = 24.0) -> float:
    """Map confidence [0,1] to radius [min_r, max_r]."""
    return min_r + confidence * (max_r - min_r)


# ---------------------------------------------------------------------------
# HTML Renderer
# ---------------------------------------------------------------------------

def render_html(
    graph: CortexGraph,
    layout: LayoutResult,
    width: int = 960,
    height: int = 720,
    title: str = "Cortex Knowledge Graph",
) -> str:
    """Render an interactive single-file HTML visualization.

    Features: Canvas rendering, hover tooltips, click-to-highlight neighbors,
    zoom/pan, color by primary tag, size by confidence, edge labels, legend.
    """
    # Build node data array
    nodes_data: list[dict] = []
    node_id_to_idx: dict[str, int] = {}
    for i, (nid, pos) in enumerate(layout.items()):
        node = graph.get_node(nid)
        if not node:
            continue
        node_id_to_idx[nid] = len(nodes_data)
        primary_tag = node.tags[0] if node.tags else "mentions"
        nodes_data.append({
            "id": nid,
            "label": node.label,
            "x": round(pos[0] * width, 2),
            "y": round(pos[1] * height, 2),
            "r": round(_node_radius(node.confidence), 1),
            "color": _tag_color(primary_tag),
            "tags": list(node.tags),
            "confidence": round(node.confidence, 2),
            "brief": node.brief or "",
        })

    # Build edge data array
    edges_data: list[dict] = []
    for edge in graph.edges.values():
        si = node_id_to_idx.get(edge.source_id)
        ti = node_id_to_idx.get(edge.target_id)
        if si is not None and ti is not None:
            edges_data.append({
                "s": si,
                "t": ti,
                "relation": edge.relation,
                "confidence": round(edge.confidence, 2),
            })

    # Build legend (only tags present in layout)
    present_tags: set[str] = set()
    for nd in nodes_data:
        present_tags.update(nd["tags"])
    legend_items = [(tag, _tag_color(tag)) for tag in CATEGORY_ORDER if tag in present_tags]
    for tag in sorted(present_tags - set(CATEGORY_ORDER)):
        legend_items.append((tag, _tag_color(tag)))

    # Escape </ sequences to prevent </script> injection in JSON data
    nodes_json = json.dumps(nodes_data).replace("</", "<\\/")
    edges_json = json.dumps(edges_data).replace("</", "<\\/")
    legend_html = "\n".join(
        f'<div><span style="display:inline-block;width:12px;height:12px;'
        f'background:{color};border-radius:50%;margin-right:4px;vertical-align:middle;">'
        f'</span>{_html_escape(tag)}</div>'
        for tag, color in legend_items
    )
    stats_text = f"{len(nodes_data)} nodes, {len(edges_data)} edges"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_html_escape(title)}</title>
<style>
body {{ margin:0; font-family:-apple-system,sans-serif; overflow:hidden; background:#f8f9fa; }}
#canvas {{ position:absolute; top:0; left:0; cursor:grab; }}
#tooltip {{ position:absolute; display:none; background:#fff; border:1px solid #ccc;
  padding:8px 12px; border-radius:6px; font-size:12px; pointer-events:none;
  max-width:300px; box-shadow:0 2px 8px rgba(0,0,0,.15); z-index:10; }}
#legend {{ position:absolute; top:12px; right:12px; background:rgba(255,255,255,.92);
  padding:10px 14px; border-radius:8px; font-size:11px; line-height:1.8;
  box-shadow:0 1px 4px rgba(0,0,0,.1); max-height:80vh; overflow-y:auto; }}
#stats {{ position:absolute; bottom:8px; left:12px; font-size:11px; color:#888; }}
#title {{ position:absolute; top:12px; left:12px; font-size:16px; font-weight:600; color:#333; }}
</style>
</head>
<body>
<canvas id="canvas"></canvas>
<div id="tooltip"></div>
<div id="title">{_html_escape(title)}</div>
<div id="legend">{legend_html}</div>
<div id="stats">{stats_text}</div>
<script>
const NODES={nodes_json};
const EDGES={edges_json};
const W={width},H={height};
const canvas=document.getElementById("canvas"),ctx=canvas.getContext("2d");
const tooltip=document.getElementById("tooltip");
let scale=1,ox=0,oy=0,dragging=false,dx=0,dy=0,selected=-1;

function resize(){{ canvas.width=window.innerWidth; canvas.height=window.innerHeight; draw(); }}
window.addEventListener("resize",resize);

function toScreen(x,y){{ return [(x+ox)*scale,(y+oy)*scale]; }}

function draw(){{
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.save(); ctx.scale(scale,scale); ctx.translate(ox,oy);
  // Edges
  for(const e of EDGES){{
    const a=NODES[e.s],b=NODES[e.t];
    ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y);
    ctx.strokeStyle=(selected===e.s||selected===e.t)?"rgba(52,73,94,.8)":"rgba(150,150,150,"+(0.15+e.confidence*0.35)+")";
    ctx.lineWidth=(selected===e.s||selected===e.t)?2:1;
    ctx.stroke();
  }}
  // Nodes
  for(let i=0;i<NODES.length;i++){{
    const n=NODES[i];
    const highlight=(selected===i)||EDGES.some(e=>(e.s===selected&&e.t===i)||(e.t===selected&&e.s===i));
    ctx.beginPath(); ctx.arc(n.x,n.y,n.r,0,Math.PI*2);
    ctx.fillStyle=highlight?n.color:(selected>=0?"rgba(200,200,200,.5)":n.color);
    ctx.globalAlpha=highlight?1:(selected>=0?0.4:0.85);
    ctx.fill();
    ctx.globalAlpha=1;
    ctx.strokeStyle=highlight?"#2c3e50":"#fff"; ctx.lineWidth=highlight?2:1; ctx.stroke();
    // Label
    if(selected<0||highlight){{
      ctx.fillStyle="#2c3e50"; ctx.font=(highlight?"bold ":"")+"11px sans-serif";
      ctx.textAlign="center"; ctx.fillText(n.label,n.x,n.y+n.r+13);
    }}
  }}
  ctx.restore();
}}

canvas.addEventListener("wheel",function(e){{
  e.preventDefault();
  const factor=e.deltaY<0?1.1:0.9;
  scale*=factor; draw();
}});
canvas.addEventListener("mousedown",function(e){{ dragging=true; dx=e.clientX; dy=e.clientY; canvas.style.cursor="grabbing"; }});
canvas.addEventListener("mousemove",function(e){{
  if(dragging){{ ox+=(e.clientX-dx)/scale; oy+=(e.clientY-dy)/scale; dx=e.clientX; dy=e.clientY; draw(); return; }}
  const mx=e.clientX/scale-ox, my=e.clientY/scale-oy;
  let hit=-1;
  for(let i=NODES.length-1;i>=0;i--){{
    const n=NODES[i],d=Math.sqrt((mx-n.x)**2+(my-n.y)**2);
    if(d<=n.r+2){{ hit=i; break; }}
  }}
  if(hit>=0){{
    const n=NODES[hit];
    tooltip.style.display="block";
    tooltip.style.left=(e.clientX+12)+"px"; tooltip.style.top=(e.clientY+12)+"px";
    tooltip.textContent=""; const b=document.createElement("b"); b.textContent=n.label; tooltip.appendChild(b);
    tooltip.appendChild(document.createTextNode(" | Tags: "+n.tags.join(", ")+" | Confidence: "+n.confidence));
    if(n.brief){{ tooltip.appendChild(document.createTextNode(" | "+n.brief)); }}
  }} else {{ tooltip.style.display="none"; }}
}});
canvas.addEventListener("mouseup",function(){{ dragging=false; canvas.style.cursor="grab"; }});
canvas.addEventListener("click",function(e){{
  const mx=e.clientX/scale-ox, my=e.clientY/scale-oy;
  let hit=-1;
  for(let i=NODES.length-1;i>=0;i--){{
    const n=NODES[i],d=Math.sqrt((mx-n.x)**2+(my-n.y)**2);
    if(d<=n.r+2){{ hit=i; break; }}
  }}
  selected=(selected===hit)?-1:hit; draw();
}});
resize();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# SVG Renderer
# ---------------------------------------------------------------------------

def render_svg(
    graph: CortexGraph,
    layout: LayoutResult,
    width: int = 960,
    height: int = 720,
    title: str = "Cortex Knowledge Graph",
) -> str:
    """Render a static SVG graph for documents/presentations."""
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}">'
    )
    parts.append('<style>'
                 'text { font-family: -apple-system, sans-serif; font-size: 10px; fill: #2c3e50; }'
                 '.edge { stroke: #bdc3c7; stroke-width: 1; }'
                 '.title { font-size: 16px; font-weight: bold; }'
                 '</style>')

    # Background
    parts.append(f'<rect width="{width}" height="{height}" fill="#f8f9fa"/>')

    # Title
    parts.append(f'<text x="12" y="28" class="title">{_html_escape(title)}</text>')

    # Build index for edge rendering
    node_id_to_idx: dict[str, int] = {}
    node_positions: list[dict] = []
    for nid, pos in layout.items():
        node = graph.get_node(nid)
        if not node:
            continue
        node_id_to_idx[nid] = len(node_positions)
        primary_tag = node.tags[0] if node.tags else "mentions"
        node_positions.append({
            "x": round(pos[0] * width, 2),
            "y": round(pos[1] * height, 2),
            "r": round(_node_radius(node.confidence), 1),
            "color": _tag_color(primary_tag),
            "label": node.label,
        })

    # Edges
    for edge in graph.edges.values():
        si = node_id_to_idx.get(edge.source_id)
        ti = node_id_to_idx.get(edge.target_id)
        if si is not None and ti is not None:
            a, b = node_positions[si], node_positions[ti]
            opacity = round(min(1.0, max(0.0, 0.2 + edge.confidence * 0.6)), 2)
            parts.append(
                f'<line x1="{a["x"]}" y1="{a["y"]}" x2="{b["x"]}" y2="{b["y"]}" '
                f'class="edge" opacity="{opacity}"/>'
            )
            # Edge label at midpoint
            mx = round((a["x"] + b["x"]) / 2, 1)
            my = round((a["y"] + b["y"]) / 2 - 4, 1)
            parts.append(
                f'<text x="{mx}" y="{my}" text-anchor="middle" '
                f'style="font-size:8px;fill:#999;">{_html_escape(edge.relation)}</text>'
            )

    # Nodes
    for np_ in node_positions:
        parts.append(
            f'<circle cx="{np_["x"]}" cy="{np_["y"]}" r="{np_["r"]}" '
            f'fill="{np_["color"]}" opacity="0.85" stroke="#fff" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{np_["x"]}" y="{round(np_["y"] + np_["r"] + 13, 1)}" '
            f'text-anchor="middle">{_html_escape(np_["label"])}</text>'
        )

    parts.append('</svg>')
    return "\n".join(parts)
