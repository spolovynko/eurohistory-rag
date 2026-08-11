"""Answers kept under the meaning of the question that produced them.

A dictionary keyed on the question string would miss "what caused the Weimar
hyperinflation?" against "what made German savings worthless in the early
1920s?", which are the same question and cost the same $0.0013 twice. Keying on
the query *vector* instead makes the two one entry -- and makes it possible,
for the first time in this system, to answer a question nobody asked. That is
what the threshold and the fingerprint below are guarding against, and it is
why this module ships unable to hit until a number has been measured.

Deliberately generic in what it stores. The thing worth caching is an `Answer`,
which lives in `service.py`, and `service.py` is the module that will use this
one -- importing it back would be a cycle. A vector-keyed store does not need
to know what it is storing, so it does not.
"""

import hashlib
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

from eurohistory_rag.generation.messages import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# How close two questions must be, as cosine similarity, before one is answered
# with the other's answer.
#
# **Measured, not guessed: 0.8124.** Tuned on the twenty `tune` pairs in
# `eval/cache_probes.toml` by the only rule the roadmap leaves open -- the
# lowest bar that admits none of their near-misses, plus a 0.005 margin. The
# worst near-miss there was `enabling-act` at 0.8074: "what powers did the
# Enabling Act give Hitler" against "how was the Enabling Act passed", which are
# the same words about the same law and different questions. The bar is set just
# above it. Cost of the rule: 5 of 20 genuine rewordings are refused. That is
# the trade the roadmap already made when it said a non-zero wrong-hit rate
# means revert -- there is nothing to balance, because one side was declared
# unacceptable in advance. D-105.
SIMILARITY_THRESHOLD = 0.8124

# How many answers are kept. Small because this holds whole answers in memory
# for a single-process, single-user deployment, and because a cache big enough
# to need eviction policy is a cache that has outgrown the problem. The oldest
# entry goes when the limit is reached.
MAX_ENTRIES = 256


def fingerprint(
    collection: str,
    points: int,
    embedding_model: str,
    generation_model: str,
) -> str:
    """What must not have changed for a cached answer to still be true.

    An answer is only as good as the corpus it was drawn from, the prompt that
    shaped it and the models on both ends -- so all four, plus the prompt text
    itself, go into one short hash. When any of them moves the hash moves, every
    existing entry becomes unreachable, and the cache is emptied rather than
    consulted and refused. Staleness is then a non-event instead of a rule
    somebody has to remember to apply.

    `points` is in here because a re-index that adds chunks changes what the
    corpus can answer without changing the collection's name.
    """
    material = "\x1f".join(
        [collection, str(points), embedding_model, generation_model, SYSTEM_PROMPT]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def unit(vector: Sequence[float]) -> list[float]:
    """The vector scaled to length one, so a dot product is a cosine.

    `text-embedding-3-small` already returns unit vectors, so this is normally a
    no-op. It is done anyway rather than assumed: the cost is 1,536 multiplies
    and the alternative is a similarity that quietly stops meaning cosine if the
    provider ever changes that, which no test would catch.
    """
    length = math.sqrt(sum(component * component for component in vector))
    if length == 0.0:
        raise ValueError("A zero vector has no direction and cannot be a cache key.")
    return [component / length for component in vector]


@dataclass(frozen=True, slots=True)
class Hit[Value]:
    """A cached answer, and what it was actually written for.

    `question` and `similarity` are carried out rather than kept private
    because the reader is told about the hit -- an answer written for a
    different question is disclosed as one, and a caller cannot disclose what
    it was not given.
    """

    value: Value
    question: str
    similarity: float


class SemanticCache[Value]:
    """Answers found by the meaning of the question, not its wording."""

    def __init__(
        self,
        fingerprint: str,
        threshold: float = SIMILARITY_THRESHOLD,
        max_entries: int = MAX_ENTRIES,
    ) -> None:
        self._fingerprint = fingerprint
        self._threshold = threshold
        self._max_entries = max_entries
        # Question, unit vector, value -- in insertion order, which is also
        # eviction order. A list rather than a dict because the lookup is a scan
        # by similarity, and there is no key to hash on.
        self._entries: list[tuple[str, list[float], Value]] = []

    def __len__(self) -> int:
        """How many answers are held."""
        return len(self._entries)

    @property
    def fingerprint(self) -> str:
        """The corpus, prompt and model state these answers were written under."""
        return self._fingerprint

    def reset(self, fingerprint: str) -> None:
        """Throw everything away and adopt a new fingerprint.

        Called when the world has moved: a re-index, a prompt edit, a model
        swap. Emptying rather than marking entries stale is the whole of the
        invalidation rule -- there is no state in which this cache holds an
        answer it believes is out of date.
        """
        if fingerprint == self._fingerprint:
            return
        logger.info(
            "cache invalidated: %s -> %s, %d answers dropped",
            self._fingerprint,
            fingerprint,
            len(self._entries),
        )
        self._fingerprint = fingerprint
        self._entries.clear()

    def lookup(self, vector: Sequence[float]) -> Hit[Value] | None:
        """The stored answer closest to this question, if it is close enough.

        The *best* match rather than the first one over the line: two entries
        can both clear the threshold and only one of them is the nearest
        meaning, and serving the merely-adequate one would make hits depend on
        insertion order.
        """
        if not self._entries:
            return None
        query = unit(vector)
        best_question, best_value, best_similarity = "", None, -1.0
        for question, stored, value in self._entries:
            similarity = sum(a * b for a, b in zip(query, stored, strict=True))
            if similarity > best_similarity:
                best_question, best_value, best_similarity = question, value, similarity
        if best_value is None or best_similarity < self._threshold:
            return None
        return Hit(value=best_value, question=best_question, similarity=best_similarity)

    def store(self, question: str, vector: Sequence[float], value: Value) -> None:
        """Keep this answer under this question's meaning."""
        self._entries.append((question, unit(vector), value))
        if len(self._entries) > self._max_entries:
            del self._entries[0]
