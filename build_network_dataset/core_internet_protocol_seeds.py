"""Inject canonical IPV4 / IPV6 graph seeds (not from IANA decimals 4 / 41 encapsulation rows)."""

from __future__ import annotations

import sys
from typing import Any, Dict

RFC_IPV4_CORE = 791
RFC_IPV6_CORE = 8200


def inject_core_internet_protocol_seeds(protocols: Dict[str, Dict[str, Any]]) -> None:
    """
    Add **IPV4** / **IPV6** graph seeds from canonical specs.

    ``protocol-numbers-1.csv`` does not assign "the IPv4/IPv6 protocol" as a teachable row;
    decimals 4 and 41 are encapsulation references. Seeds therefore do not rely on those rows.
    """

    protocols["IPV4"] = {
        "rfcs": [RFC_IPV4_CORE],
        "label": "IPv4 · Internet Protocol (RFC791; not derived from IANA decimal-4 encapsulation row)",
    }
    protocols["IPV6"] = {
        "rfcs": [RFC_IPV6_CORE],
        "label": (
            "IPv6 · Internet Protocol (RFC8200; IANA decimal 41 cites RFC2473 tunneling, not the IPv6 spec)"
        ),
    }
    print(
        "Injected core IPV4 (RFC791) and IPV6 (RFC8200) seeds.",
        file=sys.stderr,
    )
