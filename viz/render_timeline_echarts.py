#!/usr/bin/env python3
"""
Timeline + dependency graph (ECharts) from nodes.csv / edges.csv.

模块划分（可读性）：

- ``timeline_core``: 路径、基础锚点、分层启发式与边层次配色常量
- ``timeline_data``: CSV 读写/合并、IANA 知名端口→传输层边
- ``timeline_hover``: 浏览器端悬停/搜索脚本片段
- ``timeline_html``: 整页 HTML 模板

CLI 入口即本文件；从项目根或 ``viz/`` 下执行均可::

  python viz/render_timeline_echarts.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import timeline_core as tc
from timeline_core import (
    APP_EDGES_CSV,
    APP_NODES_CSV,
    DEFAULT_NETWORK_EDGES_CSV,
    DEFAULT_NETWORK_NODES_CSV,
    IANA_PORTS_CSV,
    TIMELINE_HTML,
    VIZ_DIR,
)
from timeline_data import (
    collect_iana_transport_edges,
    merge_edge_tables,
    merge_network_nodes_into,
    parse_iso_date,
    read_edges,
    read_nodes,
)
from timeline_html import build_timeline_html

PROJECT_ROOT = tc.PROJECT_ROOT


# --- CLI ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Render timeline + dependency edges in one ECharts chart.")
    ap.add_argument("--nodes", type=Path, default=APP_NODES_CSV)
    ap.add_argument(
        "--edges",
        type=Path,
        default=APP_EDGES_CSV,
        help="Primary graph edges (application RFC graph)",
    )
    ap.add_argument("--network-nodes", type=Path, default=DEFAULT_NETWORK_NODES_CSV)
    ap.add_argument("--network-edges", type=Path, default=DEFAULT_NETWORK_EDGES_CSV)
    ap.add_argument(
        "--no-merge-network",
        action="store_true",
        help="Only use --nodes/--edges",
    )
    ap.add_argument("--out", type=Path, default=TIMELINE_HTML)
    ap.add_argument("--edge-kinds", default="proto_ref", help="Comma-separated CSV edge kinds to keep")
    ap.add_argument("--max-nodes", type=int, default=300)
    ap.add_argument("--node-size", type=int, default=0, help="Fixed px scatter; 0 = auto")
    ap.add_argument(
        "--foundation",
        action="store_true",
        help="Merge synthetic IPv4/TCP/… anchor rows into nodes_map",
    )
    ap.add_argument(
        "--iana-ports-csv",
        type=Path,
        default=IANA_PORTS_CSV,
    )
    ap.add_argument("--no-iana-transport-edges", action="store_true")
    ap.add_argument("--rfc-click", choices=["none", "first", "all"], default="first")
    ap.add_argument("--label-mode", choices=["all", "hover", "select", "none"], default="hover")
    ap.add_argument("--include-unknown-birth", action="store_true")
    ap.add_argument(
        "--max-edges-per-node",
        type=int,
        default=0,
        help="When >0, cap how many edges are drawn per hovered node (default 0 = show all incident edges on hover).",
    )
    return ap.parse_args(argv)


# --- Load & merge CSVs --------------------------------------------------------------

def merge_network_dataset_if_present(
    args: argparse.Namespace,
    nodes_map: Dict[str, Dict[str, str]],
    app_edges: List[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], bool]:
    """Return combined edge table and whether network CSVs were merged."""

    if (
        bool(args.no_merge_network)
        or not args.network_nodes.is_file()
        or not args.network_edges.is_file()
    ):
        if not bool(args.no_merge_network):
            missing = []
            if not args.network_nodes.is_file():
                missing.append("nodes")
            if not args.network_edges.is_file():
                missing.append("edges")
            print(
                f"Note: network merge skipped (missing {' and '.join(missing)}): {args.network_nodes.parent}",
                flush=True,
            )
        return app_edges, False

    net_nodes = read_nodes(args.network_nodes)
    net_edges_tbl = read_edges(args.network_edges)
    merge_network_nodes_into(nodes_map, net_nodes)
    combined = merge_edge_tables(app_edges, net_edges_tbl)
    print(
        f"Merged network dataset from {args.network_nodes.parent}: "
        f"net nodes={len(net_nodes)}, edges {len(app_edges)}+{len(net_edges_tbl)} -> {len(combined)} unique rows",
        flush=True,
    )
    return combined, True


# --- Edges filtering + IANA ---------------------------------------------------------

def csv_edges_respecting_nodes(
    edges: List[Dict[str, str]],
    nodes_map: Dict[str, Dict[str, str]],
    wanted_kinds: Set[str],
) -> List[Dict[str, str]]:
    filt: List[Dict[str, str]] = []
    for e in edges:
        kind = (e.get("kind") or "").strip()
        src = (e.get("src") or "").strip()
        dst = (e.get("dst") or "").strip()
        if not kind or not src or not dst:
            continue
        if kind not in wanted_kinds:
            continue
        if src not in nodes_map or dst not in nodes_map:
            continue
        filt.append({"src": src, "dst": dst, "kind": kind})
    return filt


def attach_iana_transport_edges(
    args: argparse.Namespace,
    nodes_map: Dict[str, Dict[str, str]],
) -> List[Dict[str, str]]:
    if bool(args.no_iana_transport_edges):
        return []
    iana_edges = collect_iana_transport_edges(args.iana_ports_csv, nodes_map)
    if iana_edges:
        print(
            f"IANA transport links: {len(iana_edges)} unique service->TCP/UDP/SCTP/DCCP edges "
            f"from {args.iana_ports_csv}",
            flush=True,
        )
    elif args.iana_ports_csv.is_file():
        need = {"TCP", "UDP", "SCTP", "DCCP"}
        if not (need & set(nodes_map.keys())):
            print(
                "IANA port CSV present but no TCP/UDP/SCTP/DCCP nodes in graph; "
                "merge output/network_graph nodes or use --foundation to add transports.",
                flush=True,
            )
    return iana_edges


def degree_counter(graph_edges: List[Dict[str, str]]) -> Counter[str]:
    deg: Counter[str] = Counter()
    for e in graph_edges:
        deg[e["src"]] += 1
        deg[e["dst"]] += 1
    return deg


# --- Node caps (Top-N + T/N preserves + foundations) -------------------------------

def choose_keep_ids(
    deg: Counter[str],
    *,
    nodes_map: Dict[str, Dict[str, str]],
    max_nodes: int,
    stack_transport_network_bands: bool,
    foundation_active: bool,
) -> Tuple[List[str], Set[str]]:
    keep_ids = [nid for nid, _ in deg.most_common(max(1, int(max_nodes)))]
    seen_keep: Set[str] = set(keep_ids)

    if stack_transport_network_bands:
        preserved_tn = 0
        for nid in sorted(deg.keys()):
            if nid in seen_keep:
                continue
            row = nodes_map.get(nid) or {}
            label = (row.get("label") or nid).strip()
            if tc.guess_layer(label) in ("Transport", "Routing", tc.LAYER_NETWORK_CORE, "Network"):
                keep_ids.append(nid)
                seen_keep.add(nid)
                preserved_tn += 1
        if preserved_tn:
            print(
                f"Kept {preserved_tn} extra stack-layer node(s) below --max-nodes cutoff",
                flush=True,
            )

    if foundation_active:
        for fp in tc.FOUNDATION_PROTOS:
            if fp.id not in seen_keep:
                keep_ids.append(fp.id)
                seen_keep.add(fp.id)

    return keep_ids, seen_keep


# --- Scatter / lines ----------------------------------------------------------------

def build_scatter_rows(
    keep_ids: List[str],
    *,
    nodes_map: Dict[str, Dict[str, str]],
    deg: Counter[str],
    foundation_active: bool,
    stack_transport_network_bands: bool,
    app_tiers: Dict[str, str],
    layer_palette: Dict[str, str],
    node_size_arg: int,
    include_unknown: bool,
) -> Tuple[List[Dict], List[str], Optional[dt.date], Optional[dt.date]]:
    points: List[Dict] = []
    unknown_ids: List[str] = []
    min_d: Optional[dt.date] = None
    max_d: Optional[dt.date] = None

    for nid in keep_ids:
        n = nodes_map.get(nid) or {}
        label = (n.get("label") or nid).strip()
        raw_date = parse_iso_date(n.get("birth_date") or "")
        if foundation_active and nid in tc.FOUNDATION_IDS:
            layer = tc.FOUNDATION_LOOKUP[nid].layer
        elif stack_transport_network_bands:
            bucket = tc.guess_layer(label)
            layer = app_tiers.get(nid, "App-Low") if bucket == "Application" else bucket
        else:
            layer = app_tiers.get(nid, "App-Low")

        if raw_date is None:
            unknown_ids.append(nid)
            if not include_unknown:
                continue
        else:
            min_d = raw_date if min_d is None else min(min_d, raw_date)
            max_d = raw_date if max_d is None else max(max_d, raw_date)

        dd = int(deg.get(nid, 0))
        if foundation_active and nid in tc.FOUNDATION_IDS:
            size = int(node_size_arg) if int(node_size_arg) > 0 else 28
        elif int(node_size_arg) > 0:
            size = int(node_size_arg)
        else:
            size = 13 + min(30, int(8 * math.log(dd + 1 + 1e-9)))

        birth_disp = (n.get("birth_date") or "").strip()
        points.append(
            {
                "id": nid,
                "name": label,
                "birth_date": birth_disp,
                "defining_rfcs": (n.get("defining_rfcs") or "").strip(),
                "layer": layer,
                "degree": dd,
                "symbolSize": size,
                "itemStyle": {
                    "color": layer_palette.get(layer, "#6B7280"),
                    "opacity": 1.0,
                    "shadowBlur": 8,
                    "shadowColor": "rgba(15,23,42,0.12)",
                },
                "value": [birth_disp if raw_date else "", layer],
            }
        )

    return points, unknown_ids, min_d, max_d


def build_line_rows(
    sub_edges: List[Dict[str, str]],
    coord: Dict[str, List],
    *,
    stack_transport_network_bands: bool,
    foundation_active: bool,
    nodes_map: Dict[str, Dict[str, str]],
) -> List[Dict]:
    """Produce ECharts ``lines`` series data."""

    role_cache: Dict[str, str] = {}

    def role_cached(nid: str) -> str:
        if nid not in role_cache:
            role_cache[nid] = tc.coarse_endpoint_role(
                nid,
                foundation_active=foundation_active,
                stack_transport_network_bands=stack_transport_network_bands,
                nodes_map=nodes_map,
            )
        return role_cache[nid]

    lines_out: List[Dict] = []
    for e in sub_edges:
        a = coord.get(e["src"])
        b = coord.get(e["dst"])
        if not a or not b:
            continue
        orig_k = (e.get("kind") or "").strip()
        if stack_transport_network_bands:
            ra, rb = role_cached(e["src"]), role_cached(e["dst"])
            cat = tc.layer_pair_edge_category(ra, rb)
            lines_out.append(
                {
                    "src": e["src"],
                    "dst": e["dst"],
                    "coords": [a, b],
                    "layerLink": tc.LAYER_LINK_EDGE_LABEL_ZH[cat],
                    "dataKind": orig_k,
                    "lineStyle": {
                        "color": tc.LAYER_LINK_EDGE_COLOR[cat],
                        "width": 1.35,
                        "opacity": 0.62,
                        "curveness": 0.0,
                    },
                }
            )
        else:
            c = tc.COLOR_BY_KIND_LEGACY.get(orig_k, "#6B7280")
            lines_out.append(
                {
                    "src": e["src"],
                    "dst": e["dst"],
                    "coords": [a, b],
                    "kind": orig_k,
                    "lineStyle": {"color": c, "width": 1.35, "opacity": 0.62, "curveness": 0.0},
                }
            )

    return lines_out


def edge_legend_html(
    stack_transport_network_bands: bool,
    lines_out: List[Dict],
    sub_edges: List[Dict[str, str]],
    wanted_kinds: Set[str],
) -> Tuple[str, str]:
    if stack_transport_network_bands:
        seen_lc = {ln.get("layerLink") for ln in lines_out}
        title = "边类型（层次链）"
        order = [
            "app_transport",
            "app_routing",
            "transport_routing",
            "transport_network",
            "routing_network",
            "other",
        ]
        html = "".join(
            f'<span class="chip"><span class="swatch" style="border-top-color:{tc.LAYER_LINK_EDGE_COLOR.get(lc, "#6B7280")}"></span>'
            f"{tc.LAYER_LINK_EDGE_LABEL_ZH[lc]}</span>"
            for lc in order
            if tc.LAYER_LINK_EDGE_LABEL_ZH[lc] in seen_lc
        )
        return title, html

    kinds_in_sub = {(e.get("kind") or "").strip() for e in sub_edges}
    title = "边类型"
    order = ["proto_ref", "iana_transport", "rfc_ref", "updates", "obsoletes"]
    html = "".join(
        f'<span class="chip"><span class="swatch" style="border-top-color:{tc.COLOR_BY_KIND_LEGACY.get(k, "#6B7280")}"></span>{k}</span>'
        for k in order
        if k in kinds_in_sub and (k == "iana_transport" or k in wanted_kinds)
    )
    return title, html


# --- main ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if not args.nodes.is_file():
        print(f"Missing nodes file: {args.nodes}", file=sys.stderr)
        return 2
    if not args.edges.is_file():
        print(f"Missing edges file: {args.edges}", file=sys.stderr)
        return 2

    nodes_map = read_nodes(args.nodes)
    app_edges = read_edges(args.edges)
    edges_table, merged_network = merge_network_dataset_if_present(args, nodes_map, app_edges)

    foundation_active = bool(args.foundation)
    if foundation_active:
        tc.merge_foundation_nodes(nodes_map)

    stack_bands = bool(foundation_active or merged_network)

    wanted_kinds = {k.strip() for k in (args.edge_kinds or "").split(",") if k.strip()} or {"proto_ref"}
    filt_edges = csv_edges_respecting_nodes(edges_table, nodes_map, wanted_kinds)
    iana_edges = attach_iana_transport_edges(args, nodes_map)
    graph_edges = filt_edges + iana_edges

    if not graph_edges:
        print(
            "No edges left after filtering. Tip: use --edge-kinds proto_ref, "
            "or your graph may be RFC-only rows not matching nodes.csv.",
            file=sys.stderr,
        )
        return 3

    deg = degree_counter(graph_edges)
    keep_ids, _ = choose_keep_ids(
        deg,
        nodes_map=nodes_map,
        max_nodes=args.max_nodes,
        stack_transport_network_bands=stack_bands,
        foundation_active=foundation_active,
    )
    keep: Set[str] = set(keep_ids)
    sub_edges = [e for e in graph_edges if e["src"] in keep and e["dst"] in keep]

    layer_order, layer_palette = tc.palettes_for_stack_mode(stack_bands)

    app_nodes: List[str] = []
    for nid in keep_ids:
        if foundation_active and nid in tc.FOUNDATION_IDS:
            continue
        if stack_bands:
            row = nodes_map.get(nid) or {}
            label = (row.get("label") or nid).strip()
            if tc.guess_layer(label) == "Application":
                app_nodes.append(nid)
        else:
            app_nodes.append(nid)
    app_sorted = sorted(app_nodes, key=lambda i: (-deg.get(i, 0), i))
    app_tiers = tc.assign_application_tertiles(app_sorted)

    include_unknown = bool(args.include_unknown_birth)
    points, _unknown_ids, min_d, max_d = build_scatter_rows(
        keep_ids,
        nodes_map=nodes_map,
        deg=deg,
        foundation_active=foundation_active,
        stack_transport_network_bands=stack_bands,
        app_tiers=app_tiers,
        layer_palette=layer_palette,
        node_size_arg=args.node_size,
        include_unknown=include_unknown,
    )

    if not points:
        points, _u2, min_d, max_d = build_scatter_rows(
            keep_ids,
            nodes_map=nodes_map,
            deg=deg,
            foundation_active=foundation_active,
            stack_transport_network_bands=stack_bands,
            app_tiers=app_tiers,
            layer_palette=layer_palette,
            node_size_arg=args.node_size,
            include_unknown=True,
        )
        include_unknown = True
        if not points:
            print("No nodes to render.", flush=True)
            return 2

    placeholder_date = "1900-01-01"
    if include_unknown:
        placeholder_date = (max_d + dt.timedelta(days=400)).isoformat() if max_d else "1900-01-01"
        for p in points:
            if not (p.get("birth_date") or "").strip():
                p["value"][0] = placeholder_date

    coord = {p["id"]: p["value"] for p in points}
    lines_out = build_line_rows(
        sub_edges,
        coord,
        stack_transport_network_bands=stack_bands,
        foundation_active=foundation_active,
        nodes_map=nodes_map,
    )
    edge_title, edge_leg_html = edge_legend_html(stack_bands, lines_out, sub_edges, wanted_kinds)

    node_legend_html = "".join(
        f'<button class="chip layer-chip" type="button" data-layer="{k}" aria-pressed="true" '
        f'title="点击显示/隐藏该层"><span class="swatch" style="border-top-color:{layer_palette.get(k, "#6B7280")}"></span>{k}</button>'
        for k in layer_order
    )

    hint_edges = ""
    if stack_bands:
        hint_edges = (
            "边颜色按层次相邻关系归类（应用─传输、应用─路由、传输─路由、传输─网络、路由─网络、其他）；"
            "纵轴最下为 Network Core（IPv4 / IPv6）；其余 IANA 网络协议在 Network。"
            "悬浮可见原始 CSV 边类（proto_ref / iana_transport 等）。"
        )
    hint_rfc = "Ctrl / Cmd + 单击节点可在新标签打开定义 RFC（见 --rfc-click）。" if args.rfc_click != "none" else ""

    max_epn = max(0, int(args.max_edges_per_node))
    if max_epn > 0:
        print(
            f"Edge hover cap: at most {max_epn} edges drawn when hovering a node (0 = no cap).",
            flush=True,
        )

    edge_cap_hint = (
        "<b>边显示</b>：默认不画连线；<b>将鼠标悬停在节点上</b>时显示与该节点相关的边"
        + (f"（每条最多 {max_epn} 条，见 --max-edges-per-node）。" if max_epn > 0 else "。")
    )

    html = build_timeline_html(
        nodes_json=json.dumps(points, ensure_ascii=False),
        lines_json=json.dumps(lines_out, ensure_ascii=False),
        layer_json=json.dumps(layer_order, ensure_ascii=False),
        node_legend_html=node_legend_html,
        edge_legend_html=edge_leg_html,
        edge_legend_title=edge_title,
        hint_edges=hint_edges,
        hint_rfc=hint_rfc,
        edge_cap_hint=edge_cap_hint,
        rfc_click=args.rfc_click,
        label_mode=args.label_mode,
        max_edges_per_node=max_epn,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(f"Wrote: {args.out.resolve()}", flush=True)

    missing_birth = sum(1 for p in points if not (p.get("birth_date") or "").strip())
    if missing_birth:
        print(
            f"Note: {missing_birth} node(s) have no RFC index birth_date → x-axis at {placeholder_date}. "
            "Pass --include-unknown-birth explicitly if you rely on this layout.",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
