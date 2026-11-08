"""Two independent logging destinations, set up once at startup:

1. Stdout -- on Render this is exactly what shows up in the service's Logs
   tab. Its verbosity respects LOG_LEVEL (INFO by default; set to DEBUG as
   an env var for step-by-step scraper/Jev detail there too).
2. The in-app "Debug Mode" buffer (debug_log.py) -- always captures full
   DEBUG-level detail for whichever tournament run is currently active,
   regardless of LOG_LEVEL, so toggling Debug Mode in the browser never
   needs a Render env var change or redeploy.

The root logger itself is kept at DEBUG so both handlers see everything;
each handler's own level controls what it actually uses.
"""

from __future__ import annotations

import logging
import sys

from .config import settings
from .debug_log import TournamentLogHandler

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def setup_logging() -> None:
    stdout_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(stdout_level)
    stdout_handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))

    tournament_handler = TournamentLogHandler()
    tournament_handler.setLevel(logging.DEBUG)
    tournament_handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(stdout_handler)
    root.addHandler(tournament_handler)

    # Playwright and httpx/httpx2 (the Jev SDK's transport) are extremely
    # chatty at DEBUG; keep them at INFO so DEBUG mode shows this app's own
    # steps, not a firehose of library internals.
    for noisy in ("playwright", "httpx", "httpx2", "httpcore", "httpcore2"):
        logging.getLogger(noisy).setLevel(logging.INFO)
