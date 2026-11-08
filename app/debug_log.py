"""Per-tournament debug log capture for the UI's "Debug Mode" toggle.

This is separate from the stdout logging in logging_config.py (which feeds
Render's Logs tab and respects LOG_LEVEL): this buffer always captures full
DEBUG-level detail regardless of LOG_LEVEL, so flipping on Debug Mode in the
app never requires touching a Render env var or redeploying.

`current_tournament_id` is a ContextVar rather than a parameter threaded
through scraper.py/jev_client.py's call signatures -- it's set once near the
top of run_tournament_pipeline, and asyncio propagates a copy of the current
context into both asyncio.to_thread calls (used for the Jev SDK, which is
sync) and into each Task asyncio.gather() spawns for a team, so every log
call anywhere in that run's call tree is attributed to the right tournament
without changing unrelated modules' function signatures.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from contextvars import ContextVar

current_tournament_id: ContextVar[int | None] = ContextVar("current_tournament_id", default=None)

_LOCK = threading.Lock()
_BUFFERS: dict[int, deque[str]] = {}
_MAX_LINES = 4000


class TournamentLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        tournament_id = current_tournament_id.get()
        if tournament_id is None:
            return
        try:
            line = self.format(record)
        except Exception:
            return
        with _LOCK:
            buf = _BUFFERS.setdefault(tournament_id, deque(maxlen=_MAX_LINES))
            buf.append(line)


def get_new_lines(tournament_id: int, since: int) -> tuple[list[str], int]:
    """Returns (lines appended since `since`, new cursor to pass next time)."""
    with _LOCK:
        buf = _BUFFERS.get(tournament_id)
        lines = list(buf) if buf else []
    return lines[since:], len(lines)


def get_all_text(tournament_id: int) -> str:
    with _LOCK:
        buf = _BUFFERS.get(tournament_id)
        return "\n".join(buf) if buf else ""
