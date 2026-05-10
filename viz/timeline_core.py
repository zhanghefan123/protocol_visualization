"""
Paths, foundation anchors, protocol layer heuristics, and edge styling for the ECharts timeline.

Used by ``render_timeline_echarts.py``.
"""

from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

# --- repo layout (this file lives in viz/)
VIZ_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = VIZ_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from project_paths import (
    APP_EDGES_CSV,
    APP_NODES_CSV,
    IANA_PORTS_CSV,
    NETWORK_EDGES_CSV,
    NETWORK_NODES_CSV,
    TIMELINE_HTML,
)

DEFAULT_NETWORK_NODES_CSV = NETWORK_NODES_CSV
DEFAULT_NETWORK_EDGES_CSV = NETWORK_EDGES_CSV

# Stack band for IPv4 / IPv6 only (IANA keyword IPV4/IPV6 or foundation anchor IP).
LAYER_NETWORK_CORE = "Network Core"

IANA_TRANSPORT_TO_NODE: Dict[str, str] = {
    "tcp": "TCP",
    "udp": "UDP",
    "sctp": "SCTP",
    "dccp": "DCCP",
}

COLOR_BY_KIND_LEGACY = {
    "proto_ref": "#5B6B8C",
    "iana_transport": "#6B7A72",
    "rfc_ref": "#94A3B8",
    "updates": "#5D8A7A",
    "obsoletes": "#9B6B6B",
}

LAYER_LINK_EDGE_LABEL_ZH = {
    "app_transport": "应用─传输",
    "app_routing": "应用─路由",
    "transport_routing": "传输─路由",
    "transport_network": "传输─网络",
    "routing_network": "路由─网络",
    "other": "其他",
}

LAYER_LINK_EDGE_COLOR = {
    "app_transport": "#5A6D82",
    "app_routing": "#63617A",
    "transport_routing": "#4D6F6A",
    "transport_network": "#5C6578",
    "routing_network": "#6F6A62",
    "other": "#8B95A3",
}


@dataclasses.dataclass(frozen=True)
class FoundationProto:
    id: str
    label: str
    birth_date: str
    defining_rfcs: str
    layer: str  # "Network Core" | "Network" | "Transport"


FOUNDATION_PROTOS: Tuple[FoundationProto, ...] = (
    FoundationProto("IP", "IPv4 · Internet Protocol", "1981-09-01", "RFC791", LAYER_NETWORK_CORE),
    FoundationProto("IPV6", "IPv6 · Internet Protocol", "2017-07-01", "RFC8200", LAYER_NETWORK_CORE),
    FoundationProto("ICMP", "ICMP", "1981-09-01", "RFC792", "Network"),
    FoundationProto("IGMP", "IGMP", "1989-12-01", "RFC1112", "Network"),
    FoundationProto("ARP", "ARP", "1982-11-01", "RFC826", "Network"),
    FoundationProto("TCP", "TCP", "1981-09-01", "RFC793", "Transport"),
    FoundationProto("UDP", "UDP", "1980-08-01", "RFC768", "Transport"),
    FoundationProto("SCTP", "SCTP", "2007-09-01", "RFC4960", "Transport"),
    FoundationProto("DCCP", "DCCP", "2006-03-01", "RFC4340", "Transport"),
)

FOUNDATION_IDS: Set[str] = {p.id for p in FOUNDATION_PROTOS}
FOUNDATION_LOOKUP: Dict[str, FoundationProto] = {p.id: p for p in FOUNDATION_PROTOS}


def merge_foundation_nodes(nodes_map: Dict[str, Dict[str, str]]) -> None:
    for fp in FOUNDATION_PROTOS:
        if fp.id in nodes_map:
            continue
        nodes_map[fp.id] = {
            "id": fp.id,
            "label": fp.label,
            "birth_date": fp.birth_date,
            "defining_rfcs": fp.defining_rfcs,
            "source": "foundation anchor (timeline viz)",
        }


