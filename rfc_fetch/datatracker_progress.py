"""Thread-safe tqdm wrapper for concurrent Datatracker HTTP steps."""

from __future__ import annotations

import sys
import threading
from typing import TextIO

try:
    from tqdm import tqdm
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Progress bars require tqdm. Install with: pip install tqdm"
    ) from e


class DatatrackerHttpProgress:
    """Each ``complete_one()`` corresponds to one finished title-search HTTP step."""

    def __init__(
        self,
        total: int,
        *,
        stream: TextIO | None = None,
        desc: str = "Datatracker HTTP",
    ) -> None:
        self.total = max(0, int(total))
        self._stream = stream if stream is not None else sys.stderr
        self._desc = desc
        self._lock = threading.Lock()
        self._bar: tqdm | None = None

    def start(self) -> None:
        if self.total <= 0:
            return
        self._bar = tqdm(
            total=self.total,
            desc=self._desc,
            unit="req",
            file=self._stream,
            leave=False,
            dynamic_ncols=True,
            mininterval=0.2,
            smoothing=0.2,
        )

    def complete_one(self) -> None:
        if self._bar is None:
            return
        with self._lock:
            self._bar.update(1)

    def end_line(self) -> None:
        if self._bar is not None:
            self._bar.close()
            self._bar = None
