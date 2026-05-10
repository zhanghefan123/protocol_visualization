"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from project_paths import IANA_DATATRACKER_CACHE, IANA_PORTS_CSV, OUTPUT_RFC_FETCH_TXT_CACHE

from .pipeline import BuildConfig, run_build

_PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_CSV = IANA_PORTS_CSV
DEFAULT_DATATRACKER_CACHE = IANA_DATATRACKER_CACHE


def build_argument_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rfc-fetch",
        description="IANA well-known ports + Datatracker RFC lookup → CSV.",
    )
    p.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUTPUT_CSV),
        help=f"Output CSV path (default: {DEFAULT_OUTPUT_CSV})",
    )
    p.add_argument(
        "-j",
        "--workers",
        type=int,
        default=24,
        help="Concurrent Datatracker HTTP workers",
    )
    p.add_argument(
        "--max-hits",
        type=int,
        default=10,
        help="Maximum RFC rows to keep per service name from Datatracker",
    )
    p.add_argument(
        "--min-name-len",
        type=int,
        default=2,
        help="Skip Datatracker if the derived title phrase (IANA Description fallback: Service Name) "
        "is shorter than this",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=45.0,
        help="HTTP timeout in seconds",
    )
    p.add_argument(
        "--retries",
        type=int,
        default=4,
        help="Retries for transient HTTP errors",
    )
    p.add_argument(
        "--cache-file",
        default=str(DEFAULT_DATATRACKER_CACHE),
        help=f"JSON cache for Datatracker responses (default: {DEFAULT_DATATRACKER_CACHE})",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable reading/writing the cache file",
    )
    p.add_argument(
        "--limit-unique-names",
        type=int,
        default=0,
        help="Fetch only the first N unique names (sanity check)",
    )
    p.add_argument(
        "--cache-flush-every",
        type=int,
        default=80,
        help="Persist cache after this many new lookups (0 = end only)",
    )
    p.add_argument(
        "--named-only",
        action="store_true",
        help="Drop well-known rows with empty Service Name (legacy behaviour; default includes unnamed)",
    )
    p.add_argument(
        "--write-rows-without-rfc-hints",
        action="store_true",
        help="Also write rows with no [RFC] in IANA Reference and no Datatracker hits (empty RFC columns)",
    )
    p.add_argument(
        "--max-datatracker-phrases",
        type=int,
        default=8,
        help="Max title__icontains phrases per lookup key (extra phrases = splits/tokens from Description). "
        "Use 1 for a single query: primary IANA phrase only (no phrase expansion).",
    )
    p.add_argument(
        "--single-datatracker-query",
        action="store_true",
        help="Same as --max-datatracker-phrases 1: one HTTP title search per lookup key.",
    )
    p.add_argument(
        "--verify-port-in-rfc-body",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "After Datatracker hits, drop RFCs whose plaintext does not mention this row’s port "
            "(e.g. port N, N/tcp); fetches rfc-editor.org/rfc/rfcN.txt (cached). Default: on; "
            "use --no-verify-port-in-rfc-body to skip."
        ),
    )
    p.add_argument(
        "--rfc-body-cache-dir",
        default=None,
        help=f"Directory for cached RFC .txt files (default: {OUTPUT_RFC_FETCH_TXT_CACHE})",
    )
    p.add_argument(
        "--rfc-body-prefetch-workers",
        type=int,
        default=12,
        help="Parallel downloads when prefetching RFC plaintext for port-in-body verification",
    )
    p.add_argument(
        "--strict-rfc-port-verify",
        action="store_true",
        help="With port-in-body verification, drop hits when RFC plaintext fetch fails (default: keep on failure)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    max_phrases = 1 if args.single_datatracker_query else max(1, int(args.max_datatracker_phrases))
    cfg = BuildConfig(
        output=args.output,
        workers=args.workers,
        max_hits=args.max_hits,
        min_name_len=args.min_name_len,
        timeout=args.timeout,
        retries=args.retries,
        cache_file=None if args.no_cache else args.cache_file,
        limit_unique_names=args.limit_unique_names,
        cache_flush_every=args.cache_flush_every,
        named_only=bool(args.named_only),
        write_rows_without_rfc_hints=bool(args.write_rows_without_rfc_hints),
        max_datatracker_phrases=max_phrases,
        verify_port_in_rfc_body=args.verify_port_in_rfc_body,
        rfc_body_cache_dir=args.rfc_body_cache_dir,
        rfc_body_prefetch_workers=max(1, int(args.rfc_body_prefetch_workers)),
        strict_rfc_port_verify=bool(args.strict_rfc_port_verify),
    )
    return run_build(cfg)
