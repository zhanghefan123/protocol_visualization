"""IETF Datatracker REST queries for RFC documents."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from .constants import DATATRACKER_DOC_API
from .http_client import http_get_with_retries


def search_rfcs_by_title_phrase(
    title_search_phrase: str,
    *,
    max_results: int,
    timeout: float,
    max_retries: int,
    retry_sleep_base: float,
) -> list[dict[str, Any]]:
    """Return RFC hits whose *title* contains ``title_search_phrase`` (case-insensitive).

    Mirrors the Datatracker document list filter ``title__icontains``.
    """

    params = {
        "format": "json",
        "type__slug": "rfc",
        "title__icontains": title_search_phrase,
        "limit": max_results,
        "ordering": "-rfc_number",
    }
    url = DATATRACKER_DOC_API + "?" + urllib.parse.urlencode(params)
    data = http_get_with_retries(
        url,
        timeout=timeout,
        max_retries=max_retries,
        sleep_base=retry_sleep_base,
    )
    payload = json.loads(data.decode("utf-8"))
    out: list[dict[str, Any]] = []
    for obj in payload.get("objects") or []:
        num = obj.get("rfc_number")
        title = (obj.get("title") or "").strip()
        if num is None:
            continue
        out.append({"rfc_number": int(num), "title": title, "name": obj.get("name")})
    return out
