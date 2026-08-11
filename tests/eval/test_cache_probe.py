"""Tests for the cache probe.

The instrument, not the cache. What is checked here is that the threshold rule
is the one D-105 wrote down -- the lowest bar admitting no near-miss, plus a
margin -- and that the two populations stay separate in the report. A probe
that quietly averaged rewordings and near-misses together would produce a
plausible number and hide the only failure this phase cares about.

Nothing here calls an embedding model. The vectors are hand-made directions
whose cosines are arithmetic anyone can check.
"""

import math
from collections.abc import Sequence

import pytest

from eurohistory_rag.eval.cache_probe import (
    MARGIN,
    Pair,
    Scored,
    choose_threshold,
    cosine,
    load_pairs,
    report,
    score,
)


def pair(name: str = "a-pair", group: str = "tune") -> Pair:
    return Pair(
        id=name,
        set=group,
        original="What caused the hyperinflation?",
        paraphrase="What made savings worthless?",
        negative="How was the hyperinflation ended?",
    )


def scored(paraphrase: float, negative: float, name: str = "a-pair") -> Scored:
    return Scored(
        pair=pair(name),
        paraphrase_similarity=paraphrase,
        negative_similarity=negative,
    )


class FixedEmbedder:
    """Returns a canned vector per text, in order."""

    def __init__(self, vectors: list[list[float]]) -> None:
        self._vectors = vectors
        self.asked: list[str] = []

    @property
    def dimensions(self) -> int:
        return 3

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.asked.extend(texts)
        return self._vectors[: len(texts)]


def test_the_threshold_clears_the_worst_near_miss() -> None:
    """The rule D-105 fixed in advance: no near-miss may be admitted, so the bar
    goes just above the highest of them and the hit rate is whatever that
    costs."""
    assert choose_threshold([scored(0.90, 0.70), scored(0.85, 0.81)]) == pytest.approx(
        0.81 + MARGIN
    )


def test_the_worst_near_miss_sets_the_bar_even_when_it_beats_a_rewording() -> None:
    """The shape that breaks this feature: a near-miss closer to the original
    than the genuine rewording is. No threshold can separate that pair, and the
    rule must refuse the rewording rather than admit the near-miss."""
    threshold = choose_threshold([scored(0.60, 0.75)])

    assert threshold > 0.75
    assert threshold > 0.60


def test_tuning_on_nothing_is_refused() -> None:
    """A threshold nobody measured is the thing this function exists to
    prevent."""
    with pytest.raises(ValueError, match="needs evidence"):
        choose_threshold([])


def test_the_report_counts_the_two_populations_separately() -> None:
    """Hit rate's denominator is the rewordings; the leak's is the near-misses.
    One combined percentage over forty queries would be the conflation the
    roadmap warns about, and it would read as a good number."""
    text = report([scored(0.90, 0.70), scored(0.60, 0.70)], threshold=0.80)

    assert "hit rate       1/2 = 50.0%" in text
    assert "near-miss leak 0/2 = 0.0%" in text


def test_a_leaked_near_miss_is_named_in_the_table() -> None:
    text = report([scored(0.90, 0.85)], threshold=0.80)

    assert "LEAK" in text


def test_cosine_is_one_for_the_same_direction() -> None:
    assert cosine([3.0, 4.0, 0.0], [6.0, 8.0, 0.0]) == pytest.approx(1.0)


def test_cosine_is_zero_at_right_angles() -> None:
    assert cosine([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]) == pytest.approx(0.0)


def test_every_question_is_embedded_once_and_matched_to_its_own_pair() -> None:
    """Three texts per pair, in file order. An off-by-one here would compare a
    question with the wrong pair's rewording and the numbers would still look
    reasonable, which is why this is asserted rather than assumed."""
    embedder = FixedEmbedder([[1.0, 0.0, 0.0], [0.99, 0.14, 0.0], [0.0, 1.0, 0.0]])

    result = score(embedder, [pair()])

    assert embedder.asked == [
        "What caused the hyperinflation?",
        "What made savings worthless?",
        "How was the hyperinflation ended?",
    ]
    assert result[0].paraphrase_similarity == pytest.approx(
        0.99 / math.hypot(0.99, 0.14)
    )
    assert result[0].negative_similarity == pytest.approx(0.0)


def test_the_shipped_probe_file_splits_tuning_from_testing() -> None:
    """The roadmap is explicit that the questions which tune the threshold
    cannot be the questions that test it. This is that rule, asserted against
    the file rather than trusted to a comment in it."""
    pairs = load_pairs()
    tune = {p.id for p in pairs if p.set == "tune"}
    test = {p.id for p in pairs if p.set == "test"}

    assert tune and test
    assert tune.isdisjoint(test)


def test_every_shipped_probe_carries_a_near_miss() -> None:
    """A probe set of rewordings alone can measure how often the cache fires
    and has no way at all to measure how often it fires wrongly."""
    assert all(p.negative for p in load_pairs())
