"""Orchestrate IANA load, Datatracker concurrency, cache, and CSV export."""

from __future__ import annotations

import concurrent.futures
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .csv_export import write_wellknown_ports_csv
from .datatracker_progress import DatatrackerHttpProgress
from .http_client import write_json_atomic
from .iana import (
    build_datatracker_title_queries,
    datatracker_title_query_candidates,
    has_usable_service_name,
    iter_well_known_named_rows,
    iter_well_known_port_rows,
    load_iana_rows,
    parse_iana_rfc_numbers,
    row_datatracker_lookup_key,
    unique_sorted_lookup_keys,
)
from .workers import lookup_datatracker_with_query_candidates

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from project_paths import OUTPUT_RFC_FETCH_TXT_CACHE


def _planned_datatracker_http_count(to_fetch_jobs: list[tuple[str, tuple[str, ...]]]) -> int:
    return sum(len([p for p in qt if p and p.strip()]) for _, qt in to_fetch_jobs)


def _cache_query_tuple(cached: Any) -> tuple[str, ...] | None:
    if not isinstance(cached, dict):
        return None
    qv = cached.get("queries")
    if isinstance(qv, list) and qv and all(isinstance(x, str) for x in qv):
        return tuple(qv)
    if isinstance(cached.get("query"), str):
        return (cached["query"],)
    return None


def _cache_matches_queries(cached: Any, expected: tuple[str, ...]) -> bool:
    if _cache_query_tuple(cached) != expected:
        return False
    return isinstance(cached.get("hits"), list)


def _hits_from_cached(cached: Any) -> list[dict[str, Any]]:
    assert isinstance(cached, dict)
    return list(cached["hits"])  # type: ignore[list-item]


def cache_entry_queries(lookup_key: str, queries: tuple[str, ...], hits: list[dict[str, Any]]) -> dict[str, Any]:
    return {"queries": list(queries), "query": queries[0] if queries else "", "hits": hits}


def _rfc_nums_for_port_verify(
    rows: list[dict[str, str]],
    name_hits: dict[str, list[dict[str, Any]]],
) -> set[int]:
    nums: set[int] = set()
    for r in rows:
        port_s = (r.get("Port Number") or "").strip()
        if not port_s.isdigit():
            continue
        lk = row_datatracker_lookup_key(r)
        for h in name_hits.get(lk, []):
            nums.add(int(h["rfc_number"]))
    return nums


@dataclass(frozen=True)
class BuildConfig:
    output: str
    workers: int
    max_hits: int
    min_name_len: int
    timeout: float
    retries: int
    cache_file: str | None  # None => --no-cache
    limit_unique_names: int
    cache_flush_every: int
    named_only: bool
    write_rows_without_rfc_hints: bool
    max_datatracker_phrases: int
    verify_port_in_rfc_body: bool
    rfc_body_cache_dir: str | None
    rfc_body_prefetch_workers: int
    strict_rfc_port_verify: bool


