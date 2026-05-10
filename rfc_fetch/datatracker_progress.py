"""Thread-safe stderr progress line for Datatracker HTTP requests (stdlib only)."""

from __future__ import annotations

import shutil
import sys
import threading
from typing import TextIO


class DatatrackerHttpProgress:
    """Each ``complete_one()`` corresponds to one finished ``search_rfcs_by_title_phrase`` call."""

    def __init__(self, total: int, *, stream: TextIO | None = None, bar_width: int = 28) -> None:
        self.total = max(0, int(total))
        self.done = 0
        self._lock = threading.Lock()
        self._stream = stream if stream is not None else sys.stderr
        self._bar_width = max(8, int(bar_width))

    def _cols(self) -> int:
        try:
            return max(48, shutil.get_terminal_size().columns)
        except OSError:
            return 80

    def _render_unlocked(self) -> None:
        if self.total <= 0:
            return
        t = self.total
        d = min(self.done, t)
        cols = self._cols()
        w = max(8, min(self._bar_width, cols - 42))
        filled = int(w * d / t) if t else 0
        filled = min(max(filled, 0), w)
        bar = "#" * filled + "-" * (w - filled)
        pct = 100.0 * d / t if t else 0.0
        self._stream.write(f"\rDatatracker HTTP [{bar}] {d}/{t} ({pct:.1f}%)")
        self._stream.flush()

    def start(self) -> None:
        if self.total <= 0:
            return
        with self._lock:
            self.done = 0
            self._render_unlocked()

    def complete_one(self) -> None:
        if self.total <= 0:
            return
        with self._lock:
            self.done += 1
            self._render_unlocked()

    def end_line(self) -> None:
        if self.total <= 0:
            return
        self._stream.write("\n")
        self._stream.flush()
