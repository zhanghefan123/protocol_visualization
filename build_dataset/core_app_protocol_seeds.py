"""
Application-layer anchor protocols (additive merge with IANA port CSV seeds).

Edit ``CORE_APP_ANCHOR_SEEDS`` to add or strengthen anchors after ``collect_by_protocol``:

- **RFC numbers** are **unioned** with any existing row for the same ``Service Name`` (never
  replace the whole list).
- **``label``** and other extra keys use ``setdefault`` only — existing non-empty values from
  the CSV pipeline are **not** overwritten.
- **New** protocol ids (not in the CSV) need a non-empty ``rfcs`` list so the graph has defining
  RFCs to expand from.
"""

from __future__ import annotations

import sys
from typing import Any, Dict

# Keys: UPPERCASE protocol id (same convention as ``Service Name`` in the enriched CSV).
CORE_APP_ANCHOR_SEEDS: Dict[str, Dict[str, Any]] = {
    # Example (uncomment and edit):
    # "DNS": {"rfcs": [1034, 1035], "label": "DNS · teaching anchor"},
}


def inject_core_app_protocol_seeds(protocols: Dict[str, Dict[str, Any]]) -> None:
    """Merge ``CORE_APP_ANCHOR_SEEDS`` into ``protocols`` in place (additive; no CSV replace)."""

    if not CORE_APP_ANCHOR_SEEDS:
        return

    touched = 0
    for name, block in CORE_APP_ANCHOR_SEEDS.items():
        if not isinstance(block, dict):
            print(f"CORE_APP_ANCHOR_SEEDS[{name!r}]: ignored (value must be a mapping)", file=sys.stderr)
            continue

        raw_rfcs = block.get("rfcs")
        if raw_rfcs is not None and not isinstance(raw_rfcs, list):
            print(f"CORE_APP_ANCHOR_SEEDS[{name!r}]: rfcs must be a list, skipped", file=sys.stderr)
            continue
        raw_rfcs = raw_rfcs or []

        is_new = name not in protocols
        if is_new:
            if not raw_rfcs:
                print(
                    f"CORE_APP_ANCHOR_SEEDS[{name!r}]: skipped (new anchor needs non-empty rfcs)",
                    file=sys.stderr,
                )
                continue
            protocols[name] = {"rfcs": sorted({int(x) for x in raw_rfcs})}
        elif raw_rfcs:
            cur = {int(x) for x in (protocols[name].get("rfcs") or [])}
            cur.update(int(x) for x in raw_rfcs)
            protocols[name]["rfcs"] = sorted(cur)

        entry = protocols[name]
        lab = block.get("label")
        if lab:
            entry.setdefault("label", lab)
        for k, v in block.items():
            if k in ("rfcs", "label"):
                continue
            if v is None or v == "":
                continue
            entry.setdefault(k, v)

        touched += 1

    if touched:
        print(
            f"Merged core app anchor seeds: {touched} update(s) from CORE_APP_ANCHOR_SEEDS "
            "(RFC union / new rows; labels and other keys use setdefault).",
            file=sys.stderr,
        )