def guess_layer(proto_name: str) -> str:
    """Heuristic bucket: Application | Transport | Routing | Network Core | Network."""

    n = proto_name.upper()
    u = proto_name.strip().upper()
    tokens = {_tok for _hyp in re.split(r"[\s/\|\-]+", n) for _tok in (_hyp,)}
    tokens.add(n)

    # IPv4 / IPv6 as protocol-number keywords only — not IPV6-ICMP, MIN-IPV4, etc.
    if u in ("IP", "IPV4", "IPV6"):
        return LAYER_NETWORK_CORE
    if u.startswith("IPV6-") or u.startswith("IPV4-"):
        pass
    elif u.startswith("IPV4") or u.startswith("IPV6"):
        return LAYER_NETWORK_CORE

    routing_hits = {
        "BGP",
        "BGMP",
        "OSPF",
        "RIP",
        "RIPNG",
        "ISIS",
        "EIGRP",
        "IGRP",
        "IDRP",
        "LDP",
        "PIM",
        "MSDP",
        "NHRP",
        "BABEL",
        "AODV",
        "DVMRP",
        "RSVP",
        "OLSR",
        "RPL",
        "ZRP",
        "MPLS",
        "L2VPN",
        "SRV6",
    }
    routing_aliases = {
        "OSPFIGP",
        "MANET",
        "DSR",
        "RSVP-E2E-IGNORE",
    }

    network_hits = {
        "ICMP",
        "ICMPV6",
        "IGMP",
        "GRE",
        "IPSEC",
        "ESP",
        "AH",
        "ARP",
        "ND",
        "IPINIP",
        "IPCOMP",
        "VXLAN",
        "GENEVE",
        "ROUTING",
        "MOBILITY",
    }
    transport_hits = {"TCP", "UDP", "SCTP", "DCCP", "UDPLITE", "IRTP", "ST"}

    ip_proto_network_aliases = {
        "AGGFRAG",
        "HOPOPT",
        "IPV6-ICMP",
        "IPV6-OPTS",
        "IPV6-NONXT",
        "EGP",
        "ENCAP",
        "ENCAPSULATION",
        "L2TP",
        "MIN-IPV4",
        "MINIPV4",
        "MOBILITY-HEADER",
        "MOBILITY",
        "NARP",
        "NETBLT",
        "NSH",
        "NVP-II",
        "ROHC",
        "SHIM6",
        "RDP",
        "VRRP",
        "WESP",
        "HIP",
        "HMP",
        "ISO-TP4",
        "FC",
        "GGP",
        "ETHERIP",
        "ETHERNET",
        "BIT-EMU",
        "SKIP",
        "TLSP",
        "CRUDP",
        "SSCOPMCE",
        "PIPE",
        "UTI",
    }

    if "IS-IS" in n:
        return "Routing"
    # MPLS / L2VPN / SRv6 (incl. SR-V6, L2-VPN, MPLS-in-IP style spellings)
    n_alnum = re.sub(r"[^A-Z0-9]", "", n)
    if "MPLS" in n_alnum or "L2VPN" in n_alnum or "SRV6" in n_alnum:
        return "Routing"
    if tokens & routing_hits or tokens & routing_aliases:
        return "Routing"
    if tokens & network_hits or tokens & ip_proto_network_aliases:
        return "Network"
    if tokens & transport_hits:
        return "Transport"

    tail = "-" + n.replace(" ", "") + "-"
    if tail.find("-ICMP-") >= 0 or tail.find("-IGMP-") >= 0 or "-IPSEC-" in tail:
        return "Network"
    if tail.find("-MPLS-") >= 0 or tail.find("-L2VPN-") >= 0 or tail.find("-SRV6-") >= 0:
        return "Routing"

    return "Application"


def assign_application_tertiles(app_sorted_by_degree_desc: List[str]) -> Dict[str, str]:
    tiers: Dict[str, str] = {}
    lst = app_sorted_by_degree_desc
    n_all = len(lst)
    if n_all == 0:
        return tiers
    if n_all == 1:
        tiers[lst[0]] = "App-Mid"
        return tiers
    if n_all == 2:
        tiers[lst[0]] = "App-High"
        tiers[lst[1]] = "App-Low"
        return tiers

    hi_end = max(1, (n_all + 2) // 3)
    mid_end = max(hi_end + 1, (2 * (n_all + 1)) // 3)

    for idx, nid in enumerate(lst):
        if idx < hi_end:
            tiers[nid] = "App-High"
        elif idx < mid_end:
            tiers[nid] = "App-Mid"
        else:
            tiers[nid] = "App-Low"
    return tiers


def coarse_endpoint_role(
    nid: str,
    *,
    foundation_active: bool,
    stack_transport_network_bands: bool,
    nodes_map: Dict[str, Dict[str, str]],
) -> str:
    """Application | Transport | Routing | Network Core | Network — for stacked edge coloring."""

    if foundation_active and nid in FOUNDATION_IDS:
        ly = FOUNDATION_LOOKUP[nid].layer
        return ly if ly in ("Transport", "Network", LAYER_NETWORK_CORE) else "Network"
    row = nodes_map.get(nid) or {}
    label = (row.get("label") or nid).strip()
    if stack_transport_network_bands:
        bucket = guess_layer(label)
        if bucket == "Transport":
            return "Transport"
        if bucket == "Routing":
            return "Routing"
        if bucket == LAYER_NETWORK_CORE:
            return LAYER_NETWORK_CORE
        if bucket == "Network":
            return "Network"
        return "Application"
    return "Application"


def layer_pair_edge_category(pa: str, pb: str) -> str:
    if pa == pb:
        return "other"
    pair = tuple(sorted([pa, pb]))
    nc = LAYER_NETWORK_CORE
    if pair == ("Application", "Transport"):
        return "app_transport"
    if pair == ("Application", "Routing"):
        return "app_routing"
    if pair == ("Routing", "Transport"):
        return "transport_routing"
    if pair == ("Network", "Transport"):
        return "transport_network"
    if pair == ("Network", "Routing"):
        return "routing_network"
    # Network Core ↔ transport / routing: same bucket colors as generic Network edges
    if pair == (nc, "Transport"):
        return "transport_network"
    if pair == (nc, "Routing"):
        return "routing_network"
    return "other"


def palettes_for_stack_mode(stack_transport_network_bands: bool) -> Tuple[List[str], Dict[str, str]]:
    if stack_transport_network_bands:
        # yAxis inverse: last entry is bottom band → Network Core under Network.
        order = [
            "App-High",
            "App-Mid",
            "App-Low",
            "Transport",
            "Routing",
            "Network",
            LAYER_NETWORK_CORE,
        ]
        # Muted academic palette; App tertiles share one hue (same fill per application layer).
        _app = "#5C6F8A"
        pal = {
            "App-High": _app,
            "App-Mid": _app,
            "App-Low": _app,
            "Transport": "#3D7A72",
            "Routing": "#6B5D7F",
            "Network": "#7A6E5C",
            LAYER_NETWORK_CORE: "#2F4A66",
        }
    else:
        order = ["App-High", "App-Mid", "App-Low"]
        _app = "#5C6F8A"
        pal = {
            "App-High": _app,
            "App-Mid": _app,
            "App-Low": _app,
        }
    return order, pal
