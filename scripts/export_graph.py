#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Export the axiom graph to an interactive HTML file using WebGL (sigma.js)."""

import argparse
import json
import math
from pathlib import Path

from neo4j import GraphDatabase

# Layer colors - visually distinct palette
LAYER_COLORS = {
    # C11 - warm reds/oranges
    "c11_core": "#ff6b6b",
    "c11_stdlib": "#ee5a24",
    # C++ core - purples
    "cpp_core": "#a55eea",
    "cpp_stdlib": "#8854d0",
    # C++20 - blues/teals
    "cpp20_language": "#45aaf2",
    "cpp20_stdlib": "#0984e3",
    # Libraries - greens (will generate more if needed)
    "library": "#26de81",
}

# Extra colors for additional library layers
EXTRA_COLORS = [
    "#20bf6b",  # green
    "#f7b731",  # yellow
    "#fd9644",  # orange
    "#fc5c65",  # pink
    "#4b7bec",  # blue
    "#a55eea",  # purple
    "#26de81",  # mint
    "#2bcbba",  # teal
    "#eb3b5a",  # red
    "#fa8231",  # tangerine
]


def get_layer_color(layer: str, seen_layers: dict) -> str:
    """Get color for a layer, generating new ones for unknown layers."""
    if layer in LAYER_COLORS:
        return LAYER_COLORS[layer]

    if layer not in seen_layers:
        # Assign next available color
        idx = len(seen_layers) % len(EXTRA_COLORS)
        seen_layers[layer] = EXTRA_COLORS[idx]

    return seen_layers[layer]


def fetch_graph_data(uri: str, user: str, password: str) -> dict:
    """Fetch all axioms and relationships from Neo4j."""
    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        axioms_result = session.run("""
            MATCH (a:Axiom)
            OPTIONAL MATCH (a)-[:DEFINED_IN]->(m:KModule)
            RETURN a, m.name as module_name
            ORDER BY a.layer, m.name, a.id
        """)

        axioms = []
        for record in axioms_result:
            node = dict(record["a"])
            node["module_name"] = record["module_name"] or node.get("module_name", "unknown")
            axioms.append(node)

        deps_result = session.run("""
            MATCH (a:Axiom)-[:DEPENDS_ON]->(b:Axiom)
            RETURN a.id as from_id, b.id as to_id
        """)
        depends_on = [(r["from_id"], r["to_id"]) for r in deps_result]

        stats_result = session.run("""
            MATCH (a:Axiom) WITH count(a) as axioms
            MATCH (m:KModule) WITH axioms, count(m) as modules
            MATCH ()-[r:DEPENDS_ON]->()
            RETURN axioms, modules, count(r) as deps
        """).single()
        stats = dict(stats_result) if stats_result else {}

    driver.close()

    return {
        "axioms": axioms,
        "depends_on": depends_on,
        "stats": stats
    }


