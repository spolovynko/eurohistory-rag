"""Logging configuration, applied once at a process entry point."""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

# Libraries that log one line per request. Left at INFO they bury our own output.
NOISY_LIBRARIES = ("httpx",)


def configure_logging(*, verbose: bool = False) -> None:
    """Route log records to stderr. Call from entry points only, never a library.

    A library module cannot know whether its caller wants stderr, a file, or
    silence, so it only emits records and leaves the destination to whoever owns
    the process. That is what lets pytest capture records without any handler at
    all, and what keeps this the single place output is decided.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format=LOG_FORMAT,
        force=True,
    )
    for name in NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
