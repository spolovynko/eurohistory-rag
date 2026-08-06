"""The Bronze ingest loop: registry in, Parquet out."""

import datetime as dt
import logging
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import batched
from pathlib import Path

from eurohistory_rag.pipeline.bronze import store
from eurohistory_rag.pipeline.bronze.registry import RegistryEntry
from eurohistory_rag.pipeline.bronze.wikipedia import (
    MAX_TITLES_PER_REQUEST,
    RevisionSource,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestReport:
    """What one run did. `missing` is registry entries Wikipedia has no page for."""

    requested: int
    skipped: int
    written: int
    missing: tuple[str, ...]


def ingest(
    source: RevisionSource,
    entries: Sequence[RegistryEntry],
    root: Path,
    *,
    fetched_at: dt.datetime,
    batch_size: int = MAX_TITLES_PER_REQUEST,
    refresh: bool = False,
) -> IngestReport:
    """Fetch every registry entry not already in Bronze and append it there.

    Idempotent by default: a second run skips what the first stored, so a crash
    at article 600 costs nothing to resume. `refresh=True` ignores the skip set
    to deliberately pick up newer revisions.
    """
    if not 1 <= batch_size <= MAX_TITLES_PER_REQUEST:
        raise ValueError(f"batch_size must be 1..{MAX_TITLES_PER_REQUEST}")

    started = time.monotonic()

    done = set() if refresh else store.ingested_keys(root)
    todo = [e for e in entries if (e.theme, e.title) not in done]
    skipped = len(entries) - len(todo)

    logger.info(
        "start: %d entries, %d already in bronze, batch size %d%s",
        len(entries),
        skipped,
        batch_size,
        ", refresh" if refresh else "",
    )

    # One batch is one theme, because a Bronze row carries exactly one theme.
    by_theme: dict[str, list[str]] = defaultdict(list)
    for entry in todo:
        by_theme[entry.theme].append(entry.title)

    written = 0
    # (theme, title), so the file can say which theme lost an article. The
    # report keeps only the titles, derived from this, so there is one list.
    missing: list[tuple[str, str]] = []

    for theme, titles in by_theme.items():
        for batch in batched(titles, batch_size):
            result = source.fetch_batch(batch)
            for title in result.missing:
                logger.warning("no page for %r (theme %s)", title, theme)
            missing.extend((theme, title) for title in result.missing)
            if result.revisions:
                frame = store.to_frame(result.revisions, theme, fetched_at)
                store.write_batch(root, frame, fetched_at)
                written += len(result.revisions)
            logger.info(
                "%s: asked %d, got %d (%d/%d done)",
                theme,
                len(batch),
                len(result.revisions),
                written,
                len(todo),
            )

    path = store.write_missing(root, missing, fetched_at)

    logger.info(
        "done: %d written, %d skipped, %d missing in %.1fs (missing -> %s)",
        written,
        skipped,
        len(missing),
        time.monotonic() - started,
        path,
    )

    return IngestReport(
        requested=len(entries),
        skipped=skipped,
        written=written,
        missing=tuple(title for _, title in missing),
    )
