"""Turn seed articles into candidate titles by following their wikilinks."""

import logging
from collections import Counter
from collections.abc import Iterable

import mwparserfromhell

from eurohistory_rag.pipeline.bronze.registry import RegistryEntry
from eurohistory_rag.pipeline.bronze.seeds import Theme
from eurohistory_rag.pipeline.bronze.wikipedia import RevisionSource
from eurohistory_rag.pipeline.wikitext import normalise_target

logger = logging.getLogger(__name__)

MIN_SEEDS = 2


def extract_links(wikitext: str) -> set[str]:
    """Article titles linked from one article's wikitext."""
    return {
        target
        for link in mwparserfromhell.parse(wikitext).filter_wikilinks()
        if (target := normalise_target(str(link.title))) is not None
    }


def rank_candidates(
    links_per_seed: Iterable[set[str]], *, min_seeds: int = MIN_SEEDS
) -> dict[str, int]:
    """Count how many seeds link to each title; keep those at or above min_seeds.

    Ordered by count descending, so the most-linked titles are at the top of the
    CSV where they are easiest to review.
    """
    counts = Counter(title for links in links_per_seed for title in links)
    return {title: n for title, n in counts.most_common() if n >= min_seeds}


def curate_theme(
    source: RevisionSource, theme: Theme, *, min_seeds: int = MIN_SEEDS
) -> list[RegistryEntry]:
    """Fetch one theme's seeds and rank the articles they link to."""
    result = source.fetch_batch(theme.seeds)
    if result.missing:
        # The seed list is 13 hand-typed lines. A title that does not resolve is
        # a typo to fix, not a data condition to tolerate.
        logger.error(
            "%s: seeds not found on Wikipedia: %s",
            theme.slug,
            ", ".join(sorted(result.missing)),
        )
        raise ValueError(
            f"theme {theme.slug!r}: seeds not found on Wikipedia: "
            f"{', '.join(sorted(result.missing))}"
        )

    links_per_seed = [extract_links(rev.wikitext) for rev in result.revisions]
    ranked = rank_candidates(links_per_seed, min_seeds=min_seeds)
    # A seed is in the corpus by definition, whatever else links to it.
    for rev in result.revisions:
        ranked.setdefault(rev.title, min_seeds)

    entries = [
        RegistryEntry(theme=theme.slug, title=title, seed_count=count)
        for title, count in sorted(ranked.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    logger.info(
        "%s: %d seeds, %d links, %d candidates",
        theme.slug,
        len(result.revisions),
        sum(len(links) for links in links_per_seed),
        len(entries),
    )
    return entries


def curate(
    source: RevisionSource, themes: Iterable[Theme], *, min_seeds: int = MIN_SEEDS
) -> list[RegistryEntry]:
    """Rank candidates for every theme, in file order."""
    return [
        entry
        for theme in themes
        for entry in curate_theme(source, theme, min_seeds=min_seeds)
    ]
