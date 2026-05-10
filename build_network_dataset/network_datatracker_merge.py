"""
Merge IETF Datatracker title-search hits into network-layer protocol seed RFC sets,
mirroring the application-layer rfc_fetch strategy (multi-phrase title__icontains + JSON cache).
"""

from __future__ import annotations

import concurrent.futures
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rfc_fetch.datatracker_progress import DatatrackerHttpProgress
from rfc_fetch.http_client import write_json_atomic
from rfc_fetch.iana import (
    datatracker_protocol_query,
    datatracker_title_query_candidates,
    normalize_search_phrase,
)
from rfc_fetch.pipeline import (
    cache_entry_queries,
    load_cache,
)
from rfc_fetch.workers import lookup_datatracker_with_query_candidates

from network_rfc_decimal_verify import (
    filter_datatracker_hits_by_protocol_decimal,
    prefetch_for_hits,
)


def _keyword_to_seed_id(keyword_raw: str) -> str:
    k = (keyword_raw or "").strip().upper()
    k = re.sub(r"\([^)]*\)", "", k).strip()
    k = k.replace("/", "-")
    k = re.sub(r"[^\w\-]+", "-", k.replace(" ", "-"))
    k = re.sub(r"-+", "-", k).strip("-")
    return k


def _decimal_first(raw: str) -> int | None:
    s = (raw or "").strip()
    if not s:
        return None
    head = s.split("-", 1)[0].strip()
    try:
        return int(head)
    except ValueError:
        return None


def _row_eligible(row: dict[str, str]) -> bool:
    kw_raw = row.get("Keyword") or ""
    if re.fullmatch(r"(?i)reserved", kw_raw.strip()):
        return False
    dec0 = _decimal_first(row.get("Decimal") or "")
    if dec0 in (4, 41):
        return False
    return bool(_keyword_to_seed_id(kw_raw))


def decimals_by_seed_id(rows: list[dict[str, str]]) -> dict[str, set[int]]:
    """IANA *Decimal* column values per seed id (eligible rows only)."""

    by_seed: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        if not _row_eligible(row):
            continue
        sid = _keyword_to_seed_id(row.get("Keyword") or "")
        if not sid:
            continue
        d = _decimal_first(row.get("Decimal") or "")
        if d is not None:
            by_seed[sid].add(d)
    return {k: v for k, v in by_seed.items() if v}


def keyword_datatracker_text_variants(keyword_raw: str) -> list[str]:
    """
    Build human-style title phrases from IANA *Keyword* for Datatracker ``title__icontains``.

    - Hyphens between word chars become spaces (``IPv6-Opts`` → ``IPv6 Opts``).
    - Slashes become spaces.
    - Split on ``for`` / ``over`` / ``and`` / ``via`` so ``ISIS over IPv4`` also tries ``ISIS`` and ``IPv4``.
    """

    k = (keyword_raw or "").strip()
    if not k:
        return []
    k = re.sub(r"\([^)]*\)", "", k).strip()
    k = k.replace("\u2013", "-").replace("\u2014", "-").replace("/", " ")
    # Hyphen linking tokens (IPv6-Opts, Foo-Bar) → space-separated words for RFC titles.
    k = re.sub(r"(?<=[\w\d])-(?=[\w\d])", " ", k)
    k = normalize_search_phrase(k)
    if len(k) < 2:
        return []

    out: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        t = normalize_search_phrase(s)
        if len(t) < 2:
            return
        key = t.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append(t)

    add(k)
    for part in re.split(r"(?i)\s+(?:for|over|and|via)\s+", k):
        add(part.strip())

    return out


def gather_keyword_variants_by_seed(rows: list[dict[str, str]]) -> dict[str, list[str]]:
    """Per seed id: ordered unique Keyword-derived phrases (before Protocol column merge)."""

    by_seed: dict[str, list[str]] = defaultdict(list)
    seen_sid: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        if not _row_eligible(row):
            continue
        sid = _keyword_to_seed_id(row.get("Keyword") or "")
        if not sid:
            continue
        for v in keyword_datatracker_text_variants(row.get("Keyword") or ""):
            k = v.casefold()
            if k in seen_sid[sid]:
                continue
            seen_sid[sid].add(k)
            by_seed[sid].append(v)
    return dict(by_seed)


def gather_protocol_descriptions_by_seed(rows: list[dict[str, str]]) -> dict[str, list[str]]:
    """Protocol column texts per seed id for all eligible rows (including Reference without RFC)."""

    by_seed: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if not _row_eligible(row):
            continue
        sid = _keyword_to_seed_id(row.get("Keyword") or "")
        if not sid:
            continue
        proto = (row.get("Protocol") or "").strip()
        if proto:
            by_seed[sid].append(proto)
    return dict(by_seed)


