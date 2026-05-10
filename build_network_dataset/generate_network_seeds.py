#!/usr/bin/env python3
"""
Build protocol_seeds_network.yaml from IANA "Assigned Internet Protocol Numbers" CSV
(protocol-numbers-1.csv). Same YAML shape as output/app_graph/protocol_seeds.yaml for use with
rfc_editor_graph.py (--seeds path/to/protocol_seeds_network.yaml).

Official CSV:
  https://www.iana.org/assignments/protocol-numbers/protocol-numbers-1.csv

Decodes Keyword -> protocol id (uppercase, hyphenated) and parses RFC numbers from Reference.
Rows **without** RFC in Reference still become seeds: Datatracker title search may supply RFC numbers.
Only protocols that end up with **at least one** RFC (IANA ∪ Datatracker) appear in the YAML.

The registry lists **protocol / next-header numbers** (what runs *above* or *inside* IP in many
rows). Decimals **4** and **41** are *IPv4 / IPv6 encapsulation* (RFC2003 / RFC2473 style), not
the core Internet Protocol specs, so those CSV rows are **skipped** and **IPV4** / **IPV6**
seeds are **injected** (RFC791 / **RFC8200 only** for IPv6) before folding IPv6 extension headers in.

After building from CSV, optionally merges **Datatracker** ``title__icontains`` hits into each seed’s
``rfcs`` (same multi-phrase strategy as application-layer ``rfc_fetch``; cache under
``output/network_graph/network_datatracker_cache.json``). IANA ``Reference`` RFCs are always kept;
Datatracker numbers are **unioned**.

After that, merges ``network_seed_overrides.yaml`` (same directory by default).
Overrides may use ``replace_rfcs`` or ``extra_rfcs`` (union).

IPv6 **extension-header next-header** values (HOPOPT, …) are **folded into** ``IPV6`` (RFC union)
after the core IPv6 seed exists.

``apply_iana_protocol_number_semantics`` still fixes **ETHERNET** labelling and acts as a safety
net if an IPV4 row ever appears from CSV with only RFC2003.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Set

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from project_paths import (
    NETWORK_DATATRACKER_CACHE,
    NETWORK_PROTOCOL_NUMBERS_CSV,
    NETWORK_PROTOCOL_SEEDS_YAML,
    OUTPUT_RFC_FETCH_TXT_CACHE,
)

from network_datatracker_merge import merge_datatracker_rfcs_into_by_proto

from core_internet_protocol_seeds import RFC_IPV4_CORE, inject_core_internet_protocol_seeds

RFC_RE = re.compile(r"\bRFC\s*(\d+)\b", re.I)

_SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_CSV_URL = "https://www.iana.org/assignments/protocol-numbers/protocol-numbers-1.csv"
DEFAULT_DATA_CSV = NETWORK_PROTOCOL_NUMBERS_CSV
DEFAULT_OUTPUT = NETWORK_PROTOCOL_SEEDS_YAML
DEFAULT_OVERRIDES_YAML = _SCRIPT_DIR / "network_seed_overrides.yaml"


def keyword_to_seed_id(keyword_raw: str) -> str:
    """Map IANA Keyword to a stable YAML/protocol id (RFC graph seed name)."""

    k = (keyword_raw or "").strip().upper()
    k = re.sub(r"\([^)]*\)", "", k).strip()
    k = k.replace("/", "-")
    k = re.sub(r"[^\w\-]+", "-", k.replace(" ", "-"))
    k = re.sub(r"-+", "-", k).strip("-")
    return k


def rfcs_from_reference(ref: str) -> Set[int]:
    return {int(m.group(1)) for m in RFC_RE.finditer(ref or "")}


def download_csv(url: str, dest: Path, timeout_s: int = 60) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ietf-proto-vis/1.2 (visualization_new; generate_network_seeds)"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        dest.write_bytes(resp.read())


def _decimal_first(raw: str) -> int | None:
    s = (raw or "").strip()
    if not s:
        return None
    head = s.split("-", 1)[0].strip()
    try:
        return int(head)
    except ValueError:
        return None


def collect_network_protocols(rows: list[dict[str, str]]) -> Dict[str, Set[int]]:
    by_id: Dict[str, Set[int]] = defaultdict(set)
    skipped_reserved = 0
    skipped_id = 0
    skipped_core_encap = 0

    for row in rows:
        kw_raw = row.get("Keyword") or ""
        if re.fullmatch(r"(?i)reserved", kw_raw.strip()):
            skipped_reserved += 1
            continue
        dec0 = _decimal_first(row.get("Decimal") or "")
        # IANA decimal 4 / 41 document encapsulation over IP, not RFC791 / RFC8200 "core IP".
        if dec0 in (4, 41):
            skipped_core_encap += 1
            continue
        seed_id = keyword_to_seed_id(kw_raw)
        if not seed_id:
            skipped_id += 1
            continue
        ref = row.get("Reference") or ""
        nums = rfcs_from_reference(ref)
        # Keep seed id even when Reference has no RFC (e.g. contact name only); Datatracker may still find RFCs.
        by_id[seed_id].update(nums)

    # Debug visibility (stderr only when useful)
    if skipped_reserved:
        print(f"Skipped Keyword 'Reserved': {skipped_reserved} row(s)", file=sys.stderr)
    if skipped_id:
        print(f"Skipped empty ids after normalize: {skipped_id} row(s)", file=sys.stderr)
    if skipped_core_encap:
        print(
            f"Skipped {skipped_core_encap} IANA row(s) for decimals 4/41 (encapsulation); "
            "core IPV4/IPV6 seeds are injected separately.",
            file=sys.stderr,
        )

    return dict(by_id)


# IANA Keyword ids (after keyword_to_seed_id) merged into IPV6 — same Next-Header family as RFC8200.
_IPV6_EXT_HEADER_ALIASES: tuple[str, ...] = ("HOPOPT", "IPV6-ICMP", "IPV6-NONXT", "IPV6-OPTS")
_IPV6_CANONICAL = "IPV6"


def fold_ipv6_extension_header_seeds(protocols: Dict[str, Dict[str, Any]]) -> int:
    """
    Union RFCs from IPv6 extension-header aliases into ``IPV6`` and drop the alias entries.

    Returns the number of alias protocols removed.
    """

    if _IPV6_CANONICAL not in protocols:
        return 0
    merged = {int(x) for x in (protocols[_IPV6_CANONICAL].get("rfcs") or [])}
    removed = 0
    for alias in _IPV6_EXT_HEADER_ALIASES:
        block = protocols.pop(alias, None)
        if not block:
            continue
        merged.update(int(x) for x in (block.get("rfcs") or []))
        for k, v in block.items():
            if k == "rfcs" or v in (None, ""):
                continue
            if k not in protocols[_IPV6_CANONICAL]:
                protocols[_IPV6_CANONICAL][k] = v
        removed += 1
    protocols[_IPV6_CANONICAL]["rfcs"] = sorted(merged)
    if removed:
        print(
            f"Folded {removed} IPv6 extension-header row(s) into {_IPV6_CANONICAL}: "
            f"{', '.join(_IPV6_EXT_HEADER_ALIASES)}",
            file=sys.stderr,
        )
    return removed


_RFC_IPV4_ENCAP_IANA = 2003  # IANA "IPv4 encapsulation" reference for decimal 4
_RFC_ETHERNET_IPV6_PAYLOAD = 8986


def apply_iana_protocol_number_semantics(protocols: Dict[str, Dict[str, Any]]) -> None:
    """
    Encode registry-vs-graph intent so seeds match how we teach the protocols.

    IANA decimal **4** is named *IPv4 encapsulation* with Reference **RFC2003** (IP-in-IP),
    not the core IPv4 specification (**RFC791**). Graph seeds for keyword **IPV4** therefore
    use **791** when the CSV-derived set is only **{2003}**.

    **ETHERNET** (decimal 143) is the IPv6 next-header payload type from **RFC8986**, not
    IEEE 802.3; add a ``label`` when the seed cites only RFC8986.
    """

    ip4 = protocols.get("IPV4")
    if ip4:
        cur = {int(x) for x in (ip4.get("rfcs") or [])}
        if cur == {_RFC_IPV4_ENCAP_IANA}:
            ip4["rfcs"] = [RFC_IPV4_CORE]
            ip4.setdefault(
                "label",
                "IPv4 · Internet Protocol (IANA row documents encapsulation/RFC2003; seed uses RFC791)",
            )
            print(
                "IANA semantics: IPV4 seed uses RFC791 (CSV Reference was encapsulation/RFC2003 only).",
                file=sys.stderr,
            )

    eth = protocols.get("ETHERNET")
    if eth:
        rfcs = sorted(int(x) for x in (eth.get("rfcs") or []))
        if rfcs == [_RFC_ETHERNET_IPV6_PAYLOAD]:
            eth.setdefault(
                "label",
                "IP proto 143 · Ethernet payload in IPv6 (RFC8986 / SRv6)",
            )


def merge_network_seed_overrides(protocols: Dict[str, Dict[str, Any]], path: Path) -> int:
    """
    Shallow-merge per-protocol metadata from YAML into ``protocols`` (mutates in place).

    Optional ``replace_rfcs`` replaces the CSV-derived list. ``extra_rfcs`` is then
    unioned into ``rfcs``. Returns the number of override keys applied (for logging).
    """

    if not path.is_file():
        return 0
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ovr = raw.get("protocols") or {}
    if not isinstance(ovr, dict):
        return 0

    applied = 0
    for name, meta in ovr.items():
        if not isinstance(meta, dict):
            print(f"Override entry ignored (not a mapping): {name!r}", file=sys.stderr)
            continue
        if name not in protocols:
            print(f"Override skipped (not in IANA CSV output): {name}", file=sys.stderr)
            continue

        entry = protocols[name]
        repl = meta.get("replace_rfcs")
        if repl is not None:
            if not isinstance(repl, list):
                print(f"Override {name}: replace_rfcs must be a list, ignored", file=sys.stderr)
            else:
                entry["rfcs"] = sorted(int(x) for x in repl)
                applied += 1

        base_rfcs = {int(x) for x in (entry.get("rfcs") or [])}
        extra = meta.get("extra_rfcs") or []
        if extra:
            for x in extra:
                base_rfcs.add(int(x))
            entry["rfcs"] = sorted(base_rfcs)
            applied += 1

        for k, v in meta.items():
            if k in ("extra_rfcs", "replace_rfcs"):
                continue
            if k == "rfcs":
                print(
                    f"Override {name}: key 'rfcs' ignored (IANA CSV is authoritative); "
                    f"use 'extra_rfcs' to add RFC numbers.",
                    file=sys.stderr,
                )
                continue
            if v is None or v == "":
                continue
            entry[k] = v
            applied += 1

    return applied


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate protocol_seeds_network.yaml from IANA protocol-numbers CSV"
    )
    ap.add_argument(
        "-i",
        "--input",
        type=Path,
        default=DEFAULT_DATA_CSV,
        help=f"Local CSV path (default: {DEFAULT_DATA_CSV})",
    )
    ap.add_argument(
        "--download-url",
        default=DEFAULT_CSV_URL,
        help="URL to fetch when --fetch is used or when input file is missing",
    )
    ap.add_argument(
        "--fetch",
        action="store_true",
        help=f"Always download CSV from --download-url into --input path first",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output protocol_seeds_network.yaml path",
    )
    ap.add_argument("--max-depth", type=int, default=1, help="Written under expand.max_depth")
    ap.add_argument("--max-rfcs-total", type=int, default=250, help="Written under expand.max_rfcs_total")
    ap.add_argument(
        "--no-expand-default",
        action="store_true",
        help="Set expand.enabled to false in the generated YAML",
    )
    ap.add_argument(
        "--overrides",
        type=Path,
        default=DEFAULT_OVERRIDES_YAML,
        help=f"YAML file merged after CSV parse (default: {DEFAULT_OVERRIDES_YAML.name}; empty if missing)",
    )
    ap.add_argument(
        "--no-overrides",
        action="store_true",
        help="Do not merge --overrides even if the file exists",
    )
    ap.add_argument(
        "--iana-ipv6-extension-rows",
        action="store_true",
        help="Keep separate YAML seeds for IPv6 extension-header Next Header values (HOPOPT, IPV6-ICMP, …); default folds them into IPV6",
    )
    ap.add_argument(
        "--network-datatracker",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Union Datatracker title-search RFC hits into each seed (like app-layer rfc_fetch). Default: on; use --no-network-datatracker to skip.",
    )
    ap.add_argument(
        "--network-datatracker-cache",
        type=Path,
        default=NETWORK_DATATRACKER_CACHE,
        help="JSON cache for network Datatracker lookups",
    )
    ap.add_argument(
        "--no-network-datatracker-cache",
        action="store_true",
        help="Do not read/write network Datatracker cache",
    )
    ap.add_argument("--network-datatracker-workers", type=int, default=16)
    ap.add_argument("--network-datatracker-max-hits", type=int, default=10)
    ap.add_argument("--network-datatracker-min-phrase-len", type=int, default=2)
    ap.add_argument("--network-datatracker-max-phrases", type=int, default=8)
    ap.add_argument("--network-datatracker-timeout", type=float, default=45.0)
    ap.add_argument("--network-datatracker-retries", type=int, default=4)
    ap.add_argument(
        "--verify-network-datatracker-decimal-in-rfc-body",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "After Datatracker hits, drop RFCs whose plaintext does not mention this row’s IANA "
            "Decimal (protocol number). Uses rfc-editor .txt cache (default: shared output/rfc_fetch/rfc_txt). "
            "Use --no-verify-network-datatracker-decimal-in-rfc-body to skip."
        ),
    )
    ap.add_argument(
        "--network-datatracker-decimal-rfc-cache-dir",
        type=Path,
        default=OUTPUT_RFC_FETCH_TXT_CACHE,
        help="Directory for cached RFC .txt used by decimal-in-body filter",
    )
    ap.add_argument("--network-datatracker-decimal-prefetch-workers", type=int, default=12)
    ap.add_argument(
        "--strict-network-datatracker-decimal-verify",
        action="store_true",
        help="Drop Datatracker hits when RFC plaintext fetch fails (default: keep on failure)",
    )
    args = ap.parse_args(argv)

    if args.fetch or not args.input.is_file():
        try:
            print(f"Fetching {args.download_url} -> {args.input}", file=sys.stderr)
            download_csv(str(args.download_url), args.input)
        except urllib.error.HTTPError as e:
            print(f"HTTP error downloading CSV: {e}", file=sys.stderr)
            return 3
        except urllib.error.URLError as e:
            print(f"Network error downloading CSV: {e}", file=sys.stderr)
            return 3

    if not args.input.is_file():
        print(f"Missing CSV: {args.input} (use --fetch or place file manually)", file=sys.stderr)
        return 2

    with args.input.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    expected = {"Keyword", "Reference", "Decimal"}
    if rows and not expected.issubset(rows[0].keys()):
        print(
            "CSV columns look wrong; expected Keyword and Reference. Got: "
            + ", ".join(sorted(rows[0].keys())),
            file=sys.stderr,
        )
        return 2

    by_proto = collect_network_protocols(rows)
    if not by_proto:
        print("No eligible protocol-number rows in CSV (after Reserved / decimals 4,41 filters).", file=sys.stderr)
        return 2

    n_iana_only_empty = sum(1 for s in by_proto.values() if not s)
    if n_iana_only_empty:
        print(
            f"{n_iana_only_empty} seed id(s) have no RFC in IANA Reference; will try Datatracker only.",
            file=sys.stderr,
        )

    merge_datatracker_rfcs_into_by_proto(
        by_proto,
        rows,
        enable=bool(args.network_datatracker),
        cache_file=None if args.no_network_datatracker_cache else str(args.network_datatracker_cache),
        workers=max(1, int(args.network_datatracker_workers)),
        max_hits=max(1, int(args.network_datatracker_max_hits)),
        min_name_len=max(1, int(args.network_datatracker_min_phrase_len)),
        max_datatracker_phrases=max(1, int(args.network_datatracker_max_phrases)),
        timeout=float(args.network_datatracker_timeout),
        retries=max(0, int(args.network_datatracker_retries)),
        verify_decimal_in_rfc_body=bool(args.verify_network_datatracker_decimal_in_rfc_body),
        rfc_body_cache_dir=str(args.network_datatracker_decimal_rfc_cache_dir),
        rfc_body_prefetch_workers=max(1, int(args.network_datatracker_decimal_prefetch_workers)),
        strict_rfc_decimal_verify=bool(args.strict_network_datatracker_decimal_verify),
    )

    protocols: Dict[str, Dict[str, Any]] = {
        name: {"rfcs": sorted(nums)} for name, nums in sorted(by_proto.items()) if nums
    }
    n_dropped_empty = len(by_proto) - len(protocols)
    if n_dropped_empty:
        print(
            f"Omitted {n_dropped_empty} seed id(s) with empty rfcs after IANA ∪ Datatracker.",
            file=sys.stderr,
        )
    inject_core_internet_protocol_seeds(protocols)
    if not bool(args.iana_ipv6_extension_rows):
        fold_ipv6_extension_header_seeds(protocols)
    apply_iana_protocol_number_semantics(protocols)
    if not bool(args.no_overrides):
        n_ov = merge_network_seed_overrides(protocols, Path(args.overrides))
        if n_ov:
            print(f"Merged {n_ov} override field(s) from {args.overrides}", file=sys.stderr)

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
        f"Wrote {args.output} ({len(protocols)} protocol seeds; "
        f"{len(by_proto)} Keyword seed id(s) after CSV filters; decimals 4/41 skipped; IPV4/IPV6 injected)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
