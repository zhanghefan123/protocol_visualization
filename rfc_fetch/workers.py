"""Thread-pool worker entry points."""

from __future__ import annotations

import concurrent.futures
import os
import sys
from typing import TYPE_CHECKING, Any

from .datatracker import search_rfcs_by_title_phrase

if TYPE_CHECKING:
    from .datatracker_progress import DatatrackerHttpProgress


def lookup_datatracker_for_service(
    service_name: str,
    title_search_phrase: str,
    *,
    max_hits: int,
    timeout: float,
    max_retries: int,
    retry_sleep_base: float,
) -> tuple[str, list[dict[str, Any]]]:
    hits = search_rfcs_by_title_phrase(
        title_search_phrase,
        max_results=max_hits,
        timeout=timeout,
        max_retries=max_retries,
        retry_sleep_base=retry_sleep_base,
    )
    return service_name, hits


def lookup_datatracker_with_query_candidates(
    service_name: str,
    title_phrases: list[str],
    *,
    max_hits: int,
    max_queries: int,
    timeout: float,
    max_retries: int,
    retry_sleep_base: float,
    http_progress: DatatrackerHttpProgress | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Try several ``title__icontains`` phrases; merge RFC hits (dedupe by number), newest first overall.

    Phrases are queried with a **small inner thread pool** (default 3) so one Datatracker key does not
    spend 8× HTTP latency serially (which looks like a hang on an early tqdm step). Outer pool workers
    still cap total parallelism; set env ``RFC_FETCH_PHRASE_WORKERS=2`` to be gentler on 429.
    """

    phrase_list = [p.strip() for p in title_phrases[:max_queries] if p and p.strip()]
    if not phrase_list:
        return service_name, []

    trace = os.environ.get("RFC_FETCH_TRACE", "").strip() in ("1", "true", "yes", "on")
    if trace:
        print(
            f"[datatracker] {service_name!r}: {len(phrase_list)} phrase(s), fetching…",
            file=sys.stderr,
            flush=True,
        )

    merged: list[dict[str, Any]] = []
    seen: set[int] = set()
    per_cap = max(4, min(12, max_hits))

    def one(phrase: str) -> list[dict[str, Any]]:
        try:
            return search_rfcs_by_title_phrase(
                phrase,
                max_results=per_cap,
                timeout=timeout,
                max_retries=max_retries,
                retry_sleep_base=retry_sleep_base,
            )
        finally:
            if http_progress is not None:
                http_progress.complete_one()

    inner_n = max(1, min(int(os.environ.get("RFC_FETCH_PHRASE_WORKERS", "3")), len(phrase_list)))
    batches: list[list[str]] = []
    for i in range(0, len(phrase_list), inner_n):
        batches.append(phrase_list[i : i + inner_n])

    for batch in batches:
        if len(batch) == 1:
            partials = [one(batch[0])]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as ex:
                futs = [ex.submit(one, ph) for ph in batch]
                partials = [fut.result() for fut in concurrent.futures.as_completed(futs)]
        for partial in partials:
            for h in partial:
                n = int(h["rfc_number"])
                if n not in seen:
                    seen.add(n)
                    merged.append(h)
            if len(merged) >= max_hits:
                merged.sort(key=lambda h: int(h["rfc_number"]), reverse=True)
                return service_name, merged[:max_hits]

    merged.sort(key=lambda h: int(h["rfc_number"]), reverse=True)
    return service_name, merged[:max_hits]
