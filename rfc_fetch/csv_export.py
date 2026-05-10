"""Formatting and writing the result CSV."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .iana import csv_service_name_display, parse_iana_rfc_numbers, row_datatracker_lookup_key
from .rfc_body_port import filter_datatracker_hits_by_port_in_rfc

CSV_COLUMNS = [
    "Service Name",
    "Port Number",
    "Transport Protocol",
    "Description",
    "Datatracker title query",
    "Assignee",
    "IANA Reference",
    "IANA RFC numbers (parsed)",
    "Datatracker RFC numbers",
    "Datatracker RFC titles",
    "Datatracker hits (JSON)",
]


def format_rfc_hits(hits: list[dict[str, Any]]) -> tuple[str, str]:
    if not hits:
        return "", ""
    nums = "; ".join(f"RFC{h['rfc_number']}" for h in hits)
    titles = " | ".join(h["title"].replace("\n", " ").strip() for h in hits)
    return nums, titles


def write_wellknown_ports_csv(
    path: str,
    *,
    rows: list[dict[str, str]],
    name_hits: dict[str, list[dict[str, Any]]],
    title_query_for_service: dict[str, str],
    write_rows_without_rfc_hints: bool = False,
    verify_port_in_rfc_body: bool = False,
    rfc_body_cache_dir: Path | None = None,
    rfc_body_timeout: float = 45.0,
    strict_rfc_port_verify: bool = False,
) -> tuple[int, int]:
    """Write CSV rows that have any RFC hint (IANA Reference or Datatracker).

    If *write_rows_without_rfc_hints* is true, also writes rows with neither hint
    (RFC / Datatracker columns empty) so you can curate gaps manually.

    Returns ``(written_row_count, skipped_row_count)`` for rows with neither
    (unless *write_rows_without_rfc_hints*).
    """

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    with open(out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            lookup_key = row_datatracker_lookup_key(r)
            name = csv_service_name_display(r, lookup_key)
            ref = (r.get("Reference") or "").strip()
            iana_rfcs = parse_iana_rfc_numbers(ref)
            hits = list(name_hits.get(lookup_key, []))
            if verify_port_in_rfc_body and hits and rfc_body_cache_dir is not None:
                port_s = (r.get("Port Number") or "").strip()
                if port_s.isdigit():
                    hits = filter_datatracker_hits_by_port_in_rfc(
                        hits,
                        int(port_s),
                        cache_dir=rfc_body_cache_dir,
                        timeout=rfc_body_timeout,
                        keep_on_fetch_failure=not strict_rfc_port_verify,
                    )
            if not iana_rfcs and not hits:
                if not write_rows_without_rfc_hints:
                    skipped += 1
                    continue
            dt_nums, dt_titles = format_rfc_hits(hits)
            title_q = title_query_for_service.get(lookup_key, "")
            writer.writerow(
                {
                    "Service Name": name,
                    "Port Number": (r.get("Port Number") or "").strip(),
                    "Transport Protocol": (r.get("Transport Protocol") or "").strip(),
                    "Description": (r.get("Description") or "").strip(),
                    "Datatracker title query": title_q,
                    "Assignee": (r.get("Assignee") or "").strip(),
                    "IANA Reference": ref,
                    "IANA RFC numbers (parsed)": " ".join(f"RFC{n}" for n in iana_rfcs),
                    "Datatracker RFC numbers": dt_nums,
                    "Datatracker RFC titles": dt_titles,
                    "Datatracker hits (JSON)": json.dumps(hits, ensure_ascii=False),
                }
            )
            written += 1
    return written, skipped