def build_datatracker_phrases_by_seed(
    rows: list[dict[str, str]],
    seed_ids: set[str],
    *,
    min_len: int,
    max_phrases: int,
) -> dict[str, tuple[str, ...]]:
    desc_by_seed = gather_protocol_descriptions_by_seed(rows)
    kw_by_seed = gather_keyword_variants_by_seed(rows)
    out: dict[str, tuple[str, ...]] = {}
    for sid in sorted(seed_ids):
        # Keyword-derived phrases first (split hyphens / FOR-OVER-AND), then *Protocol* column.
        # Sort Protocol texts so merged order does not depend on IANA CSV row order (stable queries / cache).
        desc_sorted = sorted(desc_by_seed.get(sid, []), key=lambda s: s.casefold())
        merged: list[str] = []
        seen_cf: set[str] = set()
        for t in kw_by_seed.get(sid, []) + desc_sorted:
            nt = normalize_search_phrase(t)
            if len(nt) < min_len:
                continue
            cf = nt.casefold()
            if cf in seen_cf:
                continue
            seen_cf.add(cf)
            merged.append(nt)
        primary = datatracker_protocol_query(sid, merged)
        out[sid] = tuple(
            datatracker_title_query_candidates(
                sid,
                primary,
                min_len=min_len,
                max_phrases=max_phrases,
            )
        )
    return out


def _cache_query_tuple(cached: Any) -> tuple[str, ...] | None:
    if not isinstance(cached, dict):
        return None
    qv = cached.get("queries")
    if isinstance(qv, list) and qv and all(isinstance(x, str) for x in qv):
        return tuple(qv)
    if isinstance(cached.get("query"), str):
        return (cached["query"],)
    return None


def _hits_from_cached(cached: Any) -> list[dict[str, Any]]:
    assert isinstance(cached, dict)
    return list(cached["hits"])  # type: ignore[list-item]


def _planned_http_count(jobs: list[tuple[str, tuple[str, ...]]]) -> int:
    return sum(len([p for p in qt if p and p.strip()]) for _, qt in jobs)


