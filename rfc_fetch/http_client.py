"""Tiny HTTP helpers and JSON persistence (stdlib only)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .constants import DEFAULT_USER_AGENT


def fetch_url(url: str, *, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_get_with_retries(
    url: str,
    *,
    timeout: float,
    max_retries: int,
    sleep_base: float,
) -> bytes:
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fetch_url(url, timeout=timeout)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                time.sleep(sleep_base * (2**attempt))
                continue
            raise
        except urllib.error.URLError as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(sleep_base * (2**attempt))
                continue
            raise
    assert last_err is not None
    raise last_err


def write_json_atomic(path: str, data: dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=0)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    try:
        os.replace(tmp, path)
    except OSError:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=0)
        try:
            os.unlink(tmp)
        except OSError:
            pass
