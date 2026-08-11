"""Tests for the semantic answer cache.

Nothing here can tell you whether the threshold is right -- that is a question
about meaning, and only held-out paraphrases and a paid run answer it. What is
checked here is the part we wrote: that the key really is a direction in space,
that the best match wins rather than the first, that the fingerprint moves when
any of the five things behind an answer moves, and that the shipped default
cannot serve anything at all.

The last one matters most. Phase 30 shipped a ceiling whose code was provably
dead until it was measured, and this module ships in the same posture: a
threshold above 1.0 is unreachable, so a wiring mistake between here and step 6
fails closed rather than answering somebody's question with somebody else's
answer.
"""

import math

import pytest

from eurohistory_rag.generation.cache import (
    SIMILARITY_THRESHOLD,
    SemanticCache,
    fingerprint,
    unit,
)

# Two directions at right angles, and one a few degrees off the first. Hand-made
# rather than embedded so the similarities are arithmetic anyone can check.
EAST = [1.0, 0.0, 0.0]
NORTH = [0.0, 1.0, 0.0]
NEAR_EAST = [0.99, 0.14, 0.0]
NEARER_EAST = [0.999, 0.045, 0.0]


def cache(threshold: float = 0.9, max_entries: int = 256) -> SemanticCache[str]:
    """A cache with a reachable threshold, since the shipped one is not."""
    return SemanticCache(
        fingerprint="fp-1", threshold=threshold, max_entries=max_entries
    )


def test_empty_cache_never_hits() -> None:
    assert cache().lookup(EAST) is None


def test_the_same_question_comes_back() -> None:
    store = cache()
    store.store("what caused the hyperinflation?", EAST, "an answer")
    hit = store.lookup(EAST)
    assert hit is not None
    assert hit.value == "an answer"
    assert hit.question == "what caused the hyperinflation?"
    assert hit.similarity == pytest.approx(1.0)


def test_a_different_question_does_not_hit() -> None:
    store = cache()
    store.store("what caused the hyperinflation?", EAST, "an answer")
    assert store.lookup(NORTH) is None


def test_a_close_question_hits_and_says_how_close() -> None:
    store = cache(threshold=0.9)
    store.store("what caused the hyperinflation?", EAST, "an answer")
    hit = store.lookup(NEAR_EAST)
    assert hit is not None
    # cos of the angle between EAST and NEAR_EAST, once NEAR_EAST is scaled to
    # length one -- 0.99 / sqrt(0.99^2 + 0.14^2).
    assert hit.similarity == pytest.approx(0.99 / math.hypot(0.99, 0.14))


def test_the_nearest_match_wins_not_the_first() -> None:
    """Two entries over the line, and the closer one must be served.

    Serving the first one over the threshold would make which answer you get
    depend on what order questions happened to be asked in, which is the kind
    of defect that never reproduces.
    """
    store = cache(threshold=0.9)
    store.store("the adequate one", NEAR_EAST, "adequate")
    store.store("the closer one", NEARER_EAST, "closer")
    hit = store.lookup(EAST)
    assert hit is not None
    assert hit.value == "closer"


def test_the_oldest_answer_is_dropped_when_full() -> None:
    store = cache(max_entries=2)
    store.store("first", EAST, "one")
    store.store("second", NORTH, "two")
    store.store("third", NEAR_EAST, "three")
    assert len(store) == 2
    # EAST's entry is gone, so the closest thing to EAST is now NEAR_EAST's.
    hit = store.lookup(EAST)
    assert hit is not None
    assert hit.value == "three"


def test_a_zero_vector_is_refused() -> None:
    """A question with no direction cannot be a key, and must not be treated
    as one -- a zero vector would otherwise be silently equidistant from
    everything."""
    with pytest.raises(ValueError, match="no direction"):
        cache().store("nothing", [0.0, 0.0, 0.0], "an answer")


def test_a_long_vector_is_scaled_before_it_is_compared() -> None:
    assert unit([3.0, 4.0, 0.0]) == pytest.approx([0.6, 0.8, 0.0])


def test_a_scaled_question_is_the_same_question() -> None:
    store = cache()
    store.store("east", EAST, "an answer")
    hit = store.lookup([7.0, 0.0, 0.0])
    assert hit is not None
    assert hit.similarity == pytest.approx(1.0)


def test_a_new_fingerprint_empties_the_cache() -> None:
    store = cache()
    store.store("east", EAST, "an answer")
    store.reset("fp-2")
    assert len(store) == 0
    assert store.lookup(EAST) is None
    assert store.fingerprint == "fp-2"


def test_the_same_fingerprint_keeps_the_cache() -> None:
    store = cache()
    store.store("east", EAST, "an answer")
    store.reset("fp-1")
    assert len(store) == 1


def test_the_fingerprint_is_stable_for_an_unchanged_world() -> None:
    assert fingerprint("chunks", 1524, "text-embedding-3-small", "gpt-4.1-mini") == (
        fingerprint("chunks", 1524, "text-embedding-3-small", "gpt-4.1-mini")
    )


@pytest.mark.parametrize(
    "changed",
    [
        ("other", 1524, "text-embedding-3-small", "gpt-4.1-mini"),
        ("chunks", 1525, "text-embedding-3-small", "gpt-4.1-mini"),
        ("chunks", 1524, "text-embedding-3-large", "gpt-4.1-mini"),
        ("chunks", 1524, "text-embedding-3-small", "gpt-4.1"),
    ],
)
def test_the_fingerprint_moves_when_the_world_moves(
    changed: tuple[str, int, str, str],
) -> None:
    """Collection, point count, embedding model, generation model -- each on its
    own must invalidate, because each on its own can change the answer."""
    baseline = fingerprint("chunks", 1524, "text-embedding-3-small", "gpt-4.1-mini")
    assert fingerprint(*changed) != baseline


def test_the_prompt_text_is_in_the_fingerprint() -> None:
    """The prompt is the fifth thing an answer depends on and the only one with
    no argument, so this is the check that it is in there at all: a hash of four
    short strings would be far shorter to reproduce than one carrying the whole
    of system_prompt.md, and this asserts the hash is not simply of the four."""
    import hashlib

    four_only = hashlib.sha256(
        "\x1f".join(
            ["chunks", "1524", "text-embedding-3-small", "gpt-4.1-mini"]
        ).encode()
    ).hexdigest()[:16]
    assert fingerprint("chunks", 1524, "text-embedding-3-small", "gpt-4.1-mini") != (
        four_only
    )


def test_the_shipped_threshold_is_a_reachable_measured_number() -> None:
    """Until step 6 this asserted the opposite -- that the default could not be
    reached at all -- because a guessed threshold is the system confidently
    answering the wrong question. The number is now measured (0.8124, tuned on
    the twenty `tune` pairs in `eval/cache_probes.toml`) and the guard changes
    job: it must sit below 1.0 so the cache can work, and well above 0.5 so it
    is not matching unrelated questions. D-105."""
    assert 0.5 < SIMILARITY_THRESHOLD < 1.0
    store: SemanticCache[str] = SemanticCache(fingerprint="fp-1")
    store.store("east", EAST, "an answer")
    hit = store.lookup(EAST)
    assert hit is not None and hit.value == "an answer"