def merge_datatracker_rfcs_into_by_proto(
    by_proto: dict[str, set[int]],
    rows: list[dict[str, str]],
    *,
    enable: bool,
    cache_file: str | None,
    workers: int,
    max_hits: int,
    min_name_len: int,
    max_datatracker_phrases: int,
    timeout: float,
    retries: int,
    verify_decimal_in_rfc_body: bool,
    rfc_body_cache_dir: str | None,
    rfc_body_prefetch_workers: int,
    strict_rfc_decimal_verify: bool,
) -> None:
    """Union Datatracker hit RFC numbers into *by_proto* (mutates in place)."""

    if not enable:
        return

    seed_ids = set(by_proto.keys())
    if not seed_ids:
        return

    phrases_by_key = build_datatracker_phrases_by_seed(
        rows,
        seed_ids,
        min_len=min_name_len,
        max_phrases=max_datatracker_phrases,
    )

    cache: dict[str, Any] = load_cache(cache_file) if cache_file else {}
    if cache_file:
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)

    name_hits: dict[str, list[dict[str, Any]]] = {}
    to_fetch: list[tuple[str, tuple[str, ...]]] = []

    miss_no_entry = 0
    miss_bad_hits_shape = 0
    miss_queries = 0
    dbg = os.environ.get("NETWORK_DT_CACHE_DEBUG", "").strip() in ("1", "true", "yes", "on")

    for sid in sorted(seed_ids):
        qt = phrases_by_key.get(sid, ())
        if not qt:
            continue
        cached = cache.get(sid) if cache_file else None
        if cached is None:
            miss_no_entry += 1
            if dbg:
                print(f"  [network-dt cache] no entry: {sid}", file=sys.stderr, flush=True)
            to_fetch.append((sid, qt))
            continue
        if not isinstance(cached.get("hits"), list):
            miss_bad_hits_shape += 1
            if dbg:
                print(f"  [network-dt cache] hits not a list: {sid}", file=sys.stderr, flush=True)
            to_fetch.append((sid, qt))
            continue
        old_q = _cache_query_tuple(cached)
        if old_q != qt:
            miss_queries += 1
            if dbg:
                print(
                    f"  [network-dt cache] queries differ: {sid} "
                    f"(cached_len={len(old_q or ())}, now_len={len(qt)})",
                    file=sys.stderr,
                    flush=True,
                )
            to_fetch.append((sid, qt))
            continue
        name_hits[sid] = _hits_from_cached(cached)

    pending = len(to_fetch)
    skipped_short = sum(1 for sid in seed_ids if not phrases_by_key.get(sid, ()))
    reuse = len(seed_ids) - skipped_short - pending
    print(
        f"Network Datatracker: {pending} fetch(es), {reuse} cache hit(s), "
        f"{skipped_short} skipped (no query phrases ≥ min_len={min_name_len}); "
        f"workers={workers}; max {max_datatracker_phrases} phrases/key",
        file=sys.stderr,
        flush=True,
    )
    if cache_file and pending:
        parts = []
        if miss_no_entry:
            parts.append(f"no_cache_entry={miss_no_entry}")
        if miss_queries:
            parts.append(f"queries_tuple_changed={miss_queries}")
        if miss_bad_hits_shape:
            parts.append(f"bad_hits_json={miss_bad_hits_shape}")
        if parts:
            print(
                "Network Datatracker cache misses — "
                + "; ".join(parts)
                + ". "
                "Same CSV + same code should yield 0 misses once every eligible sid is written to the cache file. "
                "Changing phrase logic or IANA text invalidates entries when the stored queries tuple differs. "
                "Set NETWORK_DT_CACHE_DEBUG=1 to print each sid.",
                file=sys.stderr,
                flush=True,
            )

    workers_n = max(1, workers)
    http_progress: DatatrackerHttpProgress | None = None

    if pending:
        total_http = _planned_http_count(to_fetch)
        if total_http > 0:
            http_progress = DatatrackerHttpProgress(total_http)
            http_progress.start()
        print(
            "Network Datatracker: HTTP progress bar counts title-search requests per phrase.",
            file=sys.stderr,
            flush=True,
        )
        done_n = 0
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers_n) as ex:
                fut_map = {
                    ex.submit(
                        lookup_datatracker_with_query_candidates,
                        sid,
                        list(qt),
                        max_hits=max_hits,
                        max_queries=len(qt),
                        timeout=timeout,
                        max_retries=retries,
                        retry_sleep_base=0.5,
                        http_progress=http_progress,
                    ): sid
                    for sid, qt in to_fetch
                }
                for fut in concurrent.futures.as_completed(fut_map):
                    sid = fut_map[fut]
                    done_n += 1
                    nm, hits = fut.result()
                    name_hits[nm] = hits
        finally:
            if http_progress is not None:
                http_progress.end_line()

    dec_map = decimals_by_seed_id(rows)
    body_cache = Path(rfc_body_cache_dir) if rfc_body_cache_dir else None
    if verify_decimal_in_rfc_body and body_cache is not None and name_hits:
        print(
            "Network Datatracker: filtering hits whose plaintext lacks this seed’s IANA Decimal "
            f"(protocol number); RFC .txt cache: {body_cache}",
            file=sys.stderr,
            flush=True,
        )
        prefetch_for_hits(
            name_hits,
            cache_dir=body_cache,
            timeout=timeout,
            workers=max(1, int(rfc_body_prefetch_workers)),
        )
        n_before = sum(len(hs) for hs in name_hits.values())
        for sid in list(name_hits.keys()):
            decs = dec_map.get(sid, set())
            name_hits[sid] = filter_datatracker_hits_by_protocol_decimal(
                name_hits[sid],
                decs,
                cache_dir=body_cache,
                timeout=timeout,
                keep_on_fetch_failure=not strict_rfc_decimal_verify,
            )
        n_after = sum(len(hs) for hs in name_hits.values())
        print(
            f"Network decimal-in-body filter: {n_before} → {n_after} Datatracker hit row(s).",
            file=sys.stderr,
            flush=True,
        )
    elif verify_decimal_in_rfc_body and not body_cache:
        print(
            "Network Datatracker: verify_decimal_in_rfc_body set but no cache dir; skipping body filter.",
            file=sys.stderr,
            flush=True,
        )

    if cache_file:
        for sid in sorted(seed_ids):
            qt = phrases_by_key.get(sid, ())
            if not qt or sid not in name_hits:
                continue
            cache[sid] = cache_entry_queries(sid, qt, name_hits[sid])
        write_json_atomic(cache_file, cache)

    merged_keys = 0
    extra_rfcs = 0
    for sid in seed_ids:
        hits = name_hits.get(sid, [])
        if not hits:
            continue
        before = len(by_proto[sid])
        for h in hits:
            by_proto[sid].add(int(h["rfc_number"]))
        if len(by_proto[sid]) > before:
            merged_keys += 1
            extra_rfcs += len(by_proto[sid]) - before

    print(
        f"Network Datatracker merge: {merged_keys} seed(s) gained RFC(s) ({extra_rfcs} new RFC id(s) total).",
        file=sys.stderr,
        flush=True,
    )
