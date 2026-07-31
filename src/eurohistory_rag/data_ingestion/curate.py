"""Turn seed articles into candidate titles by following their wikilinks."""

from collections import Counter
from collections.abc import Iterable

import mwparserfromhell

from eurohistory_rag.data_ingestion.registry import RegistryEntry, Theme
from eurohistory_rag.data_ingestion.wikipedia import WikipediaClient

# Links into these namespaces are metadata or navigation, never article content.
_NON_ARTICLE_NAMESPACES = frozenset(
    {
        "category",
        "file",
        "image",
        "media",
        "template",
        "module",
        "help",
        "portal",
        "wikipedia",
        "wp",
        "special",
        "talk",
        "user",
        "draft",
        "mediawiki",
        "book",
        "timedtext",
        "wikt",
        "commons",
        "s",
    }
)
MIN_SEEDS = 2


def _is_non_article(title: str) -> bool:
    """True for `Category:1957 in Europe` and friends, false for `Star Trek: TNG`."""
    prefix, _, rest = title.partition(":")
    return bool(rest) and prefix.strip().lower() in _NON_ARTICLE_NAMESPACES


def extract_links(wikitext: str) -> set[str]:
    """Article titles linked from one article's wikitext."""
    titles: set[str] = set()
    for link in mwparserfromhell.parse(wikitext).filter_wikilinks():
        # `[[:Category:X]]`, `[[Rome#History]]`, `[[World_War_I]]` all normalise.
        title = str(link.title).strip().lstrip(":")
        title = title.split("#", 1)[0].strip().replace("_", " ")
        if not title or _is_non_article(title):
            continue
        # MediaWiki capitalises the first letter, so [[tariff]] and [[Tariff]]
        # are the same page and must not be counted twice.
        titles.add(title[0].upper() + title[1:])
    return titles


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
    client: WikipediaClient, theme: Theme, *, min_seeds: int = MIN_SEEDS
) -> list[RegistryEntry]:
    """Fetch one theme's seeds and rank the articles they link to."""
    result = client.fetch_batch(theme.seeds)
    if result.missing:
        # The seed list is 13 hand-typed lines. A title that does not resolve is
        # a typo to fix, not a data condition to tolerate.
        raise ValueError(
            f"theme {theme.slug!r}: seeds not found on Wikipedia: "
            f"{', '.join(sorted(result.missing))}"
        )

    ranked = rank_candidates(
        [extract_links(rev.wikitext) for rev in result.revisions],
        min_seeds=min_seeds,
    )
    # A seed is in the corpus by definition, whatever else links to it.
    for rev in result.revisions:
        ranked.setdefault(rev.title, min_seeds)

    return [
        RegistryEntry(theme=theme.slug, title=title, seed_count=count)
        for title, count in sorted(ranked.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def curate(
    client: WikipediaClient, themes: Iterable[Theme], *, min_seeds: int = MIN_SEEDS
) -> list[RegistryEntry]:
    """Rank candidates for every theme, in file order."""
    return [
        entry
        for theme in themes
        for entry in curate_theme(client, theme, min_seeds=min_seeds)
    ]
