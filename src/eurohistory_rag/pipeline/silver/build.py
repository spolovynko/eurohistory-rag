"""Bronze to Silver: read, deduplicate, transform, write.

The only module that knows the whole sequence. Everything it calls is pure --
no I/O below this file -- which is what lets the cleaning rules be tested
without a Parquet file anywhere in sight.
"""

import datetime as dt
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from eurohistory_rag.pipeline.silver.article import (
    extract_categories,
    extract_infobox,
    is_non_content,
)
from eurohistory_rag.pipeline.silver.sections import split_sections
from eurohistory_rag.pipeline.silver.store import SilverRow, to_frame, write

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BuildReport:
    """What one build did. `skipped` is articles judged non-content."""

    articles: int
    skipped: int
    rows: int
    path: Path


def read_articles(root: Path) -> pl.DataFrame:
    """Bronze, deduplicated to one row per article, themes collected into a list.

    An article reached by three themes is three Bronze rows with identical
    wikitext. Embedding it three times would return three identical chunks in
    one top-5, so the themes are collected and the article kept once. See
    D-035.
    """
    return (
        pl.scan_parquet(root / "**" / "*.parquet")
        .group_by("page_id")
        .agg(
            pl.col("theme").unique().sort().alias("themes"),
            pl.col("title").first(),
            pl.col("wikitext").first(),
            pl.col("revision_id").first(),
            pl.col("revision_timestamp").first(),
            pl.col("license").first(),
        )
        .sort("page_id")
        .collect()
    )


def article_rows(
    *,
    page_id: int,
    title: str,
    wikitext: str,
    themes: Sequence[str],
    revision_id: int,
    revision_timestamp: dt.datetime,
    license: str,
) -> list[SilverRow]:
    """Every Silver row one article produces.

    The infobox and the categories are read once, from the whole article, and
    copied onto each of its sections -- they describe the subject, not the
    section. They are also read before the split, because the cleaning rules
    delete them.
    """
    infobox = extract_infobox(wikitext)
    categories = extract_categories(wikitext)
    return [
        SilverRow(
            doc_id=f"{page_id}:{section.position}",
            page_id=page_id,
            position=section.position,
            title=title,
            heading=section.heading,
            text=section.text,
            themes=tuple(themes),
            link_targets=section.link_targets,
            categories=categories,
            infobox_type=infobox.type if infobox is not None else None,
            infobox=tuple(infobox.fields.items()) if infobox is not None else (),
            revision_id=revision_id,
            revision_timestamp=revision_timestamp,
            license=license,
        )
        for section in split_sections(wikitext)
    ]


def build(bronze_root: Path, silver_root: Path) -> BuildReport:
    """Rebuild the whole Silver table from Bronze.

    Not incremental and not resumable, deliberately: it takes under a minute
    and Silver is a cache, so a failed run is fixed by running it again.
    """
    started = time.monotonic()
    articles = read_articles(bronze_root)
    logger.info("start: %d articles after dedup on page_id", articles.height)

    rows: list[SilverRow] = []
    skipped = 0
    for article in articles.iter_rows(named=True):
        if is_non_content(article["title"], article["wikitext"]):
            logger.info("skipped %r: not a content article", article["title"])
            skipped += 1
            continue
        rows.extend(
            article_rows(
                page_id=article["page_id"],
                title=article["title"],
                wikitext=article["wikitext"],
                themes=article["themes"],
                revision_id=article["revision_id"],
                revision_timestamp=article["revision_timestamp"],
                license=article["license"],
            )
        )

    frame = to_frame(rows)
    path = write(silver_root, frame)
    logger.info(
        "done: %d rows from %d articles, %d skipped, in %.1fs",
        frame.height,
        articles.height - skipped,
        skipped,
        time.monotonic() - started,
    )
    return BuildReport(
        articles=articles.height, skipped=skipped, rows=frame.height, path=path
    )
