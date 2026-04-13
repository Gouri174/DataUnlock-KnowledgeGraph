"""
generate_static_graph.py
========================
Generates a fully self-contained graph.html from NAS_ALL_COMBINED.csv.
No Flask proxy needed. Works offline. Safe to upload to GitHub Pages.

Run:
    python generate_static_graph.py
    python generate_static_graph.py --obs 5 --limit 50
"""

import csv
import json
import re
import os
import sys
import argparse
from collections import defaultdict

# ---------------------------------------------------------------------------
# Build graph data from CSV
# ---------------------------------------------------------------------------

def normalize(text):
    text = re.sub(r'[^a-zA-Z0-9 ]', '', str(text or ''))
    return "".join(w.capitalize() for w in text.split())

def build_dcid(row):
    indicator = normalize(row.get("indicator", ""))
    if not indicator:
        return None, None, ""
    industry  = normalize(row.get("industry", ""))
    constant  = row.get("constant_price", "").strip()
    current   = row.get("current_price",  "").strip()
    if constant and constant not in ("", "None", "null"):
        price_type = "RealValue"
        try: value = float(constant)
        except: value = None
    elif current and current not in ("", "None", "null"):
        price_type = "Nominal"
        try: value = float(current)
        except: value = None
    else:
        return None, None, ""
    dcid = f"{price_type}_Amount_EconomicActivity_{indicator}"
    if industry:
        dcid += f"_{industry}"
    return dcid, value, price_type

def load_graph(csv_path, max_dcids=None, max_obs=5):
    rows = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    graph = {}
    for row in rows:
        dcid, value, price_type = build_dcid(row)
        if not dcid or value is None:
            continue
        if dcid not in graph:
            graph[dcid] = {
                "indicator":    row.get("indicator", ""),
                "industry":     row.get("industry",  ""),
                "price_type":   price_type,
                "observations": [],
            }
        graph[dcid]["observations"].append({
            "year":     row.get("year", ""),
            "value":    round(value, 2),
            "revision": row.get("revision", ""),
            "quarter":  row.get("quarter", "") or "",
        })

    if max_dcids:
        graph = dict(list(graph.items())[:max_dcids])

    for dcid in graph:
        graph[dcid]["observations"] = graph[dcid]["observations"][:max_obs]

    return graph

# ---------------------------------------------------------------------------
# Convert to vis.js nodes + edges
# ---------------------------------------------------------------------------

COLOR = {
    "Measure":     {"background": "#1D9E75", "border": "#085041", "highlight": {"background": "#3fb950", "border": "#085041"}},
    "Sector":      {"background": "#BA7517", "border": "#633806", "highlight": {"background": "#d29922", "border": "#633806"}},
    "PriceType":   {"background": "#7F77DD", "border": "#3C3489", "highlight": {"background": "#9d94ee", "border": "#3C3489"}},
    "StatVar":     {"background": "#185FA5", "border": "#0C447C", "highlight": {"background": "#378add", "border": "#0C447C"}},
    "Observation": {"background": "#6b7280", "border": "#374151", "highlight": {"background": "#9ca3af", "border": "#374151"}},
}

