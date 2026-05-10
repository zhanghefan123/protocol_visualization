"""Fetch RFC plaintext and verify the IANA well-known *port* appears (e.g. ``port 80``)."""

from __future__ import annotations

import concurrent.futures
import re
import sys
from pathlib import Path
from typing import Any

from .http_client import fetch_url

RFC_EDITOR_TXT_URL = "https://www.rfc-editor.org/rfc/rfc{n}.txt"


def _port_reference_regex(port: int) -> re.Pattern[str]:
    """Match common RFC/I-D phrasing and service-list style ``80/tcp``."""

    n = str(int(port))
    # Word boundary around the port digit string avoids matching 80 inside 8080.
    return re.compile(
        rf"(?is)"
        rf"(?:\bport\b\s*(?:number|no\.?)?\s*[:#]?\s*{re.escape(n)}\b)"
        rf"|(?:\b{n}\s*/\s*(?:tcp|udp|sctp|dccp)\b)"
        rf"|(?:(?:tcp|udp|sctp|dccp)\s*/\s*{re.escape(n)}\b)"
        rf"|(?:\bwell[- ]known\s+port\s+{re.escape(n)}\b)"
    )


def fetch_rfc_plaintext_cached(
    rfc_number: int,
    *,
    cache_dir: Path,
    timeout: float,
) -> str | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"rfc{rfc_number}.txt"
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    url = RFC_EDITOR_TXT_URL.format(n=rfc_number)
    try:
        raw = fetch_url(url, timeout=timeout)
        text = raw.decode("utf-8", errors="replace")
        path.write_text(text, encoding="utf-8")
        return text
    except OSError as e:
        print(f"RFC{rfc_number} plaintext fetch failed ({url}): {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"RFC{rfc_number} plaintext fetch failed ({url}): {e}", file=sys.stderr)
        return None


def prefetch_rfc_plaintexts(
    rfc_numbers: set[int],
    *,
    cache_dir: Path,
    timeout: float,
    workers: int,
) -> None:
    nums = sorted(rfc_numbers)
    if not nums:
        return
    w = max(1, min(int(workers), len(nums)))
    total = len(nums)

    def one(n: int) -> None:
        fetch_rfc_plaintext_cached(n, cache_dir=cache_dir, timeout=timeout)

    print(
        f"Prefetching {total} RFC .txt file(s) for port-in-body checks "
        f"(workers={w}; timeout up to {timeout:g}s each)…",
        file=sys.stderr,
        flush=True,
    )
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=w) as ex:
        futs = [ex.submit(one, n) for n in nums]
        for fut in concurrent.futures.as_completed(futs):
            fut.result()
            done += 1
            if done <= 10 or done % 25 == 0 or done == total:
                print(f"RFC plaintext prefetch {done}/{total}", file=sys.stderr, flush=True)
    print("RFC plaintext prefetch done.", file=sys.stderr, flush=True)


def port_mentioned_in_rfc_plaintext(port: int, body: str) -> bool:
    if body is None or not body:
        return False
    return bool(_port_reference_regex(port).search(body))


def hit_passes_port_in_body(
    hit: dict[str, Any],
    port: int,
    *,
    cache_dir: Path,
    timeout: float,
    keep_on_fetch_failure: bool,
) -> bool:
    num = int(hit["rfc_number"])
    body = fetch_rfc_plaintext_cached(num, cache_dir=cache_dir, timeout=timeout)
    if body is None:
        return keep_on_fetch_failure
    return port_mentioned_in_rfc_plaintext(port, body)


def filter_datatracker_hits_by_port_in_rfc(
    hits: list[dict[str, Any]],
    port: int,
    *,
    cache_dir: Path,
    timeout: float,
    keep_on_fetch_failure: bool,
) -> list[dict[str, Any]]:
    if not hits:
        return hits
    out: list[dict[str, Any]] = []
    for h in hits:
        if hit_passes_port_in_body(
            h,
            port,
            cache_dir=cache_dir,
            timeout=timeout,
            keep_on_fetch_failure=keep_on_fetch_failure,
        ):
            out.append(h)
    return out
