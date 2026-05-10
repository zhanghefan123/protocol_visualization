"""Load and normalize rows from IANA ``service-names-port-numbers.csv``."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import defaultdict

from .constants import (
    IANA_CSV_URL,
    RFC_REFERENCE_PATTERN,
    WELL_KNOWN_MAX_PORT,
)
from .http_client import fetch_url


def load_iana_rows() -> list[dict[str, str]]:
    raw = fetch_url(IANA_CSV_URL).decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(raw)))


def parse_iana_rfc_numbers(reference: str) -> list[int]:
    if not reference:
        return []
    nums = [int(m.group(1)) for m in RFC_REFERENCE_PATTERN.finditer(reference)]
    return sorted(set(nums))


def is_well_known_port_row(row: dict[str, str]) -> bool:
    p = (row.get("Port Number") or "").strip()
    if not p.isdigit():
        return False
    return 0 <= int(p) <= WELL_KNOWN_MAX_PORT


def iter_well_known_named_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Ports 0..1023 only; drop rows whose *Service Name* is empty."""

    return [
        r
        for r in rows
        if is_well_known_port_row(r) and (r.get("Service Name") or "").strip()
    ]


def iter_well_known_port_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Well-known port rows (0..1023), **including** empty *Service Name* (Datatracker uses Description)."""

    return [r for r in rows if is_well_known_port_row(r)]


def _norm_transport_protocol(tp: str) -> str:
    t = (tp or "").strip().upper()
    t = re.sub(r"[^\w]+", "-", t).strip("-")
    return t or "UNKNOWN"


_PHONY_SERVICE_NAMES = frozenset({"-", "—", "none"})


def has_usable_service_name(row: dict[str, str]) -> bool:
    """True if IANA *Service Name* is a real mnemonic (not blank / dash / ``n/a`` placeholders)."""

    sn = (row.get("Service Name") or "").strip()
    if not sn:
        return False
    if sn in _PHONY_SERVICE_NAMES:
        return False
    if sn.lower() in {"n/a", "na"}:
        return False
    return True


def row_datatracker_lookup_key(row: dict[str, str]) -> str:
    """Stable key for Datatracker cache/CSV: IANA *Service Name* or a synthetic id for unnamed rows."""

    if has_usable_service_name(row):
        return (row.get("Service Name") or "").strip()
    port = (row.get("Port Number") or "").strip()
    tp = _norm_transport_protocol(row.get("Transport Protocol") or "")
    desc = normalize_search_phrase(row.get("Description") or "")
    assignee = normalize_search_phrase(row.get("Assignee") or "")
    digest = hashlib.sha256(f"{desc}|{assignee}|{port}|{tp}".encode("utf-8")).hexdigest()[:8].upper()
    return f"IANA-UNNAMED-{tp}-{port}-{digest}"


def unique_sorted_service_names(rows: list[dict[str, str]]) -> list[str]:
    return sorted({(r["Service Name"] or "").strip() for r in rows if (r["Service Name"] or "").strip()})


def unique_sorted_lookup_keys(rows: list[dict[str, str]]) -> list[str]:
    """Sorted unique :func:`row_datatracker_lookup_key` values (named + synthetic)."""

    return sorted({row_datatracker_lookup_key(r) for r in rows})


_PLACEHOLDER_DESCRIPTIONS = frozenset(
    {
        "reserved",
        "unassigned",
    }
)


def normalize_search_phrase(text: str) -> str:
    """Single-line phrase for HTTP query / CSV *Datatracker title query* column."""

    return " ".join((text or "").split()).strip()


def _is_placeholder_description(text: str) -> bool:
    t = normalize_search_phrase(text).lower()
    if not t:
        return True
    if t in _PLACEHOLDER_DESCRIPTIONS:
        return True
    if t.startswith("unassigned") or t.startswith("reserved"):
        return True
    return False


_DESCRIPTION_TOKEN_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "for",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "using",
        "via",
        "over",
        "default",
        "official",
        "name",
    }
)


def datatracker_title_query_candidates(
    lookup_key: str,
    primary_phrase: str,
    *,
    min_len: int,
    max_phrases: int = 8,
) -> list[str]:
    """
    Build several ``title__icontains`` strings from the IANA-derived *primary* phrase.

    Longest-description-only matching often misses (e.g. *Domain Name Server* vs RFC titles
    *Domain names - …*). We therefore also try: the service lookup key, clause splits,
    shorter word-prefixes of the phrase, and significant single tokens (length ≥ max(4, *min_len*)).
    """

    def acceptable(s: str) -> bool:
        t = normalize_search_phrase(s)
        return bool(t) and len(t) >= min_len and not _is_placeholder_description(t)

    out: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        if len(out) >= max_phrases:
            return
        t = normalize_search_phrase(raw)
        if not acceptable(t):
            return
        k = t.casefold()
        if k in seen:
            return
        seen.add(k)
        out.append(t)

    add(primary_phrase)
    if not lookup_key.startswith("IANA-UNNAMED-"):
        add(lookup_key)

    base = normalize_search_phrase(primary_phrase)
    for chunk in re.split(r"[,;/|]+", base):
        add(chunk)
        if len(out) >= max_phrases:
            return out

    words = base.split()
    if len(words) >= 4:
        add(" ".join(words[:3]))
    if len(out) >= max_phrases:
        return out
    if len(words) >= 3:
        add(" ".join(words[:2]))
    if len(out) >= max_phrases:
        return out

    min_token = max(4, int(min_len))
    singles: list[str] = []
    for w in words:
        w2 = re.sub(r"^[\W\d]+|[\W\d]+$", "", w)
        if len(w2) < min_token:
            continue
        if w2.casefold() in _DESCRIPTION_TOKEN_STOPWORDS:
            continue
        singles.append(w2)
    for w in sorted(set(singles), key=lambda x: (-len(x), x.casefold())):
        add(w)
        if len(out) >= max_phrases:
            break
    return out


def datatracker_protocol_query(service_name: str, descriptions: list[str]) -> str:
    """Pick an IANA *Description* string to query Datatracker (full name / phrase).

    IANA descriptions are usually more verbose than the Service Name mnemonic.
    Uses the longest non-placeholder description among *descriptions*; ties use
    lexicographic ``casefold`` order. Otherwise falls back to *service_name*
    (may be empty for synthetic unnamed rows).
    """

    sn = normalize_search_phrase(service_name)
    candidates: list[str] = []
    seen: set[str] = set()
    for raw in descriptions:
        d = normalize_search_phrase(raw)
        if not d or _is_placeholder_description(d):
            continue
        if d not in seen:
            seen.add(d)
            candidates.append(d)
    if not candidates:
        return sn
    # Deterministic tie-break when multiple descriptions share the same length (stable cache queries).
    return max(candidates, key=lambda s: (len(s), s.casefold()))


def build_datatracker_title_queries(rows: list[dict[str, str]]) -> dict[str, str]:
    """Lookup key (Service Name or ``IANA-UNNAMED-…``) → phrase for ``title__icontains``."""

    bucket: defaultdict[str, list[str]] = defaultdict(list)
    for r in rows:
        key = row_datatracker_lookup_key(r)
        bucket[key].append(r.get("Description") or "")
    out: dict[str, str] = {}
    for key in sorted(bucket.keys(), key=lambda k: k.casefold()):
        texts = sorted(bucket[key], key=lambda s: s.casefold())
        if key.startswith("IANA-UNNAMED-"):
            out[key] = datatracker_protocol_query("", texts)
        else:
            out[key] = datatracker_protocol_query(key, texts)
    return out


def build_protocol_title_queries(rows: list[dict[str, str]]) -> dict[str, str]:
    """Backward-compatible alias for :func:`build_datatracker_title_queries`."""

    return build_datatracker_title_queries(rows)