def build_vis_data(graph, max_obs):
    nodes = []
    edges = []
    seen  = set()
    nid   = [0]

    id_map = {}

    def add_node(key, label, group, title="", size=16):
        if key in id_map:
            return id_map[key]
        nid[0] += 1
        i = nid[0]
        id_map[key] = i
        seen.add(key)
        nodes.append({
            "id":    i,
            "label": label[:30] + ("…" if len(label) > 30 else ""),
            "title": title or label,
            "color": COLOR[group],
            "size":  size,
            "group": group,
            "font":  {"color": "#e6edf3", "size": 11},
        })
        return i

    def add_edge(src, tgt, label):
        edges.append({"from": src, "to": tgt, "label": label,
                       "arrows": "to", "color": {"color": "#4b5563", "highlight": "#9ca3af"},
                       "font": {"color": "#6b7280", "size": 9, "strokeWidth": 0}})

    for dcid, meta in graph.items():
        indicator  = meta["indicator"]
        industry   = meta["industry"]
        price_type = meta["price_type"]

        # Measure node
        m_id = add_node(f"M:{indicator}", indicator, "Measure",
                        f"Measure: {indicator}", size=24)

        # Sector node (only if present)
        s_id = None
        if industry:
            s_id = add_node(f"S:{industry}", industry, "Sector",
                            f"Economic sector: {industry}", size=18)

        # PriceType node
        p_id = add_node(f"P:{price_type}", price_type, "PriceType",
                        f"Price type: {price_type}", size=14)

        # DCID node
        short = dcid if len(dcid) <= 40 else dcid[:38] + "…"
        d_id = add_node(
            f"D:{dcid}", short, "StatVar",
            f"DCID: {dcid}\nType: StatisticalVariable\nPrice: {price_type}\nIndicator: {indicator}" +
            (f"\nSector: {industry}" if industry else ""),
            size=16
        )

        add_edge(d_id, m_id, "MEASURES")
        add_edge(d_id, p_id, "PRICE_TYPE")
        if s_id is not None:
            add_edge(d_id, s_id, "BELONGS_TO")

        # Observation nodes
        for obs in meta["observations"][:max_obs]:
            yr  = obs["year"]
            val = obs["value"]
            qtr = obs["quarter"]
            rev = obs["revision"]
            time_label = f"{yr} Q{qtr}" if qtr else yr
            obs_key = f"O:{dcid}:{time_label}"
            o_id = add_node(
                obs_key, time_label, "Observation",
                f"Year: {time_label}\nValue: ₹{val:,.2f} Cr\nRevision: {rev}",
                size=8
            )
            add_edge(d_id, o_id, "HAS_OBS")

    return nodes, edges