def load_cache(cache_path: str) -> dict[str, Any]:
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def run_build(cfg: BuildConfig) -> int:
    print("Loading IANA CSV…", file=sys.stderr)
    raw = load_iana_rows()
    rows = iter_well_known_named_rows(raw) if cfg.named_only else iter_well_known_port_rows(raw)
    title_query_for_service = build_datatracker_title_queries(rows)

    cache_path = cfg.cache_file
    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    cache: dict[str, Any] = load_cache(cache_path) if cache_path else {}

    unique_names = unique_sorted_lookup_keys(rows)
    if cfg.limit_unique_names > 0:
        unique_names = unique_names[: cfg.limit_unique_names]

    n_synth = sum(1 for r in rows if not has_usable_service_name(r))
    print(
        f"Well-known port rows: {len(rows)}"
        + (" (Service Name required)" if cfg.named_only else f" (synthetic-key candidates: {n_synth})")
        + f"; unique Datatracker keys: {len(unique_names)}",
        file=sys.stderr,
    )

    phrases_by_key: dict[str, tuple[str, ...]] = {
        name: tuple(
            datatracker_title_query_candidates(
                name,
                title_query_for_service[name],
                min_len=cfg.min_name_len,
                max_phrases=cfg.max_datatracker_phrases,
            )
        )
        for name in unique_names
    }

    name_hits: dict[str, list[dict[str, Any]]] = {}
    to_fetch_jobs: list[tuple[str, tuple[str, ...]]] = []

    for name in unique_names:
        qt = phrases_by_key[name]
        if not qt:
            name_hits[name] = []
            continue
        cached = cache.get(name)
        if cached is not None and _cache_matches_queries(cached, qt):
            name_hits[name] = _hits_from_cached(cached)
            continue
        to_fetch_jobs.append((name, qt))

    pending = len(to_fetch_jobs)
    skipped_short = sum(1 for n in unique_names if not phrases_by_key[n])
    reuse = len(unique_names) - pending - skipped_short
    print(
        f"Datatracker: {pending} fetch(es), {reuse} reuse(s) from cache, "
        f"{skipped_short} skipped (no query phrases ≥ --min-name-len={cfg.min_name_len}); "
        f"workers={cfg.workers}; multi-phrase title search (merged hits, max {cfg.max_datatracker_phrases} phrases/key)",
        file=sys.stderr,
        flush=True,
    )

    flush_every = max(0, cfg.cache_flush_every)
    new_since_flush = 0
    workers_n = max(1, cfg.workers)

    http_progress: DatatrackerHttpProgress | None = None
    if pending:
        total_http = _planned_datatracker_http_count(to_fetch_jobs)
        if total_http > 0:
            http_progress = DatatrackerHttpProgress(total_http)
            http_progress.start()
        print(
            "Datatracker: 已提交请求；下方进度条统计 **HTTP 请求** 次数（每个 title 短语 1 次；"
            "分母为计划上限，若某键提前凑满命中数会少于分母）。",
            file=sys.stderr,
            flush=True,
        )
        done_n = 0
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers_n) as executor:
                future_to_label = {
                    executor.submit(
                        lookup_datatracker_with_query_candidates,
                        name,
                        list(qt),
                        max_hits=cfg.max_hits,
                        max_queries=len(qt),
                        timeout=cfg.timeout,
                        max_retries=cfg.retries,
                        retry_sleep_base=0.5,
                        http_progress=http_progress,
                    ): name
                    for name, qt in to_fetch_jobs
                }
                for fut in concurrent.futures.as_completed(future_to_label):
                    expected = future_to_label[fut]
                    done_n += 1
                    try:
                        nm, hits = fut.result()
                    except Exception as e:
                        print(f"FAILED {expected!r}: {e}", file=sys.stderr)
                        raise
                    name_hits[nm] = hits
                    if cache_path:
                        cache[nm] = cache_entry_queries(nm, phrases_by_key[nm], hits)
                        new_since_flush += 1
                        if flush_every and new_since_flush >= flush_every:
                            write_json_atomic(cache_path, cache)
                            new_since_flush = 0
                    if http_progress is None and (
                        done_n <= 10
                        or done_n % 25 == 0
                        or done_n == pending
                    ):
                        print(f"Datatracker progress {done_n}/{pending}", file=sys.stderr, flush=True)
        finally:
            if http_progress is not None:
                http_progress.end_line()
            if cache_path and pending:
                write_json_atomic(cache_path, cache)

    if cfg.limit_unique_names > 0:
        allowed = frozenset(unique_names)
        rows = [r for r in rows if row_datatracker_lookup_key(r) in allowed]

    n_hintless = 0
    for r in rows:
        lk = row_datatracker_lookup_key(r)
        ref = (r.get("Reference") or "").strip()
        if not parse_iana_rfc_numbers(ref) and not (name_hits.get(lk) or []):
            n_hintless += 1
    print(
        f"Rows with no RFC hint (IANA Reference + Datatracker): {n_hintless}"
        + (
            " — emitting them because --write-rows-without-rfc-hints"
            if cfg.write_rows_without_rfc_hints and n_hintless
            else (
                " — omitting them (use --write-rows-without-rfc-hints to add CSV lines with empty RFC columns)"
                if n_hintless
                else ""
            )
        ),
        file=sys.stderr,
    )

    body_cache_path: Path | None = None
    if cfg.verify_port_in_rfc_body:
        print(
            "RFC port filter: Datatracker hits are kept only if rfc-editor plaintext mentions this row’s "
            f"port (e.g. «port 80», «80/tcp»). Default .txt cache: {OUTPUT_RFC_FETCH_TXT_CACHE} "
            "(override: --rfc-body-cache-dir).",
            file=sys.stderr,
            flush=True,
        )
        body_cache_path = Path(cfg.rfc_body_cache_dir) if cfg.rfc_body_cache_dir else OUTPUT_RFC_FETCH_TXT_CACHE
        from .rfc_body_port import prefetch_rfc_plaintexts

        prefetch_rfc_plaintexts(
            _rfc_nums_for_port_verify(rows, name_hits),
            cache_dir=body_cache_path,
            timeout=cfg.timeout,
            workers=max(1, int(cfg.rfc_body_prefetch_workers)),
        )

    n_out, n_skip = write_wellknown_ports_csv(
        cfg.output,
        rows=rows,
        name_hits=name_hits,
        title_query_for_service=title_query_for_service,
        write_rows_without_rfc_hints=cfg.write_rows_without_rfc_hints,
        verify_port_in_rfc_body=cfg.verify_port_in_rfc_body,
        rfc_body_cache_dir=body_cache_path,
        rfc_body_timeout=cfg.timeout,
        strict_rfc_port_verify=cfg.strict_rfc_port_verify,
    )
    print(
        f"Wrote {cfg.output} ({n_out} data rows; skipped {n_skip} with no IANA RFC and no Datatracker hits"
        + ("; hintless rows included" if cfg.write_rows_without_rfc_hints else "")
        + ")",
        file=sys.stderr,
    )
    return 0
