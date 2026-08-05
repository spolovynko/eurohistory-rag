"""Logging configuration, applied once at a process entry point."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

# Libraries that would otherwise drown our own output. httpx logs one line per
# request at INFO; httpcore and urllib3 log connection detail at DEBUG, which
# the file handler below would happily record forever. Pinning them here is
# what keeps the file readable, so this list is load-bearing, not cosmetic.
NOISY_LIBRARIES = (
    "httpx",
    "httpcore",
    "urllib3",
    "openai",
    "qdrant_client",
    "sentence_transformers",
    "transformers",
)

LOG_FILE = Path("logs/eurohistory.log")
# An `index` or `evaluate` run writes a few hundred lines, so 5 MB x 3 holds
# months of them. The cap exists for the API process, which logs per request
# and runs until someone stops it.
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3


def configure_logging(
    *,
    verbose: bool = False,
    log_file: Path | None = LOG_FILE,
) -> None:
    """Send log records to stderr and to a file. Call from entry points only.

    A library module cannot know whether its caller wants stderr, a file, or
    silence, so it only emits records and leaves the destination to whoever owns
    the process. That is what lets pytest capture records without any handler at
    all, and what keeps this the single place output is decided.

    The two destinations are filtered separately: stderr shows what is worth
    watching live, the file records everything for afterwards. Pass
    `log_file=None` to skip the file, which is what tests do.
    """
    root = logging.getLogger()
    # Replace rather than add: configuring twice in one process must not double
    # every line. Handlers are closed so a re-run does not leak the open file.
    for existing in root.handlers[:]:
        root.removeHandler(existing)
        existing.close()

    # The root passes everything down; each handler decides what it keeps.
    root.setLevel(logging.DEBUG)
    formatter = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        rotating = RotatingFileHandler(
            log_file,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        # Always DEBUG: nobody is watching the file, and the run worth reading
        # it for is the one that already went wrong.
        rotating.setLevel(logging.DEBUG)
        rotating.setFormatter(formatter)
        root.addHandler(rotating)

    for name in NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
