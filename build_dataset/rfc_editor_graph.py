#!/usr/bin/env python3
"""
Build nodes.csv / edges.csv from protocol_seeds.yaml using RFC Editor rfc-index.xml,
optional reference expansion, updates/obsoletes edges, and proto_ref derivation.

Install deps: pip install -r build_dataset/requirements.txt
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import os
import re
import sys
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import requests
import yaml
from lxml import etree

RFC_INDEX_URL = "https://www.rfc-editor.org/rfc-index.xml"
RFC_XML_URL = "https://www.rfc-editor.org/rfc/rfc{num}.xml"
RFC_TXT_URL = "https://www.rfc-editor.org/rfc/rfc{num}.txt"

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from project_paths import APP_PROTOCOL_SEEDS_YAML, OUTPUT_APP_GRAPH, OUTPUT_CACHE_RFC_EDITOR


@dataclasses.dataclass(frozen=True)
class ProtocolSeed:
    name: str
    rfcs: Tuple[int, ...]
    # Optional CSV label when IANA id is ambiguous (e.g. ETHERNET = IP proto 143, not IEEE 802.3).
    label: Optional[str] = None


@dataclasses.dataclass
class RfcMeta:
    number: int
    title: str
    date: Optional[dt.date]
    status: Optional[str]


@dataclasses.dataclass
class Edge:
    src: str
    dst: str
    kind: str  # "proto_ref", "rfc_ref", "updates", "obsoletes"
    source: str  # e.g. "RFC8446"
    detail: str


_SESSION = requests.Session()


def _http_get(url: str, *, timeout_s: int = 60) -> bytes:
    r = _SESSION.get(url, timeout=timeout_s, headers={"User-Agent": "ietf-proto-vis/1.1 (visualization_new)"})
    r.raise_for_status()
    return r.content


def load_seeds(path: str) -> Tuple[List[ProtocolSeed], Dict]:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    protocols = raw.get("protocols", {}) or {}
    seeds: List[ProtocolSeed] = []
    for name, v in protocols.items():
        rfcs = tuple(int(x) for x in (v.get("rfcs") or []))
        if not rfcs:
            continue
        lbl = (v.get("label") or "").strip() or None
        seeds.append(ProtocolSeed(name=name, rfcs=rfcs, label=lbl))
    expand_cfg = raw.get("expand", {}) or {}
    return seeds, expand_cfg


def parse_rfc_index(xml_bytes: bytes) -> Tuple[Dict[int, RfcMeta], Dict[int, Set[int]], Dict[int, Set[int]]]:
    """
    Returns:
      - meta_by_rfc
      - updates_edges: rfc -> set(updated_rfc)
      - obsoletes_edges: rfc -> set(obsoleted_rfc)
    """
    root = etree.fromstring(xml_bytes)
    ns = root.nsmap.get(None)
    nsmap = {"x": ns} if ns else {}

    meta: Dict[int, RfcMeta] = {}
    updates: Dict[int, Set[int]] = defaultdict(set)
    obsoletes: Dict[int, Set[int]] = defaultdict(set)

    for entry in root.findall(".//x:rfc-entry" if ns else ".//rfc-entry", namespaces=nsmap):
        doc_id = (entry.findtext("x:doc-id" if ns else "doc-id", namespaces=nsmap) or "").strip()
        m = re.fullmatch(r"RFC(\d+)", doc_id)
        if not m:
            continue
        num = int(m.group(1))

        title = (entry.findtext("x:title" if ns else "title", namespaces=nsmap) or "").strip()
        date_el = entry.find("x:date" if ns else "date", namespaces=nsmap)
        month_txt = ((date_el.findtext("x:month" if ns else "month", namespaces=nsmap) if date_el is not None else "") or "").strip()
        year_txt = ((date_el.findtext("x:year" if ns else "year", namespaces=nsmap) if date_el is not None else "") or "").strip()
        day_txt = ((date_el.findtext("x:day" if ns else "day", namespaces=nsmap) if date_el is not None else "") or "").strip()
        status = (entry.findtext("x:current-status" if ns else "current-status", namespaces=nsmap) or "").strip() or None

        date_obj: Optional[dt.date] = None
        if year_txt and month_txt:
            try:
                year = int(year_txt)
                if month_txt.isdigit():
                    month = int(month_txt)
                else:
                    month = dt.datetime.strptime(month_txt, "%B").month
                day = int(day_txt) if day_txt.isdigit() else 1
                date_obj = dt.date(year, month, day)
            except Exception:
                date_obj = None

        meta[num] = RfcMeta(number=num, title=title, date=date_obj, status=status)

        for u in entry.findall("x:updates/x:doc-id" if ns else "updates/doc-id", namespaces=nsmap):
            t = (u.text or "").strip()
            mu = re.fullmatch(r"RFC(\d+)", t)
            if mu:
                updates[num].add(int(mu.group(1)))

        for o in entry.findall("x:obsoletes/x:doc-id" if ns else "obsoletes/doc-id", namespaces=nsmap):
            t = (o.text or "").strip()
            mo = re.fullmatch(r"RFC(\d+)", t)
            if mo:
                obsoletes[num].add(int(mo.group(1)))

    return meta, updates, obsoletes


def rfc_birth_date(meta_by_rfc: Dict[int, RfcMeta], rfcs: Iterable[int]) -> Optional[dt.date]:
    dates = [meta_by_rfc.get(n).date for n in rfcs if meta_by_rfc.get(n) and meta_by_rfc.get(n).date]
    return min(dates) if dates else None


def fetch_rfc_reference_numbers(rfc_num: int) -> Tuple[Set[int], str]:
    """
    Best-effort: prefer RFC XML (v3) and extract <reference> anchors.
    Fallback to RFC text and parse "RFCxxxx" patterns, biased to references sections.
    Returns: (referenced_rfc_numbers, detail_source)
    """
    try:
        xml_bytes = _http_get(RFC_XML_URL.format(num=rfc_num))
        root = etree.fromstring(xml_bytes)
        refs: Set[int] = set()
        for ref in root.findall(".//reference"):
            for si in ref.findall(".//seriesInfo"):
                if (si.get("name") or "").upper() == "RFC":
                    v = (si.get("value") or "").strip()
                    if v.isdigit():
                        refs.add(int(v))
        for xref in root.findall(".//xref"):
            t = (xref.get("target") or "").strip()
            mx = re.fullmatch(r"RFC(\d+)", t)
            if mx:
                refs.add(int(mx.group(1)))
        if refs:
            return refs, "xml"
    except Exception:
        pass

    try:
        txt = _http_get(RFC_TXT_URL.format(num=rfc_num)).decode("utf-8", errors="replace")
        lowered = txt.lower()
        start = 0
        for marker in ["normative references", "references", "informative references"]:
            idx = lowered.find(marker)
            if idx != -1:
                start = idx
                break
        window = txt[start : start + 250_000]
        refs = {int(m.group(1)) for m in re.finditer(r"\bRFC\s*([0-9]{1,5})\b", window)}
        return refs, "txt"
    except Exception:
        return set(), "none"


def cached_rfc_reference_numbers(cache_dir: str, rfc_num: int) -> Tuple[Set[int], str]:
    """
    Disk-cached wrapper for fetch_rfc_reference_numbers.
    Cache format: first line = source tag, remaining = space-separated RFC numbers.
    """
    cache_ref_path = os.path.join(cache_dir, f"rfc{rfc_num}.refs.txt")
    if os.path.exists(cache_ref_path):
        with open(cache_ref_path, "r", encoding="utf-8") as f:
            src = f.readline().strip()
            nums = {int(x) for x in f.read().strip().split() if x.strip().isdigit()}
        return nums, src or "cache"

    refs, detail_src = fetch_rfc_reference_numbers(rfc_num)
    with open(cache_ref_path, "w", encoding="utf-8") as f:
        f.write(detail_src + "\n")
        f.write(" ".join(str(x) for x in sorted(refs)) + "\n")
    return refs, detail_src


def build_protocol_lookup(seeds: List[ProtocolSeed]) -> Dict[int, Set[str]]:
    by_rfc: Dict[int, Set[str]] = defaultdict(set)
    for s in seeds:
        for n in s.rfcs:
            by_rfc[n].add(s.name)
    return by_rfc


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build nodes/edges from protocol_seeds.yaml + RFC Editor index")
    default_seeds = str(APP_PROTOCOL_SEEDS_YAML)
    ap.add_argument("--seeds", default=default_seeds, help=f"Path to protocol_seeds.yaml (default: {default_seeds})")
    ap.add_argument("--out", default=str(OUTPUT_APP_GRAPH), help="Output directory for nodes.csv / edges.csv")
    ap.add_argument(
        "--cache",
        default=str(OUTPUT_CACHE_RFC_EDITOR),
        help="Cache directory (rfc-index.xml + per-RFC reference cache)",
    )
    ap.add_argument("--workers", type=int, default=16, help="Parallel workers for fetching RFC references.")
    ap.add_argument(
        "--skip-proto-refs",
        action="store_true",
        help="Skip protocol-to-protocol edges derived from defining RFC references (faster).",
    )
    args = ap.parse_args()

    if not os.path.isfile(args.seeds):
        print(f"Seeds file not found: {args.seeds}", file=sys.stderr)
        print("Generate it with: python build_dataset/generate_seeds.py", file=sys.stderr)
        return 2

    seeds, expand_cfg = load_seeds(args.seeds)
    if not seeds:
        print("No protocols found in seeds file.", file=sys.stderr)
        return 2

    ensure_dir(args.out)
    ensure_dir(args.cache)

    index_path = os.path.join(args.cache, "rfc-index.xml")
    if not os.path.exists(index_path):
        print("Downloading RFC index...")
        with open(index_path, "wb") as f:
            f.write(_http_get(RFC_INDEX_URL))

    with open(index_path, "rb") as f:
        meta_by_rfc, updates, obsoletes = parse_rfc_index(f.read())

    expand_enabled = bool(expand_cfg.get("enabled", True))
    max_depth = int(expand_cfg.get("max_depth", 1))
    max_total = int(expand_cfg.get("max_rfcs_total", 250))

    seed_rfcs: Set[int] = set()
    for s in seeds:
        seed_rfcs.update(s.rfcs)

    discovered: Set[int] = set(seed_rfcs)
    q = deque([(n, 0) for n in sorted(seed_rfcs)])

    rfc_ref_edges: List[Tuple[int, int, str]] = []

    if expand_enabled:
        print(f"Expanding via references (depth<={max_depth}, cap={max_total})...")
        while q and len(discovered) < max_total:
            rfc, depth = q.popleft()
            if depth >= max_depth:
                continue

            refs, detail_src = cached_rfc_reference_numbers(args.cache, rfc)

            for dst in refs:
                if dst == rfc:
                    continue
                rfc_ref_edges.append((rfc, dst, f"ref({detail_src})"))
                if dst not in discovered and dst in meta_by_rfc and len(discovered) < max_total:
                    discovered.add(dst)
                    q.append((dst, depth + 1))

    nodes: List[Dict[str, str]] = []
    for s in seeds:
        birth = rfc_birth_date(meta_by_rfc, s.rfcs)
        nodes.append(
            {
                "id": s.name,
                "label": s.label or s.name,
                "birth_date": birth.isoformat() if birth else "",
                "defining_rfcs": ",".join(f"RFC{n}" for n in s.rfcs),
                "source": "RFC Editor (rfc-index.xml)",
            }
        )

    edges: List[Edge] = []

    for src_num, dsts in updates.items():
        for dst_num in dsts:
            if src_num in discovered or dst_num in discovered:
                edges.append(
                    Edge(
                        src=f"RFC{src_num}",
                        dst=f"RFC{dst_num}",
                        kind="updates",
                        source=f"RFC{src_num}",
                        detail="rfc-index.xml",
                    )
                )
    for src_num, dsts in obsoletes.items():
        for dst_num in dsts:
            if src_num in discovered or dst_num in discovered:
                edges.append(
                    Edge(
                        src=f"RFC{src_num}",
                        dst=f"RFC{dst_num}",
                        kind="obsoletes",
                        source=f"RFC{src_num}",
                        detail="rfc-index.xml",
                    )
                )

    for src_num, dst_num, detail in rfc_ref_edges:
        edges.append(
            Edge(
                src=f"RFC{src_num}",
                dst=f"RFC{dst_num}",
                kind="rfc_ref",
                source=f"RFC{src_num}",
                detail=detail,
            )
        )

    if not args.skip_proto_refs:
        proto_by_rfc = build_protocol_lookup(seeds)
        proto_ref_map: Dict[str, Set[str]] = defaultdict(set)
        defining_set: Set[int] = set()
        for s in seeds:
            defining_set.update(s.rfcs)

        refs_cache: Dict[int, Set[int]] = {}
        rfc_list = sorted(defining_set)
        if rfc_list:
            print(f"Fetching references for defining RFCs (n={len(rfc_list)}, workers={args.workers})...")
            with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as ex:
                futs = {ex.submit(cached_rfc_reference_numbers, args.cache, r): r for r in rfc_list}
                done = 0
                for fut in as_completed(futs):
                    r = futs[fut]
                    try:
                        refs_set, _ = fut.result()
                    except Exception:
                        refs_set = set()
                    refs_cache[r] = refs_set
                    done += 1
                    if done % 50 == 0:
                        print(f"  ... {done}/{len(rfc_list)}", flush=True)

        for s in seeds:
            for rfc in s.rfcs:
                for ref_rfc in refs_cache.get(rfc, set()):
                    for other_proto in proto_by_rfc.get(ref_rfc, set()):
                        if other_proto != s.name:
                            proto_ref_map[s.name].add(other_proto)

        for src_proto, dsts in proto_ref_map.items():
            for dst_proto in sorted(dsts):
                edges.append(
                    Edge(
                        src=src_proto,
                        dst=dst_proto,
                        kind="proto_ref",
                        source="defining RFC references",
                        detail="derived",
                    )
                )

    nodes_path = os.path.join(args.out, "nodes.csv")
    with open(nodes_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "label", "birth_date", "defining_rfcs", "source"])
        w.writeheader()
        for row in sorted(nodes, key=lambda r: r["id"].lower()):
            w.writerow(row)

    edges_path = os.path.join(args.out, "edges.csv")
    with open(edges_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["src", "dst", "kind", "source", "detail"])
        w.writeheader()
        for e in edges:
            w.writerow(dataclasses.asdict(e))

    print(f"Wrote: {nodes_path}")
    print(f"Wrote: {edges_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
