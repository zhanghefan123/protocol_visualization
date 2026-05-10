"""Fetch RFC plaintext from RFC Editor with a unified on-disk cache (see ``project_paths``)."""

from __future__ import annotations

import concurrent.futures
import re
import sys
from pathlib import Path
from typing import Any

from tqdm import tqdm

from .http_client import fetch_url

# Repo root on sys.path (run scripts from project root).
from project_paths import LEGACY_RFC_FETCH_TXT_DIR, RFC_BODY_CACHE_DIR

RFC_EDITOR_TXT_URL = "https://www.rfc-editor.org/rfc/rfc{n}.txt"


def _normalize_txt_cache_primary(cache_dir: Path | None) -> Path:
    return Path(cache_dir) if cache_dir is not None else RFC_BODY_CACHE_DIR


def _read_txt_with_legacy_fallback(primary: Path, rfc_number: int) -> str | None:
    legacy = LEGACY_RFC_FETCH_TXT_DIR
    name = f"rfc{rfc_number}.txt"
    primary_path = primary / name
    if primary_path.is_file():
        return primary_path.read_text(encoding="utf-8", errors="replace")
    if primary.resolve() == legacy.resolve():
        return None
    legacy_path = legacy / name
    if legacy_path.is_file():
        txt = legacy_path.read_text(encoding="utf-8", errors="replace")
        primary.mkdir(parents=True, exist_ok=True)
        try:
            primary_path.write_text(txt, encoding="utf-8")
        except OSError:
            pass
        return txt
    return None


def fetch_rfc_plaintext_cached(
    rfc_number: int,
    *,
    cache_dir: Path | None = None,
    timeout: float,
) -> str | None:
    primary = _normalize_txt_cache_primary(cache_dir)
    got = _read_txt_with_legacy_fallback(primary, rfc_number)
    if got is not None:
        return got

    primary.mkdir(parents=True, exist_ok=True)
    path = primary / f"rfc{rfc_number}.txt"
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
    cache_dir: Path | None = None,
    timeout: float,
    workers: int,
) -> None:
    nums = sorted(rfc_numbers)
    if not nums:
        return
    w = max(1, min(int(workers), len(nums)))
    total = len(nums)
    cd = _normalize_txt_cache_primary(cache_dir)

    def one(n: int) -> None:
        fetch_rfc_plaintext_cached(n, cache_dir=cd, timeout=timeout)

    with concurrent.futures.ThreadPoolExecutor(max_workers=w) as ex:
        futs = [ex.submit(one, n) for n in nums]
        for fut in tqdm(
            concurrent.futures.as_completed(futs),
            total=total,
            desc="RFC .txt prefetch",
            unit="file",
            file=sys.stderr,
            leave=False,
            dynamic_ncols=True,
            mininterval=0.25,
        ):
            fut.result()


def _port_reference_regex(port: int) -> re.Pattern[str]:
    """Match common RFC/I-D phrasing and service-list style ``80/tcp``."""

    n = str(int(port))
    return re.compile(
        rf"(?is)"
        rf"(?:\bport\b\s*(?:number|no\.?)?\s*[:#]?\s*{re.escape(n)}\b)"
        rf"|(?:\b{n}\s*/\s*(?:tcp|udp|sctp|dccp)\b)"
        rf"|(?:(?:tcp|udp|sctp|dccp)\s*/\s*{re.escape(n)}\b)"
        rf"|(?:\bwell[- ]known\s+port\s+{re.escape(n)}\b)"
    )


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
