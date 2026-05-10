"""Client-side hover, layer toggles, search (injected into timeline HTML)."""

from __future__ import annotations

# Defined before ``option`` so initial ``lines`` series can use the cap.
CAP_EDGES_HELPER_JS = r"""
    const KIND_ORDER = { proto_ref: 0, iana_transport: 1, rfc_ref: 2, updates: 3, obsoletes: 4 };
    function lineKindRank(l) {
      const k = (l.dataKind || l.kind || '').trim();
      return KIND_ORDER[k] != null ? KIND_ORDER[k] : 99;
    }
    function sortLinesForCap(a, b) {
      const ra = lineKindRank(a), rb = lineKindRank(b);
      if (ra !== rb) return ra - rb;
      const c = String(a.src || '').localeCompare(String(b.src || ''));
      if (c !== 0) return c;
      return String(a.dst || '').localeCompare(String(b.dst || ''));
    }
    /** Greedy cap: each endpoint appears in at most maxPer edges (matches Python ``cap_edges_per_node_for_display``). */
    function capEdgesPerNode(ls, maxPer) {
      if (!maxPer || maxPer <= 0 || !ls || !ls.length) return ls.slice();
      const sorted = ls.slice().sort(sortLinesForCap);
      const cnt = {};
      const out = [];
      function getc(x) { return cnt[x] || 0; }
      for (const l of sorted) {
        const s = l.src, d = l.dst;
        if (!s || !d) continue;
        if (getc(s) < maxPer && getc(d) < maxPer) {
          out.push(l);
          cnt[s] = getc(s) + 1;
          cnt[d] = getc(d) + 1;
        }
      }
      return out;
    }
""".strip()

