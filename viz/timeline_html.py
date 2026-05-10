"""Static HTML/CSS/JS skeleton for ``timeline_graph.html``."""

from __future__ import annotations

import json

from timeline_hover import CAP_EDGES_HELPER_JS, HOVER_HIGHLIGHT_JS


def build_timeline_html(
    *,
    nodes_json: str,
    lines_json: str,
    layer_json: str,
    node_legend_html: str,
    edge_legend_html: str,
    edge_legend_title: str,
    hint_edges: str,
    hint_rfc: str,
    edge_cap_hint: str,
    rfc_click: str,
    label_mode: str,
    max_edges_per_node: int,
) -> str:
    rf = json.dumps(rfc_click)
    lm = json.dumps(label_mode)
    me = json.dumps(int(max_edges_per_node))
    cap_html = (" " + edge_cap_hint) if edge_cap_hint.strip() else ""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>IANA 知名端口 · 协议时间线与依赖 · ECharts</title>
  <style>
    html {{ height: 100%; }}
    body {{
      height: 100%;
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
      background: linear-gradient(165deg, #f8fafc 0%, #eef2ff 45%, #f1f5f9 100%);
      box-sizing: border-box;
      color: #0f172a;
    }}
    .page {{ padding: 14px 16px 22px; max-width: 1920px; margin: 0 auto; }}
    #main {{
      width: 100%;
      height: calc(100vh - 148px);
      min-height: 420px;
      border-radius: 14px;
      background: rgba(255,255,255,0.72);
      box-shadow: 0 4px 24px rgba(15, 23, 42, 0.06), inset 0 1px 0 rgba(255,255,255,0.95);
      border: 1px solid rgba(226,232,240,0.9);
      backdrop-filter: blur(10px);
    }}
    .bar {{
      display: flex;
      gap: 14px;
      align-items: center;
      padding: 8px 4px 12px;
      flex-wrap: wrap;
    }}
    .legendgroup {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .spacer {{ flex: 1; min-width: 8px; }}
    .search {{ display: flex; align-items: center; gap: 8px; }}
    .search input {{
      width: min(380px, 58vw);
      padding: 8px 12px;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      outline: none;
      font-size: 13px;
      color: #0f172a;
      background: #fff;
      transition: border-color .15s, box-shadow .15s;
    }}
    .search input:focus {{ border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,0.18); }}
    .search .kbd {{
      font-size: 11px;
      color: #64748b;
      padding: 2px 6px;
      border-radius: 6px;
      background: rgba(248,250,252,0.95);
      border: 1px solid #e2e8f0;
    }}
    .hint {{
      padding: 0 4px 10px;
      color: #64748b;
      font-size: 12.5px;
      line-height: 1.5;
    }}
    .legendtitle {{ color: #0f172a; font-weight: 700; font-size: 12px; margin-right: 4px; letter-spacing: 0.02em; }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: #334155;
    }}
    .swatch {{ width: 20px; height: 0; border-top: 3px solid; border-radius: 2px; }}
    button.chip {{
      background: rgba(255,255,255,0.92);
      border: 1px solid #e2e8f0;
      border-radius: 999px;
      padding: 5px 10px;
      cursor: pointer;
      transition: transform .06s ease, border-color .15s, box-shadow .15s;
    }}
    button.chip:hover {{
      border-color: #cbd5e1;
      box-shadow: 0 1px 6px rgba(15,23,42,0.06);
    }}
    button.chip:active {{ transform: translateY(0.5px); }}
    button.chip.is-off {{ opacity: 0.42; text-decoration: line-through; }}
  </style>
