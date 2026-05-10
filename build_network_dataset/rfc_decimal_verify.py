"""Verify RFC plaintext mentions an IANA IP protocol *Decimal* (assigned protocol number)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rfc_fetch.rfc_body_port import fetch_rfc_plaintext_cached, prefetch_rfc_plaintexts


def _regex_for_decimal(d: int) -> re.Pattern[str]:
    """Match registry-style protocol number mentions; include literal ``N (decimal)`` style."""

    n = re.escape(str(int(d)))
    # Single-digit protocol numbers appear in many unrelated numeric contexts — require stronger cues.
    if d < 10:
        return re.compile(
            rf"(?is)"
            rf"(?:\bprotocol\b\s*(?:number|no\.?)?\s*[:#]?\s*{n}\b)"
            rf"|(?:\b(?:ip\s*)?protocol\s+{n}\b)"
            rf"|(?:\bnext\s+header\b\s*(?:value)?\s*[:#]?\s*{n}\b)"
            rf"|(?:\bassigned\b[^\n]{{0,24}}{n}\b)"
            rf"|(?:\({n}\)\s*\(\s*decimal\s*\))"
            rf"|(?:\b{n}\s*\(\s*decimal\s*\))"
        )
    return re.compile(
        rf"(?is)"
        rf"(?:\bprotocol\b\s*(?:number|no\.?)?\s*[:#]?\s*{n}\b)"
        rf"|(?:\bdecimal\b\s+{n}\b)"
        rf"|(?:\bassigned\b[^\n]{{0,40}}{n}\b)"
        rf"|(?:\bnext\s+header\b\s*(?:value)?\s*[:#]?\s*{n}\b)"
        rf"|(?:\({n}\)\s*\(\s*decimal\s*\))"
        rf"|(?:\b{n}\s*\(\s*decimal\s*\))"
        rf"|(?:\b{n}\s*\(\s*protocol\s*(?:number)?\s*\))"
        # Table-ish lines: "| 124 |" or " 124  "
        rf"(?:\|\s*{n}\s*\|)"
        rf"|(?<![0-9]){n}(?![0-9])"
    )


def protocol_decimal_mentioned_in_body(decimals: set[int], body: str) -> bool:
    """True if *body* appears to assign / list any of *decimals* as an IP protocol number."""

    if not decimals:
        return True
    if not (body or "").strip():
        return False
    for d in decimals:
        if _regex_for_decimal(d).search(body):
            return True
    return False


def hit_passes_decimal_in_rfc_body(
    hit: dict[str, Any],
    decimals: set[int],
    *,
    cache_dir: Path,
    timeout: float,
    keep_on_fetch_failure: bool,
) -> bool:
    num = int(hit["rfc_number"])
    body = fetch_rfc_plaintext_cached(num, cache_dir=cache_dir, timeout=timeout)
    if body is None:
        return keep_on_fetch_failure
    return protocol_decimal_mentioned_in_body(decimals, body)


def filter_datatracker_hits_by_protocol_decimal(
    hits: list[dict[str, Any]],
    decimals: set[int],
    *,
    cache_dir: Path,
    timeout: float,
    keep_on_fetch_failure: bool,
) -> list[dict[str, Any]]:
    if not hits:
        return hits
    out: list[dict[str, Any]] = []
    for h in hits:
        if hit_passes_decimal_in_rfc_body(
            h,
            decimals,
            cache_dir=cache_dir,
            timeout=timeout,
            keep_on_fetch_failure=keep_on_fetch_failure,
        ):
            out.append(h)
    return out


def prefetch_for_hits(hits_by_seed: dict[str, list[dict[str, Any]]], *, cache_dir: Path, timeout: float, workers: int) -> None:
    nums: set[int] = set()
    for hs in hits_by_seed.values():
        for h in hs:
            nums.add(int(h["rfc_number"]))
    prefetch_rfc_plaintexts(nums, cache_dir=cache_dir, timeout=timeout, workers=max(1, workers))