HOVER_HIGHLIGHT_JS = r"""
    /* allLinesFull is declared in timeline_html.py before option (same scope); do not redeclare. */
    const allPoints = points;

    let curPoints = allPoints;
    let curLinesFull = allLinesFull;
    let hiddenLayers = new Set();

    let pointIndexById = new Map();
    let neighborIdsById = new Map();

    function ensureSet(map, key) {
      if (!map.has(key)) map.set(key, new Set());
      return map.get(key);
    }

    function rebuildNeighborFromFull() {
      neighborIdsById = new Map();
      for (let i = 0; i < curLinesFull.length; i++) {
        const l = curLinesFull[i];
        if (!l || !l.src || !l.dst) continue;
        ensureSet(neighborIdsById, l.src).add(l.dst);
        ensureSet(neighborIdsById, l.dst).add(l.src);
      }
    }

    function rebuildPointIndex() {
      pointIndexById = new Map();
      for (let i = 0; i < curPoints.length; i++) {
        pointIndexById.set(curPoints[i].id, i);
      }
    }

    /** Non-hover view: no edges drawn (user toggles visibility via hover). */
    function baseLineData() {
      return [];
    }

    function renderFiltered() {
      curPoints = allPoints.filter(p => !hiddenLayers.has(p.layer));
      const ids = new Set(curPoints.map(p => p.id));
      curLinesFull = allLinesFull.filter(l => ids.has(l.src) && ids.has(l.dst));
      rebuildNeighborFromFull();
      rebuildPointIndex();
      lastHoverId = null;
      chart.setOption({
        series: [
          { data: baseLineData() },
          { data: curPoints },
        ]
      }, { notMerge: false, lazyUpdate: true });
    }

    const FADE_NODE_OPACITY = 0.12;
    const FADE_EDGE_OPACITY = 0.06;
    const FOCUS_NODE_OPACITY = 1.0;
    const FOCUS_EDGE_OPACITY = 0.92;
    /** Match timeline_html emphasis line width so directed arrows stay visible. */
    const FOCUS_EDGE_WIDTH = 4.2;
    const BASE_EDGE_OPACITY = 0.7;
    const BASE_EDGE_WIDTH = 1.85;

    function cloneLineForDraw(l, opacity, width) {
      const ls = Object.assign({}, l.lineStyle || {});
      ls.opacity = opacity;
      ls.width = width;
      ls.curveness = 0.0;
      return Object.assign({}, l, { lineStyle: ls });
    }

    function incidentEdgesFor(nodeId) {
      let inc = curLinesFull.filter(l => l.src === nodeId || l.dst === nodeId);
      if (MAX_EDGES_PER_NODE > 0 && inc.length > MAX_EDGES_PER_NODE) {
        inc = capEdgesPerNode(inc, MAX_EDGES_PER_NODE);
      }
      return inc;
    }

    function applyHover(id) {
      const display = incidentEdgesFor(id);

      const focus = new Set([id]);
      const ns = neighborIdsById.get(id);
      if (ns) for (const x of ns) focus.add(x);

      const styledPoints = curPoints.map(p => {
        const on = focus.has(p.id);
        const itemStyle = Object.assign({}, p.itemStyle || {});
        itemStyle.opacity = on ? FOCUS_NODE_OPACITY : FADE_NODE_OPACITY;
        const q = Object.assign({}, p, { itemStyle });
        if (LABEL_MODE === 'hover' || LABEL_MODE === 'select') {
          q.label = Object.assign({}, p.label || {});
          q.label.show = on;
          q.label.position = 'right';
          q.label.distance = 6;
          q.label.color = '#0F172A';
          q.label.backgroundColor = 'rgba(255,255,255,0.94)';
          q.label.borderColor = '#E2E8F0';
          q.label.borderWidth = 1;
          q.label.borderRadius = 6;
          q.label.padding = [2, 6];
          q.label.fontWeight = '500';
        }
        return q;
      });

      const styledLines = display.map(l => {
        const on = (l.src === id || l.dst === id);
        const op = on ? FOCUS_EDGE_OPACITY : FADE_EDGE_OPACITY;
        const w = on ? FOCUS_EDGE_WIDTH : BASE_EDGE_WIDTH;
        return cloneLineForDraw(l, op, w);
      });

      chart.setOption({
        series: [
          { data: styledLines },
          { data: styledPoints },
        ]
      }, { notMerge: false, lazyUpdate: true });
    }

    function resetHoverNoChart() {
      for (const p of curPoints) {
        if (p.itemStyle && typeof p.itemStyle === 'object') p.itemStyle.opacity = 1.0;
        if (p.label && typeof p.label === 'object' && (LABEL_MODE === 'hover' || LABEL_MODE === 'select')) {
          delete p.label.show;
        }
      }
    }

    function resetHover() {
      resetHoverNoChart();
      chart.setOption({
        series: [
          { data: [] },
          { data: curPoints },
        ]
      }, { notMerge: false, lazyUpdate: true });
    }

    let lastHoverId = null;
    let rafPending = false;
    chart.on('mouseover', function (params) {
      if (!params || params.seriesType !== 'scatter' || !params.data) return;
      const hid = params.data.id;
      if (!hid || hid === lastHoverId) return;
      lastHoverId = hid;
      if (rafPending) return;
      rafPending = true;
      requestAnimationFrame(() => {
        rafPending = false;
        if (lastHoverId) applyHover(lastHoverId);
      });
    });
    chart.on('mouseout', function (params) {
      if (!params || params.seriesType !== 'scatter') return;
      lastHoverId = null;
      resetHover();
    });

    for (const btn of document.querySelectorAll('.layer-chip')) {
      btn.addEventListener('click', () => {
        const layer = btn.getAttribute('data-layer');
        if (!layer) return;
        if (hiddenLayers.has(layer)) {
          hiddenLayers.delete(layer);
          btn.classList.remove('is-off');
          btn.setAttribute('aria-pressed', 'true');
        } else {
          hiddenLayers.add(layer);
          btn.classList.add('is-off');
          btn.setAttribute('aria-pressed', 'false');
        }
        renderFiltered();
      });
    }

    renderFiltered();

    const searchBox = document.getElementById('searchBox');
    function norm(s) { return String(s || '').trim().toLowerCase(); }

    function findBestMatch(query) {
      const q = norm(query);
      if (!q) return null;
      for (const p of allPoints) {
        if (norm(p.id) === q || norm(p.name) === q) return p;
      }
      for (const p of allPoints) {
        if (norm(p.name).startsWith(q) || norm(p.id).startsWith(q)) return p;
      }
      for (const p of allPoints) {
        if (norm(p.name).includes(q) || norm(p.id).includes(q)) return p;
      }
      return null;
    }

    function ensureLayerVisible(layer) {
      if (!layer) return;
      if (!hiddenLayers.has(layer)) return;
      hiddenLayers.delete(layer);
      const btn = document.querySelector('.layer-chip[data-layer="' + layer + '"]');
      if (btn) {
        btn.classList.remove('is-off');
        btn.setAttribute('aria-pressed', 'true');
      }
      renderFiltered();
    }

    function focusNodeById(id) {
      if (!id) return;
      const idx = pointIndexById.get(id);
      if (typeof idx !== 'number') return;
      applyHover(id);
      chart.dispatchAction({ type: 'showTip', seriesIndex: 1, dataIndex: idx });
    }

    function focusByQuery(q) {
      const p = findBestMatch(q);
      if (!p) return false;
      ensureLayerVisible(p.layer);
      focusNodeById(p.id);
      return true;
    }

    if (searchBox) {
      searchBox.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter') return;
        const ok = focusByQuery(searchBox.value);
        if (!ok) {
          searchBox.style.borderColor = '#EF4444';
          setTimeout(() => { searchBox.style.borderColor = ''; }, 500);
        }
      });
      searchBox.addEventListener('focus', () => {
        lastHoverId = null;
        resetHover();
      });
    }
""".strip()