</head>
<body>
  <div class="page">
    <div class="bar">
      <div class="legendgroup">
        <span class="legendtitle">节点层</span>
        {node_legend_html}
      </div>
      <div class="legendgroup">
        <span class="legendtitle">{edge_legend_title}</span>
        {edge_legend_html}
      </div>
      <div class="spacer"></div>
      <div class="search">
        <input id="searchBox" type="text" placeholder="搜索协议 ID / 标签，回车定位" autocomplete="off" />
        <span class="kbd">Enter</span>
      </div>
    </div>
    <div class="hint">横轴 earliest RFC 索引日期 · 纵轴分层（示意）。图为<b>有向依赖</b>（箭头由「源→目标」一端指向另一端，与 CSV 列 <code>src</code>/<code>dst</code> 一致）。<b>缩放/拖动</b>可用；<b>连线默认隐藏</b>，悬停节点时显示与该节点相关的边并淡化其余节点；悬停边上的箭头指向依赖方向。{hint_edges}{cap_html}{hint_rfc}</div>
    <div id="main"></div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <script>
    const points = {nodes_json};
    const lines = {lines_json};
    const allLinesFull = lines;
    const MAX_EDGES_PER_NODE = {me};
    const layers = {layer_json};
    const RFC_CLICK = {rf};
    const LABEL_MODE = {lm};

    {CAP_EDGES_HELPER_JS}

    const chart = echarts.init(document.getElementById('main'), null, {{ renderer: 'canvas' }});
    const option = {{
      backgroundColor: 'transparent',
      textStyle: {{ fontFamily: 'Segoe UI, PingFang SC, Microsoft YaHei, sans-serif' }},
      tooltip: {{
        trigger: 'item',
        appendToBody: true,
        borderColor: '#e2e8f0',
        borderWidth: 1,
        formatter: function (param) {{
          const d = param.data || {{}};
          if (param.seriesType === 'scatter') {{
            const dsc = (d.description && String(d.description).trim())
              ? '<br/><span style=\"color:#64748b\">description</span><br/>'
                + escapeHtml(String(d.description).trim()).replace(/\\n/g, '<br/>')
              : '';
            return '<div style=\"max-width:420px;line-height:1.45\">' +
              '<b>' + escapeHtml(String(d.name || d.id || '-')) + '</b><br/>' +
              '<span style=\"color:#64748b\">birth</span> ' + escapeHtml(String(d.birth_date || '-')) + '<br/>' +
              '<span style=\"color:#64748b\">layer</span> ' + escapeHtml(String(d.layer || '-')) + '<br/>' +
              '<span style=\"color:#64748b\">defining RFCs</span> ' + escapeHtml(String(d.defining_rfcs || '-')) + '<br/>' +
              '<span style=\"color:#64748b\">degree</span> ' + (d.degree ?? 0) +
              dsc +
              '</div>';
          }}
          if (param.seriesType === 'lines') {{
            const d = param.data || {{}};
            const head = d.layerLink || d.kind || '-';
            const dk = d.dataKind
              ? '<br/><span style=\"color:#64748b\">数据边类</span> ' + escapeHtml(String(d.dataKind))
              : '';
            return '<b>' + escapeHtml(String(head)) + '</b>' + dk + '<br/>' +
              escapeHtml(String(d.src||'')) + ' → ' + escapeHtml(String(d.dst||''));
          }}
          return '';
        }}
      }},
      animationDurationUpdate: 220,
      xAxis: {{
        type: 'time',
        name: 'RFC 索引日期（最早定义 RFC）',
        nameGap: 28,
        nameTextStyle: {{ color: '#64748b', fontSize: 12 }},
        axisLine: {{ lineStyle: {{ color: '#cbd5e1' }} }},
        axisLabel: {{ color: '#64748b', hideOverlap: true }},
        splitLine: {{ lineStyle: {{ color: 'rgba(226,232,240,0.65)', type: 'dashed' }} }}
      }},
      yAxis: {{
        type: 'category',
        data: layers,
        name: '层次（示意）',
        nameTextStyle: {{ color: '#64748b', fontSize: 12 }},
        axisLabel: {{ color: '#475569', fontWeight: 600 }},
        axisLine: {{ lineStyle: {{ color: '#cbd5e1' }} }},
        inverse: true
      }},
      grid: {{
        left: '3%',
        right: '4%',
        top: '8%',
        bottom: '13%',
        containLabel: true
      }},
      dataZoom: [
        {{ type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: true, filterMode: 'none' }},
        {{ type: 'slider', xAxisIndex: 0, height: 22, bottom: 16, filterMode: 'none',
           borderColor: '#e2e8f0', handleStyle: {{ color: '#6366f1' }}, textStyle: {{ color: '#64748b' }} }}
      ],
      series: [
        {{
          name: 'edges',
          type: 'lines',
          coordinateSystem: 'cartesian2d',
          /** Draw above scatter so arrowheads stay visible; silent keeps hit-testing on nodes. */
          z: 12,
          zlevel: 1,
          silent: true,
          polyline: false,
          /** Directed edges: arrow only at coords[1] (dst); keep start clean for readability. */
          symbol: ['none', 'arrow'],
          symbolSize: [0, 18],
          lineStyle: {{ width: 1.85, opacity: 0.7, cap: 'round', join: 'round' }},
          emphasis: {{
            disabled: false,
            lineStyle: {{ width: 4, opacity: 0.95 }}
          }},
          data: []
        }},
        {{
          name: 'nodes',
          type: 'scatter',
          coordinateSystem: 'cartesian2d',
          z: 3,
          zlevel: 0,
          symbolSize: function (val, params) {{
            return params.data?.symbolSize || 12;
          }},
          label: {{
            show: (LABEL_MODE === 'all'),
            formatter: function(p) {{ return p.data?.name || p.data?.id || ''; }},
            fontSize: 11,
            position: 'right',
            distance: 6,
            color: '#0f172a',
            backgroundColor: 'rgba(255,255,255,0.94)',
            borderColor: '#e2e8f0',
            borderWidth: 1,
            borderRadius: 6,
            padding: [2, 6]
          }},
          labelLayout: {{ hideOverlap: true, moveOverlap: 'shiftY' }},
          emphasis: {{
            label: {{ show: (LABEL_MODE === 'hover') }},
            scale: 1.12,
            itemStyle: {{ borderWidth: 2, borderColor: '#0f172a', shadowBlur: 12 }}
          }},
          data: points
        }}
      ]
    }};

    function escapeHtml(s) {{
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;');
    }}

    chart.setOption(option);

    function parseRfcNumbers(defining_rfcs) {{
      if (!defining_rfcs) return [];
      const parts = String(defining_rfcs).split(/[,\\s]+/).filter(Boolean);
      const nums = [];
      for (const p of parts) {{
        const m = p.match(/RFC\\s*([0-9]{{1,5}})/i);
        if (m) nums.push(m[1]);
      }}
      return Array.from(new Set(nums));
    }}

    chart.on('click', function (params) {{
      if (!params || params.seriesType !== 'scatter' || !params.data) return;
      if (RFC_CLICK === 'none') return;
      const ev = params.event?.event;
      if (!ev || !(ev.ctrlKey || ev.metaKey)) return;
      const rfcs = parseRfcNumbers(params.data.defining_rfcs);
      if (!rfcs.length) return;
      const openOne = (num) => window.open('https://www.rfc-editor.org/rfc/rfc' + num + '.html', '_blank');
      if (RFC_CLICK === 'all') {{
        for (const num of rfcs) openOne(num);
      }} else {{
        openOne(rfcs[0]);
      }}
    }});

    {HOVER_HIGHLIGHT_JS}

    window.addEventListener('resize', () => chart.resize());
  </script>
</body>
</html>"""