# ---------------------------------------------------------------------------
# Generate self-contained HTML
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>MOSPI NAS — Knowledge Graph</title>
<script src="https://cdn.jsdelivr.net/npm/vis-network@9.1.9/dist/vis-network.min.js"></script>
<link  href="https://cdn.jsdelivr.net/npm/vis-network@9.1.9/dist/dist/vis-network.min.css" rel="stylesheet"/>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', sans-serif; background: #0d1117; color: #e6edf3; height: 100vh; display: flex; flex-direction: column; }
  header { padding: 12px 20px; border-bottom: 1px solid #21262d; display: flex; align-items: center; gap: 16px; background: #161b22; }
  header h1 { font-size: 15px; font-weight: 600; }
  header span { font-size: 12px; color: #8b949e; background: #21262d; padding: 3px 8px; border-radius: 4px; }
  .controls { padding: 10px 20px; background: #161b22; border-bottom: 1px solid #21262d; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  .controls label { font-size: 12px; color: #8b949e; }
  .controls select, .controls input[type=text] { background: #21262d; border: 1px solid #30363d; color: #e6edf3; padding: 5px 10px; border-radius: 6px; font-size: 12px; }
  .controls button { background: #21262d; border: 1px solid #30363d; color: #e6edf3; padding: 5px 14px; border-radius: 6px; font-size: 12px; cursor: pointer; }
  .controls button:hover { background: #30363d; }
  #graph-container { flex: 1; position: relative; }
  #graph { width: 100%; height: 100%; }
  .legend { position: absolute; top: 12px; left: 12px; background: rgba(22,27,34,0.92); border: 1px solid #30363d; border-radius: 8px; padding: 12px 16px; font-size: 12px; }
  .leg { display: flex; align-items: center; gap: 7px; margin-bottom: 5px; }
  .leg:last-child { margin-bottom: 0; }
  .leg-dot { width: 10px; height: 10px; border-radius: 50%; }
  .tooltip-panel { position: absolute; top: 12px; right: 12px; background: rgba(22,27,34,0.95); border: 1px solid #30363d; border-radius: 8px; padding: 14px 16px; font-size: 12px; max-width: 280px; display: none; line-height: 1.7; }
  .tooltip-panel.show { display: block; }
  .tooltip-panel strong { font-size: 13px; color: #58a6ff; display: block; margin-bottom: 6px; }
  .stats { position: absolute; bottom: 12px; left: 12px; background: rgba(22,27,34,0.85); border: 1px solid #30363d; border-radius: 6px; padding: 8px 12px; font-size: 11px; color: #8b949e; }
</style>
</head>
<body>

<header>
  <h1>MOSPI NAS — Knowledge Graph</h1>
  <span>Source: indiadatacommons.org</span>
  <span id="stat-nodes" style="margin-left:auto"></span>
  <span id="stat-edges"></span>
</header>

<div class="controls">
  <label>Filter by indicator</label>
  <select id="filter-indicator" onchange="filterGraph()">
    <option value="">All indicators</option>
  </select>
  <label>Filter by sector</label>
  <select id="filter-sector" onchange="filterGraph()">
    <option value="">All sectors</option>
  </select>
  <label>Filter by price type</label>
  <select id="filter-price" onchange="filterGraph()">
    <option value="">All</option>
    <option value="RealValue">RealValue (constant)</option>
    <option value="Nominal">Nominal (current)</option>
  </select>
  <button onclick="resetFilter()">Reset</button>
  <button onclick="network.fit()">Fit view</button>
</div>

<div id="graph-container">
  <div id="graph"></div>

  <div class="legend">
    <div style="font-size:10px;color:#8b949e;margin-bottom:8px;letter-spacing:0.5px">NODE TYPES</div>
    <div class="leg"><div class="leg-dot" style="background:#1D9E75"></div>Measure (indicator)</div>
    <div class="leg"><div class="leg-dot" style="background:#BA7517"></div>Economic sector</div>
    <div class="leg"><div class="leg-dot" style="background:#7F77DD"></div>Price type</div>
    <div class="leg"><div class="leg-dot" style="background:#185FA5"></div>DCID (StatVar)</div>
    <div class="leg"><div class="leg-dot" style="background:#6b7280"></div>Observation (year+value)</div>
  </div>

  <div class="tooltip-panel" id="tooltip-panel">
    <strong id="tt-title"></strong>
    <div id="tt-body"></div>
  </div>

  <div class="stats" id="stats-bar"></div>
</div>

<script>
const ALL_NODES = __NODES__;
const ALL_EDGES = __EDGES__;

const nodeDataset = new vis.DataSet(ALL_NODES);
const edgeDataset = new vis.DataSet(ALL_EDGES);

const container = document.getElementById('graph');
const options = {
  physics: {
    solver: 'barnesHut',
    barnesHut: { gravitationalConstant: -6000, centralGravity: 0.3, springLength: 140, springConstant: 0.04, damping: 0.09 },
    maxVelocity: 50, minVelocity: 0.1,
  },
  edges: { smooth: { type: 'dynamic' }, width: 1 },
  nodes: { shape: 'dot', borderWidth: 1.5, shadow: false },
  interaction: { hover: true, tooltipDelay: 80, navigationButtons: true, keyboard: true },
  layout: { improvedLayout: false },
};

const network = new vis.Network(container, { nodes: nodeDataset, edges: edgeDataset }, options);

// Stats
document.getElementById('stat-nodes').textContent = ALL_NODES.length + ' nodes';
document.getElementById('stat-edges').textContent = ALL_EDGES.length + ' edges';

// Tooltip on click
network.on('click', params => {
  const panel = document.getElementById('tooltip-panel');
  if (params.nodes.length > 0) {
    const node = nodeDataset.get(params.nodes[0]);
    document.getElementById('tt-title').textContent = node.label;
    document.getElementById('tt-body').innerHTML = node.title.replace(/\n/g, '<br>');
    panel.classList.add('show');
  } else {
    panel.classList.remove('show');
  }
});

// Populate filter dropdowns
const indicators = [...new Set(ALL_NODES.filter(n=>n.group==='Measure').map(n=>n.title))].sort();
const sectors    = [...new Set(ALL_NODES.filter(n=>n.group==='Sector').map(n=>n.title))].sort();
const indSel  = document.getElementById('filter-indicator');
const secSel  = document.getElementById('filter-sector');
indicators.forEach(v => { const o=document.createElement('option'); o.value=v; o.textContent=v; indSel.appendChild(o); });
sectors.forEach(v    => { const o=document.createElement('option'); o.value=v; o.textContent=v; secSel.appendChild(o); });

function filterGraph() {
  const ind   = indSel.value;
  const sec   = secSel.value;
  const price = document.getElementById('filter-price').value;

  const visibleDCIDs = new Set(
    ALL_NODES
      .filter(n => n.group === 'StatVar')
      .filter(n => {
        if (ind && !n.title.includes(ind)) return false;
        if (sec && !n.title.includes(sec)) return false;
        if (price && !n.title.includes(price)) return false;
        return true;
      })
      .map(n => n.id)
  );

  const connectedIds = new Set();
  ALL_EDGES.forEach(e => {
    if (visibleDCIDs.has(e.from)) { connectedIds.add(e.from); connectedIds.add(e.to); }
  });
  if (!ind && !sec && !price) {
    nodeDataset.update(ALL_NODES.map(n => ({ id: n.id, hidden: false })));
    edgeDataset.update(ALL_EDGES.map(e => ({ id: e.id || (e.from+'_'+e.to), hidden: false })));
    return;
  }
  nodeDataset.update(ALL_NODES.map(n => ({ id: n.id, hidden: !connectedIds.has(n.id) })));
}

function resetFilter() {
  indSel.value = '';
  document.getElementById('filter-sector').value = '';
  document.getElementById('filter-price').value = '';
  nodeDataset.update(ALL_NODES.map(n => ({ id: n.id, hidden: false })));
}

network.on('stabilizationProgress', p => {
  document.getElementById('stats-bar').textContent = 'Stabilising… ' + Math.round(p.iterations/p.total*100) + '%';
});
network.on('stabilizationIterationsDone', () => {
  document.getElementById('stats-bar').textContent = ALL_NODES.length + ' nodes · ' + ALL_EDGES.length + ' edges · Click any node for details';
});
</script>
</body>
</html>
"""

def generate(csv_path, output, max_dcids, max_obs):
    print(f"Reading {csv_path} ...")
    graph = load_graph(csv_path, max_dcids=max_dcids, max_obs=max_obs)
    print(f"DCIDs: {len(graph)}")

    nodes, edges = build_vis_data(graph, max_obs)
    print(f"Nodes: {len(nodes)}  Edges: {len(edges)}")

    # Assign stable edge IDs
    for i, e in enumerate(edges):
        e["id"] = i + 1

    html = HTML_TEMPLATE.replace("__NODES__", json.dumps(nodes, ensure_ascii=False))
    html = html.replace("__EDGES__", json.dumps(edges, ensure_ascii=False))

    with open(output, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(output) / 1024
    print(f"Saved: {output}  ({size_kb:.0f} KB)")
    print(f"Upload this file to GitHub → it will work without any server.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default="mospi_nas_output/NAS_ALL_COMBINED.csv")
    parser.add_argument("--output", default="graph.html")
    parser.add_argument("--limit",  type=int, default=None, help="Max DCIDs (None = all)")
    parser.add_argument("--obs",    type=int, default=5,    help="Max observations per DCID")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"File not found: {args.input}")

    generate(args.input, args.output, args.limit, args.obs)

if __name__ == "__main__":
    main()
