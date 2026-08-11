"""Measuring a cache that can make the system confidently wrong.

The eval cannot do this job. It asks each of its 106 questions once, so a
perfect cache would fire at most four times on it -- and three of those four
are the conversation controls, which a cache would destroy by answering them
with the golden question's answer. So the cache is off in the eval, and this is
the instrument instead.

Two halves, and the split is what keeps the numbers honest.

The **free half** needs only embeddings. A threshold is a number about meaning,
and every question's meaning is a vector, so the whole of tuning can be done
without a single generation call: embed the originals, the paraphrases and the
near-misses, and read off where the two populations separate.

The **paid half** cannot be done that way. Whether a served answer actually
answers the question asked is not a cosine, and D-083 says the thing behind the
metric gets opened and read. So the test set is run through the real answer
path and every served answer is written out next to the question it was served
for.

**Hit rate and wrong-hit rate are on different populations and are never
averaged together.** Hit rate's denominator is the paraphrases, which are the
queries that *should* be served. Wrong-hit rate's denominator is the queries
that *were* served. Conflating the two is how a cache ships broken, and D-105
predicts them separately for that reason.
"""

import logging
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from eurohistory_rag.generation.cache import unit
from eurohistory_rag.retrieval.embedding import Embedder

logger = logging.getLogger(__name__)

PROBES_PATH = Path("eval/cache_probes.toml")

# How far above the worst near-miss the threshold is set. The rule below picks
# the lowest bar that admits no near-miss in the tuning set; this lifts it a
# little further, because the tuning set is twenty questions and the next
# near-miss the system meets was not one of them. Small enough not to throw away
# paraphrases wholesale, large enough not to be rounding.
MARGIN = 0.005


class Pair(BaseModel):
    """One question, one rewording of it, and one near-miss on the same topic."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    set: str = Field(pattern=r"^(tune|test)$")
    original: str = Field(min_length=1)
    paraphrase: str = Field(min_length=1)
    negative: str = Field(min_length=1)


class _ProbeFile(BaseModel):
    """The file as a whole."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pair: tuple[Pair, ...] = Field(min_length=1)


def load_pairs(path: Path = PROBES_PATH) -> tuple[Pair, ...]:
    """Every probe pair, validated."""
    with path.open("rb") as handle:
        return _ProbeFile.model_validate(tomllib.load(handle)).pair


@dataclass(frozen=True, slots=True)
class Scored:
    """How close a pair's rewording and its near-miss sit to the original."""

    pair: Pair
    paraphrase_similarity: float
    negative_similarity: float


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity, via the same normalisation the cache itself uses.

    Deliberately not a second implementation. If the cache and the instrument
    measuring it computed closeness differently, a threshold tuned here would
    mean something slightly other than the threshold applied there -- and the
    difference would be invisible in every test.
    """
    a, b = unit(left), unit(right)
    return sum(x * y for x, y in zip(a, b, strict=True))


def score(embedder: Embedder, pairs: Sequence[Pair]) -> list[Scored]:
    """Embed every question once and measure both distances from the original.

    One request per batch of texts rather than one per question: this is the
    only place in the phase that spends money on embeddings, and it is about
    a hundred short questions, which is roughly a five-thousandth of a cent.
    """
    texts = [
        text
        for pair in pairs
        for text in (pair.original, pair.paraphrase, pair.negative)
    ]
    vectors = embedder.embed(texts)
    scored = []
    for index, pair in enumerate(pairs):
        original, paraphrase, negative = vectors[index * 3 : index * 3 + 3]
        scored.append(
            Scored(
                pair=pair,
                paraphrase_similarity=cosine(original, paraphrase),
                negative_similarity=cosine(original, negative),
            )
        )
    return scored


def choose_threshold(scored: Sequence[Scored], margin: float = MARGIN) -> float:
    """The lowest bar that lets no near-miss through, plus a margin.

    The rule is forced rather than chosen. The roadmap's done-when says a
    non-zero wrong-hit rate means revert, so the only admissible threshold is
    one above every near-miss in the tuning data -- there is no trade-off to
    balance, because one side of it has been declared unacceptable in advance.
    What is left to measure is how many genuine rewordings that costs, and that
    is the hit rate.

    Raises on an empty set rather than returning a default: a threshold nobody
    measured is exactly what this function exists to prevent.
    """
    if not scored:
        raise ValueError("No pairs to tune on; a threshold needs evidence.")
    return round(max(s.negative_similarity for s in scored) + margin, 4)


def report(scored: Sequence[Scored], threshold: float) -> str:
    """Both populations, side by side, with every pair's own numbers.

    Printed in full rather than summarised because the summary is two
    percentages and the argument for trusting them is the forty rows behind
    them. A pair whose near-miss scores above its own rewording is the shape
    that breaks this feature, and only a table shows it.
    """
    lines = [f"threshold {threshold:.4f}", ""]
    lines.append(f"{'pair':<28}{'paraphrase':>12}{'near-miss':>12}  verdict")
    hits = wrong = 0
    for entry in sorted(scored, key=lambda s: s.paraphrase_similarity):
        hit = entry.paraphrase_similarity >= threshold
        leak = entry.negative_similarity >= threshold
        hits += hit
        wrong += leak
        verdict = "LEAK" if leak else ("hit" if hit else "miss")
        lines.append(
            f"{entry.pair.id:<28}{entry.paraphrase_similarity:>12.4f}"
            f"{entry.negative_similarity:>12.4f}  {verdict}"
        )
    total = len(scored)
    lines += [
        "",
        f"hit rate       {hits}/{total} = {hits / total:.1%}   "
        "(population: rewordings, which should be served)",
        f"near-miss leak {wrong}/{total} = {wrong / total:.1%}   "
        "(population: near-misses, which must not be served)",
    ]
    return "\n".join(lines)
