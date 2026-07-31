"""Wikilink extraction and the >=2-seed rule.

Everything here is pure except `curate_theme`, which takes a fake RevisionSource
rather than a client -- so the whole module tests with no network.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from eurohistory_rag.pipeline.bronze.curate import (
    curate,
    curate_theme,
    extract_links,
    rank_candidates,
)
from eurohistory_rag.pipeline.bronze.registry import Theme
from eurohistory_rag.pipeline.bronze.wikipedia import FetchResult, Revision


class FakeSource:
    """A RevisionSource backed by a dict of title -> wikitext."""

    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages
        self.calls: list[tuple[str, ...]] = []

    def fetch_batch(self, titles: Sequence[str]) -> FetchResult:
        self.calls.append(tuple(titles))
        revisions = tuple(
            Revision(
                page_id=i,
                title=t,
                requested_title=t,
                revision_id=i * 10,
                revision_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                wikitext=self._pages[t],
            )
            for i, t in enumerate(titles, start=1)
            if t in self._pages
        )
        missing = tuple(t for t in titles if t not in self._pages)
        return FetchResult(revisions=revisions, missing=missing)


# --- extract_links ---------------------------------------------------------


def test_a_plain_link_is_extracted() -> None:
    assert extract_links("see [[Marshall Plan]] for more") == {"Marshall Plan"}


def test_a_piped_link_keeps_the_target_not_the_display_text() -> None:
    """[[French Fourth Republic|France]] is an article about the Fourth Republic."""
    assert extract_links("[[French Fourth Republic|France]]") == {
        "French Fourth Republic"
    }


@pytest.mark.parametrize(
    ("wikitext", "expected"),
    [
        ("[[Rome#History]]", "Rome"),  # an anchor is the same article
        ("[[World_War_I]]", "World War I"),  # underscores are the URL form
        ("[[tariff]]", "Tariff"),  # MediaWiki capitalises the first letter
        ("[[  Rome  ]]", "Rome"),  # surrounding whitespace
    ],
)
def test_links_are_normalised(wikitext: str, expected: str) -> None:
    """Without these, the same article counts twice and the >=2 rule breaks."""
    assert extract_links(wikitext) == {expected}


@pytest.mark.parametrize(
    "wikitext",
    [
        "[[Category:1957 in Europe]]",
        "[[File:Signing.jpg|thumb|caption]]",
        "[[Template:Infobox]]",
        "[[Help:Contents]]",
        "[[:Category:Treaties]]",  # the leading-colon form
    ],
)
def test_non_article_namespaces_are_dropped(wikitext: str) -> None:
    assert extract_links(wikitext) == set()


def test_a_colon_in_a_real_title_is_kept() -> None:
    """The check is against a namespace list, not 'contains a colon'."""
    assert extract_links("[[Star Trek: The Next Generation]]") == {
        "Star Trek: The Next Generation"
    }


def test_links_inside_templates_and_tables_are_kept() -> None:
    """Infobox and table links are content -- the signatories, the depositor."""
    wikitext = (
        "{{Infobox Treaty\n| depositor = [[Government of Italy]]\n}}\n"
        '{| class="wikitable"\n| [[Konrad Adenauer]] |\n|}\n'
        "Body text linking [[Euratom]]."
    )

    assert extract_links(wikitext) == {
        "Government of Italy",
        "Konrad Adenauer",
        "Euratom",
    }


def test_the_same_link_twice_appears_once() -> None:
    assert extract_links("[[Rome]] and again [[Rome]]") == {"Rome"}


def test_no_links_gives_an_empty_set() -> None:
    assert extract_links("plain prose, no markup") == set()


# --- rank_candidates -------------------------------------------------------


def test_titles_below_the_threshold_are_dropped() -> None:
    ranked = rank_candidates([{"A", "B"}, {"B", "C"}], min_seeds=2)

    assert ranked == {"B": 2}


def test_results_are_ordered_by_count_descending() -> None:
    """The strongest candidates go to the top of the CSV, where they get read."""
    ranked = rank_candidates([{"A", "B"}, {"A", "B"}, {"A"}], min_seeds=2)

    assert list(ranked) == ["A", "B"]
    assert ranked == {"A": 3, "B": 2}


def test_min_seeds_of_one_keeps_everything() -> None:
    assert rank_candidates([{"A"}, {"B"}], min_seeds=1) == {"A": 1, "B": 1}


def test_no_seeds_gives_nothing() -> None:
    assert rank_candidates([]) == {}


# --- curate_theme ----------------------------------------------------------


THEME = Theme(slug="interwar", name="Interwar", seeds=("Weimar Republic", "Stalinism"))


def test_curate_theme_keeps_titles_both_seeds_link_to() -> None:
    source = FakeSource(
        {
            "Weimar Republic": "[[Adolf Hitler]] [[Hyperinflation]]",
            "Stalinism": "[[Adolf Hitler]] [[Gulag]]",
        }
    )

    entries = curate_theme(source, THEME)

    titles = {e.title: e.seed_count for e in entries}
    assert titles["Adolf Hitler"] == 2
    assert "Hyperinflation" not in titles  # only one seed linked to it
    assert "Gulag" not in titles


def test_curate_theme_includes_the_seeds_themselves() -> None:
    """A seed is in the corpus by definition, whatever links to it."""
    source = FakeSource({"Weimar Republic": "[[X]]", "Stalinism": "[[Y]]"})

    titles = {e.title for e in curate_theme(source, THEME)}

    assert titles == {"Weimar Republic", "Stalinism"}


def test_curate_theme_stamps_every_entry_with_the_theme_slug() -> None:
    source = FakeSource({"Weimar Republic": "[[A]]", "Stalinism": "[[A]]"})

    assert {e.theme for e in curate_theme(source, THEME)} == {"interwar"}


def test_a_seed_wikipedia_cannot_find_raises() -> None:
    """13 hand-typed titles: a typo must be loud, not silently contribute nothing."""
    source = FakeSource({"Weimar Republic": "[[A]]"})

    with pytest.raises(ValueError, match="Stalinism"):
        curate_theme(source, THEME)


def test_curate_covers_every_theme_in_order() -> None:
    themes = [
        Theme(slug="a", name="A", seeds=("P",)),
        Theme(slug="b", name="B", seeds=("Q",)),
    ]
    source = FakeSource({"P": "[[X]]", "Q": "[[Y]]"})

    entries = curate(source, themes)

    assert [e.theme for e in entries] == ["a", "b"]
    assert source.calls == [("P",), ("Q",)]
