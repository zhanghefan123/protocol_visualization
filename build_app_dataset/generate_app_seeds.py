#!/usr/bin/env python3
"""
Build protocol_seeds.yaml from output/rfc_fetch/iana_wellknown_ports_rfcs.csv
for use with rfc_editor_graph.py (same shape as a hand-written seeds file).

``python -m rfc_fetch`` only queries Datatracker for IANA rows whose *Reference* lists no RFC;
rows with Reference RFC(s) keep parsed IANA numbers and leave Datatracker columns empty.

Additive anchors: edit ``core_app_protocol_seeds.CORE_APP_ANCHOR_SEEDS`` (RFC union, no CSV replace).
Entry point: ``python build_app_dataset/generate_app_seeds.py`` (see also ``build_network_dataset/generate_network_seeds.py``).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from project_paths import APP_PROTOCOL_SEEDS_YAML, IANA_PORTS_CSV

from core_app_protocol_seeds import inject_core_app_protocol_seeds

RFC_RE = re.compile(r"RFC\s*(\d+)", re.I)

SCRIPT_DIR = Path(__file__).resolve().parent

def _rfcs_from_text(s: str) -> set[int]:
    return {int(m.group(1)) for m in RFC_RE.finditer(s or "")}


def _rfcs_from_hits_json(cell: str) -> set[int]:
    if not (cell or "").strip():
        return set()
    try:
        data: Any = json.loads(cell)
    except json.JSONDecodeError:
        return set()
    if not isinstance(data, list):
        return set()
    out: set[int] = set()
    for h in data:
        if not isinstance(h, dict):
            continue
        n = h.get("rfc_number")
        if isinstance(n, int):
            out.add(n)
        elif isinstance(n, str) and n.isdigit():
            out.add(int(n))
    return out


def collect_by_protocol(rows: list[dict[str, str]]) -> dict[str, set[int]]:
    by_proto: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        name = (row.get("Service Name") or "").strip().upper()
        if not name:
            continue
        chunk = " ".join(
            [
                row.get("IANA RFC numbers (parsed)", "") or "",
                row.get("IANA Reference", "") or "",
                row.get("Datatracker RFC numbers", "") or "",
            ]
        )
        by_proto[name].update(_rfcs_from_text(chunk))
        by_proto[name].update(_rfcs_from_hits_json(row.get("Datatracker hits (JSON)", "") or ""))
    return {k: v for k, v in by_proto.items() if v}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate protocol_seeds.yaml from enriched IANA CSV")
    ap.add_argument(
        "-i",
        "--input",
        type=Path,
        default=IANA_PORTS_CSV,
        help="Path to iana_wellknown_ports_rfcs.csv",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=APP_PROTOCOL_SEEDS_YAML,
        help=f"Where to write protocol_seeds.yaml (default: {APP_PROTOCOL_SEEDS_YAML})",
    )
    ap.add_argument("--max-depth", type=int, default=1, help="Written under expand.max_depth")
    ap.add_argument("--max-rfcs-total", type=int, default=250, help="Written under expand.max_rfcs_total")
    ap.add_argument(
        "--no-expand-default",
        action="store_true",
        help="Set expand.enabled to false in the generated YAML",
    )
    args = ap.parse_args(argv)

    if not args.input.is_file():
        print(f"Missing input CSV: {args.input}", file=sys.stderr)
        return 1

    with args.input.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    by_proto = collect_by_protocol(rows)
    if not by_proto:
        print("No protocol/RFC pairs found in CSV.", file=sys.stderr)
        return 2

    protocols: dict[str, dict[str, Any]] = {
        name: {"rfcs": sorted(nums)} for name, nums in sorted(by_proto.items())
    }
    inject_core_app_protocol_seeds(protocols)

    data = {
        "protocols": protocols,
        "expand": {
            "enabled": not args.no_expand_default,
            "max_depth": int(args.max_depth),
            "max_rfcs_total": int(args.max_rfcs_total),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(
        f"Wrote {args.output} ({len(protocols)} protocols; {len(by_proto)} from enriched CSV)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
