"""
CSV load/merge and IANA well-known-port → transport edges.

Used by ``render_timeline_echarts.py``.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

# ---------------------------------------------------------------------------
# Human-readable descriptions for tooltips (IANA ports CSV + protocol-numbers CSV)
# ---------------------------------------------------------------------------


def keyword_to_protocol_seed_id(keyword_raw: str) -> str:
    """Match ``generate_network_seeds.keyword_to_seed_id`` / network graph node ``id``."""

    k = (keyword_raw or "").strip().upper()
    k = re.sub(r"\([^)]*\)", "", k).strip()
    k = k.replace("/", "-")
    k = re.sub(r"[^\w\-]+", "-", k.replace(" ", "-"))
    k = re.sub(r"-+", "-", k).strip("-")
    return k


def _pick_longest_text(candidates: List[str]) -> str:
    cand = [t.strip() for t in candidates if t and t.strip()]
    if not cand:
        return ""
    return max(cand, key=lambda s: (len(s), s.casefold()))


def descriptions_from_iana_ports_csv(path: Path) -> Dict[str, str]:
    """Uppercased *Service Name* → longest *Description* among its port/transport rows."""

    if not path.is_file():
        return {}
    bucket: Dict[str, List[str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sn = (row.get("Service Name") or "").strip()
            if not sn:
                continue
            bucket.setdefault(sn.upper(), []).append((row.get("Description") or "").strip())
    return {svc: _pick_longest_text(descs) for svc, descs in bucket.items()}


def descriptions_from_protocol_numbers_csv(path: Path) -> Dict[str, str]:
    """Keyword-derived seed ``id`` → longest *Protocol* cell for that Keyword."""

    if not path.is_file():
        return {}
    bucket: Dict[str, List[str]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            kw_raw = (row.get("Keyword") or "").strip()
            if re.fullmatch(r"(?i)reserved", kw_raw):
                continue
            sid = keyword_to_protocol_seed_id(kw_raw)
            if not sid:
                continue
            proto = (row.get("Protocol") or "").strip()
            if proto:
                bucket.setdefault(sid, []).append(proto)
    return {sid: _pick_longest_text(texts) for sid, texts in bucket.items()}


def enrich_nodes_map_descriptions(
    nodes_map: Dict[str, Dict[str, str]],
    *,
    ports_csv: Path | None = None,
    protocol_csv: Path | None = None,
) -> None:
    """Fill ``description`` on node rows when missing (mutates *nodes_map*)."""

    pmap = descriptions_from_iana_ports_csv(ports_csv) if ports_csv else {}
    nmap = descriptions_from_protocol_numbers_csv(protocol_csv) if protocol_csv else {}
    if not pmap and not nmap:
        return
    for nid, row in nodes_map.items():
        if (row.get("description") or "").strip():
            continue
        desc = pmap.get((nid or "").strip().upper()) or nmap.get(nid, "") or ""
        if desc:
            row["description"] = desc


def enrich_nodes_list_descriptions(
    nodes: List[Dict[str, str]],
    *,
    ports_csv: Path | None = None,
    protocol_csv: Path | None = None,
) -> None:
    """Same as ``enrich_nodes_map_descriptions`` but for list of rows with ``id``."""

    m: Dict[str, Dict[str, str]] = {}
    for row in nodes:
        i = (row.get("id") or "").strip()
        if i:
            m[i] = row
    enrich_nodes_map_descriptions(m, ports_csv=ports_csv, protocol_csv=protocol_csv)

from timeline_core import IANA_TRANSPORT_TO_NODE

RFC_NUM_IN_DEFINING = re.compile(r"\bRFC\s*(\d+)\b", re.I)


def read_nodes(path: Path) -> Dict[str, Dict[str, str]]:
    nodes: Dict[str, Dict[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            nid = (row.get("id") or "").strip()
            if nid:
                nodes[nid] = row
    return nodes


def read_edges(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def parse_iso_date(s: str):
    import datetime as dt

    s = (s or "").strip()
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


def _union_defining_rfcs(a: str, b: str) -> str:
    nums = {int(m.group(1)) for m in RFC_NUM_IN_DEFINING.finditer(f"{a or ''} {b or ''}")}
    return ",".join(f"RFC{n}" for n in sorted(nums)) if nums else ""


def _earlier_birth_date_str(s1: str, s2: str) -> str:
    d1, d2 = parse_iso_date(s1), parse_iso_date(s2)
    if d1 and d2:
        return s1 if d1 <= d2 else s2
    if d1:
        return s1
    if d2:
        return s2
    return (s1 or "").strip() or (s2 or "").strip()


def merge_network_nodes_into(
    primary: Dict[str, Dict[str, str]],
    secondary: Dict[str, Dict[str, str]],
    *,
    secondary_tag: str = "output/network_graph",
) -> int:
    n = 0
    for nid, srow in secondary.items():
        n += 1
        if nid not in primary:
            row = dict(srow)
            src = (row.get("source") or "").strip()
            row["source"] = f"{secondary_tag}: {src}" if src else secondary_tag
            primary[nid] = row
            continue
        prow = primary[nid]
        merged = dict(prow)
        merged["defining_rfcs"] = _union_defining_rfcs(
            prow.get("defining_rfcs") or "", srow.get("defining_rfcs") or ""
        )
        merged["birth_date"] = _earlier_birth_date_str(
            (prow.get("birth_date") or "").strip(), (srow.get("birth_date") or "").strip()
        )
        pd = (prow.get("description") or "").strip()
        sd = (srow.get("description") or "").strip()
        if len(sd) > len(pd):
            merged["description"] = sd
        else:
            merged["description"] = pd or sd
        plab = (prow.get("label") or "").strip()
        slab = (srow.get("label") or "").strip()
        merged["label"] = plab or slab or nid
        ps = (prow.get("source") or "").strip()
        ss = (srow.get("source") or "").strip()
        if ps and ss:
            merged["source"] = f"{ps} | {secondary_tag}: {ss}"
        elif ss:
            merged["source"] = f"{ps + ' | ' if ps else ''}{secondary_tag}: {ss}"
        else:
            merged["source"] = ps or secondary_tag
        primary[nid] = merged
    return n


def merge_edge_tables(a: List[Dict[str, str]], b: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen: Set[Tuple[str, str, str, str, str]] = set()
    out: List[Dict[str, str]] = []
    for e in a + b:
        tup = (
            (e.get("src") or "").strip(),
            (e.get("dst") or "").strip(),
            (e.get("kind") or "").strip(),
            (e.get("source") or "").strip(),
            (e.get("detail") or "").strip(),
        )
        if not tup[0] or not tup[1] or not tup[2]:
            continue
        if tup in seen:
            continue
        seen.add(tup)
        out.append(dict(e))
    return out


def collect_iana_transport_edges(
    iana_csv: Path,
    nodes_map: Dict[str, Dict[str, str]],
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not iana_csv.is_file():
        return out
    seen: Set[Tuple[str, str]] = set()
    with iana_csv.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw_svc = (row.get("Service Name") or "").strip()
            raw_tp = (row.get("Transport Protocol") or "").strip().lower()
            if not raw_svc or not raw_tp:
                continue
            dst = IANA_TRANSPORT_TO_NODE.get(raw_tp)
            if not dst or dst not in nodes_map:
                continue
            svc_id = raw_svc.upper()
            if svc_id not in nodes_map:
                continue
            key = (svc_id, dst)
            if key in seen:
                continue
            seen.add(key)
            out.append({"src": svc_id, "dst": dst, "kind": "iana_transport"})
    return out