def compute_layout(axioms: list, edges: list) -> dict:
    """Compute graph layout using networkx force-directed algorithm."""
    import networkx as nx

    print("  Building networkx graph...")
    graph = nx.DiGraph()

    # Add nodes with layer attribute
    for ax in axioms:
        graph.add_node(ax["id"], layer=ax.get("layer", "unknown"))

    # Add edges
    for from_id, to_id in edges:
        if graph.has_node(from_id) and graph.has_node(to_id):
            graph.add_edge(from_id, to_id)

    print(f"  Graph has {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
    print("  Computing spring layout (this may take a moment)...")

    # Use spring layout (Fruchterman-Reingold)
    # k controls optimal distance between nodes, iterations controls quality
    pos = nx.spring_layout(
        graph,
        k=2.0 / math.sqrt(graph.number_of_nodes()),  # Optimal distance
        iterations=50,  # Balance speed vs quality
        seed=42,  # Reproducible
        scale=1000,  # Scale up for better spread
    )

    print("  Layout complete.")

    # Calculate degree for sizing
    degree = dict(graph.degree())

    positions = {}
    for node_id, (x, y) in pos.items():
        size = 3 + min(degree.get(node_id, 0) * 0.5, 15)
        positions[node_id] = {"x": x, "y": y, "size": size}

    return positions


def generate_html(data: dict) -> str:
    """Generate interactive graph HTML using sigma.js (WebGL)."""

    positions = compute_layout(data["axioms"], data["depends_on"])

    # Build dynamic color map for unknown layers
    dynamic_colors = {}

    # Build nodes
    nodes = []
    for ax in data["axioms"]:
        ax_id = ax.get("id", "unknown")
        layer = ax.get("layer", "unknown")
        pos = positions.get(ax_id, {"x": 0, "y": 0, "size": 5})
        color = get_layer_color(layer, dynamic_colors)

        nodes.append({
            "id": ax_id,
            "label": ax_id[:40],
            "x": pos["x"],
            "y": pos["y"],
            "size": pos["size"],
            "color": color,
            "layer": layer,
            "module": ax.get("module_name", ""),
            "content": (ax.get("content", "") or "")[:300],
            "function": ax.get("function", "") or "",
        })

    # Build edges
    edges = []
    for i, (from_id, to_id) in enumerate(data["depends_on"]):
        edges.append({
            "id": f"e{i}",
            "source": from_id,
            "target": to_id,
        })

    layers = sorted(set(ax.get("layer", "unknown") for ax in data["axioms"]))
    stats = data["stats"]

    # Build complete color map for JS
    all_colors = {**LAYER_COLORS, **dynamic_colors}

    layer_checkboxes = "\n".join([
        f'<label class="layer-filter">'
        f'<input type="checkbox" checked data-layer="{layer}">'
        f'<span class="layer-badge" style="background:{get_layer_color(layer, dynamic_colors)}">{layer}</span>'
        f'</label>'
        for layer in layers
    ])

    nodes_json = json.dumps(nodes)
    edges_json = json.dumps(edges)
    colors_json = json.dumps(all_colors)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Axiom Knowledge Graph (WebGL)</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/sigma.js/2.4.0/sigma.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/graphology/0.25.4/graphology.umd.min.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0f;
            color: #eee;
            overflow: hidden;
        }}
        .header {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            padding: 12px 20px;
            background: rgba(10, 10, 15, 0.95);
            backdrop-filter: blur(10px);
            display: flex;
            align-items: center;
            gap: 20px;
            flex-wrap: wrap;
            z-index: 100;
            border-bottom: 1px solid #222;
        }}
        h1 {{ font-size: 18px; color: #e94560; font-weight: 600; }}
        .stats {{ display: flex; gap: 15px; font-size: 12px; color: #888; }}
        .stats strong {{ color: #4ecca3; }}
        .controls {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-left: auto;
        }}
        .search-box {{
            padding: 8px 12px;
            border: 1px solid #333;
            border-radius: 6px;
            background: #111;
            color: #eee;
            width: 200px;
            font-size: 13px;
        }}
        .search-box:focus {{ outline: none; border-color: #4ecca3; }}
        .btn {{
            padding: 8px 14px;
            border: 1px solid #333;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            background: #111;
            color: #eee;
            transition: all 0.2s;
        }}
        .btn:hover {{ background: #4ecca3; color: #000; border-color: #4ecca3; }}
        .layer-filters {{
            position: fixed;
            top: 60px;
            left: 20px;
            background: rgba(10, 10, 15, 0.9);
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #222;
            z-index: 100;
        }}
        .layer-filter {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
            cursor: pointer;
            font-size: 12px;
        }}
        .layer-filter:last-child {{ margin-bottom: 0; }}
        .layer-badge {{
            padding: 3px 10px;
            border-radius: 4px;
            color: white;
            font-size: 11px;
        }}
        #graph {{
            width: 100vw;
            height: 100vh;
            background: #0a0a0f;
        }}
        .info-panel {{
            position: fixed;
            right: 20px;
            top: 70px;
            width: 320px;
            max-height: calc(100vh - 90px);
            background: rgba(15, 15, 20, 0.95);
            border-radius: 10px;
            padding: 16px;
            display: none;
            overflow-y: auto;
            z-index: 100;
            border: 1px solid #222;
            backdrop-filter: blur(10px);
        }}
        .info-panel.visible {{ display: block; }}
        .info-panel h3 {{
            margin: 0 0 12px 0;
            color: #4ecca3;
            font-size: 13px;
            word-break: break-all;
            padding-right: 20px;
        }}
        .info-panel .close {{
            position: absolute;
            right: 12px;
            top: 12px;
            cursor: pointer;
            color: #555;
            font-size: 20px;
            line-height: 1;
        }}
        .info-panel .close:hover {{ color: #e94560; }}
        .info-field {{ margin-bottom: 12px; }}
        .info-field label {{
            display: block;
            color: #666;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }}
        .info-field .value {{ color: #ccc; font-size: 13px; line-height: 1.5; }}
        .dep-link {{
            display: inline-block;
            color: #4ecca3;
            cursor: pointer;
            font-size: 11px;
            font-family: monospace;
            padding: 2px 0;
        }}
        .dep-link:hover {{ text-decoration: underline; }}
        .filter-btn {{
            width: 100%;
            margin-bottom: 12px;
            background: #1a3a5c;
            border-color: #2d5a87;
        }}
        .filter-btn:hover {{ background: #2d5a87; color: #fff; border-color: #4ecca3; }}
        .hint {{
            position: fixed;
            bottom: 20px;
            left: 20px;
            font-size: 11px;
            color: #444;
            z-index: 100;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Axiom Knowledge Graph</h1>
        <div class="stats">
            <span><strong>{stats.get("axioms", 0):,}</strong> nodes</span>
            <span><strong>{stats.get("deps", 0):,}</strong> edges</span>
        </div>
        <div class="controls">
            <input type="text" class="search-box" id="search" placeholder="Search...">
            <button class="btn" onclick="resetView()">Reset</button>
            <button class="btn" onclick="zoomIn()">+</button>
            <button class="btn" onclick="zoomOut()">−</button>
        </div>
    </div>

    <div class="layer-filters">
        {layer_checkboxes}
    </div>

    <div id="graph"></div>

    <div class="info-panel" id="info-panel">
        <span class="close" onclick="closeInfo()">×</span>
        <h3 id="info-id"></h3>
        <button class="btn filter-btn" onclick="filterToSubtree()" title="Show only this axiom and its dependencies">Filter to subtree ↓</button>
        <div class="info-field">
            <label>Layer</label>
            <div class="value"><span class="layer-badge" id="info-layer"></span></div>
        </div>
        <div class="info-field">
            <label>Module</label>
            <div class="value" id="info-module"></div>
        </div>
        <div class="info-field" id="info-function-field" style="display:none;">
            <label>Function</label>
            <div class="value" id="info-function"></div>
        </div>
        <div class="info-field">
            <label>Content</label>
            <div class="value" id="info-content"></div>
        </div>
        <div class="info-field">
            <label>Dependencies</label>
            <div class="value" id="info-deps"></div>
        </div>
        <div class="info-field">
            <label>Dependents</label>
            <div class="value" id="info-dependents"></div>
        </div>
    </div>

    <div class="hint">Scroll to zoom • Drag to pan • Click node for details</div>

    <script>
        const nodesData = {nodes_json};
        const edgesData = {edges_json};
        const layerColors = {colors_json};

        // Build graph
        const graph = new graphology.Graph();

        nodesData.forEach(n => {{
            graph.addNode(n.id, {{
                x: n.x,
                y: n.y,
                size: n.size,
                color: n.color,
                label: n.label,
                layer: n.layer,
                module: n.module,
                content: n.content,
                function: n.function,
                hidden: false,
            }});
        }});

        edgesData.forEach(e => {{
            if (graph.hasNode(e.source) && graph.hasNode(e.target)) {{
                graph.addEdge(e.source, e.target, {{
                    color: 'rgba(100,100,100,0.15)',
                    size: 0.3,
                }});
            }}
        }});

        // Build lookup maps
        const depsMap = new Map();
        const dependentsMap = new Map();
        edgesData.forEach(e => {{
            if (!depsMap.has(e.source)) depsMap.set(e.source, []);
            depsMap.get(e.source).push(e.target);
            if (!dependentsMap.has(e.target)) dependentsMap.set(e.target, []);
            dependentsMap.get(e.target).push(e.source);
        }});

        // Track hidden nodes in a Set for reliable filtering
        const hiddenNodes = new Set();

        // Initialize sigma with reducers for visibility
        const container = document.getElementById('graph');
        const renderer = new Sigma(graph, container, {{
            renderLabels: true,
            labelRenderedSizeThreshold: 8,
            labelFont: 'monospace',
            labelSize: 10,
            labelColor: {{ color: '#888' }},
            defaultEdgeColor: 'rgba(100,100,100,0.15)',
            minCameraRatio: 0.05,
            maxCameraRatio: 5,
            nodeReducer: (node, data) => {{
                if (hiddenNodes.has(node)) {{
                    return {{ ...data, hidden: true }};
                }}
                return data;
            }},
            edgeReducer: (edge, data) => {{
                const source = graph.source(edge);
                const target = graph.target(edge);
                if (hiddenNodes.has(source) || hiddenNodes.has(target)) {{
                    return {{ ...data, hidden: true }};
                }}
                return data;
            }},
        }});

        // Helper to update visibility
        function setNodeHidden(nodeId, hidden) {{
            if (hidden) {{
                hiddenNodes.add(nodeId);
            }} else {{
                hiddenNodes.delete(nodeId);
            }}
        }}

        function showAllNodes() {{
            hiddenNodes.clear();
            renderer.refresh();
        }}

        // Click handler
        renderer.on('clickNode', ({{ node }}) => {{
            showInfo(node);
        }});

        renderer.on('clickStage', () => {{
            closeInfo();
        }});

        function showInfo(nodeId) {{
            currentSelectedNode = nodeId;
            const attrs = graph.getNodeAttributes(nodeId);

            document.getElementById('info-id').textContent = nodeId;
            document.getElementById('info-layer').textContent = attrs.layer;
            document.getElementById('info-layer').style.background = layerColors[attrs.layer] || '#666';
            document.getElementById('info-module').textContent = attrs.module || '-';
            document.getElementById('info-content').textContent = attrs.content || '-';

            const funcField = document.getElementById('info-function-field');
            if (attrs.function) {{
                document.getElementById('info-function').textContent = attrs.function;
                funcField.style.display = 'block';
            }} else {{
                funcField.style.display = 'none';
            }}

            const deps = depsMap.get(nodeId) || [];
            document.getElementById('info-deps').innerHTML = deps.length
                ? deps.slice(0, 8).map(d => `<span class="dep-link" onclick="focusNode('${{d}}')">${{d}}</span>`).join('<br>') + (deps.length > 8 ? `<br><em style="color:#555">+${{deps.length - 8}} more</em>` : '')
                : '<em style="color:#555">None</em>';

            const dependents = dependentsMap.get(nodeId) || [];
            document.getElementById('info-dependents').innerHTML = dependents.length
                ? dependents.slice(0, 8).map(d => `<span class="dep-link" onclick="focusNode('${{d}}')">${{d}}</span>`).join('<br>') + (dependents.length > 8 ? `<br><em style="color:#555">+${{dependents.length - 8}} more</em>` : '')
                : '<em style="color:#555">None</em>';

            document.getElementById('info-panel').classList.add('visible');

            // Highlight node
            graph.setNodeAttribute(nodeId, 'highlighted', true);
            renderer.refresh();
        }}

        function closeInfo() {{
            currentSelectedNode = null;
            document.getElementById('info-panel').classList.remove('visible');
            graph.forEachNode(n => graph.setNodeAttribute(n, 'highlighted', false));
            renderer.refresh();
        }}

        function focusNode(nodeId) {{
            const attrs = graph.getNodeAttributes(nodeId);
            renderer.getCamera().animate({{ x: attrs.x, y: attrs.y, ratio: 0.3 }}, {{ duration: 300 }});
            showInfo(nodeId);
        }}

        // Search
        const searchInput = document.getElementById('search');
        searchInput.addEventListener('input', (e) => {{
            const q = e.target.value.toLowerCase().trim();
            console.log('Search query:', q || '(empty)');

            hiddenNodes.clear();
            let matchCount = 0;
            graph.forEachNode((nodeId, attrs) => {{
                const match = !q || nodeId.toLowerCase().includes(q) || (attrs.content || '').toLowerCase().includes(q);
                if (match) {{
                    matchCount++;
                }} else {{
                    hiddenNodes.add(nodeId);
                }}
            }});

            console.log('Matches:', matchCount, 'Hidden:', hiddenNodes.size);
            renderer.refresh();

            // Focus on first match
            if (q && matchCount > 0) {{
                const firstMatch = graph.findNode((nodeId) => !hiddenNodes.has(nodeId));
                if (firstMatch) {{
                    const attrs = graph.getNodeAttributes(firstMatch);
                    renderer.getCamera().animate({{ x: attrs.x, y: attrs.y, ratio: 0.5 }}, {{ duration: 300 }});
                }}
            }}
        }});

        // Layer filters
        document.querySelectorAll('.layer-filter input').forEach(cb => {{
            cb.addEventListener('change', () => {{
                const checkedLayers = Array.from(document.querySelectorAll('.layer-filter input:checked'))
                    .map(i => i.dataset.layer);

                hiddenNodes.clear();
                graph.forEachNode((nodeId, attrs) => {{
                    if (!checkedLayers.includes(attrs.layer)) {{
                        hiddenNodes.add(nodeId);
                    }}
                }});

                renderer.refresh();
            }});
        }});

        function resetView() {{
            searchInput.value = '';
            document.querySelectorAll('.layer-filter input').forEach(cb => cb.checked = true);
            hiddenNodes.clear();
            renderer.getCamera().animate({{ x: 0.5, y: 0.5, ratio: 1 }}, {{ duration: 300 }});
            renderer.refresh();
            closeInfo();
        }}

        function zoomIn() {{
            const camera = renderer.getCamera();
            camera.animate({{ ratio: camera.ratio / 1.5 }}, {{ duration: 200 }});
        }}

        function zoomOut() {{
            const camera = renderer.getCamera();
            camera.animate({{ ratio: camera.ratio * 1.5 }}, {{ duration: 200 }});
        }}

        let currentSelectedNode = null;

        function filterToSubtree() {{
            if (!currentSelectedNode) {{
                console.log('No node selected');
                return;
            }}

            console.log('Filtering to subtree of:', currentSelectedNode);

            // BFS to find all dependencies (downstream)
            const subtree = new Set();
            const queue = [currentSelectedNode];

            while (queue.length > 0) {{
                const nodeId = queue.shift();
                if (subtree.has(nodeId)) continue;
                subtree.add(nodeId);

                // Add all dependencies (nodes this one depends on)
                const deps = depsMap.get(nodeId) || [];
                deps.forEach(d => {{
                    if (!subtree.has(d) && graph.hasNode(d)) queue.push(d);
                }});
            }}

            console.log('Subtree size:', subtree.size);

            // Hide all nodes not in subtree
            hiddenNodes.clear();
            graph.forEachNode((nodeId) => {{
                if (!subtree.has(nodeId)) {{
                    hiddenNodes.add(nodeId);
                }}
            }});

            console.log('Visible nodes:', subtree.size, 'Hidden:', hiddenNodes.size);
            renderer.refresh();

            // Fit camera to visible nodes
            const visibleNodes = [];
            graph.forEachNode((nodeId, attrs) => {{
                if (!hiddenNodes.has(nodeId)) visibleNodes.push({{ x: attrs.x, y: attrs.y }});
            }});

            if (visibleNodes.length > 0) {{
                const xs = visibleNodes.map(n => n.x);
                const ys = visibleNodes.map(n => n.y);
                const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
                const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
                renderer.getCamera().animate({{ x: cx, y: cy, ratio: 0.5 }}, {{ duration: 300 }});
            }}
        }}

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') closeInfo();
            if (e.key === '/' && e.target !== searchInput) {{
                e.preventDefault();
                searchInput.focus();
            }}
        }});
    </script>
</body>
</html>
'''


def main():
    parser = argparse.ArgumentParser(description="Export axiom graph to interactive HTML (WebGL)")
    parser.add_argument("-o", "--output", type=Path, default=Path("docs/graph-export.html"),
                        help="Output HTML file path")
    parser.add_argument("--uri", default="bolt://localhost:7687", help="Neo4j URI")
    parser.add_argument("--user", default="neo4j", help="Neo4j username")
    parser.add_argument("--password", default="axiompass", help="Neo4j password")

    args = parser.parse_args()

    print(f"Connecting to Neo4j at {args.uri}...")
    data = fetch_graph_data(args.uri, args.user, args.password)

    print(f"Fetched {len(data['axioms'])} axioms, {len(data['depends_on'])} dependencies")
    print("Computing layout...")

    print("Generating HTML...")
    html_content = generate_html(data)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_content)

    print(f"Exported to {args.output} ({args.output.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
