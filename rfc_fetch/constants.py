"""Endpoints and parsing constants."""

from __future__ import annotations

import re

IANA_CSV_URL = (
    "https://www.iana.org/assignments/service-names-port-numbers/"
    "service-names-port-numbers.csv"
)

DATATRACKER_DOC_API = "https://datatracker.ietf.org/api/v1/doc/document/"

DEFAULT_USER_AGENT = (
    "rfc-fetch/1.2 (+https://www.iana.org/assignments/"
    "service-names-port-numbers/)"
)

RFC_REFERENCE_PATTERN = re.compile(r"\[RFC(\d+)\]", re.IGNORECASE)

WELL_KNOWN_MAX_PORT = 1023
